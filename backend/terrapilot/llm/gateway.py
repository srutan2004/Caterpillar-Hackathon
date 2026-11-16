"""LLM gateway (§12.3): task router → prompt → redaction → cache → rate limit → provider chain with
retries, circuit breaker and fallbacks → structured-output validation (+1 repair) → accounting.

Changing a model is a config edit (config/llm.yaml); features never import a vendor SDK.
"""

from __future__ import annotations

import json
import os
import random
import threading
import time
import uuid
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

import jsonschema

from terrapilot.core.config import ConfigBundle, get_config
from terrapilot.core.config_schema import LlmTask
from terrapilot.core.logging import get_logger
from terrapilot.core.settings import REPO_ROOT, Settings, get_settings
from terrapilot.core.timeutil import utcnow
from terrapilot.llm.cache import Cache, MemoryCache, RedisCache, cache_key
from terrapilot.llm.cassette import CassetteProvider
from terrapilot.llm.prompts import PromptRegistry
from terrapilot.llm.providers.base import LLMProvider, ProviderError
from terrapilot.llm.providers.template_provider import TemplateProvider
from terrapilot.llm.rate_limiter import CircuitBreaker, RateLimiter
from terrapilot.llm.redaction import Pseudonymiser
from terrapilot.llm.sink import CallSink, DbSink, FanoutSink, StatsSink
from terrapilot.llm.types import CallRecord, CallStatus, LLMRequest, LLMResponse, LLMResult

log = get_logger("llm.gateway")

# Named fallbacks that are not models: features interpret them (keyword router, escalation, …).
SENTINELS = {"keyword_router", "cannot_answer", "escalate", "heuristic_regex"}


class LLMUnavailableError(RuntimeError):
    def __init__(self, task: str, errors: list[str]):
        super().__init__(f"all providers failed for task '{task}': {'; '.join(errors)}")
        self.task = task
        self.errors = errors


class OutputValidationError(ValueError):
    pass


def attach_images(messages: list[dict[str, Any]], images: list[str]) -> list[dict[str, Any]]:
    """Vision messages (§12.3): images become content parts on the last user message, never top-level params."""
    out = [dict(m) for m in messages]
    idx = next((i for i in range(len(out) - 1, -1, -1) if out[i].get("role") == "user"), None)
    if idx is None:
        out.append({"role": "user", "content": ""})
        idx = len(out) - 1
    content = out[idx].get("content")
    parts: list[dict[str, Any]] = (
        list(content) if isinstance(content, list) else ([{"type": "text", "text": str(content)}] if content else [])
    )
    parts += [{"type": "image_url", "image_url": {"url": url}} for url in images]
    out[idx]["content"] = parts
    return out


@dataclass(frozen=True)
class Target:
    provider: str
    model: str

    @property
    def label(self) -> str:
        return self.provider if self.provider in ("template", "sentinel") else f"{self.provider}:{self.model}"


def parse_target(spec: str) -> Target:
    if spec == "template":
        return Target("template", "template")
    if spec in SENTINELS:
        return Target("sentinel", spec)
    provider, _, model = spec.partition(":")
    return Target(provider, model)


class LLMGateway:
    def __init__(
        self,
        config: ConfigBundle,
        settings: Settings,
        *,
        providers: dict[str, LLMProvider] | None = None,
        sink: CallSink | None = None,
        cache: Cache | None = None,
        sleep: Any = time.sleep,
    ):
        self.cfg = config
        self.llm = config.llm
        self.settings = settings
        self.profile = os.environ.get(self.llm.profile_env, settings.tp_profile)
        self.prompts = PromptRegistry(config.root)
        self.template = TemplateProvider(
            config.i18n,
            self.llm.providers["template"].model_dump().get("i18n_namespace", "llm_template"),
            config.app.locales.default,
        )
        self.limiter = RateLimiter(
            {m: (lim.rpm, lim.tpm) for m, lim in self.llm.limits.items()}, self.llm.low_headroom_fraction
        )
        cb = self.llm.resilience.get("circuit_breaker", {})
        self.breaker = CircuitBreaker(int(cb.get("failure_threshold", 5)), float(cb.get("reset_after_s", 60)))
        self.stats = StatsSink()
        self.sink: CallSink = FanoutSink(self.stats, sink) if sink else self.stats
        if cache is None:
            cache_cfg = self.llm.cache
            cache = (
                RedisCache(settings.redis_url)
                if cache_cfg.get("backend") == "redis"
                else MemoryCache(int(cache_cfg.get("max_entries", 2048)))
            )
        self.cache = cache
        self._providers: dict[str, LLMProvider] = dict(providers or {})
        self._provider_errors: dict[str, str] = {}
        self._lock = threading.Lock()
        self._sleep = sleep
        groq_cfg = self.llm.providers["groq"].model_dump()
        self.json_schema_models = set(groq_cfg.get("json_schema_models", []))
        self._schemas: dict[str, dict[str, Any]] = {}

    # ------------------------------------------------------------------ providers
    def provider(self, name: str) -> LLMProvider:
        with self._lock:
            if name in self._providers:
                return self._providers[name]
            if name in self._provider_errors:
                raise ProviderError(self._provider_errors[name])
            try:
                self._providers[name] = self._build_provider(name)
            except ProviderError as exc:
                self._provider_errors[name] = str(exc)
                raise
            return self._providers[name]

    def _build_provider(self, name: str) -> LLMProvider:
        pcfg = self.llm.providers.get(name)
        if pcfg is None:
            raise ProviderError(f"provider '{name}' is not configured")
        raw = pcfg.model_dump()
        if name == "groq":
            mode = os.environ.get("TP_LLM_CASSETTE", "off")
            inner: LLMProvider | None = None
            try:
                from terrapilot.llm.providers.groq_provider import GroqProvider

                inner = GroqProvider(self.settings.groq_key, raw.get("base_url"), int(raw.get("max_retries_sdk", 0)))
            except ProviderError:
                if mode != "replay":
                    raise
            if mode != "off":
                path = Path(os.environ.get("TP_LLM_CASSETTE_PATH", REPO_ROOT / "backend/tests/cassettes/default.json"))
                return CassetteProvider(inner, path, mode)  # type: ignore[arg-type]
            assert inner is not None
            return inner
        if name == "ollama":
            from terrapilot.llm.providers.ollama_provider import OllamaProvider

            return OllamaProvider(
                os.environ.get(raw.get("base_url_env", "OLLAMA_BASE_URL"), self.settings.ollama_base_url)
            )
        raise ProviderError(f"provider '{name}' has no chat implementation in this phase")

    # ------------------------------------------------------------------ task resolution
    def task_config(self, task: str) -> LlmTask:
        if task not in self.llm.tasks:
            raise KeyError(f"unknown LLM task '{task}'")
        base = self.llm.tasks[task]
        if self.profile == "offline" and task in self.llm.offline_overrides:
            return base.model_copy(update=self.llm.offline_overrides[task])
        return base

    def chain(self, task: str) -> list[Target]:
        cfg = self.task_config(task)
        targets = [Target(cfg.provider, cfg.model)] + [parse_target(f) for f in cfg.fallback]
        if self.profile == "offline":
            targets = [t for t in targets if t.provider != "groq"]
        return targets

    def schema(self, ref: str) -> dict[str, Any]:
        if ref not in self._schemas:
            self._schemas[ref] = json.loads((self.cfg.root / ref).read_text(encoding="utf-8"))
        return self._schemas[ref]

    # ------------------------------------------------------------------ main entry
    def run(
        self,
        task: str,
        inputs: dict[str, Any],
        *,
        locale: str | None = None,
        category: str | None = None,
        template_facts: dict[str, Any] | None = None,
        prompt_override: str | None = None,
        extra_params: dict[str, Any] | None = None,
        images: list[str] | None = None,
        trace_id: str | None = None,
    ) -> LLMResult:
        cfg = self.task_config(task)
        trace_id = trace_id or uuid.uuid4().hex[:16]
        started = time.monotonic()
        budget_s = (cfg.timeout_ms or 30000) / 1000
        prompt_path = prompt_override or cfg.prompt
        prompt_version = PromptRegistry.version(prompt_path) if prompt_path else None
        locale = locale or self.cfg.app.locales.default
        facts = template_facts if template_facts is not None else inputs.get("facts", inputs)

        pseudo = Pseudonymiser(self.llm.redaction.get("pseudonymise", []), self.llm.redaction.get("never_send", []))
        safe_inputs = pseudo.redact(inputs)

        key = None
        if cfg.cache:
            key = cache_key(
                task, prompt_version, {**inputs, "locale": locale, "category": category}, cfg.cache.get("key")
            )
            hit = self.cache.get(key)
            if hit is not None:
                result = LLMResult(
                    task=task,
                    output=hit["output"],
                    text=hit.get("text", ""),
                    provider=hit["provider"],
                    model=hit["model"],
                    status="cached",
                    prompt_version=prompt_version,
                    trace_id=trace_id,
                    latency_ms=round((time.monotonic() - started) * 1000, 2),
                )
                self._record(result, None)
                return result

        errors: list[str] = []
        primary = True
        for target in self.chain(task):
            remaining = budget_s - (time.monotonic() - started)
            try:
                if target.provider == "template":
                    output = self.template.render(task, facts, locale, category)
                    result = self._result(
                        task, output, "template", "template", primary, prompt_version, trace_id, started
                    )
                elif target.provider == "sentinel":
                    result = self._result(
                        task,
                        {"fallback": target.model},
                        "sentinel",
                        target.model,
                        primary,
                        prompt_version,
                        trace_id,
                        started,
                    )
                else:
                    if remaining <= 0:
                        raise ProviderError("latency budget exhausted")
                    if not prompt_path:
                        raise ProviderError(f"task '{task}' has no prompt")
                    variables = {"locale": locale, "category": category, **safe_inputs}
                    messages = self.prompts.render(prompt_path, variables)
                    if images:
                        messages = attach_images(messages, images)
                    response, output = self._call_model(task, cfg, target, messages, remaining, extra_params or {})
                    output = pseudo.rehydrate(output)
                    result = self._result(
                        task, output, target.provider, response.model, primary, prompt_version, trace_id, started
                    )
                    result.input_tokens, result.output_tokens = response.input_tokens, response.output_tokens
                    result.text = pseudo.rehydrate(response.text)
                result.errors = errors
                if not primary:
                    result.fallback_used = target.label
                if key and cfg.cache and target.provider not in ("template", "sentinel"):
                    self.cache.set(
                        key,
                        {
                            "output": result.output,
                            "text": result.text,
                            "provider": result.provider,
                            "model": result.model,
                        },
                        float(cfg.cache.get("ttl_s", self.llm.cache.get("default_ttl_s", 300))),
                    )
                self._record(result, "; ".join(errors) or None)
                return result
            except (ProviderError, OutputValidationError, KeyError) as exc:
                errors.append(f"{target.label}: {exc}")
                primary = False
                continue

        failed = LLMResult(
            task=task,
            output={},
            text="",
            provider="none",
            model="none",
            status="error",
            prompt_version=prompt_version,
            trace_id=trace_id,
            errors=errors,
            latency_ms=round((time.monotonic() - started) * 1000, 2),
        )
        self._record(failed, "; ".join(errors))
        raise LLMUnavailableError(task, errors)

    # ------------------------------------------------------------------ provider call with retries
    def _call_model(
        self,
        task: str,
        cfg: LlmTask,
        target: Target,
        messages: list[dict[str, Any]],
        budget_s: float,
        extra: dict[str, Any],
    ) -> tuple[LLMResponse, dict[str, Any]]:
        provider = self.provider(target.provider)
        breaker_key = target.label
        if not self.breaker.allow(breaker_key):
            raise ProviderError("circuit open")
        response_format, schema = self._response_format(cfg, target.model, messages)
        request = LLMRequest(
            task=task,
            model=target.model,
            messages=messages,
            temperature=cfg.temperature,
            max_tokens=cfg.max_tokens,
            response_format=response_format,
            timeout_s=max(0.5, budget_s),
            extra={**cfg.params, **extra},
        )
        lane = self.llm.priority_lanes.get(task, max(self.llm.priority_lanes.values(), default=3))
        retry_cfg = self.llm.resilience.get("retry", {})
        attempts = int(retry_cfg.get("max_attempts", 3)) if cfg.retry else 1
        deadline = time.monotonic() + budget_s
        last_exc: Exception | None = None
        for attempt in range(attempts):
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            if target.provider == "groq" and not self.limiter.acquire(
                target.model, request.estimated_tokens(), lane, remaining
            ):
                raise ProviderError("rate limit headroom exhausted (local bucket)")
            request.timeout_s = max(0.5, deadline - time.monotonic())
            try:
                response = provider.complete(request)
                self.limiter.update_from_headers(target.model, response.rate)
                self.breaker.record(breaker_key, True)
            except ProviderError as exc:
                self.limiter.update_from_headers(target.model, exc.rate)
                self.breaker.record(breaker_key, False)
                last_exc = exc
                if not exc.retryable or attempt == attempts - 1:
                    raise
                self._backoff(attempt, retry_cfg, exc, deadline)
                continue
            try:
                return response, self._validate(response.text, response_format, schema)
            except OutputValidationError as exc:
                # one repair round: re-ask with the validation error, then fall back
                repair = LLMRequest(
                    task=task,
                    model=target.model,
                    messages=[
                        *messages,
                        {"role": "assistant", "content": response.text},
                        {
                            "role": "user",
                            "content": f"Your reply was invalid ({exc}). Reply again with only valid JSON.",
                        },
                    ],
                    temperature=cfg.temperature,
                    max_tokens=cfg.max_tokens,
                    response_format=response_format,
                    timeout_s=max(0.5, deadline - time.monotonic()),
                    extra={**cfg.params, **extra},
                )
                repaired = provider.complete(repair)
                self.limiter.update_from_headers(target.model, repaired.rate)
                return repaired, self._validate(repaired.text, response_format, schema)
        raise ProviderError(f"exhausted retries: {last_exc}")

    def _backoff(self, attempt: int, retry_cfg: dict[str, Any], exc: ProviderError, deadline: float) -> None:
        base = float(retry_cfg.get("base_ms", 250)) / 1000
        cap = float(retry_cfg.get("max_ms", 4000)) / 1000
        jitter = float(retry_cfg.get("jitter", 0.3))
        delay = min(cap, base * (2**attempt))
        if exc.rate and exc.rate.retry_after_s:
            delay = max(delay, exc.rate.retry_after_s)
        delay *= 1 + random.uniform(-jitter, jitter)
        if time.monotonic() + delay >= deadline:
            raise exc
        self._sleep(delay)

    def _response_format(
        self, cfg: LlmTask, model: str, messages: list[dict[str, Any]]
    ) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
        rf = cfg.response_format
        if rf is None or rf.type == "text":
            return None, None
        schema = self.schema(rf.schema_ref) if rf.schema_ref else None
        if rf.type == "json_schema" and schema is not None:
            clean = {k: v for k, v in schema.items() if k not in ("$schema", "title")}
            if model in self.json_schema_models:
                return {
                    "type": "json_schema",
                    "json_schema": {"name": schema.get("title", cfg.model.replace("/", "_")), "schema": clean},
                }, schema
            messages[0]["content"] += "\nReply with JSON matching this JSON Schema: " + json.dumps(clean)
        return {"type": "json_object"}, schema

    @staticmethod
    def _validate(text: str, response_format: dict[str, Any] | None, schema: dict[str, Any] | None) -> dict[str, Any]:
        if response_format is None:
            return {"text": text.strip()}
        try:
            data = json.loads(text)
        except json.JSONDecodeError as exc:
            raise OutputValidationError(f"not JSON: {exc.msg}") from exc
        if not isinstance(data, dict):
            raise OutputValidationError("expected a JSON object")
        if schema is not None:
            try:
                jsonschema.validate(data, schema)
            except jsonschema.ValidationError as exc:
                raise OutputValidationError(exc.message) from exc
        return data

    # ------------------------------------------------------------------ accounting
    def _result(
        self,
        task: str,
        output: dict[str, Any],
        provider: str,
        model: str,
        primary: bool,
        prompt_version: str | None,
        trace_id: str,
        started: float,
    ) -> LLMResult:
        status: CallStatus = "ok" if primary else "fallback"
        text = str(output.get("text", "")) if isinstance(output, dict) else ""
        return LLMResult(
            task=task,
            output=output,
            text=text,
            provider=provider,
            model=model,
            status=status,
            prompt_version=prompt_version,
            trace_id=trace_id,
            latency_ms=round((time.monotonic() - started) * 1000, 2),
        )

    def _record(self, result: LLMResult, error: str | None) -> None:
        self.sink.write(
            CallRecord(
                id=uuid.uuid4().hex,
                ts=utcnow(),
                task=result.task,
                provider=result.provider,
                model=result.model,
                prompt_version=result.prompt_version,
                input_tokens=result.input_tokens,
                output_tokens=result.output_tokens,
                latency_ms=result.latency_ms,
                status=result.status,
                fallback_used=result.fallback_used,
                guard_flags={},
                trace_id=result.trace_id,
                error=error,
            )
        )

    def status(self) -> dict[str, Any]:
        return {
            "profile": self.profile,
            "groq_key_configured": bool(self.settings.groq_key),
            "rate_limits": self.limiter.snapshot(),
            "circuit_breakers": self.breaker.state(),
            "tasks": self.stats.summary(),
            "provider_errors": dict(self._provider_errors),
        }


@lru_cache(maxsize=1)
def get_gateway() -> LLMGateway:
    settings = get_settings()
    sink: CallSink | None = None
    if settings.tp_env != "test":
        sink = DbSink(settings.database_url)
    return LLMGateway(get_config(), settings, sink=sink)
