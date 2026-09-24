"""The knowledge graph: how documents get connected.

Three kinds of edges:

* ``explicit`` — the author linked them: ``[[Wiki Links]]`` or ``[text](other.md)``.
* ``related``  — they talk about the same things (TF-IDF cosine similarity).
* ``entity``   — Claude found the same people/companies/projects in both (after ``enrich``).
"""

from __future__ import annotations

import json
import math
from collections import defaultdict
from pathlib import Path, PurePosixPath
from urllib.parse import unquote, urlparse
from urllib.request import url2pathname

from .store import Store
from .text import MDLINK, WIKILINK

RELATED_THRESHOLD = 0.08
RELATED_MAX = 8


def _idf(store: Store) -> dict[str, float]:
    n_docs = store.db.execute("SELECT COUNT(DISTINCT doc_id) FROM terms").fetchone()[0] or 1
    return {r[0]: math.log(1 + n_docs / r[1])
            for r in store.db.execute("SELECT term, COUNT(*) FROM terms GROUP BY term")}


def _vectors(store: Store, idf: dict[str, float]) -> dict[int, dict[str, float]]:
    vecs: dict[int, dict[str, float]] = defaultdict(dict)
    for doc_id, term, tf in store.db.execute(
            "SELECT t.doc_id, t.term, t.tf FROM terms t JOIN documents d ON d.id = t.doc_id WHERE d.deleted = 0"):
        vecs[doc_id][term] = tf * idf.get(term, 0.0)
    return vecs


def _cosine(a: dict[str, float], b: dict[str, float]) -> float:
    if len(a) > len(b):
        a, b = b, a
    dot = sum(w * b.get(t, 0.0) for t, w in a.items())
    if not dot:
        return 0.0
    na = math.sqrt(sum(w * w for w in a.values()))
    nb = math.sqrt(sum(w * w for w in b.values()))
    return dot / (na * nb)


def _shared_terms(a: dict[str, float], b: dict[str, float], n: int = 4) -> str:
    shared = sorted(set(a) & set(b), key=lambda t: -(a[t] * b[t]))[:n]
    return ", ".join(shared)


def link_related(store: Store, doc_ids: list[int]) -> None:
    """Recompute similarity edges for the given (changed) documents against the whole brain."""
    if not doc_ids:
        return
    idf = _idf(store)
    vecs = _vectors(store, idf)
    for doc_id in doc_ids:
        mine = vecs.get(doc_id)
        if not mine:
            continue
        scored = []
        for other, vec in vecs.items():
            if other == doc_id:
                continue
            s = _cosine(mine, vec)
            if s >= RELATED_THRESHOLD:
                scored.append((other, round(s, 3), _shared_terms(mine, vec)))
        scored.sort(key=lambda x: -x[1])
        store.replace_links(doc_id, "related", scored[:RELATED_MAX])


def _resolve_target(store: Store, target: str, base_uri: str) -> int | None:
    target = unquote(target.strip())
    if target.startswith(("http://", "https://")):
        doc = store.get_by_uri(target)
        return doc.id if doc and store.get(doc.id) else None
    path_part = target.split("#")[0]
    if base_uri.startswith("file://") and path_part:
        base = Path(url2pathname(urlparse(base_uri).path)).parent
        candidate = (base / unquote(path_part)).resolve()
        doc = store.get_by_uri(candidate.as_uri())
        if doc and store.get(doc.id):
            return doc.id
    stem = PurePosixPath(path_part).stem or target
    doc = store.find_by_title(target) or store.find_by_title(stem)
    return doc.id if doc else None


def link_explicit(store: Store, doc_ids: list[int]) -> list[str]:
    """Create edges for [[wikilinks]] and markdown links. Returns unresolved targets."""
    unresolved = []
    for doc_id in doc_ids:
        doc = store.get(doc_id)
        if not doc:
            continue
        targets: dict[int, tuple[int, float, str]] = {}
        refs = [m.group(1) for m in WIKILINK.finditer(doc.text)]
        refs += [m.group(1) for m in MDLINK.finditer(doc.text) if not m.group(1).startswith("#")]
        for ref in refs:
            dst = _resolve_target(store, ref, doc.uri)
            if dst is None:
                unresolved.append(ref)
            elif dst != doc_id:
                targets[dst] = (dst, 1.0, ref)
        store.replace_links(doc_id, "explicit", list(targets.values()))
    return unresolved


def relink_unresolved(store: Store, new_titles: set[str]) -> list[int]:
    """Docs that mention a newly-added title via [[...]] need their explicit links refreshed."""
    if not new_titles:
        return []
    hits = []
    for row in store.db.execute("SELECT id, text FROM documents WHERE deleted = 0 AND text LIKE '%[[%'"):
        refs = {m.group(1).strip().lower() for m in WIKILINK.finditer(row["text"])}
        if refs & {t.lower() for t in new_titles}:
            hits.append(row["id"])
    return hits


def link_entities(store: Store) -> None:
    """Connect documents that share entities extracted by ``enrich``."""
    by_entity: dict[str, list[int]] = defaultdict(list)
    for row in store.db.execute("SELECT id, entities FROM documents WHERE deleted = 0 AND entities != '[]'"):
        for ent in json.loads(row["entities"]):
            by_entity[ent.strip().lower()].append(row["id"])
    edges: dict[int, dict[int, list[str]]] = defaultdict(lambda: defaultdict(list))
    for ent, ids in by_entity.items():
        if 1 < len(ids) <= 50:  # skip entities that are everywhere
            for a in ids:
                for b in ids:
                    if a != b:
                        edges[a][b].append(ent)
    store.db.execute("DELETE FROM links WHERE kind = 'entity'")
    for src, dsts in edges.items():
        store.replace_links(src, "entity", [(dst, float(len(ents)), ", ".join(ents[:4])) for dst, ents in dsts.items()])
    store.commit()


def export_graph(store: Store) -> dict:
    nodes = [{"id": d.id, "title": d.title, "kind": d.kind, "source": d.source, "uri": d.uri}
             for d in store.list_documents(limit=100000)]
    return {"nodes": nodes, "edges": store.all_links()}
