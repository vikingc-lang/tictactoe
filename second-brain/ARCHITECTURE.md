# Architecture, decisions and roadmap

## 1. Design principles

1. **Own your knowledge.** Everything lives in one local SQLite file. There's no vendor lock-in, it works
   offline, and you can move it by copying a file.
2. **Connect, don't migrate.** Keep working where you work (OneDrive, Drive, Obsidian, CRM). The brain
   indexes those places in place and never asks you to move files.
3. **Claude is the reasoning layer, not the storage layer.** Retrieval and linking are deterministic and
   free. Claude is called only to answer, enrich and create, and it always cites sources.
4. **Be an MCP citizen.** Rather than building a connector for every SaaS tool, the brain exposes itself as
   an MCP server. Claude then orchestrates it together with every other MCP server you connect
   (Gmail, Calendar, Slack, Notion, Salesforce and more).
5. **Graceful degradation.** No network or no API key still leaves a working search engine and graph.

## 2. Components

| Layer | Module | Responsibility |
|---|---|---|
| Config | `config.py` | TOML sources, `${ENV}` secrets, branded templates |
| Connectors | `connectors/` | `folder` (local + synced clouds), `gdrive` (API), `web`, `http_json` (any REST API) |
| Parsing | `parsers.py` | PDF, DOCX, PPTX, XLSX, HTML, EML, CSV/JSON, text |
| Indexing | `indexer.py`, `text.py` | Change detection (mtime → hash), chunking, term vectors, revisions, deletions |
| Store | `store.py` | SQLite + FTS5 (BM25, porter stemming), links, revisions, source status |
| Graph | `graph.py` | Explicit / related (TF-IDF cosine) / entity edges; JSON export |
| Retrieval | `search.py` | BM25 + graph boost; context expansion to neighbouring documents |
| Reasoning | `llm.py`, `brain.py` | Switchable AI: Claude API (adaptive thinking, refusal fallbacks, structured outputs), local models (Ollama native API with a larger context window, or OpenAI-compatible servers), Claude-app hand-off, or off |
| Creation | `render.py` | Markdown → DOCX, structured deck → PPTX (on your master template) |
| Interfaces | `cli.py`, `mcp_server.py`, `api.py` | CLI, MCP (stdio / HTTP), REST with bearer auth |

## 3. Build vs. buy: where this fits

| Option | Good at | Gaps this MVP fills |
|---|---|---|
| Obsidian / Logseq + plugins | Personal notes, manual linking | Office docs, cloud drives, APIs, and generating decks |
| Notion AI / Confluence AI | Q&A inside that one tool | Knowledge that lives *outside* the tool |
| Microsoft Copilot / Glean | Enterprise-wide search (M365 / SaaS) | Cost and licensing; limited control over outputs and your own graph |
| Claude Projects + connectors | Zero setup and strong reasoning | A persistent, incremental, cross-source index and graph that you own |

**Recommendation:** use this as your **personal and practice-level** brain, exposed to Claude through MCP.
If the firm already standardises on M365 Copilot or Glean, keep this for cross-client IP (frameworks,
playbooks, proposals) and point a `folder` source at the exported or synced libraries.

## 4. Risk and governance (important for client work)

- **Confidentiality:** client material reaches the Claude API only when you ask, create or enrich. Choose
  **Local AI** to keep everything on the laptop, or **Claude app** to decide prompt by prompt what you share. Use
  separate brains (separate `data_dir`) per client when NDAs require segregation, and use `exclude`
  patterns for sensitive folders.
- **Access:** the REST API and HTTP MCP server bind to localhost by default. Set `BRAIN_API_TOKEN` before
  exposing either one, and put them behind TLS or a VPN.
- **Secrets:** tokens come from environment variables through `${VAR}` and are never stored in config.
- **Auditability:** every answer and artifact lists its sources, and revisions preserve earlier versions
  of documents.

## 5. Roadmap

| Phase | Scope | Value |
|---|---|---|
| **0 – MVP (this)** | Sync, graph, search, ask, docx/pptx, MCP, REST, watch | Useful day one on your own files |
| 1 – Semantic recall | Embeddings (e.g. Voyage) alongside BM25 for hybrid search; OCR for scanned PDFs | Finds concepts, not just keywords |
| 2 – More sources | Native Gmail, Calendar, Slack and SharePoint (Graph API) connectors; RSS; meeting transcripts | Capture where work actually happens |
| 3 – Proactive brain | Scheduled digests ("what changed this week per client"), contradiction detection, stale-knowledge alerts | Learns *and* tells you what matters |
| 4 – Visual UI | Web app with graph explorer, chat, and artifact gallery | Non-CLI users, demos to clients |
| 5 – Team brain | Multi-user, per-source ACLs, Postgres/pgvector backend, SSO | Practice-wide knowledge management |
