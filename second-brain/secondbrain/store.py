"""SQLite-backed knowledge store: documents, chunks (full-text indexed), links and revisions.

One file (``brain.db``) holds everything, so the brain is portable, works fully
offline, and can be backed up by copying a single file.
"""

from __future__ import annotations

import json
import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

SCHEMA = """
CREATE TABLE IF NOT EXISTS documents (
    id            INTEGER PRIMARY KEY,
    source        TEXT NOT NULL,
    uri           TEXT NOT NULL UNIQUE,
    title         TEXT NOT NULL,
    kind          TEXT NOT NULL,
    content_hash  TEXT NOT NULL,
    modified      REAL,
    indexed_at    REAL NOT NULL,
    summary       TEXT,
    tags          TEXT DEFAULT '[]',
    entities      TEXT DEFAULT '[]',
    text          TEXT NOT NULL,
    deleted       INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_documents_source ON documents(source);

CREATE TABLE IF NOT EXISTS revisions (
    doc_id       INTEGER NOT NULL,
    content_hash TEXT NOT NULL,
    indexed_at   REAL NOT NULL,
    summary      TEXT,
    text         TEXT
);

CREATE TABLE IF NOT EXISTS chunks (
    id     INTEGER PRIMARY KEY,
    doc_id INTEGER NOT NULL,
    ord    INTEGER NOT NULL,
    text   TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_chunks_doc ON chunks(doc_id);

CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts USING fts5(
    chunk_id UNINDEXED, doc_id UNINDEXED, title, text, tokenize = 'porter unicode61'
);

CREATE TABLE IF NOT EXISTS terms (
    doc_id INTEGER NOT NULL,
    term   TEXT NOT NULL,
    tf     REAL NOT NULL,
    PRIMARY KEY (doc_id, term)
);
CREATE INDEX IF NOT EXISTS idx_terms_term ON terms(term);

CREATE TABLE IF NOT EXISTS links (
    src    INTEGER NOT NULL,
    dst    INTEGER NOT NULL,
    kind   TEXT NOT NULL,          -- explicit | related | entity
    weight REAL NOT NULL DEFAULT 1,
    label  TEXT,
    PRIMARY KEY (src, dst, kind)
);
CREATE INDEX IF NOT EXISTS idx_links_dst ON links(dst);

CREATE TABLE IF NOT EXISTS collections (
    name    TEXT PRIMARY KEY,
    doc_ids TEXT NOT NULL DEFAULT '[]',
    updated REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS sources (
    name      TEXT PRIMARY KEY,
    type      TEXT NOT NULL,
    last_sync REAL,
    last_stats TEXT
);
"""


@dataclass
class Document:
    id: int
    source: str
    uri: str
    title: str
    kind: str
    modified: float | None
    indexed_at: float
    summary: str | None
    tags: list[str]
    entities: list[str]
    text: str
    doc_date: float | None = None

    def to_dict(self, include_text: bool = False) -> dict[str, Any]:
        d = {
            "id": self.id, "source": self.source, "uri": self.uri, "title": self.title,
            "kind": self.kind, "modified": self.modified, "indexed_at": self.indexed_at,
            "summary": self.summary, "tags": self.tags, "entities": self.entities, "date": self.doc_date,
        }
        if include_text:
            d["text"] = self.text
        return d


def _row_to_doc(row: sqlite3.Row) -> Document:
    return Document(
        id=row["id"], source=row["source"], uri=row["uri"], title=row["title"], kind=row["kind"],
        modified=row["modified"], indexed_at=row["indexed_at"], summary=row["summary"],
        tags=json.loads(row["tags"] or "[]"), entities=json.loads(row["entities"] or "[]"),
        doc_date=row["doc_date"] if "doc_date" in row.keys() else None,
        text=row["text"],
    )


class Store:
    def __init__(self, path: Path | str):
        self.path = str(path)
        self.db = sqlite3.connect(self.path, check_same_thread=False, timeout=60)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("PRAGMA synchronous=NORMAL")   # safe with WAL; far fewer disk flushes while syncing
        self.db.execute("PRAGMA cache_size=-65536")    # ~64 MB page cache
        self.db.execute("PRAGMA temp_store=MEMORY")
        self.db.executescript(SCHEMA)
        self._migrate()

    def _migrate(self) -> None:
        cols = {r["name"] for r in self.db.execute("PRAGMA table_info(documents)")}
        if "doc_date" not in cols:  # added in v0.3: when the document was written/sent
            self.db.execute("ALTER TABLE documents ADD COLUMN doc_date REAL")
            self.db.execute("UPDATE documents SET doc_date = CASE WHEN modified > 1e8 THEN modified ELSE indexed_at END")
            self.db.commit()

    def close(self) -> None:
        self.db.close()

    # ---- documents -------------------------------------------------------
    def get_by_uri(self, uri: str) -> Document | None:
        row = self.db.execute("SELECT * FROM documents WHERE uri = ?", (uri,)).fetchone()
        return _row_to_doc(row) if row else None

    def get(self, doc_id: int) -> Document | None:
        row = self.db.execute("SELECT * FROM documents WHERE id = ? AND deleted = 0", (doc_id,)).fetchone()
        return _row_to_doc(row) if row else None

    def find_by_title(self, title: str) -> Document | None:
        row = self.db.execute(
            "SELECT * FROM documents WHERE deleted = 0 AND lower(title) = lower(?) ORDER BY indexed_at DESC",
            (title.strip(),),
        ).fetchone()
        return _row_to_doc(row) if row else None

    def list_documents(self, source: str | None = None, limit: int = 100, offset: int = 0,
                       kind: str | None = None) -> list[Document]:
        sql = "SELECT * FROM documents WHERE deleted = 0"
        args: list[Any] = []
        if source:
            sql += " AND source = ?"
            args.append(source)
        if kind:
            sql += " AND kind = ?"
            args.append(kind)
        sql += " ORDER BY indexed_at DESC LIMIT ? OFFSET ?"
        args += [limit, offset]
        return [_row_to_doc(r) for r in self.db.execute(sql, args)]

    def upsert_document(self, *, source: str, uri: str, title: str, kind: str, content_hash: str,
                        modified: float | None, text: str, doc_date: float | None = None) -> tuple[int, bool]:
        """Insert or update a document. Returns (doc_id, content_changed)."""
        now = time.time()
        existing = self.db.execute("SELECT * FROM documents WHERE uri = ?", (uri,)).fetchone()
        if existing is None:
            cur = self.db.execute(
                "INSERT INTO documents (source, uri, title, kind, content_hash, modified, indexed_at, text, doc_date) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (source, uri, title, kind, content_hash, modified, now, text, doc_date or now),
            )
            return int(cur.lastrowid), True
        doc_id = existing["id"]
        if existing["content_hash"] == content_hash and not existing["deleted"]:
            self.db.execute("UPDATE documents SET modified = ?, title = ?, doc_date = COALESCE(?, doc_date) WHERE id = ?",
                            (modified, title, doc_date, doc_id))
            return doc_id, False
        # Content changed: keep the previous version as a revision so history is never lost.
        self.db.execute(
            "INSERT INTO revisions (doc_id, content_hash, indexed_at, summary, text) VALUES (?, ?, ?, ?, ?)",
            (doc_id, existing["content_hash"], existing["indexed_at"], existing["summary"], existing["text"]),
        )
        self.db.execute(
            "UPDATE documents SET source = ?, title = ?, kind = ?, content_hash = ?, modified = ?, indexed_at = ?, "
            "text = ?, summary = NULL, deleted = 0, doc_date = ? WHERE id = ?",
            (source, title, kind, content_hash, modified, now, text, doc_date or now, doc_id),
        )
        return doc_id, True

    def set_enrichment(self, doc_id: int, summary: str, tags: list[str], entities: list[str]) -> None:
        self.db.execute(
            "UPDATE documents SET summary = ?, tags = ?, entities = ? WHERE id = ?",
            (summary, json.dumps(tags), json.dumps(entities), doc_id),
        )
        self.db.commit()

    def mark_deleted(self, doc_id: int) -> None:
        self.clear_derived(doc_id)
        self.db.execute("DELETE FROM links WHERE src = ? OR dst = ?", (doc_id, doc_id))
        self.db.execute("UPDATE documents SET deleted = 1 WHERE id = ?", (doc_id,))

    def purge_sources(self, keep: set[str]) -> list[str]:
        """Forget sources that are no longer configured: drop their status row and retire their documents.
        Only touches names that have a sync record, so notes and saved answers are never affected."""
        gone = [r["name"] for r in self.db.execute("SELECT name FROM sources") if r["name"] not in keep]
        for name in gone:
            for doc_id in self.uris_for_source(name).values():
                self.mark_deleted(doc_id)
            self.db.execute("DELETE FROM sources WHERE name = ?", (name,))
        if gone:
            self.db.commit()
        return gone

    def uris_for_source(self, source: str) -> dict[str, int]:
        rows = self.db.execute("SELECT uri, id FROM documents WHERE source = ? AND deleted = 0", (source,))
        return {r["uri"]: r["id"] for r in rows}

    def changed_since(self, since: float, limit: int = 200, exclude_sources: tuple[str, ...] = ()) -> list[Document]:
        marks = ",".join("?" * len(exclude_sources)) or "''"
        rows = self.db.execute(
            f"SELECT * FROM documents WHERE deleted = 0 AND indexed_at >= ? AND source NOT IN ({marks}) "
            "ORDER BY indexed_at DESC LIMIT ?", (since, *exclude_sources, limit))
        return [_row_to_doc(r) for r in rows]

    # ---- collections (named sets of reference documents) --------------------
    def collections(self) -> list[dict[str, Any]]:
        out = []
        for r in self.db.execute("SELECT * FROM collections ORDER BY name COLLATE NOCASE"):
            ids = [i for i in json.loads(r["doc_ids"]) if self.get(i)]
            out.append({"name": r["name"], "doc_ids": ids, "titles": [self.get(i).title for i in ids], "updated": r["updated"]})
        return out

    def save_collection(self, name: str, doc_ids: list[int]) -> None:
        self.db.execute("INSERT INTO collections (name, doc_ids, updated) VALUES (?, ?, ?) "
                        "ON CONFLICT(name) DO UPDATE SET doc_ids = excluded.doc_ids, updated = excluded.updated",
                        (name, json.dumps([int(i) for i in dict.fromkeys(doc_ids)]), time.time()))
        self.db.commit()

    def delete_collection(self, name: str) -> bool:
        cur = self.db.execute("DELETE FROM collections WHERE name = ?", (name,))
        self.db.commit()
        return cur.rowcount > 0

    def doc_chunks(self, doc_id: int) -> list[tuple[int, str]]:
        return [(r["ord"], r["text"]) for r in self.db.execute(
            "SELECT ord, text FROM chunks WHERE doc_id = ? ORDER BY ord", (doc_id,))]

    def modified_for_source(self, source: str) -> dict[str, float | None]:
        rows = self.db.execute("SELECT uri, modified FROM documents WHERE source = ? AND deleted = 0", (source,))
        return {r["uri"]: r["modified"] for r in rows}

    def revisions(self, doc_id: int) -> list[dict[str, Any]]:
        rows = self.db.execute(
            "SELECT content_hash, indexed_at, summary FROM revisions WHERE doc_id = ? ORDER BY indexed_at DESC",
            (doc_id,),
        )
        return [dict(r) for r in rows]

    def unenriched(self, limit: int) -> list[Document]:
        rows = self.db.execute(
            "SELECT * FROM documents WHERE deleted = 0 AND summary IS NULL ORDER BY indexed_at DESC LIMIT ?", (limit,)
        )
        return [_row_to_doc(r) for r in rows]

    # ---- chunks / terms --------------------------------------------------
    def clear_derived(self, doc_id: int) -> None:
        self.db.execute("DELETE FROM chunks_fts WHERE doc_id = ?", (doc_id,))
        self.db.execute("DELETE FROM chunks WHERE doc_id = ?", (doc_id,))
        self.db.execute("DELETE FROM terms WHERE doc_id = ?", (doc_id,))

    def write_chunks(self, doc_id: int, title: str, chunks: Iterable[str]) -> None:
        for i, text in enumerate(chunks):
            cur = self.db.execute("INSERT INTO chunks (doc_id, ord, text) VALUES (?, ?, ?)", (doc_id, i, text))
            self.db.execute(
                "INSERT INTO chunks_fts (chunk_id, doc_id, title, text) VALUES (?, ?, ?, ?)",
                (cur.lastrowid, doc_id, title, text),
            )

    def write_terms(self, doc_id: int, tf: dict[str, float]) -> None:
        self.db.executemany("INSERT INTO terms (doc_id, term, tf) VALUES (?, ?, ?)",
                            [(doc_id, t, w) for t, w in tf.items()])

    # ---- links -----------------------------------------------------------
    def replace_links(self, src: int, kind: str, targets: list[tuple[int, float, str | None]]) -> None:
        self.db.execute("DELETE FROM links WHERE src = ? AND kind = ?", (src, kind))
        self.db.executemany(
            "INSERT OR REPLACE INTO links (src, dst, kind, weight, label) VALUES (?, ?, ?, ?, ?)",
            [(src, dst, kind, w, label) for dst, w, label in targets if dst != src],
        )

    def neighbours(self, doc_id: int, limit: int = 20) -> list[dict[str, Any]]:
        """Links in both directions, strongest first."""
        rows = self.db.execute(
            """
            SELECT l.dst AS other, l.kind, l.weight, l.label, 'out' AS direction FROM links l WHERE l.src = ?
            UNION ALL
            SELECT l.src AS other, l.kind, l.weight, l.label, 'in' AS direction FROM links l WHERE l.dst = ?
            """,
            (doc_id, doc_id),
        ).fetchall()
        best: dict[int, dict[str, Any]] = {}
        for r in rows:
            score = r["weight"] + (1.0 if r["kind"] in ("explicit", "attachment") else 0.0)
            cur = best.get(r["other"])
            if cur is None or score > cur["score"]:
                best[r["other"]] = {"doc_id": r["other"], "kind": r["kind"], "weight": r["weight"],
                                    "label": r["label"], "direction": r["direction"], "score": score}
        out = []
        for item in sorted(best.values(), key=lambda x: -x["score"])[:limit]:
            doc = self.get(item["doc_id"])
            if doc:
                item["title"] = doc.title
                item["uri"] = doc.uri
                out.append(item)
        return out

    def all_links(self) -> list[dict[str, Any]]:
        return [dict(r) for r in self.db.execute(
            "SELECT l.* FROM links l JOIN documents a ON a.id = l.src JOIN documents b ON b.id = l.dst "
            "WHERE a.deleted = 0 AND b.deleted = 0")]

    # ---- sources / stats -------------------------------------------------
    def record_sync(self, name: str, type_: str, stats: dict[str, Any]) -> None:
        self.db.execute(
            "INSERT INTO sources (name, type, last_sync, last_stats) VALUES (?, ?, ?, ?) "
            "ON CONFLICT(name) DO UPDATE SET type = excluded.type, last_sync = excluded.last_sync, "
            "last_stats = excluded.last_stats",
            (name, type_, time.time(), json.dumps(stats)),
        )
        self.db.commit()

    def source_status(self) -> list[dict[str, Any]]:
        out = []
        for r in self.db.execute("SELECT * FROM sources ORDER BY name"):
            d = dict(r)
            d["last_stats"] = json.loads(d["last_stats"] or "{}")
            d["documents"] = self.db.execute(
                "SELECT COUNT(*) FROM documents WHERE source = ? AND deleted = 0", (r["name"],)).fetchone()[0]
            out.append(d)
        return out

    def stats(self) -> dict[str, Any]:
        q = lambda sql: self.db.execute(sql).fetchone()[0]  # noqa: E731
        return {
            "documents": q("SELECT COUNT(*) FROM documents WHERE deleted = 0"),
            "chunks": q("SELECT COUNT(*) FROM chunks"),
            "links": q("SELECT COUNT(*) FROM links"),
            "revisions": q("SELECT COUNT(*) FROM revisions"),
            "enriched": q("SELECT COUNT(*) FROM documents WHERE deleted = 0 AND summary IS NOT NULL"),
            "by_kind": {r[0]: r[1] for r in self.db.execute(
                "SELECT kind, COUNT(*) FROM documents WHERE deleted = 0 GROUP BY kind")},
        }

    def commit(self) -> None:
        self.db.commit()
