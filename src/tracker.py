import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .ai_engine import EmailClassification
from .email_client import Email


DB_PATH = Path.home() / ".wastemytime.db"
MARKDOWN_PATH = Path.home() / "school_deadlines.md"


def _get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = _get_conn()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS tracked_items (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            email_uid       TEXT UNIQUE,
            subject         TEXT,
            sender          TEXT,
            importance      TEXT,
            reason          TEXT,
            deadline        TEXT,
            action_required TEXT,
            summary         TEXT,
            tracked_at      TEXT,
            dismissed       INTEGER DEFAULT 0
        )
    """)
    conn.commit()
    conn.close()
    # chmod 600
    import os, stat
    os.chmod(DB_PATH, stat.S_IRUSR | stat.S_IWUSR)


def save_item(classification: EmailClassification, email_obj: Email):
    conn = _get_conn()
    conn.execute("""
        INSERT OR IGNORE INTO tracked_items
            (email_uid, subject, sender, importance, reason, deadline,
             action_required, summary, tracked_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        classification.email_uid,
        email_obj.subject,
        f"{email_obj.sender} <{email_obj.sender_email}>",
        classification.importance,
        classification.reason,
        classification.deadline,
        classification.action_required,
        classification.summary,
        datetime.now(timezone.utc).isoformat(),
    ))
    conn.commit()
    conn.close()
    _rebuild_markdown()


def get_upcoming_deadlines(days: int = 30) -> list[dict]:
    conn = _get_conn()
    cutoff = (datetime.now(timezone.utc) + timedelta(days=days)).strftime("%Y-%m-%d")
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    rows = conn.execute("""
        SELECT * FROM tracked_items
        WHERE dismissed = 0
          AND deadline IS NOT NULL
          AND deadline >= ?
          AND deadline <= ?
        ORDER BY deadline ASC
    """, (today, cutoff)).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_recent_important(days: int = 7) -> list[dict]:
    conn = _get_conn()
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    rows = conn.execute("""
        SELECT * FROM tracked_items
        WHERE dismissed = 0
          AND importance IN ('critical', 'important')
          AND tracked_at >= ?
        ORDER BY
          CASE importance WHEN 'critical' THEN 0 ELSE 1 END,
          tracked_at DESC
    """, (cutoff,)).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def dismiss_item(item_id: int):
    conn = _get_conn()
    conn.execute("UPDATE tracked_items SET dismissed = 1 WHERE id = ?", (item_id,))
    conn.commit()
    conn.close()
    _rebuild_markdown()


def get_item_counts() -> dict:
    conn = _get_conn()
    total = conn.execute("SELECT COUNT(*) FROM tracked_items WHERE dismissed = 0").fetchone()[0]
    critical = conn.execute(
        "SELECT COUNT(*) FROM tracked_items WHERE dismissed = 0 AND importance = 'critical'"
    ).fetchone()[0]
    important = conn.execute(
        "SELECT COUNT(*) FROM tracked_items WHERE dismissed = 0 AND importance = 'important'"
    ).fetchone()[0]
    conn.close()
    return {"total": total, "critical": critical, "important": important}


def _rebuild_markdown():
    deadlines = get_upcoming_deadlines(days=90)
    important = get_recent_important(days=30)

    now = datetime.now().strftime("%d %b %Y %H:%M")
    lines = [
        "# School Email Tracker",
        f"_Last updated: {now}_",
        "",
    ]

    lines.append("## ⏰ Upcoming Deadlines")
    lines.append("")
    if deadlines:
        for item in deadlines:
            days_left = (datetime.strptime(item["deadline"], "%Y-%m-%d") - datetime.now()).days
            days_str = f"{days_left}d left" if days_left >= 0 else "OVERDUE"
            lines.append(f"- **{item['subject']}**")
            lines.append(f"  - Deadline: {item['deadline']} ({days_str})")
            lines.append(f"  - From: {item['sender']}")
            if item["action_required"] and item["action_required"] != "none":
                lines.append(f"  - Action: {item['action_required']}")
            lines.append(f"  - {item['summary']}")
            lines.append(f"  - _Dismiss: `python main.py --dismiss {item['id']}`_")
            lines.append("")
    else:
        lines.append("No upcoming deadlines.")
        lines.append("")

    deadline_ids = {item["id"] for item in deadlines}
    other = [item for item in important if item["id"] not in deadline_ids]

    lines.append("## 📌 Other Important Items")
    lines.append("")
    if other:
        for item in other:
            tag = "🔴" if item["importance"] == "critical" else "🟡"
            lines.append(f"- {tag} **{item['subject']}**")
            lines.append(f"  - From: {item['sender']}")
            if item["action_required"] and item["action_required"] != "none":
                lines.append(f"  - Action: {item['action_required']}")
            lines.append(f"  - {item['summary']}")
            lines.append(f"  - _Dismiss: `python main.py --dismiss {item['id']}`_")
            lines.append("")
    else:
        lines.append("No other important items.")
        lines.append("")

    MARKDOWN_PATH.write_text("\n".join(lines))
