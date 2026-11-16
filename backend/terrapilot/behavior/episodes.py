"""Rule/episode detectors (§10.5 layer 1). Episode definitions live in config/rules/behavior.yaml; thresholds
reference the manifest. An episode opens when its condition holds, and emits a BehaviorEvent on close if it
lasted at least `min_s`. Idle episodes carry fuel, cost and CO₂ attribution.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from simpleeval import EvalWithCompoundTypes

from terrapilot.core.config import ConfigBundle
from terrapilot.core.expr import SAFE_FUNCTIONS, to_namespace
from terrapilot.domain.models import BehaviorEvent

SECONDS_PER_HOUR = 3600.0


@dataclass
class _Episode:
    kind: str
    when: str
    min_s: float
    started: datetime | None = None
    peak: dict[str, float] | None = None


class EpisodeDetector:
    def __init__(self, cfg: ConfigBundle, machine_id: str, manifest_id: str):
        self.cfg = cfg
        self.machine_id = machine_id
        self.manifest = cfg.manifests[manifest_id]
        raw = cfg.manifests_raw[manifest_id]
        self._static = {"manifest": to_namespace(raw), "app": to_namespace(cfg.app_dict())}
        self.episodes: list[_Episode] = []
        for kind, ep in cfg.behavior_rules.episodes.items():
            if ep.applies_to and self.manifest.class_ not in ep.applies_to:
                continue
            min_s = ep.min_s if isinstance(ep.min_s, int | float) else self._eval(str(ep.min_s), {})
            self.episodes.append(_Episode(kind, ep.when, float(min_s)))
        self._counter = 0
        self._run = format(int(time.time()), "x")
        costs = cfg.app.costs
        self.fuel_price = float(costs["diesel_price_per_l"])
        self.co2_per_l = float(costs["co2_kg_per_l_diesel"])
        self.idle_lph = float(self.manifest.specs.get("idle_fuel_lph", 0.0))
        self.idle_kw = float((self.manifest.specs.get("consumption_kw") or {}).get("idle", 0.0))
        self.kwh_price = float(costs["electricity_price_per_kwh"])
        self.co2_per_kwh = float(costs["co2_kg_per_kwh_grid"])
        # extra machine hours → maintenance accrual (§10.5 cost attribution)
        accrual = (cfg.costs.get("maintenance_accrual_per_h") or {}).get(self.manifest.class_, {})
        self.accrual_per_h = float(sum(accrual.values()))

    def idle_cost(self, duration_s: float) -> dict[str, float]:
        h = duration_s / SECONDS_PER_HOUR
        maint = round(h * self.accrual_per_h, 2)
        if self.manifest.powertrain == "electric":
            kwh = self.idle_kw * h
            return {
                "kwh": round(kwh, 3),
                "energy_cost": round(kwh * self.kwh_price, 2),
                "maintenance_cost": maint,
                "cost": round(kwh * self.kwh_price + maint, 2),
                "co2_kg": round(kwh * self.co2_per_kwh, 3),
            }
        fuel = self.idle_lph * h
        return {
            "fuel_l": round(fuel, 3),
            "fuel_cost": round(fuel * self.fuel_price, 2),
            "maintenance_cost": maint,
            "cost": round(fuel * self.fuel_price + maint, 2),
            "co2_kg": round(fuel * self.co2_per_l, 3),
        }

    def _eval(self, expr: str, names: dict[str, Any]) -> Any:
        return EvalWithCompoundTypes(names={**names, **self._static}, functions=SAFE_FUNCTIONS).eval(expr.strip())

    def _active(self, expr: str, names: dict[str, Any]) -> bool:
        try:
            return bool(self._eval(expr, names))
        except Exception:
            return False

    def running(self, kind: str, now: datetime) -> float:
        """Seconds the given episode has been open (0 when closed) — e.g. the live idle timer."""
        ep = next((e for e in self.episodes if e.kind == kind), None)
        return (now - ep.started).total_seconds() if ep and ep.started else 0.0

    def update(
        self, state: dict[str, Any], now: datetime, operator_id: str, task_id: str | None = None
    ) -> list[BehaviorEvent]:
        names = {k: to_namespace(v) for k, v in state.items()}
        idle_ep = next((e for e in self.episodes if e.kind == "idle"), None)
        names["episode"] = to_namespace({"idle": bool(idle_ep and idle_ep.started)})
        out: list[BehaviorEvent] = []
        for ep in self.episodes:
            active = self._active(ep.when, names)
            if active and ep.started is None:
                ep.started = now
            elif not active and ep.started is not None:
                duration = (now - ep.started).total_seconds()
                if duration >= ep.min_s:
                    out.append(self._event(ep, ep.started, now, operator_id, task_id))
                ep.started = None
        return out

    def flush(self, now: datetime, operator_id: str, task_id: str | None = None) -> list[BehaviorEvent]:
        out = []
        for ep in self.episodes:
            if ep.started is not None and (now - ep.started).total_seconds() >= ep.min_s:
                out.append(self._event(ep, ep.started, now, operator_id, task_id))
            ep.started = None
        return out

    def _event(
        self, ep: _Episode, start: datetime, end: datetime, operator_id: str, task_id: str | None
    ) -> BehaviorEvent:
        self._counter += 1
        duration = (end - start).total_seconds()
        cost: dict[str, float] = {}
        if ep.kind in ("idle", "high_rpm_idle"):
            cost = self.idle_cost(duration)
        return BehaviorEvent(
            id=f"BE-{self.machine_id}-{self._run}-{self._counter:05d}",
            machine_id=self.machine_id,
            operator_id=operator_id,
            kind=ep.kind,
            start_ts=start,
            end_ts=end,
            metrics={"duration_s": round(duration, 1)},
            cost=cost,
        )


def idle_cost_so_far(detector: EpisodeDetector, now: datetime) -> dict[str, float]:
    s = detector.running("idle", now)
    return {"idle_s": round(s, 1), **detector.idle_cost(s)}
