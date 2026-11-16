"""VCR-style cassettes at the provider level so tests never consume Groq quota (§12.3, §15).

Modes (env TP_LLM_CASSETTE, or explicit):
* ``off``    — pass through to the real provider
* ``replay`` — only serve recorded responses; a miss raises (CI default)
* ``record`` — call the real provider and save every response
* ``auto``   — replay when recorded, otherwise record
"""

from __future__ import annotations

import hashlib
import json
import threading
from pathlib import Path
from typing import Any, Literal

from terrapilot.llm.providers.base import LLMProvider, ProviderError
from terrapilot.llm.types import LLMRequest, LLMResponse

Mode = Literal["off", "replay", "record", "auto"]


def request_fingerprint(request: LLMRequest) -> str:
    blob = json.dumps(
        {
            "model": request.model,
            "messages": request.messages,
            "temperature": request.temperature,
            "max_tokens": request.max_tokens,
            "response_format": request.response_format,
        },
        sort_keys=True,
        default=str,
    )
    return hashlib.sha256(blob.encode()).hexdigest()[:24]


class CassetteMiss(ProviderError):
    pass


class CassetteProvider:
    def __init__(self, inner: LLMProvider | None, path: Path, mode: Mode, name: str = "groq"):
        self.inner = inner
        self.path = path
        self.mode = mode
        self.name = name
        self._lock = threading.Lock()
        self._data: dict[str, Any] = (
            json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {"interactions": {}}
        )

    def complete(self, request: LLMRequest) -> LLMResponse:
        key = request_fingerprint(request)
        recorded = self._data["interactions"].get(key)
        if recorded and self.mode in ("replay", "auto"):
            return LLMResponse(
                text=recorded["text"],
                model=recorded.get("model", request.model),
                input_tokens=recorded.get("input_tokens", 0),
                output_tokens=recorded.get("output_tokens", 0),
            )
        if self.mode == "replay":
            raise CassetteMiss(f"no recorded interaction {key} for task '{request.task}' in {self.path.name}")
        if self.inner is None:
            raise ProviderError("cassette recording needs a real provider")
        response = self.inner.complete(request)
        if self.mode in ("record", "auto"):
            with self._lock:
                self._data["interactions"][key] = {
                    "task": request.task,
                    "model": response.model,
                    "request_messages": request.messages,
                    "text": response.text,
                    "input_tokens": response.input_tokens,
                    "output_tokens": response.output_tokens,
                }
                self.path.parent.mkdir(parents=True, exist_ok=True)
                self.path.write_text(json.dumps(self._data, indent=2, ensure_ascii=False), encoding="utf-8")
        return response

    def list_models(self) -> list[str]:
        if self.mode == "replay" or self.inner is None:
            return list(self._data.get("models", []))
        models = self.inner.list_models()
        if self.mode in ("record", "auto"):
            self._data["models"] = models
        return models
