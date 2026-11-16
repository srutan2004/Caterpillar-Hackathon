"""Gateway request/response types."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal

CallStatus = Literal["ok", "fallback", "error", "cached"]


IMAGE_TOKENS = 800  # rough per-image cost, so the rate limiter accounts for vision calls


@dataclass
class LLMRequest:
    task: str
    model: str
    messages: list[dict[str, Any]]
    temperature: float | None = None
    max_tokens: int | None = None
    response_format: dict[str, Any] | None = None
    timeout_s: float = 30.0
    stream: bool = False
    extra: dict[str, Any] = field(default_factory=dict)

    def estimated_tokens(self) -> int:
        chars = 0
        for m in self.messages:
            content = m.get("content", "")
            if isinstance(content, list):  # vision parts: count text, price images at a flat rate
                chars += sum(len(str(p.get("text", ""))) for p in content if p.get("type") == "text")
                chars += IMAGE_TOKENS * 4 * sum(1 for p in content if p.get("type") == "image_url")
            else:
                chars += len(str(content))
        return chars // 4 + (self.max_tokens or 256)


@dataclass
class RateLimitInfo:
    remaining_tokens: int | None = None
    remaining_requests: int | None = None
    limit_tokens: int | None = None
    limit_requests: int | None = None
    reset_tokens_s: float | None = None
    reset_requests_s: float | None = None
    retry_after_s: float | None = None


@dataclass
class LLMResponse:
    text: str
    model: str
    input_tokens: int = 0
    output_tokens: int = 0
    rate: RateLimitInfo | None = None
    raw: dict[str, Any] | None = None


@dataclass
class LLMResult:
    """What features receive. `output` is the validated structured output (or {"text": ...})."""

    task: str
    output: dict[str, Any]
    text: str
    provider: str
    model: str
    status: CallStatus
    prompt_version: str | None = None
    fallback_used: str | None = None
    latency_ms: float = 0.0
    input_tokens: int = 0
    output_tokens: int = 0
    trace_id: str = ""
    errors: list[str] = field(default_factory=list)


@dataclass
class CallRecord:
    id: str
    ts: datetime
    task: str
    provider: str
    model: str
    prompt_version: str | None
    input_tokens: int
    output_tokens: int
    latency_ms: float
    status: CallStatus
    fallback_used: str | None
    guard_flags: dict[str, Any]
    trace_id: str
    error: str | None = None
