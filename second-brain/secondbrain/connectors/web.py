"""Web pages and online files by URL (articles, public docs, PDFs, RSS-linked pages)."""

from __future__ import annotations

import urllib.request
from pathlib import PurePosixPath
from typing import Any, Iterator
from urllib.parse import urlparse

from . import Item

USER_AGENT = "SecondBrain/0.1 (+personal knowledge indexer)"


def fetch(url: str, headers: dict[str, str] | None = None, timeout: int = 30) -> tuple[bytes, str]:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, **(headers or {})})
    with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310 - URLs come from the user's config
        return resp.read(), resp.headers.get_content_type()


def ext_for(url: str, content_type: str | None = None) -> str:
    suffix = PurePosixPath(urlparse(url).path).suffix.lower()
    if suffix in {".pdf", ".docx", ".pptx", ".xlsx", ".md", ".txt", ".csv", ".json"}:
        return suffix
    if content_type == "application/pdf":
        return ".pdf"
    return ".html"


class WebConnector:
    def __init__(self, name: str, options: dict[str, Any]):
        self.name = name
        self.urls: list[str] = options.get("urls", [])

    def items(self) -> Iterator[Item]:
        for url in self.urls:
            title = urlparse(url).netloc + urlparse(url).path
            # modified=None -> the indexer fetches and compares content hashes each sync.
            yield Item(uri=url, title=title, ext=ext_for(url), modified=None,
                       load=lambda u=url: fetch(u)[0])
