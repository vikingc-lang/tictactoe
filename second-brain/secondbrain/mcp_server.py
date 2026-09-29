"""MCP server: plug the brain into Claude Desktop, Claude Code, Cowork or any MCP client.

Once connected, Claude can search your knowledge, follow connections, capture new
facts and produce documents/decks — and combine that with every other MCP server
you have connected (Gmail, Calendar, Slack, Drive, Notion, CRM...).

Run:  brain mcp                  (stdio, for desktop clients)
      brain mcp --http --port 8765  (streamable HTTP, for remote clients)
"""

from __future__ import annotations

from typing import Any

from mcp.server.mcpserver import MCPServer

from .brain import Brain
from .config import refresh_ai_settings

INSTRUCTIONS = """This server is the user's second brain: their documents, notes and prior work, indexed and linked.
Search it before answering questions about the user's work, clients, projects or past decisions.
Use `remember` to save durable facts, decisions and meeting outcomes the user shares, so the brain keeps learning.
Cite documents by title when you use them.

If a tool returns mode "handoff", the brain's own AI is set to "Claude app": you are the writer. Follow the
returned `prompt` (it holds the instructions and the numbered sources) and write the answer yourself. For documents,
then save your Markdown with `save_document`; for decks, save your outline with `save_deck`."""

HANDOFF_NEXT = {
    "ask": "Answer the question yourself from the sources in `prompt`, citing them as [n].",
    "digest": "Write the briefing yourself from the documents in `prompt`, citing them as [n].",
    "document": "Write the document in Markdown following `prompt`, then call save_document(title, markdown, format, "
                "sources) with the `sources` list from this result.",
    "deck": "Write the deck outline following `prompt`, then call save_deck(title, outline, sources) with the "
            "`sources` list from this result.",
}


def _for_caller(result: dict[str, Any], step: str) -> dict[str, Any]:
    """In Claude-app mode the calling model does the writing: hand it the prepared prompt and the next step."""
    if result.get("mode") == "handoff":
        result = {k: v for k, v in result.items() if k != "handoff"} | {"prompt": result["handoff"],
                                                                         "next_step": HANDOFF_NEXT[step]}
    return result


def build_server(brain: Brain | None = None) -> MCPServer:
    brain = brain or Brain()
    mcp = MCPServer(name="second-brain", instructions=INSTRUCTIONS)

    def fresh() -> Brain:  # follow AI changes made in the app while this server keeps running
        refresh_ai_settings(brain.config.data_dir)
        return brain

    @mcp.tool()
    def search(query: str, limit: int = 8, source: str | None = None, days: int | None = None) -> list[dict[str, Any]]:
        """Full-text search across every connected source. Returns matching passages with doc ids and dates.
        days: only documents dated within the last N days."""
        return [h.to_dict() for h in brain.search(query, limit=limit, source=source, days=days)]

    @mcp.tool()
    def get_document(doc_id: int, max_chars: int = 20000) -> dict[str, Any]:
        """Read a document (text, summary, tags), its connected documents and revision history."""
        doc = brain.document(doc_id)
        if doc is None:
            return {"error": f"no document {doc_id}"}
        doc["text"] = doc["text"][:max_chars]
        return doc

    @mcp.tool()
    def related(doc_id: int, limit: int = 15) -> list[dict[str, Any]]:
        """Documents connected to this one (explicit links, similar topics, shared people/companies)."""
        return brain.related(doc_id, limit)

    @mcp.tool()
    def ask(question: str) -> dict[str, Any]:
        """Answer a question from the knowledge base with numbered citations."""
        return _for_caller(fresh().ask(question), "ask")

    @mcp.tool()
    def whats_new(days: int = 7, brief: bool = False) -> dict[str, Any]:
        """What arrived or changed in the brain in the last N days (emails, documents, notes).
        brief=true also returns a short cited briefing written by Claude."""
        return _for_caller(fresh().whats_new(days, use_ai=brief), "digest")

    @mcp.tool()
    def remember(text: str, title: str | None = None, tags: list[str] | None = None) -> dict[str, Any]:
        """Save a note, fact, decision or meeting outcome into the brain so it can be recalled later."""
        return brain.remember(text, title, tags)

    @mcp.tool()
    def create_document(topic: str, format: str = "docx", instructions: str = "",
                        doc_ids: list[int] | None = None, use_ai: bool = True) -> dict[str, Any]:
        """Write a grounded document (brief, memo, proposal, report) as .md or .docx. Returns the file path.
        doc_ids: reference documents to use (ids from `search`); omit to let the brain pick.
        use_ai=false assembles a draft from the references without calling Claude."""
        return _for_caller(fresh().create_document(topic, fmt=format, instructions=instructions, doc_ids=doc_ids,
                                                   use_ai=use_ai), "document")

    @mcp.tool()
    def create_deck(topic: str, slides: int = 8, instructions: str = "",
                    doc_ids: list[int] | None = None, use_ai: bool = True) -> dict[str, Any]:
        """Build a PowerPoint deck grounded in the knowledge base. Returns the .pptx path.
        doc_ids: reference documents to use (ids from `search`); omit to let the brain pick.
        use_ai=false builds the deck from the references without calling Claude."""
        return _for_caller(fresh().create_deck(topic, slides=slides, instructions=instructions, doc_ids=doc_ids,
                                               use_ai=use_ai), "deck")

    @mcp.tool()
    def save_document(title: str, markdown: str, format: str = "docx",
                      sources: list[dict[str, Any]] | None = None) -> dict[str, Any]:
        """Save a document you wrote (Markdown) into the brain's outputs as .docx or .md. Returns the file path.
        sources: the numbered sources you cited ([{"n", "doc_id", "title"}]), e.g. from create_document."""
        return brain.save_written(title, markdown, format, sources)

    @mcp.tool()
    def save_deck(title: str, outline: str, sources: list[dict[str, Any]] | None = None) -> dict[str, Any]:
        """Save a deck you wrote as PowerPoint (.pptx). outline is Markdown: '# Deck title', a subtitle line,
        then per slide '## Action title', '- bullets' and 'Notes: speaker notes'. Returns the file path."""
        return brain.save_written(title, outline, "pptx", sources)

    @mcp.tool()
    def sync(source: str | None = None) -> list[dict[str, Any]]:
        """Re-scan connected sources (or one source) and index anything new or changed."""
        return [s.as_dict() for s in brain.sync(source)]

    @mcp.tool()
    def status() -> dict[str, Any]:
        """Sources, document counts, links and when each source last synced."""
        return brain.status()

    return mcp


def main(http: bool = False, host: str = "127.0.0.1", port: int = 8765, config: str | None = None) -> None:
    from .config import load_config

    server = build_server(Brain(load_config(config)))
    if http:
        server.run("streamable-http", host=host, port=port)
    else:
        server.run("stdio")
