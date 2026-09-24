"""The ``Brain``: one object that the CLI, REST API and MCP server all share."""

from __future__ import annotations

import hashlib
import re
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from . import graph
from .config import BrainConfig, load_config
from .connectors import Item
from .indexer import SyncStats, index_item, refresh_links, sync_source
from .llm import LLM, LLMUnavailable
from .render import Deck, Slide, deck_to_pptx, markdown_to_docx
from .search import Hit, search
from .store import Store

ANSWER_SYSTEM = """You are the user's second brain: a research partner that answers from their own knowledge base.
Ground every claim in the numbered sources provided and cite them inline like [1] or [2][4].
If the sources don't contain the answer, say what is missing rather than guessing, then offer what you do know,
clearly marked as general knowledge. Prefer crisp, structured answers a busy consultant can act on."""

DOC_SYSTEM = """You write polished business documents (briefs, memos, proposals, reports) in Markdown, grounded in the
user's knowledge base. Use headings, short paragraphs, bullets and tables where they help. Cite sources inline as [n].
End with a '## Sources' section listing each cited source as '[n] Title'. Output only the document."""

DECK_SYSTEM = """You design executive slide decks grounded in the user's knowledge base. Each slide has an action title
(a full-sentence takeaway, not a topic label), 3-5 concise bullets (indent sub-points with two spaces), and speaker
notes that cite sources as [n]. Tell one clear storyline: situation, complication, insight, recommendation, next steps."""

ENRICH_SYSTEM = """You catalogue documents for a personal knowledge base. Return a 2-3 sentence summary, 3-8 short
lowercase topic tags, and the named entities (people, organisations, products, projects, places) mentioned."""


class Enrichment(BaseModel):
    summary: str
    tags: list[str] = Field(default_factory=list)
    entities: list[str] = Field(default_factory=list)


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:60] or "untitled"


def format_context(hits: list[Hit], max_chars: int = 60000) -> tuple[str, list[dict[str, Any]]]:
    """Number the sources (one number per document) and build the context block."""
    numbers: dict[int, int] = {}
    sources: list[dict[str, Any]] = []
    blocks: list[str] = []
    used = 0
    for h in hits:
        if h.doc_id not in numbers:
            numbers[h.doc_id] = len(numbers) + 1
            sources.append({"n": numbers[h.doc_id], "doc_id": h.doc_id, "title": h.title, "uri": h.uri})
        block = f"[{numbers[h.doc_id]}] {h.title}\n{h.text}"
        if used + len(block) > max_chars:
            break
        blocks.append(block)
        used += len(block)
    return "\n\n---\n\n".join(blocks), sources


class Brain:
    def __init__(self, config: BrainConfig | None = None, llm: LLM | None = None):
        self.config = config or load_config()
        self.store = Store(self.config.db_path)
        self.llm = llm or LLM(self.config.model, self.config.effort)

    # ---- ingest ----------------------------------------------------------
    def sync(self, source_name: str | None = None, on_progress=None) -> list[SyncStats]:
        results = []
        for src in self.config.all_sources():
            if source_name and src.name != source_name:
                continue
            results.append(sync_source(self.store, src, on_progress))
        if self.config.auto_enrich:
            self.enrich(limit=25)
        return results

    def remember(self, text: str, title: str | None = None, tags: list[str] | None = None) -> dict[str, Any]:
        """Capture a note/fact straight into the brain (from chat, an MCP client or the API)."""
        title = title or text.strip().splitlines()[0][:80]
        stamp = datetime.now().strftime("%Y-%m-%d %H:%M")
        body = f"# {title}\n\n{text.strip()}\n\n_captured {stamp}_"
        if tags:
            body += "\n\ntags: " + ", ".join(tags)
        uri = "memory:" + hashlib.sha1(f"{title}\n{text}".encode()).hexdigest()[:16]
        item = Item(uri=uri, title=title, ext=".md", modified=time.time(), load=lambda: b"")
        doc_id, outcome = index_item(self.store, "memory", item, text=body)
        self.store.commit()
        refresh_links(self.store, [doc_id])
        return {"doc_id": doc_id, "title": title, "status": outcome}

    def enrich(self, limit: int = 20) -> dict[str, Any]:
        """Have Claude summarise, tag and extract entities; then connect docs that share entities."""
        done, errors = 0, []
        for doc in self.store.unenriched(limit):
            try:
                result = self.llm.structured(
                    ENRICH_SYSTEM, f"Title: {doc.title}\n\n{doc.text[:40000]}", Enrichment, max_tokens=4000)
            except LLMUnavailable as exc:
                errors.append(str(exc))
                break
            self.store.set_enrichment(doc.id, result.summary, result.tags, result.entities)
            done += 1
        graph.link_entities(self.store)
        return {"enriched": done, "errors": errors}

    # ---- retrieve --------------------------------------------------------
    def search(self, query: str, limit: int = 8, source: str | None = None) -> list[Hit]:
        return search(self.store, query, limit=limit, source=source)

    def related(self, doc_id: int, limit: int = 15) -> list[dict[str, Any]]:
        return self.store.neighbours(doc_id, limit)

    def document(self, doc_id: int) -> dict[str, Any] | None:
        doc = self.store.get(doc_id)
        if not doc:
            return None
        out = doc.to_dict(include_text=True)
        out["related"] = self.related(doc_id, 10)
        out["revisions"] = self.store.revisions(doc_id)
        return out

    def _context_hits(self, query: str, k: int) -> list[Hit]:
        hits = self.search(query, limit=k)
        # Pull in the strongest neighbour of the top hits so connected knowledge comes along.
        seen = {h.doc_id for h in hits}
        for h in hits[:3]:
            for n in self.related(h.doc_id, 2):
                if n["doc_id"] not in seen:
                    seen.add(n["doc_id"])
                    doc = self.store.get(n["doc_id"])
                    if doc:
                        hits.append(Hit(doc.id, 0, doc.title, doc.uri, doc.source,
                                        doc.summary or doc.text[:1200], 0.0))
        return hits

    # ---- create ----------------------------------------------------------
    def ask(self, question: str, k: int = 8) -> dict[str, Any]:
        hits = self._context_hits(question, k)
        context, sources = format_context(hits)
        if not hits:
            return {"answer": "Nothing in the brain matches that yet. Add sources or `remember` some notes.",
                    "sources": [], "mode": "empty"}
        prompt = f"<sources>\n{context}\n</sources>\n\nQuestion: {question}"
        try:
            return {"answer": self.llm.text(ANSWER_SYSTEM, prompt, max_tokens=16000), "sources": sources,
                    "mode": "claude"}
        except LLMUnavailable as exc:
            passages = "\n\n".join(f"[{s['n']}] {s['title']}\n" + next(h.text[:500] for h in hits if h.doc_id == s["doc_id"])
                                   for s in sources)
            return {"answer": f"(Claude unavailable: {exc}. Most relevant passages:)\n\n{passages}",
                    "sources": sources, "mode": "extractive"}

    def _output_path(self, topic: str, ext: str) -> Path:
        return self.config.output_dir / f"{datetime.now():%Y-%m-%d}-{_slug(topic)}{ext}"

    def create_document(self, topic: str, fmt: str = "md", instructions: str = "", k: int = 12) -> dict[str, Any]:
        hits = self._context_hits(topic, k)
        context, sources = format_context(hits)
        prompt = (f"<sources>\n{context}\n</sources>\n\nWrite a document about: {topic}\n"
                  f"{'Additional instructions: ' + instructions if instructions else ''}")
        try:
            markdown = self.llm.text(DOC_SYSTEM, prompt)
        except LLMUnavailable as exc:
            markdown = f"# {topic}\n\n> Draft outline — Claude unavailable ({exc}).\n\n" + "\n\n".join(
                f"## {s['title']}\n\n" + next(h.text[:800] for h in hits if h.doc_id == s["doc_id"]) + f" [{s['n']}]"
                for s in sources)
            markdown += "\n\n## Sources\n\n" + "\n".join(f"- [{s['n']}] {s['title']}" for s in sources)
        md_path = self._output_path(topic, ".md")
        md_path.write_text(markdown, encoding="utf-8")
        out = {"path": str(md_path), "format": "md", "sources": sources}
        if fmt == "docx":
            docx_path = markdown_to_docx(markdown, self._output_path(topic, ".docx"), self.config.doc_template)
            out.update(path=str(docx_path), format="docx", markdown_path=str(md_path))
        return out

    def create_deck(self, topic: str, slides: int = 8, instructions: str = "", k: int = 12) -> dict[str, Any]:
        hits = self._context_hits(topic, k)
        context, sources = format_context(hits)
        prompt = (f"<sources>\n{context}\n</sources>\n\nCreate a {slides}-slide deck (excluding the title slide) "
                  f"about: {topic}\n{'Additional instructions: ' + instructions if instructions else ''}")
        try:
            deck = self.llm.structured(DECK_SYSTEM, prompt, Deck)
            mode = "claude"
        except LLMUnavailable:
            deck = Deck(title=topic, subtitle="Draft built from your knowledge base", slides=[
                Slide(title=s["title"],
                      bullets=[ln.strip()[:160] for ln in next(h.text for h in hits if h.doc_id == s["doc_id"]).splitlines()
                               if ln.strip()][:5],
                      speaker_notes=f"Source [{s['n']}] {s['uri']}")
                for s in sources[:slides]])
            mode = "extractive"
        path = deck_to_pptx(deck, self._output_path(topic, ".pptx"),
                            [f"[{s['n']}] {s['title']}" for s in sources], self.config.deck_template)
        return {"path": str(path), "format": "pptx", "slides": len(deck.slides), "sources": sources, "mode": mode}

    # ---- info ------------------------------------------------------------
    def status(self) -> dict[str, Any]:
        return {"stats": self.store.stats(), "sources": self.store.source_status(),
                "configured_sources": [{"name": s.name, "type": s.type} for s in self.config.all_sources()],
                "db": str(self.config.db_path), "outputs": str(self.config.output_dir), "model": self.config.model}

    def graph(self) -> dict[str, Any]:
        return graph.export_graph(self.store)
