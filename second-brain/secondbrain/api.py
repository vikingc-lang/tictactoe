"""HTTP server: the web app (``/``) plus a REST API for other tools (Zapier/Make/n8n, scripts, bots).

Endpoints (JSON):
  GET  /status                      GET  /documents?source=&limit=
  GET  /search?q=...&limit=8        GET  /documents/{id}
  GET  /graph                       GET  /documents/{id}/related
  GET  /documents/{id}/file         GET  /outputs/{filename}      (download originals / creations)
  POST /ask        {"question"}     POST /remember {"text", "title"?, "tags"?}
  POST /sync       {"source"?}      (runs in the background; poll /status)
  POST /enrich     {"limit"?}
  POST /sources    {"type", "name", "target"}      POST /sources/remove {"name"}
  POST /create/document {"topic", "format"?, "instructions"?}
  POST /create/deck     {"topic", "slides"?, "instructions"?}
  POST /settings/claude-key {"key"}   (only from this computer)

Set ``BRAIN_API_TOKEN`` to require ``Authorization: Bearer <token>``. Binds to 127.0.0.1 by default.
"""

from __future__ import annotations

import hmac
import ipaddress
import json
import mimetypes
import os
import re
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, quote, unquote, urlparse
from urllib.request import url2pathname

from .brain import Brain
from .config import DEFAULT_HOME, append_source, load_config, remove_source, save_secret

UI_FILE = Path(__file__).parent / "ui" / "index.html"


def claude_configured() -> bool:
    return bool(os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN")
                or (Path.home() / ".config" / "anthropic").is_dir())


class BrainService:
    """Shares one Brain between request threads and the background watcher."""

    def __init__(self, brain: Brain):
        self.brain = brain
        self.lock = threading.RLock()  # one SQLite connection: serialise access
        self.sync_state: dict[str, Any] = {"running": False, "last_finished": None, "last_results": []}

    def config_file(self) -> Path:
        return self.brain.config.config_path or DEFAULT_HOME / "brain.toml"

    def reload_config(self) -> None:
        path = self.config_file()
        cfg = load_config(str(path)) if path.exists() else self.brain.config
        with self.lock:
            self.brain.config = cfg

    def _run_sync(self, source: str | None) -> None:
        # A separate connection: SQLite (WAL) lets the UI keep searching while this thread writes.
        worker = Brain(self.brain.config, llm=self.brain.llm)

        def progress(stats) -> None:
            self.sync_state["progress"] = f"{stats.source}: {stats.seen} files checked, {stats.added} new"

        try:
            results = [s.as_dict() for s in worker.sync(source, on_progress=progress)]
            self.sync_state["last_results"] = results
        except Exception as exc:  # surface the problem in the UI rather than killing the thread
            self.sync_state["last_results"] = [{"source": source or "all", "errors": [str(exc)]}]
        finally:
            worker.store.close()
            self.sync_state.update(running=False, last_finished=time.time(), progress="")

    def start_sync(self, source: str | None = None) -> dict[str, Any]:
        if self.sync_state["running"]:
            return {"started": False, "reason": "a sync is already running"}
        self.sync_state["running"] = True
        threading.Thread(target=self._run_sync, args=(source,), daemon=True).start()
        return {"started": True}

    def start_watcher(self, interval: int) -> None:
        def loop() -> None:
            while True:
                time.sleep(interval)
                if not self.sync_state["running"]:
                    self.sync_state["running"] = True
                    self._run_sync(None)

        threading.Thread(target=loop, daemon=True).start()

    def status(self) -> dict[str, Any]:
        with self.lock:
            out = self.brain.status()
        out["sync"] = self.sync_state
        out["claude_configured"] = claude_configured()
        out["config_file"] = str(self.config_file())
        out["configured_sources"] = [
            {"name": s.name, "type": s.type, **{k: v for k, v in s.options.items() if k != "headers"}}
            for s in self.brain.config.all_sources()]
        return out


def _is_local(address: str) -> bool:
    try:
        return ipaddress.ip_address(address).is_loopback
    except ValueError:
        return False


def make_handler(service: BrainService, token: str | None):
    brain_ref = service

    class Handler(BaseHTTPRequestHandler):
        server_version = "SecondBrain/0.2"

        def log_message(self, fmt, *args):  # quieter logs
            pass

        @property
        def brain(self) -> Brain:
            return brain_ref.brain

        def _send(self, code: int, payload: Any) -> None:
            body = json.dumps(payload, default=str).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _send_file(self, path: Path, download: bool = False) -> None:
            data = path.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", mimetypes.guess_type(path.name)[0] or "application/octet-stream")
            self.send_header("Content-Length", str(len(data)))
            disposition = "attachment" if download else "inline"
            self.send_header("Content-Disposition", f"{disposition}; filename*=UTF-8''{quote(path.name)}")
            self.end_headers()
            self.wfile.write(data)

        def _authorised(self) -> bool:
            if not token:
                return True
            supplied = self.headers.get("Authorization", "").removeprefix("Bearer ").strip()
            if not supplied:  # browser downloads can't set headers
                supplied = parse_qs(urlparse(self.path).query).get("token", [""])[0]
            return hmac.compare_digest(supplied, token)

        def _body(self) -> dict[str, Any]:
            length = int(self.headers.get("Content-Length") or 0)
            return json.loads(self.rfile.read(length) or b"{}") if length else {}

        def _route(self, method: str) -> None:
            url = urlparse(self.path)
            p = url.path.rstrip("/") or "/"
            if method == "GET" and p in {"/", "/index.html"}:
                body = UI_FILE.read_bytes()
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return
            if not self._authorised():
                return self._send(401, {"error": "unauthorised"})
            q = {k: v[0] for k, v in parse_qs(url.query).items()}
            try:
                result = self._dispatch(method, p, q)
            except (KeyError, ValueError, json.JSONDecodeError, FileNotFoundError) as exc:
                return self._send(400, {"error": str(exc) or exc.__class__.__name__})
            except PermissionError as exc:
                return self._send(403, {"error": str(exc)})
            if result is None:
                return self._send(404, {"error": "not found"})
            if isinstance(result, Path):
                return self._send_file(result, download=q.get("download") == "1")
            self._send(200, result)

        def _document_file(self, doc_id: int) -> Path | None:
            with service.lock:
                doc = self.brain.store.get(doc_id)
            if not doc or not doc.uri.startswith("file:"):
                return None
            path = Path(url2pathname(urlparse(doc.uri).path))
            return path if path.is_file() else None

        def _output_file(self, name: str) -> Path | None:
            out_dir = self.brain.config.output_dir.resolve()
            path = (out_dir / unquote(name)).resolve()
            if path.parent != out_dir:
                raise PermissionError("outside the outputs folder")
            return path if path.is_file() else None

        def _dispatch(self, method: str, p: str, q: dict[str, str]) -> Any:
            brain, lock = self.brain, service.lock
            if method == "GET":
                if p == "/status":
                    return service.status()
                if m := re.fullmatch(r"/documents/(\d+)/file", p):
                    return self._document_file(int(m.group(1)))
                if m := re.fullmatch(r"/outputs/([^/]+)", p):
                    return self._output_file(m.group(1))
                with lock:
                    if p == "/search":
                        return [h.to_dict() for h in brain.search(q["q"], int(q.get("limit", 8)), q.get("source"))]
                    if p == "/graph":
                        return brain.graph()
                    if p == "/documents":
                        return [d.to_dict() for d in brain.store.list_documents(
                            q.get("source"), int(q.get("limit", 100)), int(q.get("offset", 0)))]
                    if m := re.fullmatch(r"/documents/(\d+)", p):
                        return brain.document(int(m.group(1)))
                    if m := re.fullmatch(r"/documents/(\d+)/related", p):
                        return brain.related(int(m.group(1)))
                return None
            if method != "POST":
                return None
            body = self._body()
            if p == "/sync":
                return service.start_sync(body.get("source"))
            if p == "/sources":
                return self._add_source(body)
            if p == "/sources/remove":
                if not remove_source(service.config_file(), body["name"]):
                    raise ValueError(f"no source named {body['name']!r}")
                service.reload_config()
                return {"removed": body["name"]}
            if p == "/settings/claude-key":
                if not _is_local(self.client_address[0]):
                    raise PermissionError("the Claude key can only be set from this computer")
                key = body["key"].strip()
                if not key:
                    raise ValueError("key is empty")
                save_secret(brain.config.data_dir, "ANTHROPIC_API_KEY", key)
                brain.llm._client = None  # pick up the new key on the next call
                return {"saved": True}
            with lock:
                if p == "/ask":
                    return brain.ask(body["question"])
                if p == "/remember":
                    return brain.remember(body["text"], body.get("title"), body.get("tags"))
                if p == "/enrich":
                    return brain.enrich(int(body.get("limit", 20)))
                if p == "/create/document":
                    return self._with_download(brain.create_document(
                        body["topic"], body.get("format", "md"), body.get("instructions", "")))
                if p == "/create/deck":
                    return self._with_download(brain.create_deck(
                        body["topic"], int(body.get("slides", 8)), body.get("instructions", "")))
            return None

        def _with_download(self, result: dict[str, Any]) -> dict[str, Any]:
            result["download"] = "/outputs/" + quote(Path(result["path"]).name)
            return result

        def _add_source(self, body: dict[str, Any]) -> dict[str, Any]:
            type_, name, target = body["type"], body["name"].strip(), body["target"].strip()
            if not re.fullmatch(r"[A-Za-z0-9 _.\-]{1,60}", name):
                raise ValueError("name: use letters, numbers, spaces, - or _")
            if any(s.name == name for s in self.brain.config.all_sources()):
                raise ValueError(f"a source named {name!r} already exists")
            if type_ == "folder":
                folder = Path(target).expanduser()
                if not folder.is_dir():
                    raise FileNotFoundError(f"folder not found on this computer: {folder}")
                options: dict[str, Any] = {"path": str(folder.resolve())}
            elif type_ == "web":
                options = {"urls": [u.strip() for u in re.split(r"[\s,]+", target) if u.strip()]}
            elif type_ == "gdrive":
                options = {"folder_id": target,
                           "credentials": body.get("credentials") or str(DEFAULT_HOME / "gdrive-sa.json")}
            elif type_ == "http_json":
                options = {"url": target}
            else:
                raise ValueError(f"unknown source type {type_!r}")
            config_file = service.config_file()
            if not config_file.exists():
                config_file.parent.mkdir(parents=True, exist_ok=True)
                config_file.write_text("[brain]\n", encoding="utf-8")
            append_source(config_file, name, type_, **options)
            service.reload_config()
            service.start_sync(name)
            return {"added": name, "syncing": True}

        def do_GET(self):  # noqa: N802
            self._route("GET")

        def do_POST(self):  # noqa: N802
            self._route("POST")

    return Handler


def make_server(brain: Brain, host: str = "127.0.0.1", port: int = 8787,
                watch: bool = False) -> ThreadingHTTPServer:
    service = BrainService(brain)
    if watch:
        service.start_watcher(max(15, brain.config.watch_interval))
    server = ThreadingHTTPServer((host, port), make_handler(service, os.environ.get("BRAIN_API_TOKEN")))
    server.service = service  # type: ignore[attr-defined]
    return server


def main(host: str = "127.0.0.1", port: int = 8787, open_browser: bool = False, watch: bool = False) -> None:
    server = make_server(Brain(), host, port, watch=watch)
    url = f"http://{'localhost' if host in {'127.0.0.1', '0.0.0.0'} else host}:{server.server_address[1]}"
    print(f"Second Brain is running at {url}  (Ctrl+C to stop)")
    if open_browser:
        import webbrowser

        threading.Timer(0.8, lambda: webbrowser.open(url)).start()
    server.serve_forever()
