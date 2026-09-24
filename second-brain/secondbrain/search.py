"""Retrieval: full-text search (BM25) with a small boost from the knowledge graph."""

from __future__ import annotations

from dataclasses import dataclass

from .store import Store
from .text import tokenize


@dataclass
class Hit:
    doc_id: int
    chunk_id: int
    title: str
    uri: str
    source: str
    text: str
    score: float

    def to_dict(self) -> dict:
        return dict(self.__dict__)


def _fts_query(query: str) -> str:
    terms = tokenize(query) or [w for w in query.split() if w]
    return " OR ".join('"' + t.replace('"', "") + '"' for t in terms[:20])


def search(store: Store, query: str, limit: int = 8, per_doc: int = 2, source: str | None = None) -> list[Hit]:
    q = _fts_query(query)
    if not q:
        return []
    sql = """
        SELECT f.chunk_id, f.doc_id, f.text, bm25(chunks_fts, 0, 0, 3.0, 1.0) AS rank,
               d.title, d.uri, d.source
        FROM chunks_fts f JOIN documents d ON d.id = f.doc_id
        WHERE chunks_fts MATCH ? AND d.deleted = 0
    """
    args: list = [q]
    if source:
        sql += " AND d.source = ?"
        args.append(source)
    sql += " ORDER BY rank LIMIT ?"
    args.append(limit * 6)
    rows = store.db.execute(sql, args).fetchall()
    if not rows:
        return []

    # Graph boost: chunks from documents linked to other top results are more likely to matter.
    top_docs = {r["doc_id"] for r in rows[: limit * 2]}
    placeholders = ",".join("?" * len(top_docs))
    degree: dict[int, int] = {}
    for r in store.db.execute(
            f"SELECT src, COUNT(*) FROM links WHERE src IN ({placeholders}) AND dst IN ({placeholders}) GROUP BY src",
            [*top_docs, *top_docs]):
        degree[r[0]] = r[1]

    hits: list[Hit] = []
    per: dict[int, int] = {}
    for r in rows:
        score = -r["rank"] * (1 + 0.15 * degree.get(r["doc_id"], 0))
        hits.append(Hit(r["doc_id"], r["chunk_id"], r["title"], r["uri"], r["source"], r["text"], round(score, 4)))
    hits.sort(key=lambda h: -h.score)
    out = []
    for h in hits:
        if per.get(h.doc_id, 0) >= per_doc:
            continue
        per[h.doc_id] = per.get(h.doc_id, 0) + 1
        out.append(h)
        if len(out) >= limit:
            break
    return out
