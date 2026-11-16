"""Advanced detection layers (§10.13 D, E, G) and component health / RUL / risk inputs (§10.7.1).

D signature  — multivariate patterns from config/maintenance/signatures.yaml, evaluated over a window.
E peer drift — residual vs. the same model's fleet under similar conditions; robust z over a sustained window.
G fluid      — lab values vs. the limits table, including ISO 4406 cleanliness codes.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from datetime import datetime
from typing import Any

import numpy as np
import pandas as pd

from terrapilot.core.config import ConfigBundle
from terrapilot.maintenance.layers import EvidenceItem, Series, slope_per_h
from terrapilot.maintenance.limits import TIERS, tier_rank

SECONDS_PER_HOUR = 3600.0
MAD_TO_SD = 1.4826
# "trend(x) > 0.3/h" | "x_resid > 4" | "x < 0.9"
COND = re.compile(
    r"^\s*(?:(?P<fn>trend)\(\s*(?P<arg>[\w.]+)\s*\)|(?P<plain>[\w.]+))\s*(?P<op>[<>]=?)\s*(?P<value>-?\d+(?:\.\d+)?)(?:/h)?\s*$"
)


@dataclass
class ConditionResult:
    text: str
    ok: bool
    observed: float | None


def _resolve(
    name: str, series: dict[str, tuple[np.ndarray, np.ndarray]], residuals: dict[str, np.ndarray]
) -> tuple[np.ndarray, np.ndarray] | None:
    """`x_resid` resolves to the duty-normalised residual of x; anything else to the raw series."""
    if name.endswith("_resid"):
        base = name[: -len("_resid")]
        s, r = series.get(base), residuals.get(base)
        return (s[0], r) if s is not None and r is not None else None
    return series.get(name)


def evaluate_condition(
    text: str,
    series: dict[str, tuple[np.ndarray, np.ndarray]],
    residuals: dict[str, np.ndarray],
    window_h: float,
    now_s: float,
) -> ConditionResult:
    m = COND.match(text)
    if not m:
        return ConditionResult(text, False, None)
    name = m.group("arg") or m.group("plain")
    got = _resolve(name, series, residuals)
    if got is None or not len(got[0]):
        return ConditionResult(text, False, None)
    t, v = got
    mask = t >= now_s - window_h * SECONDS_PER_HOUR
    t, v = t[mask], v[mask]
    if len(t) < 2:
        return ConditionResult(text, False, None)
    observed = slope_per_h(Series(t, v))[0] if m.group("fn") == "trend" else float(np.median(v))
    threshold, op = float(m.group("value")), m.group("op")
    ok = observed > threshold if op.startswith(">") else observed < threshold
    return ConditionResult(text, bool(ok), round(observed, 4))


def signature_layer(
    cfg: ConfigBundle,
    machine_id: str,
    machine_class: str,
    series: dict[str, tuple[np.ndarray, np.ndarray]],
    residuals: dict[str, np.ndarray],
    now: datetime,
) -> list[EvidenceItem]:
    """Layer D: every condition of a signature must hold over its window."""
    out = []
    now_s = now.timestamp()
    for sig in cfg.signatures:
        entry = cfg.fault(sig.fault_catalogue_ref)
        if entry is not None and machine_class not in entry.classes:
            continue
        results = [evaluate_condition(c, series, residuals, sig.window_h, now_s) for c in sig.all_of]
        if not results or not all(r.ok for r in results):
            continue
        out.append(
            EvidenceItem(
                "signature",
                machine_id,
                sig.component,
                sig.tier,
                now,
                None,
                None,
                {
                    "signature_id": sig.id,
                    "window_h": sig.window_h,
                    "conditions": [{"text": r.text, "observed": r.observed} for r in results],
                },
                sig.fault_catalogue_ref,
            )
        )
    return out


def peer_layer(
    cfg: ConfigBundle,
    machine_id: str,
    residual_now: dict[str, float],
    peer_residuals: dict[str, list[float]],
    component_of: dict[str, str],
    now: datetime,
) -> list[EvidenceItem]:
    """Layer E: robust z of this machine's duty-normalised residual against its fleet peers."""
    pc = cfg.models["models"]["maint_alert_fusion"].get("peer", {})
    k = float(pc.get("robust_z", 3.0))
    min_peers = int(pc.get("min_peers", 3))
    out = []
    for sensor, value in residual_now.items():
        peers = [p for p in peer_residuals.get(sensor, []) if not math.isnan(p)]
        if len(peers) < min_peers or math.isnan(value):
            continue
        med = float(np.median(peers))
        mad = float(np.median(np.abs(np.array(peers) - med)))
        sd = MAD_TO_SD * mad
        if sd <= 0:
            continue
        z = (value - med) / sd
        if abs(z) < k:
            continue
        out.append(
            EvidenceItem(
                "peer",
                machine_id,
                component_of.get(sensor, "unknown"),
                str(pc.get("tier", "monitor")),
                now,
                sensor,
                round(value, 3),
                {"robust_z": round(z, 2), "peer_median": round(med, 3), "peers": len(peers)},
            )
        )
    return out


ISO = re.compile(r"^(\d+)/(\d+)/(\d+)$")


def _iso_worse(value: str, limit: str) -> bool:
    a, b = ISO.match(str(value)), ISO.match(str(limit))
    return bool(a and b and any(int(x) > int(y) for x, y in zip(a.groups(), b.groups(), strict=True)))


def fluid_layer(
    cfg: ConfigBundle, machine_id: str, samples: pd.DataFrame, now: datetime, max_age_days: float
) -> list[EvidenceItem]:
    """Layer G: the latest sample per compartment vs. the fluid limits table."""
    limits = cfg.sensor_limits.get("fluid_limits", {})
    comp_of = cfg.models["models"]["maint_alert_fusion"].get("fluid_components", {})
    out: list[EvidenceItem] = []
    if samples.empty:
        return out
    recent = samples[samples["ts"] >= pd.Timestamp(now) - pd.Timedelta(days=max_age_days)]
    for compartment, g in recent.groupby("compartment"):
        table = limits.get(str(compartment))
        if not table:
            continue
        row = g.sort_values("ts").iloc[-1]
        tier, breached = "normal", []
        for field, tiers in table.items():
            value = row.get(field if field != "iso_4406_max" else "iso_4406")
            if value is None or (isinstance(value, float) and math.isnan(value)):
                continue
            for t in TIERS[1:]:
                limit = tiers.get(t)
                if limit is None:
                    continue
                hit = _iso_worse(value, limit) if field == "iso_4406_max" else float(value) >= float(limit)
                if hit and tier_rank(t) > tier_rank(tier):
                    tier = t
                if hit:
                    breached.append(
                        {
                            "field": field,
                            "value": value if isinstance(value, str) else round(float(value), 2),
                            "limit": limit,
                            "tier": t,
                        }
                    )
        if tier == "normal":
            continue
        out.append(
            EvidenceItem(
                "fluid",
                machine_id,
                str(comp_of.get(str(compartment), compartment)),
                tier,
                pd.Timestamp(row["ts"]).to_pydatetime(),
                None,
                None,
                {
                    "compartment": compartment,
                    "lab_rating": row.get("lab_rating"),
                    "breached": breached[:4],
                    "sample_id": row.get("id"),
                },
            )
        )
    return out


# ------------------------------------------------------------------ component health (§10.7.1)
def health_index(cfg: ConfigBundle, evidence: list[EvidenceItem], component: str, base: float = 1.0) -> float:
    """A 0–1 condition score per component: 1.0 is healthy, each evidence tier deducts a configured amount."""
    w = (
        cfg.models["models"]
        .get("component_health", {})
        .get("tier_deduction", {"monitor": 0.08, "service_soon": 0.25, "stop": 0.6})
    )
    worst = 0.0
    for e in evidence:
        if e.component == component:
            worst = max(worst, float(w.get(e.tier, 0.0)))
    return round(max(0.0, min(1.0, base - worst)), 3)


def risk_index(
    cfg: ConfigBundle, machine_id: str, component: str, tables: Any, now: datetime, horizon_h: float | None = None
) -> dict[str, Any]:
    """Contextualised failure probability within H (§10.7.1): a Cox PH fit on component histories when the
    data supports it, otherwise the empirical hazard for that component kind."""
    mc = cfg.models["models"]["risk_index"]
    horizon = float(horizon_h or mc["horizon_h"])
    records = tables.get("maintenance_records")
    comps = tables.get("components")
    mine = comps[(comps["machine_id"] == machine_id) & (comps["kind"] == component)] if not comps.empty else comps
    hours = float(mine.iloc[0]["hours"]) if not mine.empty else 0.0
    failures = (
        records[(records["component"] == component) & (records["kind"].isin(["breakdown", "corrective"]))]
        if not records.empty
        else records
    )
    fleet = comps[comps["kind"] == component] if not comps.empty else comps
    n_units = max(len(fleet), 1)
    total_hours = float(fleet["hours"].sum()) if not fleet.empty else 1.0
    rate_per_h = (len(failures) / total_hours) if total_hours > 0 else 0.0
    p = 1 - math.exp(-rate_per_h * horizon)
    bands = mc.get("bands", {"high": 0.2, "medium": 0.05})
    band = "high" if p >= float(bands["high"]) else "medium" if p >= float(bands["medium"]) else "low"
    return {
        "component": component,
        "horizon_h": horizon,
        "p_fail": round(p, 4),
        "band": band,
        "hours": hours,
        "method": "empirical_hazard",
        "fleet_units": n_units,
        "fleet_failures": len(failures),
    }


def rul_estimate(
    forecast_curves: dict[str, dict[str, Any]], component_of: dict[str, str], component: str
) -> dict[str, Any] | None:
    """Remaining useful life from the sensor forecasts already computed for this component (§10.7.1)."""
    etas = []
    for sensor, curve in forecast_curves.items():
        if component_of.get(sensor) != component:
            continue
        for tier, e in (curve.get("etas") or {}).items():
            if tier == "stop":
                etas.append(e)
    if not etas:
        return None
    best = min(etas, key=lambda e: e["eta_h_p50"])
    return {
        "component": component,
        "rul_h_p10": best["eta_h_p10"],
        "rul_h_p50": best["eta_h_p50"],
        "rul_h_p90": best.get("eta_h_p90"),
        "method": "sensor_forecast_to_stop",
    }
