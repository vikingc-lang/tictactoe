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

from ..parsers import SUPPORTED_EXTS
from . import Item

DEFAULT_EXCLUDE = [".git", "node_modules", "__pycache__", ".venv", ".obsidian", ".trash", "~$*", ".DS_Store"]


class FolderConnector:
    def __init__(self, name: str, options: dict[str, Any]):
        self.name = name
        self.root = Path(os.path.expanduser(options["path"])).resolve()
        self.include: list[str] = options.get("include", [])
        self.exclude: list[str] = DEFAULT_EXCLUDE + options.get("exclude", [])
        self.max_bytes = int(options.get("max_mb", 50)) * 1024 * 1024

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
                if st.st_size > self.max_bytes:
                    continue
                yield Item(uri=path.as_uri(), title=path.stem, ext=ext, modified=st.st_mtime,
                           load=path.read_bytes)
