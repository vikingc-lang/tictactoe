"""Turn a parsed email into brain items: one for the message, one per readable attachment."""

from __future__ import annotations

import os
from typing import Iterator

from ..emails import ParsedEmail
from ..parsers import SUPPORTED_EXTS
from . import Item

# Attachments that are really just more email get indexed as email too.
ATTACHMENT_EXTS = (SUPPORTED_EXTS - {".mbox"}) | {".eml"}


def _unavailable() -> bytes:  # cached items are never loaded (the indexer sees they're unchanged)
    raise RuntimeError("item content not loaded")


def email_to_items(uri: str, parsed: ParsedEmail, modified: float | None,
                   attachments: bool = True) -> Iterator[Item]:
    yield Item(uri=uri, title=parsed.subject or "(no subject)", ext=".eml", modified=modified,
               load=_unavailable, text=parsed.as_text())
    if not attachments:
        return
    for i, att in enumerate(parsed.attachments):
        if att.ext not in ATTACHMENT_EXTS:
            continue
        yield Item(uri=f"{uri}#att{i}-{att.filename}", title=os.path.splitext(att.filename)[0], ext=att.ext,
                   modified=modified, load=lambda d=att.data: d, parent_uri=uri)


def cached_items(uri: str, known: dict[str, float | None], modified: float | None) -> list[Item] | None:
    """If this email and its attachments are already indexed at this version, re-announce them
    without downloading or parsing anything. Returns None when (re)processing is needed."""
    if modified is None or known.get(uri, -1) != modified:
        return None
    prefix = uri + "#"
    out = [Item(uri=uri, title="", ext=".eml", modified=modified, load=_unavailable)]
    for u, m in known.items():
        if u.startswith(prefix):
            if m != modified:
                return None
            out.append(Item(uri=u, title="", ext=os.path.splitext(u)[1].lower() or ".eml", modified=modified,
                            load=_unavailable, parent_uri=uri))
    return out
