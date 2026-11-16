"""Provider interface. Every provider (Groq, Ollama, local, template, cassette) implements `complete`."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from terrapilot.llm.types import LLMRequest, LLMResponse, RateLimitInfo


class ProviderError(Exception):
    def __init__(
        self,
        message: str,
        *,
        status: int | None = None,
        retryable: bool = False,
        rate: RateLimitInfo | None = None,
    ):
        super().__init__(message)
        self.status = status
        self.retryable = retryable
        self.rate = rate


@runtime_checkable
class LLMProvider(Protocol):
    name: str

    def complete(self, request: LLMRequest) -> LLMResponse: ...

    def list_models(self) -> list[str]: ...
