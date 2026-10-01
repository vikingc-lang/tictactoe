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
from .llm import Handoff, LLMUnavailable, SwitchableLLM, handoff_text
from .render import Deck, Slide, deck_to_pptx, markdown_to_docx, parse_deck_markdown
from .search import GENERATED_SOURCES, Hit, search
from .store import Store
from .text import tokenize

ANSWER_SYSTEM = """You are the user's second brain: a research partner that answers from their own knowledge base.
Ground every claim in the numbered sources provided and cite them inline like [1] or [2][4].
If the sources don't contain the answer, say what is missing rather than guessing, then offer what you do know,
clearly marked as general knowledge. Prefer crisp, structured answers a busy consultant can act on.
Each source shows its date; when sources disagree, prefer the most recent and say so. If there is an earlier
conversation, treat the new question as a follow-up to it."""

DIGEST_SYSTEM = """You brief a busy consultant on what is new in their knowledge base. From the numbered documents
that arrived or changed recently, write a short Markdown briefing: 3-6 headline bullets (decisions, commitments,
numbers, risks, deadlines), then a short "Worth reading" list. Cite every point as [n]. No preamble."""

DOC_SYSTEM = """You write polished business documents (briefs, memos, proposals, reports) in Markdown, grounded in the
user's knowledge base. Use headings, short paragraphs, bullets and tables where they help. Cite sources inline as [n].
End with a '## Sources' section listing each cited source as '[n] Title'. Output only the document."""

DECK_SYSTEM = """You design executive slide decks grounded in the user's knowledge base. Each slide has an action title
(a full-sentence takeaway, not a topic label), 3-5 concise bullets (indent sub-points with two spaces), and speaker
notes that cite sources as [n]. Tell one clear storyline: situation, complication, insight, recommendation, next steps."""

# Claude-app mode: the deck comes back as pasted text, so ask for an outline we can turn into PowerPoint.
DECK_OUTLINE = """Reply with only the deck, in exactly this Markdown format (no other text):

# Deck title
Subtitle line

## Slide 1 action title (a full-sentence takeaway)
- bullet
- bullet
Notes: speaker notes citing sources as [n]

## Slide 2 action title
..."""

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
            sources.append({"n": numbers[h.doc_id], "doc_id": h.doc_id, "title": h.title, "uri": h.uri,
                            "date": h.date})
        when = f" ({datetime.fromtimestamp(h.date):%Y-%m-%d})" if h.date else ""
        block = f"[{numbers[h.doc_id]}] {h.title}{when}\n{h.text}"
        if used + len(block) > max_chars:
            break
        blocks.append(block)
        used += len(block)
    return "\n\n---\n\n".join(blocks), sources


class Brain:
    def __init__(self, config: BrainConfig | None = None, llm=None):
        self.config = config or load_config()
        self.store = Store(self.config.db_path)
        self.llm = llm or SwitchableLLM(self.config.model, self.config.effort)

    # ---- which AI is answering ---------------------------------------------
    @property
    def ai_kind(self) -> str:
        return getattr(self.llm, "kind", "claude")

    @property
    def ai_label(self) -> str:
        return getattr(self.llm, "label", "Claude")

    def _format(self, hits: list[Hit], max_chars: int = 60000) -> tuple[str, list[dict[str, Any]]]:
        return format_context(hits, min(max_chars, getattr(self.llm, "context_chars", max_chars)))

    # ---- ingest ----------------------------------------------------------
    def sync(self, source_name: str | None = None, on_progress=None, should_stop=None,
             on_source=None) -> list[SyncStats]:
        results = []
        todo = [s for s in self.config.all_sources() if not source_name or s.name == source_name]
        for i, src in enumerate(todo):
            if should_stop and should_stop():
                break
            if on_source:
                on_source(i, len(todo), src.name)
            results.append(sync_source(self.store, src, on_progress, should_stop))
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
        # Saved answers are the brain's own words: kept apart so they never pose as evidence for new answers.
        source = "_answers" if "answer" in (tags or []) else "memory"
        doc_id, outcome = index_item(self.store, source, item, text=body)
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
            except Handoff:
                errors.append("summarising runs inside the app: switch AI to Claude (API key) or Local AI")
                break
            except LLMUnavailable as exc:
                errors.append(str(exc))
                break
            self.store.set_enrichment(doc.id, result.summary, result.tags, result.entities)
            done += 1
        graph.link_entities(self.store)
        return {"enriched": done, "errors": errors}

    # ---- retrieve --------------------------------------------------------
    def search(self, query: str, limit: int = 8, source: str | None = None, days: int | None = None) -> list[Hit]:
        since = time.time() - days * 86400 if days else None
        return search(self.store, query, limit=limit, source=source, since=since)

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
        # Answers and creations are grounded in original material; the brain's own earlier outputs are
        # only used when nothing else matches (or when the user picks them as references).
        hits = search(self.store, query, limit=k, include_generated=False) or self.search(query, limit=k)
        # Pull in the strongest neighbour of the top hits so connected knowledge comes along.
        seen = {h.doc_id for h in hits}
        for h in hits[:3]:
            for n in self.related(h.doc_id, 2):
                if n["doc_id"] not in seen:
                    seen.add(n["doc_id"])
                    doc = self.store.get(n["doc_id"])
                    if doc and doc.source not in GENERATED_SOURCES:
                        hits.append(Hit(doc.id, 0, doc.title, doc.uri, doc.source,
                                        doc.summary or doc.text[:1200], 0.0, doc.doc_date))
        return hits

    # ---- create ----------------------------------------------------------
    def ask(self, question: str, k: int = 8, history: list[dict[str, str]] | None = None) -> dict[str, Any]:
        """Answer from the knowledge base. ``history`` = earlier turns [{"q": ..., "a": ...}] for follow-ups."""
        history = [t for t in (history or []) if t.get("q")][-3:]
        # Follow-ups ("and the risks?") are searched together with the previous question.
        hits = self._context_hits(f"{question} {history[-1]['q']}" if history else question, k)
        context, sources = self._format(hits)
        if not hits:
            return {"answer": "Nothing in the brain matches that yet. Add sources or `remember` some notes.",
                    "sources": [], "mode": "empty"}
        convo = "".join(f"Q: {t['q']}\nA: {str(t.get('a', ''))[:1500]}\n\n" for t in history)
        prompt = (f"<sources>\n{context}\n</sources>\n\n"
                  + (f"<conversation>\n{convo.strip()}\n</conversation>\n\n" if convo else "")
                  + f"Question: {question}")
        try:
            return {"answer": self.llm.text(ANSWER_SYSTEM, prompt, max_tokens=16000), "sources": sources,
                    "mode": self.ai_kind, "ai": self.ai_label}
        except Handoff as h:
            return {"answer": "", "handoff": h.text, "sources": sources, "mode": "handoff"}
        except LLMUnavailable as exc:
            passages = "\n\n".join(f"[{s['n']}] {s['title']}\n" + next(h.text[:500] for h in hits if h.doc_id == s["doc_id"])
                                   for s in sources)
            return {"answer": passages, "sources": sources, "mode": "extractive", "reason": f"AI unavailable: {exc}"}

    def whats_new(self, days: int = 7, use_ai: bool = False, limit: int = 40) -> dict[str, Any]:
        """What arrived or changed recently (excluding the brain's own creations), optionally briefed by Claude."""
        docs = self.store.changed_since(time.time() - days * 86400, limit=200, exclude_sources=tuple(GENERATED_SOURCES))
        by_source: dict[str, int] = {}
        by_kind: dict[str, int] = {}
        for d in docs:
            by_source[d.source] = by_source.get(d.source, 0) + 1
            by_kind[d.kind] = by_kind.get(d.kind, 0) + 1
        out: dict[str, Any] = {
            "days": days, "count": len(docs), "by_source": by_source, "by_kind": by_kind,
            "docs": [{"id": d.id, "title": d.title, "kind": d.kind, "source": d.source, "date": d.doc_date,
                      "indexed_at": d.indexed_at} for d in docs[:limit]],
            "briefing": None, "sources": [], "mode": "list",
        }
        if use_ai and docs:
            hits = [Hit(d.id, 0, d.title, d.uri, d.source, d.summary or d.text[:1500], 0.0, d.doc_date) for d in docs[:limit]]
            context, sources = self._format(hits, max_chars=50000)
            out["sources"] = sources
            try:
                out["briefing"] = self.llm.text(DIGEST_SYSTEM, f"<documents>\n{context}\n</documents>\n\n"
                                                f"Brief me on the last {days} days.", max_tokens=8000)
                out["mode"], out["ai"] = self.ai_kind, self.ai_label
            except Handoff as h:
                out["mode"], out["handoff"] = "handoff", h.text
            except LLMUnavailable as exc:
                out["mode"], out["error"] = "list", str(exc)
        return out

    # ---- collections ------------------------------------------------------
    def collections(self) -> list[dict[str, Any]]:
        return self.store.collections()

    def save_collection(self, name: str, doc_ids: list[int]) -> dict[str, Any]:
        name = name.strip()
        if not name or len(name) > 80:
            raise ValueError("collection name must be 1-80 characters")
        ids = [int(i) for i in doc_ids if self.store.get(int(i))]
        if not ids:
            raise ValueError("a collection needs at least one existing document")
        self.store.save_collection(name, ids)
        return {"name": name, "doc_ids": ids}

    def delete_collection(self, name: str) -> dict[str, Any]:
        if not self.store.delete_collection(name):
            raise ValueError(f"no collection named {name!r}")
        return {"deleted": name}

    def _output_path(self, topic: str, ext: str) -> Path:
        return self.config.output_dir / f"{datetime.now():%Y-%m-%d}-{_slug(topic)}{ext}"

    def reference_hits(self, doc_ids: list[int], topic: str, per_doc: int = 8) -> list[Hit]:
        """Passages from documents the user picked, most relevant to the topic first, kept in reading order."""
        terms = set(tokenize(topic))
        hits: list[Hit] = []
        for doc_id in dict.fromkeys(doc_ids):  # de-duplicate, keep the user's order
            doc = self.store.get(int(doc_id))
            if not doc:
                continue
            chunks = self.store.doc_chunks(doc.id)
            ranked = sorted(chunks, key=lambda c: (-len(terms & set(tokenize(c[1]))), c[0]))[:per_doc]
            for ord_, text in sorted(ranked):
                hits.append(Hit(doc.id, ord_, doc.title, doc.uri, doc.source, text, 0.0, doc.doc_date))
        return hits

    def _creation_context(self, topic: str, k: int, doc_ids: list[int] | None) -> tuple[list[Hit], str, list[dict]]:
        hits = self.reference_hits(doc_ids, topic) if doc_ids else self._context_hits(topic, k)
        if not hits:
            raise ValueError("no reference material: pick documents, or add sources to the brain first")
        context, sources = self._format(hits)
        return hits, context, sources

    @staticmethod
    def _passages(hits: list[Hit], source: dict[str, Any], limit: int = 3) -> list[str]:
        return [h.text for h in hits if h.doc_id == source["doc_id"]][:limit]

    def create_document(self, topic: str, fmt: str = "md", instructions: str = "", k: int = 12,
                        doc_ids: list[int] | None = None, use_ai: bool = True) -> dict[str, Any]:
        """Write a document. ``doc_ids`` pins the references; ``use_ai=False`` builds a draft without Claude."""
        hits, context, sources = self._creation_context(topic, k, doc_ids)
        markdown, mode = None, "no_ai"
        if use_ai:
            prompt = (f"<sources>\n{context}\n</sources>\n\nWrite a document about: {topic}\n"
                      f"{'Additional instructions: ' + instructions if instructions else ''}")
            try:
                markdown, mode = self.llm.text(DOC_SYSTEM, prompt), self.ai_kind
            except Handoff as h:
                return {"mode": "handoff", "handoff": h.text, "sources": sources, "topic": topic, "format": fmt}
            except LLMUnavailable as exc:
                mode, note = "extractive", f"AI unavailable ({exc})"
        if markdown is None:
            note = "Draft assembled from your reference documents (no AI)" if mode == "no_ai" else note
            markdown = f"# {topic}\n\n> {note}.\n\n" + "\n\n".join(
                f"## {s['title']}\n\n" + "\n\n".join(p.strip()[:1200] for p in self._passages(hits, s)) + f" [{s['n']}]"
                for s in sources)
            markdown += "\n\n## Sources\n\n" + "\n".join(f"- [{s['n']}] {s['title']}" for s in sources)
        return self._write_document(topic, markdown, fmt, sources, mode)

    def _write_document(self, topic: str, markdown: str, fmt: str, sources: list[dict], mode: str) -> dict[str, Any]:
        md_path = self._output_path(topic, ".md")
        md_path.write_text(markdown, encoding="utf-8")
        out = {"path": str(md_path), "format": "md", "sources": sources, "mode": mode, "ai": self.ai_label}
        if fmt == "docx":
            docx_path = markdown_to_docx(markdown, self._output_path(topic, ".docx"), self.config.doc_template)
            out.update(path=str(docx_path), format="docx", markdown_path=str(md_path))
        return out

    def create_deck(self, topic: str, slides: int = 8, instructions: str = "", k: int = 12,
                    doc_ids: list[int] | None = None, use_ai: bool = True) -> dict[str, Any]:
        """Build a deck. ``doc_ids`` pins the references; ``use_ai=False`` builds it without Claude."""
        hits, context, sources = self._creation_context(topic, k, doc_ids)
        deck, mode = None, "no_ai"
        if use_ai:
            prompt = (f"<sources>\n{context}\n</sources>\n\nCreate a {slides}-slide deck (excluding the title slide) "
                      f"about: {topic}\n{'Additional instructions: ' + instructions if instructions else ''}")
            try:
                deck, mode = self.llm.structured(DECK_SYSTEM, prompt, Deck), self.ai_kind
            except Handoff:
                return {"mode": "handoff", "handoff": handoff_text(DECK_SYSTEM + "\n\n" + DECK_OUTLINE, prompt),
                        "sources": sources, "topic": topic, "format": "pptx"}
            except LLMUnavailable:
                mode = "extractive"
        if deck is None:
            def bullets(source: dict[str, Any]) -> list[str]:
                lines = [ln.strip().lstrip("#-•* ").strip() for p in self._passages(hits, source) for ln in p.splitlines()]
                return [ln[:160] for ln in lines if len(ln) > 3 and ln != source["title"]][:5]

            deck = Deck(title=topic, subtitle="Draft built from your reference documents",
                        slides=[Slide(title=s["title"], bullets=bullets(s), speaker_notes=f"Source [{s['n']}] {s['uri']}")
                                for s in sources[:slides]])
        return self._write_deck(topic, deck, sources, mode)

    def _write_deck(self, topic: str, deck: Deck, sources: list[dict], mode: str) -> dict[str, Any]:
        path = deck_to_pptx(deck, self._output_path(topic, ".pptx"),
                            [f"[{s['n']}] {s['title']}" for s in sources], self.config.deck_template)
        return {"path": str(path), "format": "pptx", "slides": len(deck.slides), "sources": sources, "mode": mode,
                "ai": self.ai_label}

    def save_written(self, topic: str, text: str, fmt: str = "docx",
                     sources: list[dict[str, Any]] | None = None) -> dict[str, Any]:
        """Turn text Claude wrote elsewhere (pasted from the Claude app, or sent by Claude Desktop over MCP)
        into a file in the outputs folder: ``md``/``docx`` from Markdown, ``pptx`` from a deck outline."""
        text = (text or "").strip()
        if not text:
            raise ValueError("paste Claude's reply first")
        sources = [{"n": int(s.get("n", i + 1)), "doc_id": s.get("doc_id"), "title": str(s.get("title", "")),
                    "uri": s.get("uri", "")} for i, s in enumerate(sources or [])]
        if fmt == "pptx":
            deck = parse_deck_markdown(text, fallback_title=topic)
            if not deck.slides:
                raise ValueError("no slides found: each slide should start with '## ' followed by its title")
            return {**self._write_deck(topic, deck, sources, "claude_app"), "ai": "Claude app"}
        return {**self._write_document(topic, text, fmt if fmt in ("md", "docx") else "docx", sources, "claude_app"),
                "ai": "Claude app"}

    # ---- info ------------------------------------------------------------
    def status(self) -> dict[str, Any]:
        return {"stats": self.store.stats(), "sources": self.store.source_status(),
                "configured_sources": [{"name": s.name, "type": s.type} for s in self.config.all_sources()],
                "db": str(self.config.db_path), "outputs": str(self.config.output_dir), "model": self.config.model,
                "ai": {"mode": self.ai_kind, "label": self.ai_label}}

    def graph(self) -> dict[str, Any]:
        return graph.export_graph(self.store)
