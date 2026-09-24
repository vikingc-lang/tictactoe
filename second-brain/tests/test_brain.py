"""End-to-end tests: sync real files, link them, search, learn, create artifacts, serve API/MCP."""

from __future__ import annotations

import asyncio
import json
import threading
import urllib.request
from pathlib import Path

import docx
import pytest
from pptx import Presentation

from secondbrain.brain import Brain, Enrichment
from secondbrain.config import BrainConfig, SourceConfig
from secondbrain.llm import LLMUnavailable
from secondbrain.render import Deck, Slide


class OfflineLLM:
    """Simulates having no Claude credentials."""

    def text(self, *a, **k):
        raise LLMUnavailable("no credentials")

    def structured(self, *a, **k):
        raise LLMUnavailable("no credentials")


class FakeLLM:
    def __init__(self):
        self.prompts = []

    def text(self, system, prompt, max_tokens=0):
        self.prompts.append(prompt)
        return "# Pricing Strategy Brief\n\n## Summary\n\nAcme prefers **value-based** pricing [1].\n\n- point one\n- point two\n\n| A | B |\n|---|---|\n| 1 | 2 |\n\n## Sources\n\n[1] Acme"

    def structured(self, system, prompt, schema, max_tokens=0):
        self.prompts.append(prompt)
        if schema is Deck:
            return Deck(title="Acme Pricing", subtitle="Board update",
                        slides=[Slide(title="Value pricing wins", bullets=["Margin up", "  sub point"],
                                      speaker_notes="See [1]")])
        return Enrichment(summary="About Acme.", tags=["pricing"], entities=["Acme Corp"])


@pytest.fixture
def workspace(tmp_path: Path):
    notes = tmp_path / "notes"
    (notes / "clients").mkdir(parents=True)
    (notes / "Acme Corp.md").write_text(
        "# Acme Corp\n\nAcme is a manufacturing client. Pricing strategy review planned for Q3.\n"
        "Key contact: Jane Rivera. See [[Pricing Playbook]] and [meeting](clients/kickoff.md).\n", encoding="utf-8")
    (notes / "Pricing Playbook.md").write_text(
        "# Pricing Playbook\n\nValue-based pricing beats cost-plus pricing for manufacturing clients. "
        "Pricing strategy should anchor on customer value, willingness to pay and competitive pricing.\n",
        encoding="utf-8")
    (notes / "clients" / "kickoff.md").write_text(
        "# Kickoff meeting\n\nAcme kickoff. Discussed pricing strategy, manufacturing margins and value pricing.\n",
        encoding="utf-8")
    d = docx.Document()
    d.add_heading("Supply Chain Assessment", 1)
    d.add_paragraph("Logistics costs rose 12 percent. Warehouse automation recommended for the manufacturing network.")
    d.save(str(notes / "supply.docx"))
    prs = Presentation()
    s = prs.slides.add_slide(prs.slide_layouts[1])
    s.shapes.title.text = "Market Entry"
    s.placeholders[1].text = "Enter the Brazilian market through a distributor partnership."
    prs.save(str(notes / "market.pptx"))
    (notes / "ignore.bin").write_bytes(b"\x00\x01")

    cfg = BrainConfig(data_dir=tmp_path / "data", output_dir=tmp_path / "out",
                      sources=[SourceConfig("notes", "folder", {"path": str(notes)})])
    cfg.data_dir.mkdir()
    cfg.output_dir.mkdir()
    return cfg, notes


def test_sync_parses_formats_and_is_incremental(workspace):
    cfg, notes = workspace
    brain = Brain(cfg, llm=OfflineLLM())
    stats = {s.source: s for s in brain.sync()}
    assert stats["notes"].added == 5 and not stats["notes"].errors
    kinds = brain.store.stats()["by_kind"]
    assert kinds["note"] == 3 and kinds["document"] == 1 and kinds["presentation"] == 1

    again = {s.source: s for s in brain.sync()}["notes"]
    assert again.added == 0 and again.updated == 0 and again.unchanged == 5


def test_links_explicit_and_related(workspace):
    cfg, _ = workspace
    brain = Brain(cfg, llm=OfflineLLM())
    brain.sync()
    acme = brain.store.find_by_title("Acme Corp")
    related = {n["title"]: n for n in brain.related(acme.id)}
    assert related["Pricing Playbook"]["kind"] == "explicit"     # [[wikilink]]
    assert related["Kickoff meeting"]["kind"] == "explicit"      # markdown relative link
    playbook = brain.store.find_by_title("Pricing Playbook")
    kinds = {n["title"]: n["kind"] for n in brain.related(playbook.id)}
    assert "Kickoff meeting" in kinds                            # similar topic, no explicit link


def test_search_finds_content_inside_office_files(workspace):
    cfg, _ = workspace
    brain = Brain(cfg, llm=OfflineLLM())
    brain.sync()
    assert brain.search("warehouse automation")[0].title == "Supply Chain Assessment"
    assert brain.search("Brazilian distributor")[0].title == "Market Entry"
    assert brain.search("pricing strategy")[0].title in {"Pricing Playbook", "Acme Corp", "Kickoff meeting"}


def test_changes_create_revisions_and_deletions_are_forgotten(workspace):
    cfg, notes = workspace
    brain = Brain(cfg, llm=OfflineLLM())
    brain.sync()
    playbook = notes / "Pricing Playbook.md"
    playbook.write_text("# Pricing Playbook\n\nNew guidance: subscription pricing for services.\n", encoding="utf-8")
    import os, time
    os.utime(playbook, (time.time() + 5, time.time() + 5))
    stats = brain.sync()[0]
    assert stats.updated == 1
    doc = brain.store.find_by_title("Pricing Playbook")
    assert len(brain.store.revisions(doc.id)) == 1
    assert brain.search("subscription")[0].doc_id == doc.id

    (notes / "market.pptx").unlink()
    assert brain.sync()[0].removed == 1
    assert brain.search("Brazilian") == []


def test_unreachable_source_keeps_existing_knowledge(workspace, tmp_path):
    cfg, notes = workspace
    brain = Brain(cfg, llm=OfflineLLM())
    brain.sync()
    cfg.sources[0].options["path"] = str(tmp_path / "unplugged-drive")
    stats = brain.sync("notes")[0]
    assert stats.errors and stats.removed == 0
    assert brain.store.stats()["documents"] == 5


def test_remember_learns_and_links(workspace):
    cfg, _ = workspace
    brain = Brain(cfg, llm=OfflineLLM())
    brain.sync()
    r = brain.remember("Acme agreed to pilot value-based pricing in two plants. See [[Acme Corp]].",
                       title="Acme pricing decision", tags=["decision"])
    assert brain.search("pilot plants")[0].doc_id == r["doc_id"]
    assert "Acme Corp" in {n["title"] for n in brain.related(r["doc_id"])}


def test_ask_offline_returns_cited_passages(workspace):
    cfg, _ = workspace
    brain = Brain(cfg, llm=OfflineLLM())
    brain.sync()
    result = brain.ask("What pricing approach suits manufacturing clients?")
    assert result["mode"] == "extractive" and result["sources"]
    assert "[1]" in result["answer"]


def test_ask_with_claude_passes_numbered_sources(workspace):
    cfg, _ = workspace
    llm = FakeLLM()
    brain = Brain(cfg, llm=llm)
    brain.sync()
    result = brain.ask("pricing strategy?")
    assert result["mode"] == "claude"
    assert "<sources>" in llm.prompts[0] and "[1]" in llm.prompts[0]


def test_create_docx_and_deck_and_learn_from_outputs(workspace):
    cfg, _ = workspace
    brain = Brain(cfg, llm=FakeLLM())
    brain.sync()
    d = brain.create_document("Acme pricing strategy", fmt="docx")
    assert Path(d["path"]).suffix == ".docx" and Path(d["markdown_path"]).exists()
    texts = [p.text for p in docx.Document(d["path"]).paragraphs]
    assert "Pricing Strategy Brief" in texts and "point one" in texts

    deck = brain.create_deck("Acme pricing strategy", slides=3)
    prs = Presentation(deck["path"])
    titles = [s.shapes.title.text for s in prs.slides]
    assert titles[:2] == ["Acme Pricing", "Value pricing wins"] and titles[-1] == "Sources"

    stats = {s.source: s for s in brain.sync()}
    assert stats["_outputs"].added == 3        # md + docx + pptx are now part of the brain


def test_deck_offline_fallback(workspace):
    cfg, _ = workspace
    brain = Brain(cfg, llm=OfflineLLM())
    brain.sync()
    deck = brain.create_deck("pricing strategy", slides=2)
    assert deck["mode"] == "extractive" and Path(deck["path"]).exists()


def test_enrich_links_shared_entities(workspace):
    cfg, _ = workspace
    brain = Brain(cfg, llm=FakeLLM())
    brain.sync()
    assert brain.enrich(limit=50)["enriched"] == 5
    doc = brain.store.find_by_title("Supply Chain Assessment")
    assert doc.summary == "About Acme." and doc.entities == ["Acme Corp"]
    assert any(n["kind"] == "entity" for n in brain.related(doc.id, 50))


def test_rest_api(workspace, monkeypatch):
    from secondbrain.api import make_server

    cfg, _ = workspace
    monkeypatch.setenv("BRAIN_API_TOKEN", "s3cret")
    brain = Brain(cfg, llm=OfflineLLM())
    server = make_server(brain, "127.0.0.1", 0)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{server.server_address[1]}"

    def call(path, body=None, token="s3cret"):
        req = urllib.request.Request(base + path, data=json.dumps(body).encode() if body is not None else None,
                                     headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"})
        with urllib.request.urlopen(req) as r:
            return json.loads(r.read())

    try:
        with pytest.raises(urllib.error.HTTPError):
            call("/status", token="wrong")
        assert call("/sync", {})[0]["added"] == 5
        hits = call("/search?q=warehouse")
        assert hits[0]["title"] == "Supply Chain Assessment"
        assert call(f"/documents/{hits[0]['doc_id']}")["kind"] == "document"
        assert call("/remember", {"text": "Call Jane on Friday"})["status"] == "added"
        assert call("/graph")["nodes"]
    finally:
        server.shutdown()


def test_mcp_server_exposes_tools(workspace):
    from secondbrain.mcp_server import build_server

    cfg, _ = workspace
    brain = Brain(cfg, llm=OfflineLLM())
    brain.sync()
    server = build_server(brain)
    names = {t.name for t in asyncio.run(server.list_tools())}
    assert {"search", "ask", "remember", "related", "create_document", "create_deck", "sync", "status"} <= names
