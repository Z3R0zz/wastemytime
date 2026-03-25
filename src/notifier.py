import shutil
import subprocess


def _has_notify_send() -> bool:
    return shutil.which("notify-send") is not None

def _send(title: str, body: str, urgency: str, icon: str, timeout_ms: int):
    if not _has_notify_send():
        print(f"[{urgency.upper()}] {title}: {body}")
        return

    cmd = [
        "notify-send",
        "--app-name=wastemytime",
        f"--urgency={urgency}",
        f"--icon={icon}",
    ]
    if timeout_ms > 0:
        cmd.append(f"--expire-time={timeout_ms}")
    cmd.extend([title, body])

    try:
        subprocess.run(cmd, check=False, timeout=5)
    except Exception:
        print(f"[{urgency.upper()}] {title}: {body}")


def notify_important_email(
    subject: str,
    sender: str,
    reason: str,
    importance: str,
    deadline: str | None,
    config: dict,
):
    notif_cfg = config.get("notifications", {})
    timeout_ms = notif_cfg.get("timeout_ms", 8000)

    if importance == "critical":
        urgency = notif_cfg.get("urgency_critical", "critical")
        icon = "dialog-error"
        title = f"🔴 CRITICAL: {subject}"
    else:
        urgency = notif_cfg.get("urgency_normal", "normal")
        icon = "dialog-information"
        title = f"📌 Important: {subject}"

    body = f"From: {sender}\n{reason}"
    if deadline:
        body += f"\nDeadline: {deadline}"

    _send(title, body, urgency, icon, timeout_ms)


def notify_weekly_digest(digest_text: str, config: dict):
    notif_cfg = config.get("notifications", {})
    timeout_ms = notif_cfg.get("timeout_ms", 8000)

    preview = digest_text[:300]
    if len(digest_text) > 300:
        preview += "..."

    _send(
        "📋 Weekly Email Digest",
        preview,
        notif_cfg.get("urgency_normal", "normal"),
        "appointment-soon",
        timeout_ms,
    )


def notify_deadline_reminder(subject: str, days_left: int, action: str):
    urgency = "critical" if days_left <= 1 else "normal"
    icon = "dialog-error" if days_left <= 1 else "appointment-soon"
    title = f"⏰ Deadline in {days_left}d: {subject}"
    body = f"Action: {action}" if action and action != "none" else "Check your email for details."

    _send(title, body, urgency, icon, 0)  # persistent for deadline reminders
