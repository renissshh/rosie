"""Provider-agnostic LLM client.

Ollama (local, free) and most free-tier cloud APIs (e.g. Gemini) expose the
OpenAI chat-completions format, so one small client covers all of them.
`FallbackLLM` tries the local model first and only uses the cloud when the
local one is down, which keeps Rosie free to run.
"""

from __future__ import annotations

import json
import logging
import os
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, Protocol

import httpx

from rosie.config import LLMConfig
from rosie.ratelimit import RateLimiter

log = logging.getLogger("rosie.llm")


class LLMError(RuntimeError):
    """The model could not produce a reply."""


@dataclass(frozen=True)
class ToolCall:
    id: str
    name: str
    arguments: dict[str, Any]


@dataclass(frozen=True)
class ChatResult:
    text: str | None
    tool_calls: list[ToolCall] = field(default_factory=list)
    model: str = ""


class ChatModel(Protocol):
    def chat(
        self, messages: list[dict[str, Any]], tools: list[dict[str, Any]] | None = None
    ) -> ChatResult: ...


def _parse_arguments(raw: Any) -> dict[str, Any]:
    if isinstance(raw, dict):
        return raw
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise LLMError(f"model returned invalid tool arguments: {raw!r}") from exc
    if not isinstance(parsed, dict):
        raise LLMError(f"tool arguments must be an object, got {type(parsed).__name__}")
    return parsed


def parse_chat_response(body: Mapping[str, Any]) -> ChatResult:
    try:
        message = body["choices"][0]["message"]
    except (KeyError, IndexError, TypeError) as exc:
        raise LLMError(f"unexpected response shape: {str(body)[:200]}") from exc
    calls = [
        ToolCall(
            id=call.get("id", f"call_{i}"),
            name=call["function"]["name"],
            arguments=_parse_arguments(call["function"].get("arguments")),
        )
        for i, call in enumerate(message.get("tool_calls") or [])
    ]
    return ChatResult(text=message.get("content"), tool_calls=calls, model=body.get("model", ""))


class OpenAICompatibleLLM:
    def __init__(
        self,
        config: LLMConfig,
        http: httpx.Client | None = None,
        environ: Mapping[str, str] | None = None,
    ) -> None:
        self.config = config
        self._http = http or httpx.Client(timeout=config.timeout_s)
        self._environ = os.environ if environ is None else environ
        # Free tiers cut you off (or bill) past their quota: stay under it.
        self.limiter = RateLimiter(config.max_per_minute) if config.max_per_minute else None

    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self.config.api_key_env:
            key = self._environ.get(self.config.api_key_env)
            if not key:
                raise LLMError(f"{self.config.api_key_env} is not set")
            headers["Authorization"] = f"Bearer {key}"
        return headers

    def chat(
        self, messages: list[dict[str, Any]], tools: list[dict[str, Any]] | None = None
    ) -> ChatResult:
        if self.limiter is not None and not self.limiter.allow():
            wait = self.limiter.retry_after()
            raise LLMError(f"{self.config.model} rate limit reached; try again in {wait:.0f} s")
        payload: dict[str, Any] = {"model": self.config.model, "messages": messages}
        if tools:
            payload["tools"] = tools
        url = self.config.base_url.rstrip("/") + "/chat/completions"
        try:
            response = self._http.post(url, json=payload, headers=self._headers())
        except httpx.HTTPError as exc:
            raise LLMError(f"{self.config.provider} unreachable: {exc}") from exc
        if response.status_code >= 400:
            raise LLMError(
                f"{self.config.provider} HTTP {response.status_code}: {response.text[:200]}"
            )
        return parse_chat_response(response.json())


class FallbackLLM:
    """Try each model in order; the first one that answers wins."""

    def __init__(self, *models: ChatModel) -> None:
        if not models:
            raise ValueError("FallbackLLM needs at least one model")
        self.models = models

    def chat(
        self, messages: list[dict[str, Any]], tools: list[dict[str, Any]] | None = None
    ) -> ChatResult:
        errors: list[str] = []
        for model in self.models:
            try:
                return model.chat(messages, tools)
            except LLMError as exc:
                log.warning("model failed, trying next: %s", exc)
                errors.append(str(exc))
        raise LLMError("all models failed: " + " | ".join(errors))


def build_llm(primary: LLMConfig, fallback: LLMConfig | None = None) -> ChatModel:
    models: list[ChatModel] = [OpenAICompatibleLLM(primary)]
    if fallback is not None:
        models.append(OpenAICompatibleLLM(fallback))
    return models[0] if len(models) == 1 else FallbackLLM(*models)
