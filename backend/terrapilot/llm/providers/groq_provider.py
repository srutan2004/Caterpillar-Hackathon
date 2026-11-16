"""Groq Cloud provider via the official `groq` SDK (OpenAI-compatible endpoint).

Supports chat completions (JSON schema / JSON object / text), vision messages, streaming, audio
transcription and the Batch API. Rate-limit headers are parsed from every response so the gateway's
token buckets stay in sync with the account's real headroom.
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from pathlib import Path
from typing import Any

from terrapilot.llm.providers.base import ProviderError
from terrapilot.llm.types import LLMRequest, LLMResponse, RateLimitInfo

_DURATION = re.compile(r"(?:(\d+(?:\.\d+)?)h)?(?:(\d+(?:\.\d+)?)m(?!s))?(?:(\d+(?:\.\d+)?)s)?(?:(\d+(?:\.\d+)?)ms)?")


def parse_duration_s(value: str | None) -> float | None:
    """Groq reset headers look like '7.66s', '2m59.56s' or '120ms'."""
    if not value:
        return None
    try:
        return float(value)
    except ValueError:
        pass
    m = _DURATION.fullmatch(value.strip())
    if not m:
        return None
    h, mnt, s, ms = (float(x) if x else 0.0 for x in m.groups())
    return h * 3600 + mnt * 60 + s + ms / 1000


def parse_rate_headers(headers: Any) -> RateLimitInfo:
    def _int(name: str) -> int | None:
        v = headers.get(name) if headers is not None else None
        try:
            return int(float(v)) if v is not None else None
        except ValueError:
            return None

    get = headers.get if headers is not None else (lambda _n: None)
    return RateLimitInfo(
        remaining_tokens=_int("x-ratelimit-remaining-tokens"),
        remaining_requests=_int("x-ratelimit-remaining-requests"),
        limit_tokens=_int("x-ratelimit-limit-tokens"),
        limit_requests=_int("x-ratelimit-limit-requests"),
        reset_tokens_s=parse_duration_s(get("x-ratelimit-reset-tokens")),
        reset_requests_s=parse_duration_s(get("x-ratelimit-reset-requests")),
        retry_after_s=parse_duration_s(get("retry-after")),
    )


class GroqProvider:
    name = "groq"

    def __init__(self, api_key: str | None, base_url: str | None = None, max_retries: int = 0):
        if not api_key:
            raise ProviderError("GROQ_API_KEY is not set", retryable=False)
        import groq

        self._groq = groq
        kwargs: dict[str, Any] = {"api_key": api_key, "max_retries": max_retries}
        if base_url:
            # The SDK expects the host root; it appends /openai/v1 itself.
            kwargs["base_url"] = base_url.removesuffix("/openai/v1").removesuffix("/")
        self.client = groq.Groq(**kwargs)

    # ------------------------------------------------------------------ chat
    def complete(self, request: LLMRequest) -> LLMResponse:
        params = self._params(request)
        try:
            raw = self.client.chat.completions.with_raw_response.create(**params, timeout=request.timeout_s)
            completion = raw.parse()
            rate = parse_rate_headers(raw.headers)
        except self._groq.APIStatusError as exc:
            rate = parse_rate_headers(getattr(exc.response, "headers", None))
            status = exc.status_code
            raise ProviderError(
                f"groq {status}: {_short(exc)}", status=status, retryable=status in (429, 500, 502, 503, 504), rate=rate
            ) from exc
        except (self._groq.APITimeoutError, self._groq.APIConnectionError) as exc:
            raise ProviderError(f"groq connection: {_short(exc)}", retryable=True) from exc
        choice = completion.choices[0]
        usage = completion.usage
        return LLMResponse(
            text=choice.message.content or "",
            model=completion.model,
            input_tokens=getattr(usage, "prompt_tokens", 0) or 0,
            output_tokens=getattr(usage, "completion_tokens", 0) or 0,
            rate=rate,
            raw={"id": completion.id, "finish_reason": choice.finish_reason},
        )

    def stream(self, request: LLMRequest) -> Iterator[str]:
        params = self._params(request) | {"stream": True}
        try:
            for chunk in self.client.chat.completions.create(**params, timeout=request.timeout_s):
                delta = chunk.choices[0].delta.content if chunk.choices else None
                if delta:
                    yield delta
        except self._groq.APIStatusError as exc:
            raise ProviderError(
                f"groq {exc.status_code}: {_short(exc)}", status=exc.status_code, retryable=False
            ) from exc

    def _params(self, request: LLMRequest) -> dict[str, Any]:
        params: dict[str, Any] = {"model": request.model, "messages": request.messages}
        if request.temperature is not None:
            params["temperature"] = request.temperature
        if request.max_tokens is not None:
            params["max_completion_tokens"] = request.max_tokens
        if request.response_format is not None:
            params["response_format"] = request.response_format
        params.update(request.extra)
        return params

    # ------------------------------------------------------------------ models
    def list_models(self) -> list[str]:
        try:
            return sorted(m.id for m in self.client.models.list().data)
        except self._groq.APIStatusError as exc:
            raise ProviderError(f"groq {exc.status_code}: {_short(exc)}", status=exc.status_code) from exc
        except (self._groq.APITimeoutError, self._groq.APIConnectionError) as exc:
            raise ProviderError(f"groq connection: {_short(exc)}", retryable=True) from exc

    # ------------------------------------------------------------------ audio
    def transcribe(self, audio_path: Path, model: str, language: str | None = None) -> dict[str, Any]:
        with audio_path.open("rb") as fh:
            result = self.client.audio.transcriptions.create(
                file=(audio_path.name, fh.read()),
                model=model,
                response_format="verbose_json",
                language=language or "en",
            )
        return result.model_dump() if hasattr(result, "model_dump") else dict(result)

    # ------------------------------------------------------------------ batch API
    def upload_batch_file(self, jsonl_path: Path) -> str:
        with jsonl_path.open("rb") as fh:
            uploaded = self.client.files.create(file=(jsonl_path.name, fh.read()), purpose="batch")
        return str(uploaded.id)

    def create_batch(
        self, input_file_id: str, completion_window: str, metadata: dict[str, str] | None = None
    ) -> dict[str, Any]:
        batch = self.client.batches.create(
            input_file_id=input_file_id,
            endpoint="/v1/chat/completions",
            completion_window=completion_window,
            metadata=metadata,
        )
        return batch.model_dump()

    def get_batch(self, batch_id: str) -> dict[str, Any]:
        return self.client.batches.retrieve(batch_id).model_dump()

    def download_file(self, file_id: str) -> str:
        return self.client.files.content(file_id).text()


def _short(exc: Exception) -> str:
    text = str(exc)
    return text if len(text) < 300 else text[:300] + "…"
