"""Behaviour outputs (§10.5): operator scorecard, idle summary (fuel/CO₂/cost) and adaptive-assignment triggers."""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from typing import Any

import pandas as pd

from terrapilot.core.config import ConfigBundle
from terrapilot.ml.data import Tables

SECONDS_PER_HOUR = 3600.0


def _json(v: Any) -> dict[str, Any]:
    if isinstance(v, dict):
        return v
    if isinstance(v, str) and v:
        try:
            out = json.loads(v)
            return out if isinstance(out, dict) else {}
        except json.JSONDecodeError:
            return {}
    return {}


def _events(
    tables: Tables, since: datetime, operator_id: str | None = None, site_machines: list[str] | None = None
) -> pd.DataFrame:
    if tables.source == "db":
        sql = "SELECT * FROM behavior_events WHERE start_ts >= :since"
        params: dict[str, Any] = {"since": since}
        if operator_id:
            sql += " AND operator_id = :op"
            params["op"] = operator_id
        ev = tables.get("behavior_events", sql, params)
    else:
        ev = tables.get("behavior_events")
        ev = ev[ev["start_ts"] >= pd.Timestamp(since)]
        if operator_id:
            ev = ev[ev["operator_id"] == operator_id]
    if site_machines is not None:
        ev = ev[ev["machine_id"].isin(site_machines)]
    return ev


def idle_summary(
    cfg: ConfigBundle, tables: Tables, now: datetime, days: int, site_id: str | None = None
) -> dict[str, Any]:
    machines = tables.get("machines")
    ids = machines[machines["site_id"] == site_id]["id"].tolist() if site_id else None
    ev = _events(tables, now - timedelta(days=days), site_machines=ids)
    idle = ev[ev["kind"].isin(["idle", "high_rpm_idle"])]
    costs = idle["cost"].map(_json)
    total = {k: float(sum(c.get(k, 0.0) or 0.0 for c in costs)) for k in ("fuel_l", "kwh", "cost", "co2_kg")}
    hours = float(
        sum(_json(m).get("duration_s", 0.0) for m in idle[idle["kind"] == "idle"]["metrics"]) / SECONDS_PER_HOUR
    )
    by_machine = (
        idle.assign(c=costs.map(lambda c: float(c.get("cost", 0.0) or 0.0)))
        .groupby("machine_id")["c"]
        .sum()
        .sort_values(ascending=False)
    )
    return {
        "days": days,
        "site_id": site_id,
        "episodes": int((idle["kind"] == "idle").sum()),
        "idle_hours": round(hours, 1),
        "fuel_l": round(total["fuel_l"], 1),
        "kwh": round(total["kwh"], 1),
        "co2_kg": round(total["co2_kg"], 1),
        "cost": round(total["cost"], 0),
        "currency": cfg.app.costs["currency"],
        "by_machine": [{"machine_id": m, "cost": round(float(v), 0)} for m, v in by_machine.head(10).items()],
    }


def scorecard(cfg: ConfigBundle, tables: Tables, operator_id: str, now: datetime, days: int) -> dict[str, Any]:
    """Counts, rates and costs over the window; every figure is traceable to behaviour events or compliance rows."""
    since = now - timedelta(days=days)
    ev = _events(tables, since, operator_id)
    counts = ev["kind"].value_counts().to_dict()
    belt = tables.get("seatbelt_compliance")
    belt = belt[(belt["operator_id"] == operator_id) & (pd.to_datetime(belt["date"]) >= pd.Timestamp(since.date()))]
    active_s = float(belt["active_s"].sum())
    compliance = 1 - float(belt["unbelted_active_s"].sum()) / active_s if active_s > 0 else None
    idle = ev[ev["kind"] == "idle"]
    idle_s = float(sum(_json(m).get("duration_s", 0.0) for m in idle["metrics"]))
    idle_cost = float(sum(float(_json(c).get("cost", 0.0) or 0.0) for c in idle["cost"]))
    from terrapilot.analytics.anomaly import load_anomalies

    anomalies = load_anomalies(cfg)
    n_anom = 0
    if not anomalies.empty:
        a = anomalies[(anomalies["operator_id"] == operator_id) & (anomalies["ts"] >= pd.Timestamp(since))]
        n_anom = len(a)
    unsafe_kinds = [k for k in cfg.behavior_rules.episodes if k not in ("idle", "high_rpm_idle")]
    return {
        "operator_id": operator_id,
        "days": days,
        "active_hours": round(active_s / SECONDS_PER_HOUR, 1),
        "seatbelt_compliance": None if compliance is None else round(compliance, 4),
        "idle_ratio": round(idle_s / active_s, 4) if active_s > 0 else None,
        "idle_cost": round(idle_cost, 0),
        "currency": cfg.app.costs["currency"],
        "unsafe_events": {k: int(counts.get(k, 0)) for k in unsafe_kinds},
        "unusual_cycles": n_anom,
        "suggested_modules": suggested_modules(cfg, counts, idle_s / active_s if active_s > 0 else 0.0, ev, now),
    }


def suggested_modules(
    cfg: ConfigBundle, counts: dict[str, int], idle_ratio: float, ev: pd.DataFrame, now: datetime
) -> list[dict[str, Any]]:
    """Adaptive assignment rules (§10.8.5) evaluated over their own windows."""
    out = []
    for rule in cfg.behavior_rules.model_dump().get("adaptive_assignment", []):
        sig = rule["signal"]
        for key, value in rule.items():
            if not key.startswith("min_"):
                continue
            days = int(key.rsplit("_", 1)[-1].rstrip("d"))
            window = ev[ev["start_ts"] >= pd.Timestamp(now - timedelta(days=days))] if not ev.empty else ev
            if key.startswith("min_ratio"):
                fired = idle_ratio >= float(value)
                observed: float = round(idle_ratio, 3)
            else:
                observed = int((window["kind"] == sig).sum()) if not window.empty else 0
                fired = observed >= float(value)
            if fired:
                out.append({"signal": sig, "module": rule["module"], "observed": observed, "threshold": value})
    return out
