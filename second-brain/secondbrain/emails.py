"""Email parsing shared by the IMAP connector, folder sources (.eml / .mbox / .msg) and the parsers.

An email becomes one document (headers + readable body + a list of its attachments), and every
attachment in a supported format becomes its own document, linked back to the email.
"""

from __future__ import annotations

import email
import email.utils
import mailbox
import os
import re
from dataclasses import dataclass, field
from email import policy
from email.message import EmailMessage
from pathlib import Path
from typing import Iterator

MAX_ATTACHMENT_BYTES = 25 * 1024 * 1024


@dataclass
class Attachment:
    filename: str
    data: bytes

    @property
    def ext(self) -> str:
        return os.path.splitext(self.filename)[1].lower()


@dataclass
class ParsedEmail:
    subject: str
    sender: str
    to: str
    date: str
    timestamp: float | None
    body: str
    message_id: str = ""
    attachments: list[Attachment] = field(default_factory=list)

    def as_text(self) -> str:
        lines = [f"# {self.subject or '(no subject)'}", "",
                 f"From: {self.sender}", f"To: {self.to}", f"Date: {self.date}"]
        if self.attachments:
            lines.append("Attachments: " + ", ".join(a.filename for a in self.attachments))
        return "\n".join(lines) + "\n\n" + self.body.strip()


def _html_to_text(html: str) -> str:
    from .parsers import html_to_text  # local import: parsers imports this module

    return html_to_text(html)[1]


def _safe_filename(name: str) -> str:
    name = re.sub(r"[\\/:*?\"<>|\r\n]+", "_", name).strip() or "attachment"
    return name[:150]


def parse_bytes(raw: bytes) -> ParsedEmail:
    """Parse an RFC 822 message (.eml / IMAP fetch / one mbox entry)."""
    msg: EmailMessage = email.message_from_bytes(raw, policy=policy.default)  # type: ignore[assignment]
    return _from_message(msg)


def _from_message(msg: EmailMessage) -> ParsedEmail:
    body_part = msg.get_body(preferencelist=("plain", "html"))
    body = ""
    if body_part is not None:
        try:
            body = body_part.get_content()
        except (LookupError, UnicodeDecodeError):
            body = body_part.get_payload(decode=True).decode("utf-8", errors="replace")
        if body_part.get_content_type() == "text/html":
            body = _html_to_text(body)
    attachments = []
    for part in msg.iter_attachments():
        filename = part.get_filename()
        if not filename:
            continue
        data = part.get_payload(decode=True) or b""
        if part.get_content_type() == "message/rfc822" and not data:
            inner = part.get_payload()
            data = inner[0].as_bytes() if isinstance(inner, list) and inner else b""
        if data and len(data) <= MAX_ATTACHMENT_BYTES:
            attachments.append(Attachment(_safe_filename(filename), data))
    date = str(msg.get("date", "") or "")
    try:
        ts = email.utils.parsedate_to_datetime(date).timestamp() if date else None
    except (TypeError, ValueError):
        ts = None
    return ParsedEmail(subject=str(msg.get("subject", "") or ""), sender=str(msg.get("from", "") or ""),
                       to=str(msg.get("to", "") or ""), date=date, timestamp=ts, body=body or "",
                       message_id=str(msg.get("message-id", "") or "").strip(), attachments=attachments)


def parse_msg(raw: bytes) -> ParsedEmail:
    """Outlook .msg files (needs the optional ``extract-msg`` package)."""
    try:
        import extract_msg
    except ImportError as exc:
        raise ValueError("install extract-msg to read Outlook .msg files: pip install extract-msg") from exc
    m = extract_msg.openMsg(raw)
    try:
        body = m.body or (_html_to_text(m.htmlBody.decode("utf-8", "replace")) if m.htmlBody else "")
        attachments = []
        for a in m.attachments:
            data = getattr(a, "data", None)
            name = getattr(a, "longFilename", None) or getattr(a, "shortFilename", None)
            if isinstance(data, bytes) and name and len(data) <= MAX_ATTACHMENT_BYTES:
                attachments.append(Attachment(_safe_filename(name), data))
        ts = m.date.timestamp() if getattr(m, "date", None) else None
        return ParsedEmail(subject=m.subject or "", sender=m.sender or "", to=m.to or "", date=str(m.date or ""),
                           timestamp=ts, body=body or "", message_id=getattr(m, "messageId", "") or "",
                           attachments=attachments)
    finally:
        m.close()


def parse_file_bytes(raw: bytes, ext: str) -> ParsedEmail:
    return parse_msg(raw) if ext == ".msg" else parse_bytes(raw)


def iter_mbox(path: Path) -> Iterator[tuple[int, ParsedEmail]]:
    """Messages of an .mbox archive (Gmail Takeout, Thunderbird, Apple Mail export)."""
    box = mailbox.mbox(str(path), create=False)
    try:
        for i, key in enumerate(box.iterkeys()):
            yield i, parse_bytes(box.get_bytes(key))
    finally:
        box.close()
