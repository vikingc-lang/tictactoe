"""Email mailboxes over IMAP: Gmail, iCloud, Yahoo, Fastmail, Zoho, company mail servers.

    [[sources]]
    name = "gmail"
    type = "imap"
    host = "imap.gmail.com"
    username = "you@gmail.com"
    password = "${GMAIL_APP_PASSWORD}"     # an app password, not your normal password
    folders = ["INBOX", "[Gmail]/Sent Mail"]
    since_days = 365                        # how far back to read
    search = 'FROM "acme.com"'              # optional extra IMAP search criteria
    attachments = true                      # index PDF/Word/Excel/PowerPoint attachments too

Microsoft 365 / Outlook.com mailboxes need OAuth: set ``oauth2_token = "${O365_TOKEN}"`` to an
access token with the IMAP.AccessAsUser.All scope (or save Outlook emails into a folder source).

Messages are opened read-only with BODY.PEEK, so nothing is marked as read, and each message is
downloaded only once. Emails that later leave the search window stay in the brain (``prune = false``).
"""

from __future__ import annotations

import imaplib
from datetime import date, timedelta
from typing import Any, Iterator
from urllib.parse import quote

from ..emails import parse_bytes
from . import Item
from .email_items import cached_items, email_to_items

_MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
MESSAGE_VERSION = 1.0  # emails never change once sent, so every message has the same change marker


def imap_date(d: date) -> str:
    return f"{d.day:02d}-{_MONTHS[d.month - 1]}-{d.year}"  # locale-independent, e.g. 05-Mar-2026


class ImapConnector:
    def __init__(self, name: str, options: dict[str, Any]):
        self.name = name
        self.host: str = options["host"]
        self.port = int(options.get("port", 993))
        self.ssl = bool(options.get("ssl", True))
        self.username: str = options["username"]
        self.password: str = options.get("password", "")
        self.oauth2_token: str = options.get("oauth2_token", "")
        self.folders: list[str] = options.get("folders", ["INBOX"])
        self.since_days = int(options.get("since_days", 365))
        self.max_messages = int(options.get("max_messages", 2000))
        self.search: str = options.get("search", "")
        self.attachments = bool(options.get("attachments", True))
        self.prune = bool(options.get("prune", False))
        self.timeout = float(options.get("timeout", 30))
        self.known: dict[str, float | None] = {}

    def _connect(self) -> imaplib.IMAP4:
        try:
            conn = (imaplib.IMAP4_SSL(self.host, self.port, timeout=self.timeout) if self.ssl
                    else imaplib.IMAP4(self.host, self.port, timeout=self.timeout))
        except (TimeoutError, OSError) as exc:
            raise ConnectionError(f"can't reach {self.host}:{self.port} ({exc or 'timed out'})") from exc
        if not self.ssl:
            conn.starttls()
        if self.oauth2_token:
            auth = f"user={self.username}\x01auth=Bearer {self.oauth2_token}\x01\x01".encode()
            conn.authenticate("XOAUTH2", lambda _: auth)
        else:
            if not self.password:
                raise ValueError(f"{self.name}: no password (use an app password, e.g. password = \"${{GMAIL_APP_PASSWORD}}\")")
            conn.login(self.username, self.password)
        return conn

    def items(self) -> Iterator[Item]:
        conn = self._connect()
        try:
            since = imap_date(date.today() - timedelta(days=self.since_days))
            for folder in self.folders:
                typ, _ = conn.select(f'"{folder}"', readonly=True)
                if typ != "OK":
                    raise ValueError(f"{self.name}: cannot open folder {folder!r}")
                validity = (conn.response("UIDVALIDITY")[1] or [b"0"])[0]
                validity = validity.decode() if isinstance(validity, bytes) else str(validity)
                criteria = f"SINCE {since}" + (f" {self.search}" if self.search else "")
                typ, data = conn.uid("SEARCH", None, criteria)
                if typ != "OK":
                    raise ValueError(f"{self.name}: search failed in {folder!r}")
                uids = (data[0] or b"").split()[-self.max_messages:]
                base = f"imap://{quote(self.username)}@{self.host}/{quote(folder, safe='')}/{validity}"
                for uid in reversed(uids):  # newest first
                    uid_s = uid.decode()
                    uri = f"{base}/{uid_s}"
                    cached = cached_items(uri, self.known, MESSAGE_VERSION)
                    if cached is not None:
                        yield from cached
                        continue
                    typ, fetched = conn.uid("FETCH", uid_s, "(BODY.PEEK[])")
                    raw = next((part[1] for part in fetched or [] if isinstance(part, tuple)), None)
                    if typ != "OK" or not raw:
                        continue
                    yield from email_to_items(uri, parse_bytes(raw), MESSAGE_VERSION, self.attachments)
        finally:
            try:
                conn.logout()
            except (imaplib.IMAP4.error, OSError):
                pass
