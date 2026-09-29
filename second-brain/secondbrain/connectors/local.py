"""Local folders — including cloud folders synced to disk.

This one connector covers offline folders, USB/network drives, and every cloud
service with a desktop sync client: OneDrive, SharePoint, Dropbox, Google Drive
for desktop, iCloud Drive, Box. Point ``path`` at the synced folder.
"""

from __future__ import annotations

import fnmatch
import os
from pathlib import Path
from typing import Any, Iterator

from ..emails import iter_mbox, parse_file_bytes
from ..parsers import EMAIL_EXTS, SUPPORTED_EXTS
from . import Item
from .email_items import cached_items, email_to_items

DEFAULT_EXCLUDE = [".git", "node_modules", "__pycache__", ".venv", ".obsidian", ".trash", "~$*", ".DS_Store"]


class FolderConnector:
    def __init__(self, name: str, options: dict[str, Any]):
        self.name = name
        self.root = Path(os.path.expanduser(options["path"])).resolve()
        self.include: list[str] = options.get("include", [])
        self.exclude: list[str] = DEFAULT_EXCLUDE + options.get("exclude", [])
        self.max_bytes = int(options.get("max_mb", 50)) * 1024 * 1024
        self.mbox_max_bytes = int(options.get("mbox_max_mb", 2048)) * 1024 * 1024
        self.attachments = bool(options.get("attachments", True))
        self.known: dict[str, float | None] = {}

    def _excluded(self, name: str) -> bool:
        return any(fnmatch.fnmatch(name, pat) for pat in self.exclude)

    def items(self) -> Iterator[Item]:
        if not self.root.exists():
            raise FileNotFoundError(f"folder not found: {self.root}")
        for dirpath, dirnames, filenames in os.walk(self.root):
            dirnames[:] = [d for d in dirnames if not self._excluded(d)]
            for fname in filenames:
                if self._excluded(fname):
                    continue
                path = Path(dirpath) / fname
                ext = path.suffix.lower()
                if ext not in SUPPORTED_EXTS:
                    continue
                if self.include and not any(fnmatch.fnmatch(fname, pat) for pat in self.include):
                    continue
                try:
                    st = path.stat()
                except OSError:
                    continue
                if ext in EMAIL_EXTS:
                    yield from self._email_items(path, ext, st.st_mtime, st.st_size)
                    continue
                if st.st_size > self.max_bytes:
                    continue
                yield Item(uri=path.as_uri(), title=path.stem, ext=ext, modified=st.st_mtime,
                           load=path.read_bytes)

    def _email_items(self, path: Path, ext: str, mtime: float, size: int) -> Iterator[Item]:
        """Saved emails (.eml, Outlook .msg) and mail archives (.mbox): one item per message plus
        one per attachment. Unchanged files are re-announced from the index without re-parsing."""
        uri = path.as_uri()
        if ext != ".mbox":
            cached = cached_items(uri, self.known, mtime)
            if cached is not None:
                yield from cached
                return
        elif self.known.get(f"{uri}#msg0") == mtime:
            for u, m in self.known.items():  # whole archive unchanged
                if u.startswith(uri + "#") and m == mtime:
                    yield Item(uri=u, title="", ext=".eml", modified=mtime, load=_never)
            return
        try:
            if ext == ".mbox":
                if size > self.mbox_max_bytes:
                    raise ValueError(f"mail archive larger than {self.mbox_max_bytes // 2**20} MB (raise mbox_max_mb)")
                for i, parsed in iter_mbox(path):
                    yield from email_to_items(f"{uri}#msg{i}", parsed, mtime, self.attachments)
            else:
                if size > self.max_bytes:
                    return
                yield from email_to_items(uri, parse_file_bytes(path.read_bytes(), ext), mtime, self.attachments)
        except Exception as exc:  # report as a per-file error instead of failing the whole folder
            message = str(exc)

            def fail() -> bytes:
                raise ValueError(message)

            yield Item(uri=uri, title=path.stem, ext=".eml", modified=None, load=fail)


def _never() -> bytes:
    raise RuntimeError("item content not loaded")
