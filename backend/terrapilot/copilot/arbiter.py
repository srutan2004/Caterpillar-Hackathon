"""Arbiter (§12.1 step 2): one advisory at a time.

score = base_priority(category) × severity_weight × urgency × novelty, with a minimum dwell, a per-category
cooldown and hysteresis against flicker. In precision mode (e.g. while cutting grade) only the configured
categories may speak. Open caution/warning alerts pre-empt the advisory entirely (the banner shows the alert).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from simpleeval import EvalWithCompoundTypes

from terrapilot.copilot.generators import Candidate
from terrapilot.core.expr import SAFE_FUNCTIONS, to_namespace

PREEMPTING = ("caution", "warning")


@dataclass
class Shown:
    candidate: Candidate
    score: float
    since: datetime
    advisory_id: str


class Arbiter:
    def __init__(self, copilot_cfg: dict[str, Any]):
        self.c = copilot_cfg
        self.shown: Shown | None = None
        self.last_by_category: dict[str, datetime] = {}
        self.last_by_key: dict[str, datetime] = {}
        self._n = 0

    def _precision(self, state: dict[str, Any]) -> bool:
        expr = (self.c.get("precision_mode") or {}).get("when")
        if not expr:
            return False
        try:
            names = {k: to_namespace(v) if isinstance(v, dict) else v for k, v in state.items()}
            return bool(EvalWithCompoundTypes(names=names, functions=SAFE_FUNCTIONS).eval(expr))
        except Exception:
            return False

    def score(self, cand: Candidate, now: datetime) -> float:
        cat = self.c["categories"][cand.category]
        sev = float(self.c["severity_weight"].get(cand.severity, 1.0))
        nov = 1.0
        last = self.last_by_key.get(cand.key)
        if last is not None and (now - last).total_seconds() < float(self.c["novelty"]["window_s"]):
            nov = float(self.c["novelty"]["repeat_decay"])
        return float(cat["base_priority"]) * sev * max(cand.urgency, 0.1) * nov

    def select(
        self, candidates: list[Candidate], state: dict[str, Any], open_alerts: list[Any], now: datetime
    ) -> tuple[Candidate | None, bool]:
        """Returns (candidate to show, is_new). None while an alert pre-empts or nothing qualifies."""
        if any(getattr(a, "severity", None) in PREEMPTING for a in open_alerts):
            return None, False
        allowed = set((self.c.get("precision_mode") or {}).get("categories", [])) if self._precision(state) else None
        if self.shown is not None:  # expire first, so an expired advisory is subject to its category cooldown
            ttl = float(self.c["categories"][self.shown.candidate.category]["ttl_s"])
            age = (now - self.shown.since).total_seconds()
            live_keys = {c.key for c in candidates}
            if age >= ttl or (self.shown.candidate.key not in live_keys and age >= float(self.c["dwell_s"])):
                self.shown = None
        pool = []
        for cand in candidates:
            if allowed is not None and cand.category not in allowed:
                continue
            cd = float(self.c["categories"][cand.category]["cooldown_s"])
            last = self.last_by_category.get(cand.category)
            same_as_shown = self.shown is not None and self.shown.candidate.key == cand.key
            if last is not None and (now - last).total_seconds() < cd and not same_as_shown:
                continue
            pool.append((self.score(cand, now), cand))
        if not pool:
            return (self.shown.candidate, False) if self.shown else (None, False)
        best_score, best = max(pool, key=lambda x: x[0])
        if self.shown is not None:
            if best.key == self.shown.candidate.key:
                self.shown.candidate = best  # refresh facts (e.g. distance changed)
                return best, False
            dwell_ok = (now - self.shown.since).total_seconds() >= float(self.c["dwell_s"])
            beats = best_score > self.shown.score * float(self.c["hysteresis"]["switch_margin"])
            if not (dwell_ok and beats):
                return self.shown.candidate, False
        self._n += 1
        self.shown = Shown(best, best_score, now, f"adv-{self._n:05d}")
        self.last_by_category[best.category] = now
        self.last_by_key[best.key] = now
        return best, True
