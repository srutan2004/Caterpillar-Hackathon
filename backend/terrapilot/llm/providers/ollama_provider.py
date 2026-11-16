"""Ollama provider (offline profile / fallback) through its OpenAI-compatible endpoint."""

from __future__ import annotations

from typing import Any

import httpx

from terrapilot.llm.providers.base import ProviderError
from terrapilot.llm.types import LLMRequest, LLMResponse


class OllamaProvider:
    name = "ollama"

    def __init__(self, base_url: str):
        self.base_url = base_url.rstrip("/")

    def complete(self, request: LLMRequest) -> LLMResponse:
        body: dict[str, Any] = {"model": request.model, "messages": request.messages, "stream": False}
        if request.temperature is not None:
            body["temperature"] = request.temperature
        if request.max_tokens is not None:
            body["max_tokens"] = request.max_tokens
        if request.response_format and request.response_format.get("type") in ("json_object", "json_schema"):
            body["response_format"] = {"type": "json_object"}
        try:
            resp = httpx.post(f"{self.base_url}/v1/chat/completions", json=body, timeout=request.timeout_s)
        except httpx.HTTPError as exc:
            raise ProviderError(f"ollama connection: {exc}", retryable=False) from exc
        if resp.status_code >= 400:
            raise ProviderError(f"ollama {resp.status_code}: {resp.text[:200]}", status=resp.status_code)
        data = resp.json()
        usage = data.get("usage") or {}
        return LLMResponse(
            text=data["choices"][0]["message"].get("content") or "",
            model=data.get("model", request.model),
            input_tokens=usage.get("prompt_tokens", 0),
            output_tokens=usage.get("completion_tokens", 0),
        )

    def list_models(self) -> list[str]:
        try:
            resp = httpx.get(f"{self.base_url}/api/tags", timeout=5)
            resp.raise_for_status()
        except httpx.HTTPError as exc:
            raise ProviderError(f"ollama unavailable: {exc}") from exc
        return sorted(m["name"] for m in resp.json().get("models", []))
