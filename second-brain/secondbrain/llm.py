"""Thin wrapper around the Claude API.

Credentials are resolved by the Anthropic SDK (``ANTHROPIC_API_KEY``,
``ANTHROPIC_AUTH_TOKEN`` or an ``ant auth login`` profile). Without them the
brain still indexes, links and searches — only generation needs Claude.
"""

from __future__ import annotations

from typing import TypeVar

import anthropic
from pydantic import BaseModel

T = TypeVar("T", bound=BaseModel)

# Models that support server-side refusal fallbacks ("default" routing).
FALLBACK_MODELS = {"claude-opus-5", "claude-fable-5-1"}


NO_CREDENTIALS = "no Claude credentials - set ANTHROPIC_API_KEY or run `ant auth login`"


class LLMUnavailable(RuntimeError):
    """No usable Claude credentials, or the request could not be served."""


class LLM:
    def __init__(self, model: str = "claude-opus-5", effort: str = "high"):
        self.model = model
        self.effort = effort
        self._client: anthropic.Anthropic | None = None

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
