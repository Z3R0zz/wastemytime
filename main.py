#!/usr/bin/env python3
import argparse
import getpass
import os
import signal
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import schedule
import yaml

from src.ai_engine import classify_email, generate_weekly_digest
from src.email_client import Email, fetch_new_emails, STATE_FILE
from src.notifier import (
    notify_deadline_reminder,
    notify_important_email,
    notify_weekly_digest,
)
from src.tracker import (
    dismiss_item,
    get_item_counts,
    get_recent_important,
    get_upcoming_deadlines,
    init_db,
    save_item,
)


def load_config() -> dict:
    config_path = Path(__file__).parent / "config.yaml"
    with open(config_path) as f:
        return yaml.safe_load(f)


def resolve_password(config: dict) -> str:
    """Resolve IMAP password: keyring -> env var -> config.yaml fallback."""
    username = config["imap"]["username"]

    try:
        import keyring
        password = keyring.get_password("wastemytime", username)
        if password:
            return password
    except Exception:
        pass

    env_pw = os.environ.get("WASTEMYTIME_PASSWORD")
    if env_pw:
        return env_pw

    cfg_pw = config["imap"].get("password")
    if cfg_pw and cfg_pw != "YOUR_PASSWORD":
        print(
            "WARNING: Reading password from config.yaml. "
            "Use --set-password to store it securely in your system keyring.",
            file=sys.stderr,
        )
        return cfg_pw

    print(
        "ERROR: No password configured.\n"
        "  Option 1: python main.py --set-password  (recommended, uses system keyring)\n"
        "  Option 2: Set WASTEMYTIME_PASSWORD environment variable\n"
        "  Option 3: Add 'password' field to config.yaml (least secure)",
        file=sys.stderr,
    )
    sys.exit(1)


def store_password(config: dict):
    """Store IMAP password in the system keyring."""
    try:
        import keyring
    except ImportError:
        print(
            "ERROR: 'keyring' package not installed. Run: pip install keyring",
            file=sys.stderr,
        )
        sys.exit(1)

    username = config["imap"]["username"]
    password = getpass.getpass(f"IMAP password for {username}: ")
    keyring.set_password("wastemytime", username, password)
    print(f"Password stored in system keyring for {username}.")


def check_emails(config: dict):
    print(f"[{datetime.now():%H:%M:%S}] Checking emails...")
    try:
        emails = fetch_new_emails(config)
    except Exception as e:
        print(f"  Error fetching emails: {e}")
        return

    if not emails:
        print("  No new emails.")
        return

    print(f"  Found {len(emails)} new email(s). Classifying...")
    threshold = config["ai"].get("notification_threshold", 0.75)

    for em in emails:
        classification = classify_email(em, config)
        print(f"  [{classification.importance}] {em.subject} (confidence: {classification.confidence:.2f})")

        if classification.importance in ("important", "critical"):
            save_item(classification, em)

            if classification.confidence >= threshold:
                notify_important_email(
                    subject=em.subject,
                    sender=em.sender,
                    reason=classification.reason,
                    importance=classification.importance,
                    deadline=classification.deadline,
                    config=config,
                )

    near_deadlines = get_upcoming_deadlines(days=3)
    for item in near_deadlines:
        days_left = (datetime.strptime(item["deadline"], "%Y-%m-%d") - datetime.now()).days
        if days_left <= 3:
            notify_deadline_reminder(item["subject"], days_left, item["action_required"])


def run_digest(config: dict):
    print("Generating weekly digest...")
    from src.ai_engine import EmailClassification

    recent = get_recent_important(days=7)
    items = [
        EmailClassification(
            email_uid=r["email_uid"],
            importance=r["importance"],
            confidence=1.0,
            reason=r["reason"],
            deadline=r["deadline"],
            action_required=r["action_required"],
            summary=r["summary"],
        )
        for r in recent
    ]

    digest = generate_weekly_digest(items, config)
    print("\n" + digest + "\n")
    notify_weekly_digest(digest, config)


def print_deadlines():
    deadlines = get_upcoming_deadlines(days=30)
    if not deadlines:
        print("No upcoming deadlines.")
        return

    print("Upcoming Deadlines:")
    print("-" * 60)
    for item in deadlines:
        days_left = (datetime.strptime(item["deadline"], "%Y-%m-%d") - datetime.now()).days
        days_str = f"{days_left}d left" if days_left >= 0 else "OVERDUE"
        print(f"  [{item['importance'].upper()}] {item['subject']}")
        print(f"    Deadline: {item['deadline']} ({days_str})")
        print(f"    Action: {item['action_required']}")
        print(f"    ID: {item['id']}")
        print()


def print_status():
    counts = get_item_counts()
    last_fetch = "never"
    if STATE_FILE.exists():
        import json
        state = json.loads(STATE_FILE.read_text())
        if state.get("last_fetch"):
            last_fetch = state["last_fetch"]

    print("wastemytime Status")
    print("-" * 40)
    print(f"  Last fetch:      {last_fetch}")
    print(f"  Tracked items:   {counts['total']}")
    print(f"  Critical:        {counts['critical']}")
    print(f"  Important:       {counts['important']}")


def daemon_mode(config: dict):
    poll_minutes = config["schedule"].get("poll_interval_minutes", 15)
    digest_day = config["schedule"].get("digest_day", "monday")
    digest_time = config["schedule"].get("digest_time", "08:00")

    print(f"Starting daemon — polling every {poll_minutes}m, digest on {digest_day} at {digest_time}")

    check_emails(config)

    schedule.every(poll_minutes).minutes.do(check_emails, config)
    getattr(schedule.every(), digest_day).at(digest_time).do(run_digest, config)

    running = True

    def handle_signal(sig, frame):
        nonlocal running
        print("\nShutting down...")
        running = False

    signal.signal(signal.SIGINT, handle_signal)
    signal.signal(signal.SIGTERM, handle_signal)

    while running:
        schedule.run_pending()
        time.sleep(30)


def main():
    parser = argparse.ArgumentParser(description="wastemytime // email classifier and tracker")
    parser.add_argument("--daemon", action="store_true", help="Run as daemon with scheduled polling")
    parser.add_argument("--digest", action="store_true", help="Generate and display weekly digest")
    parser.add_argument("--deadlines", action="store_true", help="Show upcoming deadlines")
    parser.add_argument("--dismiss", type=int, metavar="ID", help="Dismiss a tracked item by ID")
    parser.add_argument("--status", action="store_true", help="Show status info")
    parser.add_argument("--set-password", action="store_true", help="Store IMAP password in system keyring")
    args = parser.parse_args()

    config = load_config()
    init_db()

    if args.set_password:
        store_password(config)
    elif args.status:
        print_status()
    elif args.deadlines:
        print_deadlines()
    elif args.dismiss is not None:
        dismiss_item(args.dismiss)
        print(f"Dismissed item {args.dismiss}.")
    elif args.digest:
        run_digest(config)
    elif args.daemon:
        config["imap"]["password"] = resolve_password(config)
        daemon_mode(config)
    else:
        config["imap"]["password"] = resolve_password(config)
        check_emails(config)


if __name__ == "__main__":
    main()
