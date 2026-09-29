"""Connectors pull items from a place (folder, cloud drive, website, API) into the brain.

Every connector yields :class:`Item` objects. The indexer only calls ``item.load()``
when an item looks new or changed, so incremental syncs stay cheap.

To add a new place, write a class with ``__init__(self, name, options)`` and
``items(self) -> Iterator[Item]`` and register it in ``CONNECTORS``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Iterator, Protocol

from ..config import SourceConfig


@dataclass
class Item:
    uri: str                      # stable, unique identifier (path, URL, drive id...)
    title: str
    ext: str                      # file extension used to pick a parser, e.g. ".pdf"
    modified: float | None        # change marker; None means "always check the content hash"
    load: Callable[[], bytes]
    text: str | None = None       # already-extracted text (skips the file parser)
    parent_uri: str | None = None  # e.g. the email an attachment came with
    date: float | None = None      # when it was written/sent (defaults to the file's modified time)


class Connector(Protocol):
    name: str

    def items(self) -> Iterator[Item]: ...

    # Optional hooks the indexer sets/reads:
    #   known: dict[str, float | None]  - uri -> stored change marker, so a connector can skip
    #                                      re-downloading things it already delivered (e.g. emails)
    #   prune: bool                      - False keeps documents that disappear from the source


def build_connector(source: SourceConfig) -> Connector:
    from .gdrive import GoogleDriveConnector
    from .http_json import HttpJsonConnector
    from .imap import ImapConnector
    from .local import FolderConnector
    from .web import WebConnector

    registry = {
        "folder": FolderConnector,
        "gdrive": GoogleDriveConnector,
        "web": WebConnector,
        "http_json": HttpJsonConnector,
        "imap": ImapConnector,
    }
    if source.type not in registry:
        raise ValueError(f"unknown source type '{source.type}' (known: {', '.join(sorted(registry))})")
    return registry[source.type](source.name, source.options)
