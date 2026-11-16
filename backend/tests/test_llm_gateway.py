from __future__ import annotations

import json
from pathlib import Path

import pytest

from terrapilot.core.config import ConfigBundle
from terrapilot.core.settings import Settings
from terrapilot.llm.cache import MemoryCache
from terrapilot.llm.cassette import CassetteMiss, CassetteProvider, request_fingerprint
from terrapilot.llm.gateway import LLMGateway, LLMUnavailableError
from terrapilot.llm.providers.base import ProviderError
from terrapilot.llm.providers.groq_provider import parse_duration_s, parse_rate_headers
from terrapilot.llm.rate_limiter import CircuitBreaker, RateLimiter
from terrapilot.llm.redaction import Pseudonymiser, RedactionError
from terrapilot.llm.types import LLMRequest, LLMResponse, RateLimitInfo

NARRATION_INPUTS = {"category": "grade", "facts": {"deviation_cm": 4, "direction": "raise"}, "max_words": 12}


class FakeProvider:
    name = "groq"

    def __init__(self, replies: list[str | Exception]):
        self.replies = list(replies)
        self.requests: list[LLMRequest] = []

    def complete(self, request: LLMRequest) -> LLMResponse:
        self.requests.append(request)
        reply = self.replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return LLMResponse(text=reply, model=request.model, input_tokens=10, output_tokens=5)

    def list_models(self) -> list[str]:
        return []


def settings(**kw: object) -> Settings:
    return Settings(_env_file=None, groq_api_key=None, tp_env="test", **kw)  # type: ignore[call-arg]


def gateway(cfg: ConfigBundle, provider: object | None = None, **kw: object) -> LLMGateway:
    providers = {"groq": provider} if provider else None
    return LLMGateway(cfg, settings(**kw), providers=providers, cache=MemoryCache(), sleep=lambda _s: None)  # type: ignore[arg-type]


def test_primary_success_validates_schema(cfg: ConfigBundle) -> None:
    fake = FakeProvider([json.dumps({"text": "Raise bucket 4 cm"})])
    res = gateway(cfg, fake).run("live_narration", NARRATION_INPUTS, category="grade")
    assert res.status == "ok" and res.output == {"text": "Raise bucket 4 cm"}
    assert res.prompt_version == "live_narration.v3"
    # json_schema models get strict structured output; others get json_object + the schema embedded in the prompt
    fmt = fake.requests[0].response_format or {}
    if cfg.llm.tasks["live_narration"].model in cfg.llm.providers["groq"].model_dump().get("json_schema_models", []):
        assert fmt["type"] == "json_schema" and fmt["json_schema"]["schema"]["properties"]["text"]
    else:
        assert fmt == {"type": "json_object"}
        assert "JSON Schema" in fake.requests[0].messages[0]["content"]


def test_no_key_falls_back_to_template(cfg: ConfigBundle) -> None:
    res = gateway(cfg).run("live_narration", NARRATION_INPUTS, category="grade")
    assert res.status == "fallback" and res.provider == "template"
    assert res.output["text"] == "Adjust bucket 4 cm — raise to design grade"
    assert any("GROQ_API_KEY" in e for e in res.errors)


def test_invalid_output_is_repaired_once(cfg: ConfigBundle) -> None:
    fake = FakeProvider(["not json", json.dumps({"text": "ok"})])
    res = gateway(cfg, fake).run("live_narration", NARRATION_INPUTS, category="grade")
    assert res.status == "ok" and res.output == {"text": "ok"} and len(fake.requests) == 2


def test_invalid_twice_falls_back(cfg: ConfigBundle) -> None:
    fake = FakeProvider(["nope", json.dumps({"wrong": 1})])
    res = gateway(cfg, fake).run("live_narration", NARRATION_INPUTS, category="grade")
    assert res.provider == "template"


def test_narrator_never_retries(cfg: ConfigBundle) -> None:
    fake = FakeProvider([ProviderError("429", status=429, retryable=True)])
    res = gateway(cfg, fake).run("live_narration", NARRATION_INPUTS, category="grade")
    assert res.provider == "template" and len(fake.requests) == 1


def test_retry_on_429_for_retrying_tasks(cfg: ConfigBundle) -> None:
    ok = json.dumps({"summary": "s", "likely_cause": "c", "next_step": "n"})
    fake = FakeProvider([ProviderError("rate", status=429, retryable=True, rate=RateLimitInfo(retry_after_s=0.01)), ok])
    res = gateway(cfg, fake).run(
        "maint_explainer", {"audience": "technician", "evidence": {"x": 1}, "manual_excerpt": "m"}
    )
    assert res.status == "ok" and len(fake.requests) == 2


def test_cache_hit(cfg: ConfigBundle) -> None:
    fake = FakeProvider([json.dumps({"text": "Raise bucket 4 cm"})])
    gw = gateway(cfg, fake)
    gw.run("live_narration", NARRATION_INPUTS, category="grade")
    second = gw.run("live_narration", NARRATION_INPUTS, category="grade")
    assert second.status == "cached" and len(fake.requests) == 1
    summary = gw.status()["tasks"]["live_narration"]
    assert summary["by_status"] == {"ok": 1, "cached": 1}


def test_task_without_template_raises(cfg: ConfigBundle) -> None:
    with pytest.raises(LLMUnavailableError):
        gateway(cfg).run("eval_judge", {})


def test_never_send_is_enforced(cfg: ConfigBundle) -> None:
    with pytest.raises(RedactionError):
        gateway(cfg, FakeProvider([])).run("summaries", {"driver_camera_frames": "..."})


def test_pseudonymisation_roundtrip() -> None:
    p = Pseudonymiser(["operator_name"], [])
    red = p.redact({"operator_name": "Asha Rao", "note": "Asha Rao reported a leak"})
    assert "Asha Rao" not in json.dumps(red)
    assert p.rehydrate(red["note"]) == "Asha Rao reported a leak"


def test_offline_profile_skips_groq(cfg: ConfigBundle) -> None:
    gw = gateway(cfg, tp_profile="offline")
    assert all(t.provider != "groq" for t in gw.chain("live_narration"))
    assert (
        gw.run(
            "plan_explainer", {"facts": {}}, template_facts={"recommended_start": "09:45", "saving_min": 22}
        ).provider
        == "template"
    )


def test_cassette_replay(cfg: ConfigBundle, tmp_path: Path) -> None:
    gw = gateway(cfg, FakeProvider([]))
    messages = gw.prompts.render("prompts/live_narration.v3.j2", {"locale": "en", **NARRATION_INPUTS})
    cfg_task = cfg.llm.tasks["live_narration"]
    rf, _ = gw._response_format(cfg_task, cfg_task.model, messages)
    req = LLMRequest(
        task="live_narration",
        model=cfg_task.model,
        messages=messages,
        temperature=cfg_task.temperature,
        max_tokens=cfg_task.max_tokens,
        response_format=rf,
    )
    cassette = tmp_path / "c.json"
    cassette.write_text(
        json.dumps({"interactions": {request_fingerprint(req): {"text": json.dumps({"text": "from cassette"})}}})
    )
    replay = CassetteProvider(None, cassette, "replay")
    res = gateway(cfg, replay).run("live_narration", NARRATION_INPUTS, category="grade")
    assert res.output == {"text": "from cassette"}
    with pytest.raises(CassetteMiss):
        replay.complete(LLMRequest(task="x", model="m", messages=[]))


def test_rate_limiter_buckets_and_headers() -> None:
    now = [0.0]
    rl = RateLimiter(
        {"m": (2, 1000)},
        low_headroom_fraction=0.2,
        clock=lambda: now[0],
        sleep=lambda s: now.__setitem__(0, now[0] + s),
    )
    assert rl.try_acquire("m", 100, lane=0) == 0
    assert rl.try_acquire("m", 100, lane=0) == 0
    assert rl.try_acquire("m", 100, lane=0) > 0  # rpm exhausted
    assert rl.acquire("m", 100, lane=0, max_wait_s=60)  # waits for refill
    rl.update_from_headers("m", RateLimitInfo(remaining_tokens=10, retry_after_s=5))
    assert rl.try_acquire("m", 10, lane=0) == pytest.approx(5, abs=0.1)
    assert rl.try_acquire("unknown", 10, lane=3) == 0


def test_low_priority_yields_when_headroom_low() -> None:
    rl = RateLimiter({"m": (100, 1000)}, low_headroom_fraction=0.5, clock=lambda: 0.0)
    rl.update_from_headers("m", RateLimitInfo(remaining_tokens=300))
    assert rl.try_acquire("m", 10, lane=2) > 0  # content_gen-style lane waits
    assert rl.try_acquire("m", 10, lane=0) == 0  # narration lane proceeds


def test_circuit_breaker() -> None:
    t = [0.0]
    cb = CircuitBreaker(2, 10, clock=lambda: t[0])
    cb.record("k", False)
    cb.record("k", False)
    assert not cb.allow("k")
    t[0] = 11
    assert cb.allow("k")


def test_groq_header_parsing() -> None:
    assert parse_duration_s("2m59.56s") == pytest.approx(179.56)
    assert parse_duration_s("120ms") == pytest.approx(0.12)
    info = parse_rate_headers(
        {"x-ratelimit-remaining-tokens": "5800", "x-ratelimit-limit-tokens": "6000", "retry-after": "3"}
    )
    assert info.remaining_tokens == 5800 and info.limit_tokens == 6000 and info.retry_after_s == 3
