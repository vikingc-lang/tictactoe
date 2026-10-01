"""Command line: ``brain <command>``. Run ``brain -h`` for help."""

from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from pathlib import Path

from .config import DEFAULT_HOME, append_source, find_config_path


def _brain(args):
    from .brain import Brain
    from .config import load_config

    return Brain(load_config(args.config))


def _print(obj) -> None:
    print(json.dumps(obj, indent=2, default=str, ensure_ascii=False))


def cmd_init(args) -> None:
    path = Path(args.config or DEFAULT_HOME / "brain.toml").expanduser()
    if path.exists():
        print(f"config already exists: {path}")
        return
    example = Path(__file__).resolve().parent.parent / "brain.example.toml"
    path.parent.mkdir(parents=True, exist_ok=True)
    if example.exists():
        path.write_text(example.read_text(encoding="utf-8"), encoding="utf-8")
    else:
        path.write_text('[brain]\nmodel = "claude-opus-5"\n', encoding="utf-8")
    print(f"created {path} - edit it to add your folders, drives and APIs, then run: brain sync")


def cmd_add(args) -> None:
    path = find_config_path(args.config) or Path(DEFAULT_HOME / "brain.toml")
    options = {}
    if args.type == "folder":
        options["path"] = str(Path(args.target).expanduser().resolve())
    elif args.type == "web":
        options["urls"] = [args.target]
    elif args.type == "gdrive":
        options["folder_id"] = args.target
        options["credentials"] = args.credentials or str(DEFAULT_HOME / "gdrive-sa.json")
    elif args.type == "http_json":
        options["url"] = args.target
    elif args.type == "imap":
        import getpass
        import re

        from .api import MAIL_SERVERS
        from .config import load_config, save_secret

        host = args.host or MAIL_SERVERS.get(args.target.split("@")[-1].lower())
        if not host:
            sys.exit("pass --host with your provider's IMAP server")
        secret = "MAIL_PASSWORD_" + re.sub(r"[^A-Z0-9]+", "_", args.name.upper()).strip("_")
        save_secret(load_config(args.config).data_dir, secret, getpass.getpass(f"App password for {args.target}: "))
        options.update(host=host, username=args.target, password="${" + secret + "}",
                       folders=[f.strip() for f in args.folders.split(",")], since_days=args.since_days)
    append_source(path, args.name, args.type, **options)
    print(f"added source '{args.name}' to {path}")


def cmd_sync(args) -> None:
    brain = _brain(args)
    for s in brain.sync(args.source):
        d = s.as_dict()
        errs = d.pop("errors")
        print(f"{d.pop('source'):<20} " + "  ".join(f"{k}={v}" for k, v in d.items()) +
              (f"  errors={len(errs)}" if errs else ""))
        for e in errs[:5]:
            print(f"    ! {e}")


def cmd_watch(args) -> None:
    brain = _brain(args)
    interval = args.interval or brain.config.watch_interval
    print(f"watching {len(brain.config.all_sources())} sources every {interval}s (Ctrl+C to stop)")
    while True:
        for s in brain.sync():
            if s.added or s.updated or s.removed:
                print(f"[{time.strftime('%H:%M:%S')}] {s.source}: +{s.added} ~{s.updated} -{s.removed}")
        time.sleep(interval)


def cmd_search(args) -> None:
    for h in _brain(args).search(args.query, args.limit, args.source, args.days):
        snippet = " ".join(h.text.split())[:220]
        print(f"#{h.doc_id:<5} {h.title}  ({h.source})\n       {snippet}\n")


def cmd_digest(args) -> None:
    from datetime import datetime

    d = _brain(args).whats_new(args.days, use_ai=args.ai)
    print(f"{d['count']} new or changed in the last {d['days']} days"
          + (": " + ", ".join(f"{n} {k}" for k, n in d["by_kind"].items()) if d["by_kind"] else ""))
    if d.get("handoff"):
        _handoff(d["handoff"])
    if d["briefing"]:
        print("\n" + d["briefing"] + "\n")
    elif d.get("error"):
        print(f"(briefing unavailable: {d['error']})")
    for doc in d["docs"]:
        when = datetime.fromtimestamp(doc["date"]).strftime("%Y-%m-%d") if doc["date"] else ""
        print(f"  #{doc['id']:<5} {when}  {doc['title']}  ({doc['source']})")


def _handoff(prompt: str, then: str = "") -> None:
    print("AI is set to the Claude app. Paste everything between the lines into Claude (claude.ai or the desktop app)"
          + (f", {then}" if then else "") + ":\n" + "-" * 72 + "\n" + prompt + "\n" + "-" * 72)


def cmd_ask(args) -> None:
    result = _brain(args).ask(args.question)
    if result.get("handoff"):
        return _handoff(result["handoff"])
    if result.get("reason"):
        print(f"({result['reason']}. Most relevant passages:)\n")
    print(result["answer"])
    if result["sources"]:
        print("\nSources:")
        for s in result["sources"]:
            print(f"  [{s['n']}] {s['title']}  <{s['uri']}>")


def cmd_remember(args) -> None:
    text = args.text if args.text != "-" else sys.stdin.read()
    _print(_brain(args).remember(text, args.title, args.tags.split(",") if args.tags else None))


def cmd_show(args) -> None:
    doc = _brain(args).document(args.doc_id)
    if not doc:
        sys.exit(f"no document {args.doc_id}")
    doc["text"] = doc["text"][: args.chars]
    _print(doc)


def cmd_related(args) -> None:
    for n in _brain(args).related(args.doc_id, args.limit):
        print(f"#{n['doc_id']:<5} {n['kind']:<8} {n['weight']:<6} {n['title']}   {n['label'] or ''}")


def cmd_enrich(args) -> None:
    _print(_brain(args).enrich(args.limit))


def cmd_create(args) -> None:
    brain = _brain(args)
    opts = {"instructions": args.instructions or "", "use_ai": not args.no_ai,
            "doc_ids": [int(i) for i in args.docs.split(",")] if args.docs else None}
    if args.what == "deck":
        result = brain.create_deck(args.topic, args.slides, **opts)
    else:
        result = brain.create_document(args.topic, args.what, **opts)
    if result.get("handoff"):
        fmt = "pptx" if args.what == "deck" else args.what
        pending = _pending_file(brain, args.topic)  # so save-reply knows the format and the numbered sources
        pending.parent.mkdir(parents=True, exist_ok=True)
        pending.write_text(json.dumps({"format": fmt, "sources": result["sources"]}), encoding="utf-8")
        return _handoff(result["handoff"], "save Claude's reply in a text file, then run:\n"
                                           f"  brain save-reply \"{args.topic}\" --file reply.txt")
    print(f"created {result['path']}")


def _pending_file(brain, topic: str) -> Path:
    import re

    return brain.config.data_dir / "pending" / (re.sub(r"[^a-z0-9]+", "-", topic.lower()).strip("-")[:60] + ".json")


def cmd_save_reply(args) -> None:
    brain = _brain(args)
    text = sys.stdin.read() if args.file == "-" else Path(args.file).read_text(encoding="utf-8")
    pending_path = _pending_file(brain, args.topic)
    pending = json.loads(pending_path.read_text(encoding="utf-8")) if pending_path.is_file() else {}
    sources = json.loads(args.sources) if args.sources else pending.get("sources")
    result = brain.save_written(args.topic, text, args.format or pending.get("format", "docx"), sources)
    pending_path.unlink(missing_ok=True)
    print(f"created {result['path']}")


def cmd_ai(args) -> None:
    from . import claude_desktop
    from .config import load_config, save_secret
    from .llm import LLMUnavailable, LocalLLM, ai_settings

    cfg = load_config(args.config)
    if args.action == "set":
        if not args.mode:
            sys.exit("say which AI: brain ai set claude | local | claude_app | off")
        if args.mode == "local":
            save_secret(cfg.data_dir, "BRAIN_LOCAL_PROVIDER", args.provider or "ollama")
            save_secret(cfg.data_dir, "BRAIN_LOCAL_URL", args.url or "")
            save_secret(cfg.data_dir, "BRAIN_LOCAL_MODEL", args.model or "")
        save_secret(cfg.data_dir, "BRAIN_AI_MODE", args.mode)
    if args.action == "models":
        s = ai_settings()
        try:
            print("\n".join(LocalLLM(args.provider or s["local_provider"], args.url or s["local_url"]).models())
                  or "no models installed (Ollama: ollama pull llama3.1)")
        except LLMUnavailable as exc:
            sys.exit(str(exc))
        return
    if args.action == "test":
        brain = _brain(args)
        try:
            print(f"{brain.ai_label}: {brain.llm.text('You are a helpful assistant.', 'Reply with just: ready', 20)}")
        except LLMUnavailable as exc:
            sys.exit(f"{brain.ai_label}: {exc}")
        return
    if args.action == "connect-desktop":
        r = claude_desktop.connect(cfg.config_path)
        print(f"Claude Desktop now has the brain as a connector ({r['config_path']}). Restart Claude Desktop.")
        return
    _print({**ai_settings(), "claude_desktop": claude_desktop.status()})


def cmd_status(args) -> None:
    _print(_brain(args).status())


def cmd_graph(args) -> None:
    data = _brain(args).graph()
    Path(args.out).write_text(json.dumps(data, indent=1), encoding="utf-8")
    print(f"wrote {len(data['nodes'])} nodes / {len(data['edges'])} edges to {args.out}")


def cmd_api(args) -> None:
    from .api import main

    main(args.host, args.port, config=args.config)


def cmd_ui(args) -> None:
    from .api import main

    main(args.host, args.port, open_browser=not args.no_browser, watch=not args.no_watch, config=args.config)


def cmd_mcp(args) -> None:
    from .mcp_server import main

    main(http=args.http, host=args.host, port=args.port, config=args.config)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="brain", description="Your second brain: connect, learn, recall, create.")
    p.add_argument("--config", help="path to brain.toml")
    p.add_argument("-v", "--verbose", action="store_true")
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("init", help="create a starter brain.toml").set_defaults(fn=cmd_init)

    a = sub.add_parser("add", help="connect a new source")
    a.add_argument("type", choices=["folder", "imap", "web", "gdrive", "http_json"])
    a.add_argument("name")
    a.add_argument("target", help="folder path, email address (imap), URL, or Drive folder id")
    a.add_argument("--credentials", help="service-account JSON for gdrive")
    a.add_argument("--host", help="IMAP server (auto for Gmail, iCloud, Yahoo, Fastmail, Zoho)")
    a.add_argument("--folders", default="INBOX", help="IMAP folders, comma separated")
    a.add_argument("--since-days", type=int, default=365, help="how far back to read email")
    a.set_defaults(fn=cmd_add)

    s = sub.add_parser("sync", help="index new/changed content from sources")
    s.add_argument("source", nargs="?")
    s.set_defaults(fn=cmd_sync)

    w = sub.add_parser("watch", help="keep syncing continuously")
    w.add_argument("--interval", type=int)
    w.set_defaults(fn=cmd_watch)

    se = sub.add_parser("search", help="keyword search")
    se.add_argument("query")
    se.add_argument("--limit", type=int, default=8)
    se.add_argument("--source")
    se.add_argument("--days", type=int, help="only documents dated in the last N days")
    se.set_defaults(fn=cmd_search)

    dg = sub.add_parser("digest", help="what's new in the last N days (optionally briefed by Claude)")
    dg.add_argument("--days", type=int, default=7)
    dg.add_argument("--ai", action="store_true", help="add a short cited briefing written by Claude")
    dg.set_defaults(fn=cmd_digest)

    q = sub.add_parser("ask", help="ask a question, answered with citations")
    q.add_argument("question")
    q.set_defaults(fn=cmd_ask)

    r = sub.add_parser("remember", help="capture a note or fact ('-' reads stdin)")
    r.add_argument("text")
    r.add_argument("--title")
    r.add_argument("--tags", help="comma separated")
    r.set_defaults(fn=cmd_remember)

    sh = sub.add_parser("show", help="show a document with its connections")
    sh.add_argument("doc_id", type=int)
    sh.add_argument("--chars", type=int, default=3000)
    sh.set_defaults(fn=cmd_show)

    rl = sub.add_parser("related", help="list connected documents")
    rl.add_argument("doc_id", type=int)
    rl.add_argument("--limit", type=int, default=15)
    rl.set_defaults(fn=cmd_related)

    e = sub.add_parser("enrich", help="Claude summarises, tags and links documents by entity")
    e.add_argument("--limit", type=int, default=20)
    e.set_defaults(fn=cmd_enrich)

    c = sub.add_parser("create", help="generate an artifact from your knowledge")
    c.add_argument("what", choices=["md", "docx", "deck"])
    c.add_argument("topic")
    c.add_argument("--slides", type=int, default=8)
    c.add_argument("--instructions")
    c.add_argument("--docs", help="reference document ids to use, comma separated (see `brain search`)")
    c.add_argument("--no-ai", action="store_true", help="assemble from the references without calling Claude")
    c.set_defaults(fn=cmd_create)

    sub.add_parser("status", help="sources and stats").set_defaults(fn=cmd_status)

    sr = sub.add_parser("save-reply", help="turn a reply written in the Claude app into a .docx/.md/.pptx")
    sr.add_argument("topic")
    sr.add_argument("--format", choices=["docx", "md", "pptx"], help="default: what `brain create` asked for, else docx")
    sr.add_argument("--file", default="-", help="file with Claude's reply ('-' reads stdin)")
    sr.add_argument("--sources", help="numbered sources as JSON (normally remembered from `brain create`)")
    sr.set_defaults(fn=cmd_save_reply)

    ai = sub.add_parser("ai", help="choose the AI: Claude API, local AI (Ollama/LM Studio), the Claude app, or off")
    ai.add_argument("action", nargs="?", default="status", choices=["status", "set", "models", "test", "connect-desktop"])
    ai.add_argument("mode", nargs="?", choices=["claude", "local", "claude_app", "off"], help="for `set`")
    ai.add_argument("--provider", choices=["ollama", "openai"],
                    help="local AI server: ollama, or openai for LM Studio and other OpenAI-compatible servers")
    ai.add_argument("--url", help="local AI address (default http://localhost:11434 or http://localhost:1234/v1)")
    ai.add_argument("--model", help="local model name, e.g. llama3.1:8b (default: first installed)")
    ai.set_defaults(fn=cmd_ai)

    g = sub.add_parser("graph", help="export the knowledge graph as JSON")
    g.add_argument("--out", default="brain-graph.json")
    g.set_defaults(fn=cmd_graph)

    api = sub.add_parser("api", help="run the REST API")
    api.add_argument("--host", default="127.0.0.1")
    api.add_argument("--port", type=int, default=8787)
    api.set_defaults(fn=cmd_api)

    ui = sub.add_parser("ui", help="open the web app (keeps syncing in the background)")
    ui.add_argument("--host", default="127.0.0.1")
    ui.add_argument("--port", type=int, default=8787)
    ui.add_argument("--no-browser", action="store_true", help="don't open a browser tab")
    ui.add_argument("--no-watch", action="store_true", help="don't auto-sync in the background")
    ui.set_defaults(fn=cmd_ui)

    m = sub.add_parser("mcp", help="run the MCP server (stdio by default)")
    m.add_argument("--http", action="store_true", help="serve streamable HTTP instead of stdio")
    m.add_argument("--host", default="127.0.0.1")
    m.add_argument("--port", type=int, default=8765)
    m.set_defaults(fn=cmd_mcp)
    return p


def main(argv: list[str] | None = None) -> None:
    args = build_parser().parse_args(argv)
    logging.basicConfig(level=logging.INFO if args.verbose else logging.WARNING, stream=sys.stderr)
    try:
        args.fn(args)
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
