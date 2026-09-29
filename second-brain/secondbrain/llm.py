"""The AI behind answers, briefings, documents and decks, selectable at runtime.

Modes (``BRAIN_AI_MODE``, set from the app's settings or ``brain ai set``):

* ``claude``      Claude through the API. Credentials are resolved by the Anthropic SDK
                  (``ANTHROPIC_API_KEY``, ``ANTHROPIC_AUTH_TOKEN`` or an ``ant auth login`` profile).
* ``local``       A model running on this computer: Ollama (native API) or any OpenAI-compatible
                  server such as LM Studio. Fully offline; nothing leaves the machine.
* ``claude_app``  No API key: the brain prepares the complete prompt (instructions + your sources) for
                  you to paste into Claude (claude.ai or the desktop app, on your subscription). Claude
                  Desktop can also use the brain directly through its MCP server.
* ``off``         No AI. Search, connections and "Build without AI" still work.
"""

from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request
from typing import Any, TypeVar

import anthropic
from pydantic import BaseModel, ValidationError

T = TypeVar("T", bound=BaseModel)

AI_MODES = ("claude", "local", "claude_app", "off")
LOCAL_PROVIDERS = {"ollama": "http://localhost:11434", "openai": "http://localhost:1234/v1"}

# Models that support server-side refusal fallbacks ("default" routing).
FALLBACK_MODELS = {"claude-opus-5", "claude-fable-5-1"}

NO_CREDENTIALS = "no Claude credentials - set ANTHROPIC_API_KEY or run `ant auth login`"


class LLMUnavailable(RuntimeError):
    """No usable AI, or the request could not be served."""


class Handoff(LLMUnavailable):
    """Claude-app mode: instead of calling an AI, hand the finished prompt to the user to paste into Claude."""

    def __init__(self, system: str, prompt: str):
        super().__init__("AI runs in the Claude app: copy the prepared prompt into Claude")
        self.system, self.prompt = system, prompt

    @property
    def text(self) -> str:
        return handoff_text(self.system, self.prompt)


def handoff_text(system: str, prompt: str) -> str:
    return ("I'm working from documents in my personal knowledge base (my \"second brain\"). "
            "Follow these instructions:\n\n" + system + "\n\n" + prompt)


def claude_configured() -> bool:
    from pathlib import Path
    return bool(os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN")
                or (Path.home() / ".config" / "anthropic").is_dir())


class ClaudeLLM:
    kind = "claude"
    context_chars = 60000

    def __init__(self, model: str = "claude-opus-5", effort: str = "high"):
        self.model = model
        self.effort = effort
        self._client: anthropic.Anthropic | None = None

    @property
    def label(self) -> str:
        return "Claude"

    @property
    def client(self) -> anthropic.Anthropic:
        if self._client is None:
            self._client = anthropic.Anthropic()
        return self._client

    def text(self, system: str, prompt: str, max_tokens: int = 64000) -> str:
        kwargs = {}
        if self.model in FALLBACK_MODELS:
            kwargs = {"betas": ["server-side-fallback-2026-07-01"], "fallbacks": "default"}
        try:
            with self.client.beta.messages.stream(
                model=self.model,
                max_tokens=max_tokens,
                system=system,
                thinking={"type": "adaptive"},
                output_config={"effort": self.effort},
                messages=[{"role": "user", "content": prompt}],
                **kwargs,
            ) as stream:
                message = stream.get_final_message()
        except TypeError as exc:  # SDK raises TypeError when no auth method resolves
            raise LLMUnavailable(NO_CREDENTIALS) from exc
        except anthropic.AuthenticationError as exc:
            raise LLMUnavailable("Claude credentials were rejected") from exc
        except anthropic.APIConnectionError as exc:
            raise LLMUnavailable("cannot reach the Claude API (offline?)") from exc
        if message.stop_reason == "refusal":
            raise LLMUnavailable("Claude declined this request")
        return "".join(b.text for b in message.content if b.type == "text").strip()

    def structured(self, system: str, prompt: str, schema: type[T], max_tokens: int = 16000) -> T:
        try:
            response = self.client.messages.parse(
                model=self.model,
                max_tokens=max_tokens,
                system=system,
                thinking={"type": "adaptive"},
                messages=[{"role": "user", "content": prompt}],
                output_format=schema,
            )
        except TypeError as exc:
            raise LLMUnavailable(NO_CREDENTIALS) from exc
        except anthropic.AuthenticationError as exc:
            raise LLMUnavailable("Claude credentials were rejected") from exc
        except anthropic.APIConnectionError as exc:
            raise LLMUnavailable("cannot reach the Claude API (offline?)") from exc
        if response.stop_reason == "refusal" or response.parsed_output is None:
            raise LLMUnavailable(f"no structured output (stop_reason={response.stop_reason})")
        return response.parsed_output


LLM = ClaudeLLM  # backwards-compatible name

_THINK = re.compile(r"<think>.*?</think>", re.S)  # reasoning models (Qwen3, DeepSeek-R1) think out loud


def parse_json_reply(text: str) -> Any:
    """JSON from a model reply that may wrap it in prose or ```json fences."""
    text = _THINK.sub("", text).strip()
    fenced = re.search(r"```(?:json)?\s*(.*?)```", text, re.S)
    if fenced:
        text = fenced.group(1)
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end < start:
        raise ValueError("no JSON object in the reply")
    return json.loads(text[start:end + 1])


class LocalLLM:
    """A model on this computer. ``provider`` is ``ollama`` (native API, lets us raise the context window)
    or ``openai`` (any OpenAI-compatible server: LM Studio, llama.cpp, vLLM, Jan, LocalAI...)."""

    kind = "local"
    context_chars = 24000   # local models have smaller context windows: send fewer, better passages

    def __init__(self, provider: str = "ollama", url: str = "", model: str = "", timeout: float = 900,
                 num_ctx: int = 16384):
        self.provider = provider if provider in LOCAL_PROVIDERS else "ollama"
        self.url = (url or LOCAL_PROVIDERS[self.provider]).rstrip("/")
        self.model = model
        self.timeout = timeout
        self.num_ctx = num_ctx

    @property
    def label(self) -> str:
        return f"Local AI ({self.model or 'auto'})"

    def _request(self, path: str, body: dict | None = None, timeout: float | None = None) -> dict:
        req = urllib.request.Request(self.url + path, data=json.dumps(body).encode() if body is not None else None,
                                     headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=timeout or self.timeout) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", "replace")[:300]
            if exc.code == 404 and "model" in detail.lower():
                raise LLMUnavailable(f"the local model '{self.model}' isn't installed ({detail.strip()})") from exc
            raise LLMUnavailable(f"local AI error {exc.code}: {detail.strip()}") from exc
        except (urllib.error.URLError, TimeoutError, ConnectionError) as exc:
            app = "Ollama" if self.provider == "ollama" else "your local AI server (e.g. LM Studio)"
            raise LLMUnavailable(f"cannot reach {app} at {self.url}: is it running?") from exc

    def models(self) -> list[str]:
        if self.provider == "ollama":
            return sorted(m["name"] for m in self._request("/api/tags", timeout=10).get("models", []))
        return sorted(m["id"] for m in self._request("/models", timeout=10).get("data", []))

    def _model(self) -> str:
        if not self.model:
            installed = self.models()
            if not installed:
                raise LLMUnavailable("no local models installed yet (Ollama: `ollama pull llama3.1`)")
            self.model = installed[0]
        return self.model

    def _chat(self, system: str, prompt: str, max_tokens: int, schema: dict | None = None) -> str:
        messages = [{"role": "system", "content": system}, {"role": "user", "content": prompt}]
        if self.provider == "ollama":
            body: dict[str, Any] = {"model": self._model(), "messages": messages, "stream": False,
                                    "options": {"num_ctx": self.num_ctx, "num_predict": min(max_tokens, 8192)}}
            if schema:
                body["format"] = schema
            reply = self._request("/api/chat", body).get("message", {}).get("content", "")
        else:
            body = {"model": self._model(), "messages": messages, "max_tokens": min(max_tokens, 8192), "stream": False}
            if schema:
                body["response_format"] = {"type": "json_schema",
                                           "json_schema": {"name": "reply", "strict": True, "schema": schema}}
            try:
                data = self._request("/chat/completions", body)
            except LLMUnavailable:
                if not schema:
                    raise
                body.pop("response_format")  # older servers: fall back to asking nicely for JSON
                data = self._request("/chat/completions", body)
            reply = (data.get("choices") or [{}])[0].get("message", {}).get("content") or ""
        return _THINK.sub("", reply).strip()

    def text(self, system: str, prompt: str, max_tokens: int = 8192) -> str:
        reply = self._chat(system, prompt, max_tokens)
        if not reply:
            raise LLMUnavailable("the local model returned an empty reply")
        return reply

    def structured(self, system: str, prompt: str, schema: type[T], max_tokens: int = 8192) -> T:
        json_schema = schema.model_json_schema()
        system = (f"{system}\n\nReply with only a JSON object that matches this JSON schema, no other text:\n"
                  f"{json.dumps(json_schema)}")
        last: Exception | None = None
        for _ in range(2):  # small models occasionally slip; one retry fixes most of it
            try:
                return schema.model_validate(parse_json_reply(self._chat(system, prompt, max_tokens, json_schema)))
            except (ValueError, ValidationError) as exc:
                last = exc
        raise LLMUnavailable(f"the local model didn't return valid structured output ({last})")


class HandoffLLM:
    kind = "claude_app"
    label = "Claude app"
    context_chars = 60000

    def text(self, system: str, prompt: str, max_tokens: int = 0) -> str:
        raise Handoff(system, prompt)

    def structured(self, system: str, prompt: str, schema: type[T], max_tokens: int = 0) -> T:
        raise Handoff(system, prompt)


class NoLLM:
    kind = "off"
    label = "AI off"
    context_chars = 60000

    def text(self, *a, **k) -> str:
        raise LLMUnavailable("AI is switched off in settings")

    def structured(self, *a, **k):
        raise LLMUnavailable("AI is switched off in settings")


def ai_settings() -> dict[str, str]:
    """The current AI settings (from the environment / secrets.env)."""
    mode = os.environ.get("BRAIN_AI_MODE", "claude").strip().lower()
    provider = os.environ.get("BRAIN_LOCAL_PROVIDER", "ollama").strip().lower()
    return {"mode": mode if mode in AI_MODES else "claude",
            "local_provider": provider if provider in LOCAL_PROVIDERS else "ollama",
            "local_url": os.environ.get("BRAIN_LOCAL_URL", "").strip(),
            "local_model": os.environ.get("BRAIN_LOCAL_MODEL", "").strip()}


class SwitchableLLM:
    """Delegates to the AI chosen in settings, re-read on every call so a change applies immediately."""

    def __init__(self, model: str = "claude-opus-5", effort: str = "high"):
        self.claude = ClaudeLLM(model, effort)
        self._local: tuple[tuple, LocalLLM] | None = None

    @property
    def model(self) -> str:
        return self.claude.model

    def current(self):
        s = ai_settings()
        if s["mode"] == "local":
            key = (s["local_provider"], s["local_url"], s["local_model"])
            if not self._local or self._local[0] != key:
                self._local = (key, LocalLLM(*key))
            return self._local[1]
        return {"claude": self.claude, "claude_app": HandoffLLM(), "off": NoLLM()}[s["mode"]]

    @property
    def kind(self) -> str:
        return self.current().kind

    @property
    def label(self) -> str:
        return self.current().label

    @property
    def context_chars(self) -> int:
        return self.current().context_chars

    def text(self, system: str, prompt: str, max_tokens: int = 64000) -> str:
        return self.current().text(system, prompt, max_tokens)

    def structured(self, system: str, prompt: str, schema: type[T], max_tokens: int = 16000) -> T:
        return self.current().structured(system, prompt, schema, max_tokens)
