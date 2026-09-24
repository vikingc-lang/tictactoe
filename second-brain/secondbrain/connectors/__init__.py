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


class Connector(Protocol):
    name: str

    def items(self) -> Iterator[Item]: ...


def build_connector(source: SourceConfig) -> Connector:
    from .gdrive import GoogleDriveConnector
    from .http_json import HttpJsonConnector
    from .local import FolderConnector
    from .web import WebConnector

    registry = {
        "folder": FolderConnector,
        "gdrive": GoogleDriveConnector,
        "web": WebConnector,
        "http_json": HttpJsonConnector,
    }
    if source.type not in registry:
        raise ValueError(f"unknown source type '{source.type}' (known: {', '.join(sorted(registry))})")
    return registry[source.type](source.name, source.options)
