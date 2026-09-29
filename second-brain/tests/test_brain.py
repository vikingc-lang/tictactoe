"""End-to-end tests: sync real files, link them, search, learn, create artifacts, serve API/MCP."""

from __future__ import annotations

import asyncio
import email.utils
import json
import threading
import time
import urllib.error
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


def _serve(brain, **kw):
    from secondbrain.api import make_server

    server = make_server(brain, "127.0.0.1", 0, **kw)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, f"http://127.0.0.1:{server.server_address[1]}"


def _call(base, path, body=None, token=None, raw=False):
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(base + path, data=json.dumps(body).encode() if body is not None else None,
                                 headers=headers)
    with urllib.request.urlopen(req) as r:
        data = r.read()
        return data if raw else json.loads(data)


def _wait_for_sync(base, token=None):
    for _ in range(200):
        status = _call(base, "/status", token=token)
        if not status["sync"]["running"]:
            return status
        time.sleep(0.05)
    raise AssertionError("sync did not finish")


def test_rest_api(workspace, monkeypatch):
    cfg, _ = workspace
    monkeypatch.setenv("BRAIN_API_TOKEN", "s3cret")
    brain = Brain(cfg, llm=OfflineLLM())
    server, base = _serve(brain)
    try:
        with pytest.raises(urllib.error.HTTPError):
            _call(base, "/status", token="wrong")
        assert _call(base, "/sync", {}, token="s3cret")["started"] is True
        status = _wait_for_sync(base, "s3cret")
        assert status["stats"]["documents"] == 5 and status["sync"]["last_results"][0]["added"] == 5
        hits = _call(base, "/search?q=warehouse", token="s3cret")
        assert hits[0]["title"] == "Supply Chain Assessment"
        assert _call(base, f"/documents/{hits[0]['doc_id']}", token="s3cret")["kind"] == "document"
        original = _call(base, f"/documents/{hits[0]['doc_id']}/file?token=s3cret", raw=True)
        assert original[:2] == b"PK"                               # the real .docx comes back
        assert _call(base, "/remember", {"text": "Call Jane on Friday"}, token="s3cret")["status"] == "added"
        assert _call(base, "/graph", token="s3cret")["nodes"]
    finally:
        server.shutdown()


def test_web_ui_flow(workspace, tmp_path, monkeypatch):
    cfg, notes = workspace
    monkeypatch.delenv("BRAIN_API_TOKEN", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    cfg.config_path = tmp_path / "brain.toml"
    cfg.config_path.write_text(f'[brain]\ndata_dir = {json.dumps(str(cfg.data_dir))}\n'
                               f'output_dir = {json.dumps(str(cfg.output_dir))}\n', encoding="utf-8")
    cfg.sources = []
    brain = Brain(cfg, llm=OfflineLLM())
    server, base = _serve(brain)
    try:
        html = _call(base, "/", raw=True).decode()
        assert "<title>Second Brain</title>" in html

        # add a folder from the UI: it's written to brain.toml and synced in the background
        with pytest.raises(urllib.error.HTTPError):
            _call(base, "/sources", {"type": "folder", "name": "Bad", "target": str(tmp_path / "missing")})
        assert _call(base, "/sources", {"type": "folder", "name": "My Notes", "target": str(notes)})["syncing"]
        status = _wait_for_sync(base)
        assert status["stats"]["documents"] == 5
        assert "My Notes" in cfg.config_path.read_text()
        assert any(s["name"] == "My Notes" for s in status["configured_sources"])

        # create a deck and download it
        deck = _call(base, "/create/deck", {"topic": "pricing strategy", "slides": 2})
        data = _call(base, deck["download"] + "?download=1", raw=True)
        assert data[:2] == b"PK"
        with pytest.raises(urllib.error.HTTPError):
            _call(base, "/outputs/..%2F..%2Fbrain.toml", raw=True)

        # save a Claude key locally
        assert _call(base, "/settings/claude-key", {"key": "sk-ant-test"})["saved"]
        assert "ANTHROPIC_API_KEY=sk-ant-test" in (cfg.data_dir / "secrets.env").read_text()
        assert _call(base, "/status")["claude_configured"] is True

        # remove the source again
        _call(base, "/sources/remove", {"name": "My Notes"})
        assert "My Notes" not in cfg.config_path.read_text()
    finally:
        server.shutdown()


def test_windows_paths_survive_config_round_trip(tmp_path):
    from secondbrain.config import append_source, load_config

    path = tmp_path / "brain.toml"
    path.write_text(f"[brain]\ndata_dir = {json.dumps(str(tmp_path / 'd'))}\n", encoding="utf-8")
    append_source(path, "OneDrive", "folder", path="C:\\Users\\me\\OneDrive - Contoso\\Clients")
    cfg = load_config(str(path))
    assert cfg.sources[0].options["path"] == "C:\\Users\\me\\OneDrive - Contoso\\Clients"


def test_mcp_server_exposes_tools(workspace):
    from secondbrain.mcp_server import build_server

    cfg, _ = workspace
    brain = Brain(cfg, llm=OfflineLLM())
    brain.sync()
    server = build_server(brain)
    names = {t.name for t in asyncio.run(server.list_tools())}
    assert {"search", "ask", "remember", "related", "create_document", "create_deck", "sync", "status"} <= names


# ---------------------------------------------------------------- email
def _make_email(subject, body, attachments=(), sender="Marco Lindqvist <marco@acme.example>", date="Mon, 21 Sep 2026 10:00:00 +0000"):
    from email.message import EmailMessage

    msg = EmailMessage()
    msg["From"], msg["To"], msg["Subject"], msg["Date"] = sender, "Jane Rivera <jane@firm.example>", subject, date
    msg["Message-ID"] = f"<{abs(hash(subject))}@acme.example>"
    msg.set_content(body)
    for filename, data, maintype, subtype in attachments:
        msg.add_attachment(data, maintype=maintype, subtype=subtype, filename=filename)
    return msg.as_bytes()


def _docx_bytes(heading, text):
    import io
    d = docx.Document()
    d.add_heading(heading, 1)
    d.add_paragraph(text)
    buf = io.BytesIO()
    d.save(buf)
    return buf.getvalue()


DOCX = ("application", "vnd.openxmlformats-officedocument.wordprocessingml.document")


def test_email_files_with_attachments_and_mbox(tmp_path, monkeypatch):
    import mailbox

    mail = tmp_path / "mail"
    mail.mkdir()
    (mail / "budget.eml").write_bytes(_make_email(
        "Pumps pilot budget", "Jane, the pilot budget is approved at EUR 300k. Proposal attached.",
        [("Pilot Proposal.docx", _docx_bytes("Pilot Proposal", "Distributor pricing corridors for pumps."), *DOCX),
         ("logo.png", b"\x89PNG....", "image", "png")]))
    box = mailbox.mbox(str(mail / "archive.mbox"))
    box.add(_make_email("Kickoff agenda", "Agenda: churn analysis and warehouse automation."))
    box.add(_make_email("Minutes", "Tom agreed to join distributor interviews.",
                        [("notes.txt", b"Interview list: Globex, Initech.", "text", "plain")]))
    box.close()

    cfg = BrainConfig(data_dir=tmp_path / "data", output_dir=tmp_path / "out",
                      sources=[SourceConfig("mail", "folder", {"path": str(mail)})])
    cfg.data_dir.mkdir()
    cfg.output_dir.mkdir()
    brain = Brain(cfg, llm=OfflineLLM())
    stats = brain.sync("mail")[0]
    assert stats.errors == [] and stats.added == 5          # 3 emails + docx + txt (the png is skipped)

    email_doc = brain.store.find_by_title("Pumps pilot budget")
    assert email_doc.kind == "email" and "Attachments: Pilot Proposal.docx, logo.png" in email_doc.text
    hit = brain.search("distributor pricing corridors")[0]
    assert hit.title == "Pilot Proposal"                    # text inside the attachment is searchable
    rel = {n["title"]: n["kind"] for n in brain.related(email_doc.id)}
    assert rel["Pilot Proposal"] == "attachment"            # attachment linked to its email
    assert brain.search("Globex Initech")[0].title == "notes"

    # Unchanged mail files are not re-parsed on the next sync.
    import secondbrain.connectors.local as local
    monkeypatch.setattr(local, "parse_file_bytes", lambda *a: (_ for _ in ()).throw(AssertionError("re-parsed")))
    monkeypatch.setattr(local, "iter_mbox", lambda *a: (_ for _ in ()).throw(AssertionError("re-parsed")))
    again = brain.sync("mail")[0]
    assert again.unchanged == 5 and again.removed == 0 and again.errors == []


def test_outlook_msg_without_library_is_a_file_error(tmp_path):
    mail = tmp_path / "mail"
    mail.mkdir()
    (mail / "note.msg").write_bytes(b"\xd0\xcf\x11\xe0 not really")
    (mail / "ok.eml").write_bytes(_make_email("Fine", "All good"))
    cfg = BrainConfig(data_dir=tmp_path / "data", output_dir=tmp_path / "out",
                      sources=[SourceConfig("mail", "folder", {"path": str(mail)})])
    cfg.data_dir.mkdir()
    cfg.output_dir.mkdir()
    stats = Brain(cfg, llm=OfflineLLM()).sync("mail")[0]
    assert stats.added == 1 and len(stats.errors) == 1       # one bad file never stops the rest


class FakeIMAP:
    """Just enough of imaplib.IMAP4_SSL for the connector."""
    mailbox: dict[str, dict[int, bytes]] = {}
    fetches: list[str] = []
    logins: list[tuple] = []

    def __init__(self, host, port, timeout=None):
        assert timeout  # never hang on an unreachable server
        self.host, self.selected = host, None

    def login(self, user, password):
        FakeIMAP.logins.append((user, password))
        return "OK", [b"logged in"]

    def select(self, folder, readonly=False):
        assert readonly
        self.selected = folder.strip('"')
        return ("OK", [b"1"]) if self.selected in self.mailbox else ("NO", [b"no such folder"])

    def response(self, code):
        return code, [b"777"]

    def uid(self, command, *args):
        if command == "SEARCH":
            assert args[1].startswith("SINCE ")
            return "OK", [b" ".join(str(u).encode() for u in sorted(self.mailbox[self.selected]))]
        uid, spec = args
        assert spec == "(BODY.PEEK[])"                      # never marks mail as read
        FakeIMAP.fetches.append(uid)
        return "OK", [(b"1 (UID %s BODY[] {n}" % uid.encode(), self.mailbox[self.selected][int(uid)]), b")"]

    def logout(self):
        return "BYE", []


def test_imap_mailbox_sync(tmp_path, monkeypatch):
    import imaplib

    monkeypatch.setattr(imaplib, "IMAP4_SSL", FakeIMAP)
    monkeypatch.setenv("TEST_MAIL_PW", "app-password")
    FakeIMAP.mailbox = {"INBOX": {
        1: _make_email("SOW signed", "Acme signed the statement of work.",
                       [("SOW.docx", _docx_bytes("Statement of Work", "Phase 1 pricing diagnostic, 8 weeks."), *DOCX)]),
        2: _make_email("Lunch?", "Are you free Thursday?", sender="Tom <tom@acme.example>"),
    }}
    FakeIMAP.fetches, FakeIMAP.logins = [], []
    from secondbrain.config import expand_env
    cfg = BrainConfig(data_dir=tmp_path / "data", output_dir=tmp_path / "out", sources=[SourceConfig(
        "work-mail", "imap", expand_env({"host": "imap.example.com", "username": "jane@firm.example",
                                         "password": "${TEST_MAIL_PW}", "folders": ["INBOX"]}))])
    cfg.data_dir.mkdir()
    cfg.output_dir.mkdir()
    brain = Brain(cfg, llm=OfflineLLM())

    stats = brain.sync("work-mail")[0]
    assert stats.added == 3 and stats.errors == []
    assert FakeIMAP.logins == [("jane@firm.example", "app-password")]
    sow = brain.search("pricing diagnostic")[0]
    assert sow.title == "Statement of Work"
    email_doc = brain.store.find_by_title("SOW signed")
    assert email_doc.kind == "email" and "From: Marco Lindqvist" in email_doc.text
    assert sow.doc_id in {n["doc_id"] for n in brain.related(email_doc.id)}

    # Second sync downloads nothing already known; a new message is picked up; deleted mail is kept.
    FakeIMAP.fetches = []
    del FakeIMAP.mailbox["INBOX"][2]
    FakeIMAP.mailbox["INBOX"][3] = _make_email("Follow-up", "Next steering committee on 10 October.")
    stats = brain.sync("work-mail")[0]
    assert FakeIMAP.fetches == ["3"] and stats.added == 1 and stats.removed == 0
    assert brain.store.find_by_title("Lunch?") is not None


def test_add_mailbox_via_api_keeps_password_secret(tmp_path, monkeypatch):
    import imaplib

    class PickyIMAP(FakeIMAP):
        def login(self, user, password):
            if password != "right-pw":
                raise imaplib.IMAP4.error("AUTHENTICATIONFAILED")
            return super().login(user, password)

    monkeypatch.setattr(imaplib, "IMAP4_SSL", PickyIMAP)
    monkeypatch.delenv("BRAIN_API_TOKEN", raising=False)
    FakeIMAP.mailbox = {"INBOX": {1: _make_email("Hello", "First email")}}
    cfg = BrainConfig(data_dir=tmp_path / "data", output_dir=tmp_path / "out")
    cfg.data_dir.mkdir()
    cfg.output_dir.mkdir()
    cfg.config_path = tmp_path / "brain.toml"
    cfg.config_path.write_text(f"[brain]\ndata_dir = {json.dumps(str(cfg.data_dir))}\n"
                               f"output_dir = {json.dumps(str(cfg.output_dir))}\n", encoding="utf-8")
    server, base = _serve(Brain(cfg, llm=OfflineLLM()))
    try:
        req = {"type": "imap", "name": "Personal mail", "target": "me@gmail.com", "password": "wrong"}
        with pytest.raises(urllib.error.HTTPError) as err:
            _call(base, "/sources", req)
        assert "couldn't sign in to imap.gmail.com" in json.loads(err.value.read())["error"]
        assert "Personal mail" not in cfg.config_path.read_text()

        assert _call(base, "/sources", {**req, "password": "right-pw"})["syncing"]
        status = _wait_for_sync(base)
        assert status["stats"]["documents"] == 1
        toml = cfg.config_path.read_text()
        assert "right-pw" not in toml and "${MAIL_PASSWORD_PERSONAL_MAIL}" in toml
        assert "MAIL_PASSWORD_PERSONAL_MAIL=right-pw" in (cfg.data_dir / "secrets.env").read_text()
        mail_src = next(s for s in status["configured_sources"] if s["name"] == "Personal mail")
        assert "password" not in mail_src and mail_src["host"] == "imap.gmail.com"
    finally:
        server.shutdown()
        import os
        os.environ.pop("MAIL_PASSWORD_PERSONAL_MAIL", None)


# ---------------------------------------------------------------- create from chosen references
class ExplodingLLM:
    def text(self, *a, **k):
        raise AssertionError("Claude must not be called")

    structured = text


def test_create_with_chosen_references_uses_only_those(workspace):
    cfg, _ = workspace
    llm = FakeLLM()
    brain = Brain(cfg, llm=llm)
    brain.sync()
    supply = brain.store.find_by_title("Supply Chain Assessment")
    market = brain.store.find_by_title("Market Entry")
    result = brain.create_document("Operations brief", fmt="docx", doc_ids=[supply.id, market.id, supply.id])
    assert result["mode"] == "claude"
    assert [s["title"] for s in result["sources"]] == ["Supply Chain Assessment", "Market Entry"]
    prompt = llm.prompts[-1]
    assert "Warehouse automation" in prompt and "Brazilian" in prompt
    assert "Pricing Playbook" not in prompt and "Acme Corp" not in prompt   # nothing else sneaks in

    deck = brain.create_deck("Operations", slides=2, doc_ids=[market.id])
    assert [s["title"] for s in deck["sources"]] == ["Market Entry"]


def test_create_without_ai_never_calls_claude(workspace):
    cfg, _ = workspace
    brain = Brain(cfg, llm=ExplodingLLM())
    brain.sync()
    playbook = brain.store.find_by_title("Pricing Playbook")
    doc = brain.create_document("Pricing note", fmt="docx", doc_ids=[playbook.id], use_ai=False)
    assert doc["mode"] == "no_ai"
    texts = "\n".join(p.text for p in docx.Document(doc["path"]).paragraphs)
    assert "Value-based pricing beats cost-plus" in texts and "no AI" in texts
    deck = brain.create_deck("Pricing", slides=3, use_ai=False)          # no picks: brain chooses sources
    assert deck["mode"] == "no_ai" and deck["sources"]
    slides = Presentation(deck["path"]).slides
    assert any("Value-based pricing" in sh.text_frame.text for s in slides for sh in s.shapes if sh.has_text_frame)


def test_create_api_accepts_references_and_no_ai(workspace, monkeypatch):
    cfg, _ = workspace
    monkeypatch.delenv("BRAIN_API_TOKEN", raising=False)
    brain = Brain(cfg, llm=ExplodingLLM())
    brain.sync()
    market = brain.store.find_by_title("Market Entry")
    server, base = _serve(brain)
    try:
        r = _call(base, "/create/deck", {"topic": "Brazil", "slides": 2, "doc_ids": [market.id], "use_ai": False})
        assert r["mode"] == "no_ai" and [s["title"] for s in r["sources"]] == ["Market Entry"]
        assert _call(base, r["download"] + "?download=1", raw=True)[:2] == b"PK"
        with pytest.raises(urllib.error.HTTPError):                       # unknown ids -> clear error
            _call(base, "/create/document", {"topic": "x", "doc_ids": [99999], "use_ai": False})
    finally:
        server.shutdown()


# ---------------------------------------------------------------- v0.3: search quality, dates, follow-ups, digest, collections
def test_search_handles_accents_and_short_terms(workspace):
    cfg, notes = workspace
    (notes / "roadmap.md").write_text("# Q3 AI roadmap\n\nThe AI programme for HR and M&A starts in Q3 in Zürich.\n", encoding="utf-8")
    brain = Brain(cfg, llm=OfflineLLM())
    brain.sync()
    for q in ["Zürich", "zurich", "AI strategy", "HR", "Q3", "M&A"]:
        assert brain.search(q)[0].title == "Q3 AI roadmap", q


def test_empty_files_are_reported_not_indexed(workspace):
    cfg, notes = workspace
    (notes / "blank.md").write_text("   \n", encoding="utf-8")
    stats = Brain(cfg, llm=OfflineLLM()).sync()[0]
    assert stats.added == 5 and any("no readable text" in e for e in stats.errors)


def test_generated_documents_rank_below_originals(workspace):
    cfg, _ = workspace
    brain = Brain(cfg, llm=OfflineLLM())
    brain.sync()
    brain.create_document("Warehouse automation memo", use_ai=False,
                          doc_ids=[brain.store.find_by_title("Supply Chain Assessment").id])
    stats = {s.source: s for s in brain.sync()}
    assert stats["_outputs"].added == 1
    memo = brain.store.find_by_title("Warehouse automation memo")
    assert memo.id in {h.doc_id for h in brain.search("warehouse automation")}      # still findable in Search
    context = brain._context_hits("warehouse automation", 8)
    assert context and memo.id not in {h.doc_id for h in context}                 # but not cited in answers
    only_memo = brain._context_hits("Warehouse automation memo", 8)
    assert only_memo


def test_saved_answers_are_not_used_as_evidence(workspace):
    cfg, _ = workspace
    brain = Brain(cfg, llm=OfflineLLM())
    brain.sync()
    saved = brain.remember("Question: warehouse automation?\n\nWarehouse automation in Lyon [1].",
                           "Answer: warehouse automation", ["answer"])
    note = brain.remember("Warehouse automation vendor shortlist agreed with the COO.", "Vendor shortlist")
    assert brain.store.get(saved["doc_id"]).source == "_answers"
    assert brain.store.get(note["doc_id"]).source == "memory"
    assert saved["doc_id"] in {h.doc_id for h in brain.search("warehouse automation")}   # findable
    context = {h.doc_id for h in brain._context_hits("warehouse automation", 8)}
    assert note["doc_id"] in context and saved["doc_id"] not in context               # own notes count, own answers don't
    assert saved["doc_id"] not in {d["id"] for d in brain.whats_new(7)["docs"]}


def test_documents_carry_dates_used_for_filters_and_prompts(tmp_path):
    import os
    mail = tmp_path / "mail"
    mail.mkdir()
    (mail / "old.eml").write_bytes(_make_email("Old pricing note", "Pricing corridors v1.", date="Mon, 06 Jan 2025 09:00:00 +0000"))
    (mail / "new.eml").write_bytes(_make_email("New pricing note", "Pricing corridors v2.",
                                               date=email.utils.formatdate(time.time() - 86400)))
    old_file = mail / "legacy.md"
    old_file.write_text("# Legacy pricing\n\nPricing corridors v0.", encoding="utf-8")
    os.utime(old_file, (time.time() - 400 * 86400,) * 2)
    cfg = BrainConfig(data_dir=tmp_path / "data", output_dir=tmp_path / "out",
                      sources=[SourceConfig("mail", "folder", {"path": str(mail)})])
    cfg.data_dir.mkdir()
    cfg.output_dir.mkdir()
    llm = FakeLLM()
    brain = Brain(cfg, llm=llm)
    brain.sync()
    old = brain.store.find_by_title("Old pricing note")
    assert time.strftime("%Y-%m-%d", time.gmtime(old.doc_date)) == "2025-01-06"   # the email's sent date
    assert {h.title for h in brain.search("pricing corridors", days=30)} == {"New pricing note"}
    assert len({h.doc_id for h in brain.search("pricing corridors")}) == 3
    brain.ask("What are the latest pricing corridors?")
    assert "Old pricing note (2025-01-06)" in llm.prompts[-1]                  # Claude sees the dates


def test_store_migrates_databases_without_dates(tmp_path):
    import sqlite3
    db = tmp_path / "brain.db"
    con = sqlite3.connect(db)
    con.execute("CREATE TABLE documents (id INTEGER PRIMARY KEY, source TEXT NOT NULL, uri TEXT NOT NULL UNIQUE, "
                "title TEXT NOT NULL, kind TEXT NOT NULL, content_hash TEXT NOT NULL, modified REAL, indexed_at REAL NOT NULL, "
                "summary TEXT, tags TEXT DEFAULT '[]', entities TEXT DEFAULT '[]', text TEXT NOT NULL, deleted INTEGER NOT NULL DEFAULT 0)")
    con.execute("INSERT INTO documents (source, uri, title, kind, content_hash, modified, indexed_at, text) "
                "VALUES ('s', 'u', 'T', 'note', 'h', 1700000000, 1790000000, 'x')")
    con.commit()
    con.close()
    from secondbrain.store import Store
    store = Store(db)
    assert store.get(1).doc_date == 1700000000


def test_follow_up_questions_use_the_conversation(workspace):
    cfg, _ = workspace
    llm = FakeLLM()
    brain = Brain(cfg, llm=llm)
    brain.sync()
    first = brain.ask("What is in the supply chain assessment?")
    brain.ask("And what does it recommend?", history=[{"q": "What is in the supply chain assessment?", "a": first["answer"]}])
    prompt = llm.prompts[-1]
    assert "<conversation>" in prompt and "Q: What is in the supply chain assessment?" in prompt
    assert "Supply Chain Assessment" in prompt                                # retrieval followed the thread


def test_whats_new_digest(workspace):
    cfg, _ = workspace
    llm = FakeLLM()
    brain = Brain(cfg, llm=llm)
    brain.sync()
    brain.create_document("pricing output", use_ai=False)
    brain.sync()
    d = brain.whats_new(7)
    assert d["count"] == 5 and d["mode"] == "list" and d["by_kind"]["note"] == 3   # outputs excluded
    b = brain.whats_new(7, use_ai=True)
    assert b["mode"] == "claude" and b["briefing"] and b["sources"]
    assert "Brief me on the last 7 days" in llm.prompts[-1]
    assert Brain(cfg, llm=OfflineLLM()).whats_new(7, use_ai=True)["mode"] == "list"


def test_collections_api(workspace, monkeypatch):
    cfg, _ = workspace
    monkeypatch.delenv("BRAIN_API_TOKEN", raising=False)
    brain = Brain(cfg, llm=OfflineLLM())
    brain.sync()
    ids = [brain.store.find_by_title(t).id for t in ("Acme Corp", "Pricing Playbook")]
    server, base = _serve(brain)
    try:
        _call(base, "/collections", {"name": "Acme", "doc_ids": ids + [99999]})
        cols = _call(base, "/collections")
        assert cols == [{"name": "Acme", "doc_ids": ids, "titles": ["Acme Corp", "Pricing Playbook"], "updated": cols[0]["updated"]}]
        with pytest.raises(urllib.error.HTTPError):
            _call(base, "/collections", {"name": "Empty", "doc_ids": [99999]})
        _call(base, "/collections/remove", {"name": "Acme"})
        assert _call(base, "/collections") == []
        assert _call(base, "/digest?days=7")["count"] == 5
    finally:
        server.shutdown()


def test_app_stays_responsive_while_claude_works(workspace, monkeypatch):
    cfg, _ = workspace
    monkeypatch.delenv("BRAIN_API_TOKEN", raising=False)

    class SlowLLM(FakeLLM):
        def text(self, *a, **k):
            time.sleep(1.5)
            return "done [1]"

    brain = Brain(cfg, llm=SlowLLM())
    brain.sync()
    server, base = _serve(brain)
    try:
        t = threading.Thread(target=lambda: _call(base, "/ask", {"question": "warehouse automation?"}))
        t.start()
        time.sleep(0.3)
        start = time.time()
        assert _call(base, "/status")["stats"]["documents"] == 5
        assert _call(base, "/search?q=pricing")
        assert time.time() - start < 1.0                                       # not blocked by the Claude call
        t.join()
    finally:
        server.shutdown()


# ---- AI modes: local AI (Ollama / OpenAI-compatible), Claude app hand-off, off ---------------------------

class _FakeLocalAI:
    """A stand-in for Ollama (native API) and LM Studio (OpenAI-compatible API) on localhost."""

    def __init__(self, reject_schema=False):
        from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

        self.requests = []
        fake = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def _json(self, code, payload):
                body = json.dumps(payload).encode()
                self.send_response(code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_GET(self):  # noqa: N802
                if self.path == "/api/tags":
                    return self._json(200, {"models": [{"name": "qwen3:8b"}, {"name": "llama3.1:8b"}]})
                if self.path == "/v1/models":
                    return self._json(200, {"data": [{"id": "local-model"}]})
                self._json(404, {"error": "nope"})

            def do_POST(self):  # noqa: N802
                body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                fake.requests.append((self.path, body))
                wants_json = "format" in body or "response_format" in body or "JSON schema" in body["messages"][0]["content"]
                deck = {"title": "Ops", "subtitle": "s", "slides": [{"title": "Automate Lyon", "bullets": ["a"],
                                                                      "speaker_notes": "[1]"}]}
                content = ("<think>hmm</think>```json\n" + json.dumps(deck) + "\n```") if wants_json else \
                    "<think>let me see</think>Warehouse automation is planned [1]."
                if self.path == "/api/chat":
                    return self._json(200, {"message": {"role": "assistant", "content": content}})
                if self.path == "/v1/chat/completions":
                    if reject_schema and "response_format" in body:
                        return self._json(400, {"error": "response_format not supported"})
                    return self._json(200, {"choices": [{"message": {"role": "assistant", "content": content}}]})
                self._json(404, {"error": "nope"})

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), H)
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def close(self):
        self.server.shutdown()


@pytest.fixture
def ai_env(monkeypatch):
    for key in ("BRAIN_AI_MODE", "BRAIN_LOCAL_PROVIDER", "BRAIN_LOCAL_URL", "BRAIN_LOCAL_MODEL"):
        monkeypatch.setenv(key, "")
    return monkeypatch


def test_local_ai_ollama_answers_and_builds_decks(workspace, ai_env):
    from secondbrain.llm import LocalLLM

    fake = _FakeLocalAI()
    try:
        cfg, _ = workspace
        ai_env.setenv("BRAIN_AI_MODE", "local")
        ai_env.setenv("BRAIN_LOCAL_URL", fake.url)
        brain = Brain(cfg)
        brain.sync()
        assert brain.ai_kind == "local" and brain.ai_label == "Local AI (auto)"
        r = brain.ask("What about warehouse automation?")
        assert r["mode"] == "local" and r["answer"] == "Warehouse automation is planned [1]."   # <think> removed
        path, body = fake.requests[-1]
        assert path == "/api/chat" and body["model"] == "llama3.1:8b"         # an installed model is picked
        assert body["options"]["num_ctx"] >= 16384                           # bigger context than Ollama's default
        assert len(body["messages"][1]["content"]) < 26000                   # context sized for a local model
        deck = brain.create_deck("Warehouse automation plan", slides=3)
        assert deck["mode"] == "local" and Path(deck["path"]).exists()
        assert "format" in fake.requests[-1][1]                              # JSON schema passed to Ollama
        assert LocalLLM("ollama", fake.url).models() == ["llama3.1:8b", "qwen3:8b"]
    finally:
        fake.close()


def test_local_ai_openai_compatible_falls_back_without_schema(ai_env):
    from secondbrain.llm import LocalLLM
    from secondbrain.render import Deck

    fake = _FakeLocalAI(reject_schema=True)
    try:
        llm = LocalLLM("openai", fake.url + "/v1")
        assert llm.models() == ["local-model"]
        deck = llm.structured("Make a deck.", "about ops", Deck)
        assert deck.slides[0].title == "Automate Lyon"
        paths = [p for p, _ in fake.requests]
        assert paths == ["/v1/chat/completions", "/v1/chat/completions"]     # retried without response_format
        assert "response_format" not in fake.requests[-1][1]
    finally:
        fake.close()


def test_local_ai_not_running_is_explained(ai_env):
    from secondbrain.llm import LLMUnavailable, LocalLLM

    with pytest.raises(LLMUnavailable, match="cannot reach Ollama.*is it running"):
        LocalLLM("ollama", "http://127.0.0.1:9", "llama3.1").text("s", "p")


def test_claude_app_mode_hands_off_prompts_and_builds_files_from_replies(workspace, ai_env):
    cfg, _ = workspace
    ai_env.setenv("BRAIN_AI_MODE", "claude_app")
    brain = Brain(cfg)
    brain.sync()
    r = brain.ask("What about warehouse automation?")
    assert r["mode"] == "handoff" and "Supply Chain Assessment" in r["handoff"] and "cite them inline" in r["handoff"]
    before = set(cfg.output_dir.iterdir())
    doc = brain.create_document("Warehouse automation brief", fmt="docx")
    assert doc["mode"] == "handoff" and "Write a document about: Warehouse automation brief" in doc["handoff"]
    assert set(cfg.output_dir.iterdir()) == before                          # nothing written until the reply
    out = brain.save_written("Warehouse automation brief", "# Ops brief\n\nAutomate Lyon [1].", "docx", doc["sources"])
    assert out["path"].endswith(".docx") and out["mode"] == "claude_app"
    assert "Automate Lyon" in "\n".join(p.text for p in docx.Document(out["path"]).paragraphs)
    deck = brain.create_deck("Warehouse automation plan", slides=2)
    assert deck["mode"] == "handoff" and "## Slide 1 action title" in deck["handoff"]
    reply = "# Ops plan\nBoard update\n\n## Automating Lyon pays back in 14 months\n- EUR 300k\nNotes: [1]\n\n## Next\n- pilot"
    pptx = brain.save_written("Warehouse automation plan", reply, "pptx", deck["sources"])
    titles = [s.shapes.title.text for s in Presentation(pptx["path"]).slides if s.shapes.title]
    assert "Automating Lyon pays back in 14 months" in titles and pptx["slides"] == 2
    with pytest.raises(ValueError):
        brain.save_written("x", "just prose, no slides", "pptx")
    assert brain.whats_new(7, use_ai=True)["mode"] == "handoff"
    assert "Claude app" in brain.enrich(1)["errors"][0] or "switch AI" in brain.enrich(1)["errors"][0]


def test_ai_off_and_switching_apply_immediately(workspace, ai_env):
    cfg, _ = workspace
    brain = Brain(cfg)
    brain.sync()
    ai_env.setenv("BRAIN_AI_MODE", "off")
    r = brain.ask("warehouse automation?")
    assert r["mode"] == "extractive" and "switched off" in r["reason"]
    ai_env.setenv("BRAIN_AI_MODE", "claude_app")
    assert brain.ask("warehouse automation?")["mode"] == "handoff"             # same Brain, no restart


def test_ai_settings_api_and_reply_upload(workspace, ai_env):
    cfg, _ = workspace
    ai_env.delenv("BRAIN_API_TOKEN", raising=False)
    fake = _FakeLocalAI()
    brain = Brain(cfg)
    brain.sync()
    server, base = _serve(brain)
    try:
        with pytest.raises(urllib.error.HTTPError):
            _call(base, "/settings/ai", {"mode": "genius"})
        _call(base, "/settings/ai", {"mode": "local", "local_provider": "ollama", "local_url": fake.url,
                                     "local_model": "llama3.1:8b"})
        status = _call(base, "/status")
        assert status["ai"]["mode"] == "local" and status["ai"]["label"] == "Local AI (llama3.1:8b)"
        assert (cfg.data_dir / "secrets.env").read_text().count("BRAIN_AI_MODE=local") == 1
        assert _call(base, f"/settings/ai/models?provider=ollama&url={fake.url}")["models"] == ["llama3.1:8b", "qwen3:8b"]
        test = _call(base, "/settings/ai/test", {})
        assert test["ok"] and "Warehouse" in test["reply"]
        assert _call(base, "/ask", {"question": "warehouse automation?"})["mode"] == "local"
        _call(base, "/settings/ai", {"mode": "claude_app"})
        doc = _call(base, "/create/document", {"topic": "Warehouse automation brief", "format": "docx"})
        assert doc["mode"] == "handoff" and "download" not in doc
        made = _call(base, "/create/from-reply", {"topic": "Warehouse automation brief", "text": "# Ops\n\nDone [1].", "format": "docx",
                                                  "sources": doc["sources"]})
        assert made["download"].endswith(".docx") and _call(base, made["download"], raw=True)[:2] == b"PK"
    finally:
        server.shutdown()
        fake.close()


def test_connect_claude_desktop_keeps_existing_settings(tmp_path):
    from secondbrain import claude_desktop

    path = tmp_path / "Claude" / "claude_desktop_config.json"
    path.parent.mkdir()
    path.write_text(json.dumps({"mcpServers": {"gmail": {"command": "x"}}, "theme": "dark"}), encoding="utf-8")
    assert claude_desktop.status(path) == {"config_path": str(path), "app_found": True, "connected": False}
    r = claude_desktop.connect(tmp_path / "brain.toml", path)
    data = json.loads(path.read_text())
    assert r["connected"] and data["theme"] == "dark" and "gmail" in data["mcpServers"]
    entry = data["mcpServers"]["second-brain"]
    assert entry["args"][-1] == "mcp" and str(tmp_path / "brain.toml") in entry["args"]
    assert path.with_suffix(".json.bak").exists()
    path.write_text("{broken", encoding="utf-8")
    with pytest.raises(ValueError, match="isn't valid JSON"):
        claude_desktop.connect(None, path)


def test_mcp_hands_the_writing_to_the_calling_model(workspace, ai_env):
    from secondbrain.mcp_server import _for_caller

    cfg, _ = workspace
    ai_env.setenv("BRAIN_AI_MODE", "claude_app")
    brain = Brain(cfg)
    brain.sync()
    r = _for_caller(brain.create_document("Warehouse automation brief", fmt="docx"), "document")
    assert "prompt" in r and "handoff" not in r and "save_document" in r["next_step"]
    assert _for_caller({"mode": "claude", "answer": "x"}, "ask") == {"mode": "claude", "answer": "x"}
