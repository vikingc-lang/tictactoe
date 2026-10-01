"""HTTP server: the web app (``/``) plus a REST API for other tools (Zapier/Make/n8n, scripts, bots).

Endpoints (JSON):
  GET  /status                      GET  /documents?source=&kind=&limit=&offset=
  GET  /search?q=...&limit=8        GET  /documents/{id}
  GET  /graph                       GET  /documents/{id}/related
  GET  /documents/{id}/file         GET  /outputs/{filename}      (download originals / creations)
  GET  /search?q=&days=30            (days: only documents dated in the last N days)
  POST /ask        {"question", "history"?: [{"q", "a"}]}   POST /remember {"text", "title"?, "tags"?}
  GET  /digest?days=7               POST /digest {"days"?, "use_ai"?}   (what's new, optionally briefed)
  GET  /collections                 POST /collections {"name", "doc_ids"}   POST /collections/remove {"name"}
  POST /sync       {"source"?}      (runs in the background; poll /status)
  POST /enrich     {"limit"?}
  POST /sources    {"type", "name", "target"}      POST /sources/remove {"name"}
  POST /create/document {"topic", "format"?, "instructions"?, "doc_ids"?, "use_ai"?}
  POST /create/deck     {"topic", "slides"?, "instructions"?, "doc_ids"?, "use_ai"?}
        doc_ids pins the reference documents (else the brain picks); use_ai=false builds without Claude
  POST /settings/claude-key {"key"}   (only from this computer)
  GET  /settings/ai                 POST /settings/ai {"mode": claude|local|claude_app|off, "local_provider"?,
                                                       "local_url"?, "local_model"?}   (only from this computer)
  GET  /settings/ai/models?provider=&url=     POST /settings/ai/test    (list / try the local AI)
  POST /settings/claude-desktop     (connect the Claude desktop app to this brain; only from this computer)
  POST /create/from-reply {"topic", "text", "format": docx|md|pptx, "sources"?}   (Claude-app mode: build the
        file from the reply the user pasted back)

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
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, quote, unquote, urlparse
from urllib.request import url2pathname

from .brain import Brain
from . import claude_desktop
from .config import DEFAULT_HOME, append_source, load_config, remove_source, save_secret
from .llm import AI_MODES, LOCAL_PROVIDERS, LLMUnavailable, LocalLLM, ai_settings, claude_configured, pull_status, start_pull

UI_FILE = Path(__file__).parent / "ui" / "index.html"
SECRET_OPTIONS = {"headers", "password", "oauth2_token", "credentials"}  # never sent to the browser

MAIL_SERVERS = {  # sensible IMAP defaults by email domain
    "gmail.com": "imap.gmail.com", "googlemail.com": "imap.gmail.com",
    "icloud.com": "imap.mail.me.com", "me.com": "imap.mail.me.com", "mac.com": "imap.mail.me.com",
    "yahoo.com": "imap.mail.yahoo.com", "fastmail.com": "imap.fastmail.com", "zoho.com": "imap.zoho.com",
    "outlook.com": "outlook.office365.com", "hotmail.com": "outlook.office365.com", "live.com": "outlook.office365.com",
}


class BrainService:
    """Shares one Brain between request threads and the background watcher."""

    def __init__(self, brain: Brain):
        self.brain = brain
        self.lock = threading.RLock()  # one SQLite connection: serialise access
        self.sync_state: dict[str, Any] = {"running": False, "last_finished": None, "last_results": []}
        self.stop_event = threading.Event()
        self.purge_removed()

    def purge_removed(self) -> None:
        """Forget sources that were removed from the config (their status rows and documents)."""
        with self.lock:
            self.brain.store.purge_sources({s.name for s in self.brain.config.all_sources()})

    def stop_sync(self) -> dict[str, Any]:
        if not self.sync_state["running"]:
            return {"stopping": False}
        self.stop_event.set()
        self.sync_state["stopping"] = True
        return {"stopping": True}

    @contextmanager
    def worker(self):
        """A Brain on its own SQLite connection for slow work (Claude calls), so the app never freezes."""
        w = Brain(self.brain.config, llm=self.brain.llm)
        try:
            yield w
        finally:
            w.store.close()

    def config_file(self) -> Path:
        return self.brain.config.config_path or DEFAULT_HOME / "brain.toml"

    def reload_config(self) -> None:
        path = self.config_file()
        cfg = load_config(str(path)) if path.exists() else self.brain.config
        with self.lock:
            self.brain.config = cfg
        self.purge_removed()

    def _run_sync(self, source: str | None) -> None:
        # A separate connection: SQLite (WAL) lets the UI keep searching while this thread writes.
        worker = Brain(self.brain.config, llm=self.brain.llm)

        self.stop_event.clear()
        self.sync_state.update(stopping=False, index=0, total=0, source="", seen=0, added=0)

        def progress(stats) -> None:
            self.sync_state.update(seen=stats.seen, added=stats.added, updated=stats.updated,
                                   progress=f"{stats.source}: {stats.seen} files checked, {stats.added} new")

        def on_source(i: int, n: int, name: str) -> None:
            self.sync_state.update(index=i, total=n, source=name, seen=0, added=0,
                                   progress=f"{name}: starting…")

        try:
            results = [s.as_dict() for s in worker.sync(source, on_progress=progress,
                                                        should_stop=self.stop_event.is_set, on_source=on_source)]
            self.sync_state["last_results"] = results
        except Exception as exc:  # surface the problem in the UI rather than killing the thread
            self.sync_state["last_results"] = [{"source": source or "all", "errors": [str(exc)]}]
        finally:
            worker.store.close()
            self.sync_state.update(running=False, stopping=False, last_finished=time.time(), progress="")

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
        out["ai"] = {**ai_settings(), "label": self.brain.ai_label}
        out["config_file"] = str(self.config_file())
        out["configured_sources"] = [
            {"name": s.name, "type": s.type, **{k: v for k, v in s.options.items() if k not in SECRET_OPTIONS}}
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
        server_version = "SecondBrain/0.4"

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
                        days = int(q["days"]) if q.get("days") else None
                        return [h.to_dict() for h in brain.search(q["q"], int(q.get("limit", 8)), q.get("source"), days)]
                    if p == "/digest":
                        return brain.whats_new(int(q.get("days", 7)))
                    if p == "/settings/ai":
                        return {**ai_settings(), "label": brain.ai_label, "claude_configured": claude_configured(),
                                "claude_desktop": claude_desktop.status()}
                    if p == "/collections":
                        return brain.collections()
                    if p == "/graph":
                        return brain.graph()
                    if p == "/documents":
                        return [d.to_dict() for d in brain.store.list_documents(
                            q.get("source"), int(q.get("limit", 100)), int(q.get("offset", 0)), q.get("kind"))]
                    if m := re.fullmatch(r"/documents/(\d+)", p):
                        return brain.document(int(m.group(1)))
                    if m := re.fullmatch(r"/documents/(\d+)/related", p):
                        return brain.related(int(m.group(1)))
                if p == "/settings/ai/pull":
                    return pull_status()
                if p == "/settings/ai/models":
                    local = LocalLLM(q.get("provider", "ollama"), q.get("url", ""))
                    try:
                        return {"models": local.models(), "url": local.url}
                    except LLMUnavailable as exc:
                        return {"models": [], "url": local.url, "error": str(exc)}
                return None
            if method != "POST":
                return None
            body = self._body()
            if p == "/sync":
                return service.start_sync(body.get("source"))
            if p == "/sync/stop":
                return service.stop_sync()
            if p == "/pick-folder":
                if self.client_address[0] not in {"127.0.0.1", "::1"}:
                    raise PermissionError("the folder picker only works from this computer")
                return {"path": _pick_folder()}
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
                claude = getattr(brain.llm, "claude", brain.llm)
                claude._client = None  # pick up the new key on the next call
                return {"saved": True}
            if p in ("/settings/ai", "/settings/claude-desktop"):
                if not _is_local(self.client_address[0]):
                    raise PermissionError("AI settings can only be changed from this computer")
                if p == "/settings/claude-desktop":
                    return claude_desktop.connect(service.config_file() if service.config_file().exists() else None)
                return self._save_ai(body)
            if p == "/settings/ai/pull":
                if not _is_local(self.client_address[0]):
                    raise PermissionError("models can only be downloaded from this computer")
                return start_pull(body.get("url", ""), body.get("model", ""))
            if p == "/settings/ai/test":
                with service.worker() as w:
                    try:
                        reply = w.llm.text("You are a helpful assistant.", "Reply with just the word: ready", 20)
                        return {"ok": True, "reply": reply[:200], "label": w.ai_label}
                    except LLMUnavailable as exc:
                        return {"ok": False, "error": str(exc), "label": w.ai_label}
            if p == "/create/from-reply":
                with lock:
                    return self._with_download(brain.save_written(
                        body["topic"], body["text"], body.get("format", "docx"), body.get("sources")))
            # Slow work that may call Claude runs on its own connection, outside the shared lock.
            if p in ("/ask", "/enrich", "/digest", "/create/document", "/create/deck"):
                with service.worker() as w:
                    if p == "/ask":
                        return w.ask(body["question"], history=body.get("history"))
                    if p == "/enrich":
                        return w.enrich(int(body.get("limit", 20)))
                    if p == "/digest":
                        return w.whats_new(int(body.get("days", 7)), use_ai=body.get("use_ai", False) is True)
                    opts = {"instructions": body.get("instructions", ""), "use_ai": body.get("use_ai", True) is not False,
                            "doc_ids": [int(i) for i in body.get("doc_ids") or []] or None}
                    if p == "/create/deck":
                        return self._with_download(w.create_deck(body["topic"], int(body.get("slides", 8)), **opts))
                    return self._with_download(w.create_document(body["topic"], body.get("format", "md"), **opts))
            with lock:
                if p == "/remember":
                    return brain.remember(body["text"], body.get("title"), body.get("tags"))
                if p == "/collections":
                    return brain.save_collection(body["name"], body.get("doc_ids") or [])
                if p == "/collections/remove":
                    return brain.delete_collection(body["name"])
            return None

        def _with_download(self, result: dict[str, Any]) -> dict[str, Any]:
            if result.get("path"):  # Claude-app hand-offs have no file yet
                result["download"] = "/outputs/" + quote(Path(result["path"]).name)
            return result

        def _save_ai(self, body: dict[str, Any]) -> dict[str, Any]:
            mode = str(body.get("mode", "")).strip()
            if mode not in AI_MODES:
                raise ValueError(f"mode must be one of {', '.join(AI_MODES)}")
            data_dir = self.brain.config.data_dir
            if mode == "local":
                provider = str(body.get("local_provider") or "ollama")
                if provider not in LOCAL_PROVIDERS:
                    raise ValueError("local_provider must be ollama or openai")
                url = str(body.get("local_url") or "").strip()
                if url and not re.match(r"^https?://", url):
                    raise ValueError("the local AI address should start with http:// (e.g. http://localhost:11434)")
                save_secret(data_dir, "BRAIN_LOCAL_PROVIDER", provider)
                save_secret(data_dir, "BRAIN_LOCAL_URL", url)
                save_secret(data_dir, "BRAIN_LOCAL_MODEL", str(body.get("local_model") or "").strip())
            save_secret(data_dir, "BRAIN_AI_MODE", mode)
            return {**ai_settings(), "label": self.brain.ai_label}

        def _mail_options(self, name: str, address: str, body: dict[str, Any]) -> dict[str, Any]:
            from .connectors.imap import ImapConnector

            if "@" not in address:
                raise ValueError("enter the full email address")
            host = (body.get("host") or "").strip() or MAIL_SERVERS.get(address.split("@")[1].lower(), "")
            if not host:
                raise ValueError("enter the IMAP server of your email provider (e.g. imap.example.com)")
            password = (body.get("password") or "").strip()
            if not password:
                raise ValueError("enter an app password for this mailbox")
            folders = [f.strip() for f in str(body.get("folders") or "INBOX").split(",") if f.strip()]
            options: dict[str, Any] = {"host": host, "username": address, "folders": folders,
                                       "since_days": int(body.get("since_days") or 365)}
            probe = ImapConnector(name, {**options, "password": password, "timeout": 10})
            try:  # check the sign-in before saving anything
                probe._connect().logout()
            except Exception as exc:
                raise ValueError(f"couldn't sign in to {host}: {exc}. Check the address and app password.") from exc
            secret = "MAIL_PASSWORD_" + re.sub(r"[^A-Z0-9]+", "_", name.upper()).strip("_")
            save_secret(self.brain.config.data_dir, secret, password)
            options["password"] = "${" + secret + "}"
            return options

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
            elif type_ == "imap":
                options = self._mail_options(name, target, body)
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


def _pick_folder() -> str:
    """Show the operating system's folder picker (on the machine running the app); '' if cancelled."""
    import subprocess
    import sys

    script = (
        "import tkinter as tk\n"
        "from tkinter import filedialog\n"
        "r = tk.Tk(); r.withdraw(); r.attributes('-topmost', True)\n"
        "print(filedialog.askdirectory(title='Choose a folder for your Second Brain', mustexist=True))\n"
    )
    try:
        out = subprocess.run([sys.executable, "-c", script], capture_output=True, text=True, timeout=300)
    except subprocess.TimeoutExpired:
        return ""
    if out.returncode != 0:
        raise RuntimeError("couldn't open the folder picker; paste the folder path instead")
    return out.stdout.strip().replace("/", os.sep)


def make_server(brain: Brain, host: str = "127.0.0.1", port: int = 8787,
                watch: bool = False) -> ThreadingHTTPServer:
    service = BrainService(brain)
    if watch:
        service.start_watcher(max(15, brain.config.watch_interval))
    server = ThreadingHTTPServer((host, port), make_handler(service, os.environ.get("BRAIN_API_TOKEN")))
    server.service = service  # type: ignore[attr-defined]
    return server


def main(host: str = "127.0.0.1", port: int = 8787, open_browser: bool = False, watch: bool = False,
         config: str | None = None) -> None:
    server = make_server(Brain(load_config(config)), host, port, watch=watch)
    url = f"http://{'localhost' if host in {'127.0.0.1', '0.0.0.0'} else host}:{server.server_address[1]}"
    print(f"Second Brain is running at {url}  (Ctrl+C to stop)")
    if open_browser:
        import webbrowser

        threading.Timer(0.8, lambda: webbrowser.open(url)).start()
    server.serve_forever()
