"""Live Situational Copilot (§12.1): generators → arbiter → template (immediately) → Groq narrator (async) →
validator → advisory. `make_advisor` is the hook the scenario manager hands to the edge pipeline.

The edge tick never waits for the LLM: the template advisory is published at once; if the narration arrives
within the advisory's TTL and passes the validator, the same advisory id is re-published with the LLM text.
"""

from __future__ import annotations

from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

from terrapilot.copilot.arbiter import Arbiter
from terrapilot.copilot.generators import Candidate, GenContext, generate
from terrapilot.copilot.guard_log import guard_row
from terrapilot.copilot.validator import validate
from terrapilot.core.config import ConfigBundle
from terrapilot.core.logging import get_logger

log = get_logger("copilot.live")


@dataclass
class Pending:
    advisory: dict[str, Any]
    future: Future[Any]
    deadline: datetime


@dataclass
class LiveAdvisor:
    cfg: ConfigBundle
    machine_id: str
    manifest: dict[str, Any]
    locale: str
    gateway: Any = None
    extras: dict[str, Any] = field(default_factory=dict)
    guard_events: list[dict[str, Any]] = field(default_factory=list)
    published: list[dict[str, Any]] = field(default_factory=list)
    on_guard: Callable[[dict[str, Any]], None] | None = None

    def __post_init__(self) -> None:
        c = self.cfg.copilot
        self.arbiter = Arbiter(c)
        self.period = timedelta(seconds=1 / float(c.get("tick_hz", 2)))
        self._last: datetime | None = None
        narr = c.get("narrator", {})
        self.narrate = bool(narr.get("enabled", True)) and self.gateway is not None
        self.pool = (
            ThreadPoolExecutor(max_workers=int(narr.get("workers", 2)), thread_name_prefix="narrator")
            if self.narrate
            else None
        )
        self.pending: dict[str, Pending] = {}

    # ------------------------------------------------------------------ templates
    def template_text(self, cand: Candidate) -> str:
        from terrapilot.llm.providers.template_provider import TemplateProvider

        tp = TemplateProvider(self.cfg.i18n, "llm_template", self.cfg.app.locales.default)
        return str(tp.render("live_narration", cand.facts, self.locale, cand.template).get("text", ""))

    def _advisory(self, cand: Candidate, adv_id: str, text: str, source: str, score: float) -> dict[str, Any]:
        cat = self.cfg.copilot["categories"][cand.category]
        return {
            "id": adv_id,
            "category": cand.category,
            "severity": cand.severity,
            "text": text,
            "source": source,
            "facts": cand.facts,
            "expires_in_s": float(cat["ttl_s"]),
            "priority": round(score, 1),
        }

    # ------------------------------------------------------------------ narration
    def _narrate(self, cand: Candidate) -> Any:
        return self.gateway.run(
            "live_narration",
            {
                "category": cand.category,
                "facts": cand.facts,
                "max_words": int(self.cfg.copilot["max_words"]),
                "context": {"machine_class": self.manifest["class"], "currency": self.cfg.app.costs["currency"]},
            },
            locale=self.locale,
            category=cand.template,
            template_facts=cand.facts,
        )

    def _collect(self, now: datetime) -> list[dict[str, Any]]:
        out = []
        for adv_id, p in list(self.pending.items()):
            if not p.future.done():
                if now > p.deadline:
                    self.pending.pop(adv_id)
                continue
            self.pending.pop(adv_id)
            shown = self.arbiter.shown
            if shown is None or shown.advisory_id != adv_id or now > p.deadline:
                continue  # superseded or too late — the template stays
            try:
                res = p.future.result()
            except Exception as exc:  # the narrator must never break the tick
                log.warning("narration failed", error=str(exc))
                continue
            if res.provider == "template":
                continue
            text = str(res.output.get("text", "")).strip()
            verdict = validate(
                text, p.advisory["facts"], self.cfg.copilot["validator"], int(self.cfg.copilot["max_words"])
            )
            if not verdict.ok:
                row = guard_row(
                    "output",
                    "narration_validator",
                    "keep_template",
                    {"task": "live_narration", "reasons": verdict.reasons, "text": text},
                    text,
                    now,
                )
                self.guard_events.append(row)
                if self.on_guard is not None:
                    self.on_guard(row)
                continue
            out.append({**p.advisory, "text": text, "source": "llm"})
        return out

    # ------------------------------------------------------------------ tick
    def __call__(self, state: dict[str, Any], open_alerts: list[Any], now: datetime) -> list[dict[str, Any]]:
        out = self._collect(now)
        if self._last is not None and now - self._last < self.period:
            return out
        self._last = now
        ctx = GenContext(self.cfg, self.manifest, now, self.extras)
        cand, is_new = self.arbiter.select(generate(state, ctx), state, open_alerts, now)
        if cand is None or not is_new or self.arbiter.shown is None:
            return out
        shown = self.arbiter.shown
        adv = self._advisory(cand, shown.advisory_id, self.template_text(cand), "template", shown.score)
        out.append(adv)
        self.published.append(adv)
        if self.pool is not None:
            ttl = timedelta(seconds=float(adv["expires_in_s"]))
            self.pending[adv["id"]] = Pending(adv, self.pool.submit(self._narrate, cand), now + ttl)
        return out

    def close(self) -> None:
        if self.pool is not None:
            self.pool.shutdown(wait=False, cancel_futures=True)


def make_advisor(
    cfg: ConfigBundle, machine_id: str, *, with_llm: bool = True, locale: str | None = None
) -> LiveAdvisor:
    """Hook used by the scenario manager (api/routers/live.py) and `tp sim`."""
    from terrapilot.sim.world import load_context

    world = load_context(machine_id, None, None)
    manifest = cfg.manifests_raw[str(world.machine["manifest_id"])]
    gateway = None
    if with_llm:
        from terrapilot.llm.gateway import get_gateway

        gateway = get_gateway()
    return LiveAdvisor(cfg, machine_id, manifest, locale or cfg.app.locales.default, gateway)
