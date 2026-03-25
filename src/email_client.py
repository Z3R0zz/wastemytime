import imaplib
import email
import email.header
import email.utils
import json
import os
import stat
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from html.parser import HTMLParser
from pathlib import Path


STATE_FILE = Path.home() / ".wastemytime_state.json"


@dataclass
class Email:
    uid: str
    subject: str
    sender: str
    sender_email: str
    received_at: datetime
    body_preview: str
    body: str
    is_read: bool


class _HTMLStripper(HTMLParser):
    def __init__(self):
        super().__init__()
        self._parts = []

    def handle_data(self, data):
        self._parts.append(data)

    def get_text(self):
        return "".join(self._parts)


def _strip_html(html: str) -> str:
    s = _HTMLStripper()
    s.feed(html)
    return s.get_text()


def _decode_header(raw: str | None) -> str:
    if not raw:
        return ""
    parts = email.header.decode_header(raw)
    decoded = []
    for data, charset in parts:
        if isinstance(data, bytes):
            decoded.append(data.decode(charset or "utf-8", errors="replace"))
        else:
            decoded.append(data)
    return " ".join(decoded)


def _extract_body(msg: email.message.Message) -> str:
    if msg.is_multipart():
        text_part = None
        html_part = None
        for part in msg.walk():
            ct = part.get_content_type()
            if ct == "text/plain" and text_part is None:
                text_part = part
            elif ct == "text/html" and html_part is None:
                html_part = part
        chosen = text_part or html_part
        if chosen is None:
            return ""
        payload = chosen.get_payload(decode=True)
        if payload is None:
            return ""
        charset = chosen.get_content_charset() or "utf-8"
        text = payload.decode(charset, errors="replace")
        if chosen.get_content_type() == "text/html":
            text = _strip_html(text)
        return text
    else:
        payload = msg.get_payload(decode=True)
        if payload is None:
            return ""
        charset = msg.get_content_charset() or "utf-8"
        text = payload.decode(charset, errors="replace")
        if msg.get_content_type() == "text/html":
            text = _strip_html(text)
        return text


def _load_state() -> dict:
    if STATE_FILE.exists():
        return json.loads(STATE_FILE.read_text())
    return {"seen_uids": [], "last_fetch": None}


def _save_state(state: dict):
    STATE_FILE.write_text(json.dumps(state, default=str))
    os.chmod(STATE_FILE, stat.S_IRUSR | stat.S_IWUSR)


def fetch_new_emails(config: dict) -> list[Email]:
    imap_cfg = config["imap"]
    state = _load_state()
    seen_uids = set(state.get("seen_uids", []))

    conn = imaplib.IMAP4_SSL(imap_cfg["host"], imap_cfg["port"])
    try:
        conn.login(imap_cfg["username"], imap_cfg["password"])
        conn.select("INBOX", readonly=True)

        if state.get("last_fetch"):
            since_date = datetime.fromisoformat(state["last_fetch"]).date()
        else:
            since_date = (datetime.now(timezone.utc) - timedelta(days=imap_cfg.get("lookback_days", 7))).date()

        since_str = since_date.strftime("%d-%b-%Y")
        _status, data = conn.uid("search", None, f"SINCE {since_str}")

        state["last_fetch"] = datetime.now(timezone.utc).isoformat()

        if not data or not data[0] or not data[0].strip():
            _save_state(state)
            return []

        all_uids = data[0].split()
        fetch_limit = imap_cfg.get("fetch_limit", 30)
        all_uids = all_uids[-fetch_limit:]

        new_uids = [u for u in all_uids if u.decode() not in seen_uids]
        if not new_uids:
            _save_state(state)
            return []

        emails = []
        for uid_bytes in new_uids:
            uid_str = uid_bytes.decode()
            _status, msg_data = conn.uid("fetch", uid_bytes, "(RFC822 FLAGS)")
            if not msg_data or not msg_data[0] or not isinstance(msg_data[0], tuple):
                continue

            meta = msg_data[0][0] if isinstance(msg_data[0][0], bytes) else b""
            is_read = b"\\Seen" in meta

            raw_email = msg_data[0][1]
            msg = email.message_from_bytes(raw_email)

            subject = _decode_header(msg.get("Subject"))
            from_header = msg.get("From", "")
            sender_name, sender_addr = email.utils.parseaddr(from_header)
            sender_name = _decode_header(sender_name) or sender_addr

            date_str = msg.get("Date", "")
            received_at = email.utils.parsedate_to_datetime(date_str) if date_str else datetime.now(timezone.utc)

            body = _extract_body(msg)
            body_truncated = body[:3000]
            body_preview = body[:200]

            emails.append(Email(
                uid=uid_str,
                subject=subject,
                sender=sender_name,
                sender_email=sender_addr,
                received_at=received_at,
                body_preview=body_preview,
                body=body_truncated,
                is_read=is_read,
            ))

            seen_uids.add(uid_str)

        state["seen_uids"] = list(seen_uids)
        _save_state(state)

        return emails
    finally:
        try:
            conn.logout()
        except Exception:
            pass
