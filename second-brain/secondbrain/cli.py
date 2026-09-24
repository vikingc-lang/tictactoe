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
    for h in _brain(args).search(args.query, args.limit, args.source):
        snippet = " ".join(h.text.split())[:220]
        print(f"#{h.doc_id:<5} {h.title}  ({h.source})\n       {snippet}\n")


def cmd_ask(args) -> None:
    result = _brain(args).ask(args.question)
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
    if args.what == "deck":
        result = brain.create_deck(args.topic, args.slides, args.instructions or "")
    else:
        result = brain.create_document(args.topic, args.what, args.instructions or "")
    print(f"created {result['path']}")


def cmd_status(args) -> None:
    _print(_brain(args).status())


def cmd_graph(args) -> None:
    data = _brain(args).graph()
    Path(args.out).write_text(json.dumps(data, indent=1), encoding="utf-8")
    print(f"wrote {len(data['nodes'])} nodes / {len(data['edges'])} edges to {args.out}")


def cmd_api(args) -> None:
    from .api import main

    main(args.host, args.port)


def cmd_mcp(args) -> None:
    from .mcp_server import main

    main(http=args.http, host=args.host, port=args.port)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="brain", description="Your second brain: connect, learn, recall, create.")
    p.add_argument("--config", help="path to brain.toml")
    p.add_argument("-v", "--verbose", action="store_true")
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("init", help="create a starter brain.toml").set_defaults(fn=cmd_init)

    a = sub.add_parser("add", help="connect a new source")
    a.add_argument("type", choices=["folder", "web", "gdrive", "http_json"])
    a.add_argument("name")
    a.add_argument("target", help="folder path, URL, or Drive folder id")
    a.add_argument("--credentials", help="service-account JSON for gdrive")
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
    se.set_defaults(fn=cmd_search)

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
    c.set_defaults(fn=cmd_create)

    sub.add_parser("status", help="sources and stats").set_defaults(fn=cmd_status)

    g = sub.add_parser("graph", help="export the knowledge graph as JSON")
    g.add_argument("--out", default="brain-graph.json")
    g.set_defaults(fn=cmd_graph)

    api = sub.add_parser("api", help="run the REST API")
    api.add_argument("--host", default="127.0.0.1")
    api.add_argument("--port", type=int, default=8787)
    api.set_defaults(fn=cmd_api)

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
