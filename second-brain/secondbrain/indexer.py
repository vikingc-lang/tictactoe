"""Incremental sync: pull items from every source, parse, chunk, index and link them."""

from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass, field
from typing import Callable

from . import graph
from .config import SourceConfig
from .connectors import Item, build_connector
from .parsers import MAX_TEXT_CHARS, kind_for, parse
from .store import Store
from .text import chunk_text, term_frequencies, title_from_text

log = logging.getLogger("secondbrain.indexer")


@dataclass
class SyncStats:
    source: str
    seen: int = 0
    added: int = 0
    updated: int = 0
    unchanged: int = 0
    removed: int = 0
    errors: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {k: v for k, v in self.__dict__.items()}


def index_item(store: Store, source: str, item: Item, text: str | None = None) -> tuple[int, str]:
    """Index a single item. Returns (doc_id, 'added' | 'updated' | 'unchanged')."""
    existing = store.get_by_uri(item.uri)
    if (text is None and existing is not None and item.modified is not None
            and existing.modified == item.modified and store.get(existing.id) is not None):
        return existing.id, "unchanged"
    title_hint = None
    if text is None:
        text = item.text
        title_hint = item.title if item.text is not None else None
    if text is None:
        text, title_hint = parse(item.load(), item.ext)
    text = text.strip()
    if len(text) > MAX_TEXT_CHARS:
        text = text[:MAX_TEXT_CHARS] + "\n\n… (document truncated for indexing)"
    if not text:
        raise ValueError("no readable text (empty file, or a scanned PDF that needs OCR)")
    title = title_hint or title_from_text(text) or item.title
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
    doc_id, changed = store.upsert_document(
        source=source, uri=item.uri, title=title, kind=kind_for(item.ext), content_hash=digest,
        modified=item.modified, text=text,
        doc_date=item.date or (item.modified if item.modified and item.modified > 1e8 else None),
    )
    if not changed:
        return doc_id, "unchanged"
    store.clear_derived(doc_id)
    store.write_chunks(doc_id, title, chunk_text(text))
    store.write_terms(doc_id, term_frequencies(f"{title}\n{text}"))
    return doc_id, "added" if existing is None else "updated"


def refresh_links(store: Store, changed: list[int]) -> None:
    if not changed:
        return
    titles = {d.title for i in changed if (d := store.get(i))}
    graph.link_explicit(store, sorted(set(changed) | set(graph.relink_unresolved(store, titles))))
    graph.link_related(store, changed)
    store.commit()


def sync_source(store: Store, source: SourceConfig,
                on_progress: Callable[[SyncStats], None] | None = None,
                should_stop: Callable[[], bool] | None = None) -> SyncStats:
    stats = SyncStats(source.name)
    stopped = False
    connector = build_connector(source)
    known = store.uris_for_source(source.name)
    connector.known = store.modified_for_source(source.name)  # lets connectors skip re-downloading
    seen: set[str] = set()
    changed: list[int] = []
    children: dict[str, list[int]] = {}  # parent uri -> changed attachment doc ids
    try:
        for item in connector.items():
            if should_stop and should_stop():
                stopped = True
                break
            stats.seen += 1
            seen.add(item.uri)
            try:
                doc_id, outcome = index_item(store, source.name, item)
            except Exception as exc:  # one bad file must not stop the sync
                stats.errors.append(f"{item.uri}: {exc}")
                log.warning("failed to index %s: %s", item.uri, exc)
                continue
            setattr(stats, outcome, getattr(stats, outcome) + 1)
            if outcome != "unchanged":
                changed.append(doc_id)
                if item.parent_uri:
                    children.setdefault(item.parent_uri, []).append(doc_id)
            if stats.seen % 25 == 0:
                store.commit()  # keep write transactions short so readers and `remember` aren't blocked
                if on_progress:
                    on_progress(stats)
    except Exception as exc:
        # Source unreachable (offline drive, network down): keep what we already know.
        stats.errors.append(f"source error: {exc}")
        store.commit()
        store.record_sync(source.name, source.type, stats.as_dict())
        return stats
    if stopped:  # cancelled part-way: keep everything already indexed, and don't treat unvisited files as deleted
        store.commit()
        stats.errors.append("stopped before finishing; press Sync to continue")
        store.record_sync(source.name, source.type, stats.as_dict())
        return stats
    if getattr(connector, "prune", True):
        for uri, doc_id in known.items():
            if uri not in seen:
                store.mark_deleted(doc_id)
                stats.removed += 1
    for parent_uri, child_ids in children.items():
        parent = store.get_by_uri(parent_uri)
        if parent:
            store.replace_links(parent.id, "attachment", [(c, 1.0, "attachment") for c in child_ids])
    store.commit()
    refresh_links(store, changed)
    store.record_sync(source.name, source.type, stats.as_dict())
    return stats
