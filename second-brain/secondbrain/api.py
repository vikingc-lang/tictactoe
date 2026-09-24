"""REST API so other tools (Zapier/Make/n8n, scripts, a web UI, Slack bots) can use the brain.

Endpoints (JSON):
  GET  /status                      GET  /documents?source=&limit=
  GET  /search?q=...&limit=8        GET  /documents/{id}
  GET  /graph                       GET  /documents/{id}/related
  POST /ask        {"question"}     POST /remember {"text", "title"?, "tags"?}
  POST /sync       {"source"?}      POST /enrich   {"limit"?}
  POST /create/document {"topic", "format"?, "instructions"?}
  POST /create/deck     {"topic", "slides"?, "instructions"?}

Set ``BRAIN_API_TOKEN`` to require ``Authorization: Bearer <token>``. Binds to 127.0.0.1 by default.
"""

from __future__ import annotations

import hmac
import json
import os
import re
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import parse_qs, urlparse

from .brain import Brain


def make_handler(brain: Brain, token: str | None):
    lock = threading.Lock()  # one SQLite connection: serialise access

    class Handler(BaseHTTPRequestHandler):
        server_version = "SecondBrain/0.1"

        def log_message(self, fmt, *args):  # quieter logs
            pass

        def _send(self, code: int, payload: Any) -> None:
            body = json.dumps(payload, default=str).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _authorised(self) -> bool:
            if not token:
                return True
            supplied = self.headers.get("Authorization", "").removeprefix("Bearer ").strip()
            return hmac.compare_digest(supplied, token)

        def _body(self) -> dict[str, Any]:
            length = int(self.headers.get("Content-Length") or 0)
            return json.loads(self.rfile.read(length) or b"{}") if length else {}

        def _route(self, method: str) -> None:
            if not self._authorised():
                return self._send(401, {"error": "unauthorised"})
            url = urlparse(self.path)
            q = {k: v[0] for k, v in parse_qs(url.query).items()}
            p = url.path.rstrip("/") or "/"
            try:
                with lock:
                    result = self._dispatch(method, p, q)
            except (KeyError, ValueError, json.JSONDecodeError) as exc:
                return self._send(400, {"error": str(exc)})
            if result is None:
                return self._send(404, {"error": "not found"})
            self._send(200, result)

        def _dispatch(self, method: str, p: str, q: dict[str, str]) -> Any:
            if method == "GET":
                if p == "/status":
                    return brain.status()
                if p == "/search":
                    return [h.to_dict() for h in brain.search(q["q"], int(q.get("limit", 8)), q.get("source"))]
                if p == "/graph":
                    return brain.graph()
                if p == "/documents":
                    return [d.to_dict() for d in brain.store.list_documents(q.get("source"), int(q.get("limit", 100)))]
                if m := re.fullmatch(r"/documents/(\d+)", p):
                    return brain.document(int(m.group(1)))
                if m := re.fullmatch(r"/documents/(\d+)/related", p):
                    return brain.related(int(m.group(1)))
            elif method == "POST":
                body = self._body()
                if p == "/ask":
                    return brain.ask(body["question"])
                if p == "/remember":
                    return brain.remember(body["text"], body.get("title"), body.get("tags"))
                if p == "/sync":
                    return [s.as_dict() for s in brain.sync(body.get("source"))]
                if p == "/enrich":
                    return brain.enrich(int(body.get("limit", 20)))
                if p == "/create/document":
                    return brain.create_document(body["topic"], body.get("format", "md"), body.get("instructions", ""))
                if p == "/create/deck":
                    return brain.create_deck(body["topic"], int(body.get("slides", 8)), body.get("instructions", ""))
            return None

        def do_GET(self):  # noqa: N802
            self._route("GET")

        def do_POST(self):  # noqa: N802
            self._route("POST")

    return Handler


def make_server(brain: Brain, host: str = "127.0.0.1", port: int = 8787) -> ThreadingHTTPServer:
    return ThreadingHTTPServer((host, port), make_handler(brain, os.environ.get("BRAIN_API_TOKEN")))


def main(host: str = "127.0.0.1", port: int = 8787) -> None:
    server = make_server(Brain(), host, port)
    print(f"Second Brain API on http://{host}:{port}")
    server.serve_forever()
