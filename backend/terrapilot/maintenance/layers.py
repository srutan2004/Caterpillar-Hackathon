"""Detection layers (§10.13). Each returns an `EvidenceItem` or None; all are deterministic or classical.

A limit/band (debounced), B rate of change (fast per-minute and slow per-hour, Theil–Sen), C time-to-threshold
forecast (irregular-interval Holt with slope uncertainty → ETA p10/p50/p90, lead-time aware), F service-interval
counters, H fault codes.
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta
from typing import Any

import numpy as np
from scipy import stats

from terrapilot.maintenance.limits import TIERS, bad_sign, band_tier, threshold, tier_rank

SECONDS_PER_HOUR = 3600.0
MINUTES_PER_HOUR = 60.0


@dataclass
class EvidenceItem:
    layer: str  # limit | rate | forecast | interval | fault_code | signature | peer | fluid
    machine_id: str
    component: str
    tier: str
    ts: datetime
    sensor_id: str | None = None
    value: float | None = None
    detail: dict[str, Any] = field(default_factory=dict)
    catalogue_code: str | None = None

    def as_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["ts"] = self.ts.isoformat()
        return d


@dataclass
class Series:
    """Operating samples of one sensor: times as POSIX seconds (machine time) and values."""

    t: np.ndarray
    v: np.ndarray
    rpm: np.ndarray | None = None

    def window(self, since_s: float) -> Series:
        m = self.t >= since_s
        return Series(self.t[m], self.v[m], None if self.rpm is None else self.rpm[m])

    def __len__(self) -> int:
        return len(self.t)


def _ts(t: float) -> datetime:
    from datetime import UTC

    return datetime.fromtimestamp(float(t), UTC)


# ------------------------------------------------------------------ A: limit / band
def limit_layer(
    s: Series, limit: dict[str, Any], machine_id: str, component: str, sensor_id: str
) -> EvidenceItem | None:
    if not len(s):
        return None
    deb = float(limit.get("debounce_s") or 0.0)
    recent = s.window(float(s.t[-1]) - deb)
    if not len(recent):
        recent = s.window(float(s.t[-1]))
    tiers = [
        band_tier(limit, float(v), None if recent.rpm is None else float(recent.rpm[i])) for i, v in enumerate(recent.v)
    ]
    tier = min(tiers, key=tier_rank)  # sustained for the whole debounce window
    if tier == "normal":
        return None
    return EvidenceItem(
        "limit",
        machine_id,
        component,
        tier,
        _ts(s.t[-1]),
        sensor_id,
        round(float(s.v[-1]), 3),
        {"threshold": threshold(limit, tier), "debounce_s": deb, "unit": limit.get("unit")},
    )


# ------------------------------------------------------------------ B: rate of change
def slope_per_h(s: Series) -> tuple[float, float, float]:
    """Theil–Sen slope per hour with its 90% confidence bounds."""
    hours = (s.t - s.t[0]) / SECONDS_PER_HOUR
    res = stats.theilslopes(s.v, hours, alpha=0.90)
    return float(res.slope), float(res.low_slope), float(res.high_slope)


def _covered(w: Series, span_s: float, coverage: float) -> bool:
    return len(w) >= 2 and (float(w.t[-1]) - float(w.t[0])) >= coverage * span_s


def rate_layer(
    s: Series,
    limit: dict[str, Any],
    machine_id: str,
    component: str,
    sensor_id: str,
    min_points: int,
    coverage: float = 0.0,
) -> EvidenceItem | None:
    best: EvidenceItem | None = None
    for key, per, win_key, scale in (
        ("rate_limit", "per_min", "window_min", MINUTES_PER_HOUR),
        ("trend_limit", "per_h", "window_h", 1.0),
    ):
        cfg = limit.get(key)
        if not cfg or not len(s):
            continue
        win_s = float(cfg[win_key]) * (SECONDS_PER_HOUR / scale)
        w = s.window(float(s.t[-1]) - win_s)
        if len(w) < min_points or not _covered(w, win_s, coverage):
            continue
        slope, lo, hi = slope_per_h(w)
        limit_h = float(cfg[per]) * scale
        # the whole confidence band must be past the limit in the configured direction
        fired = lo >= limit_h if limit_h > 0 else hi <= limit_h
        if fired:
            ev = EvidenceItem(
                "rate",
                machine_id,
                component,
                str(cfg["tier"]),
                _ts(s.t[-1]),
                sensor_id,
                round(float(w.v[-1]), 3),
                {
                    "slope_per_h": round(slope, 4),
                    "limit_per_h": limit_h,
                    "window_h": round(win_s / SECONDS_PER_HOUR, 2),
                    "kind": key,
                },
            )
            if best is None or tier_rank(ev.tier) > tier_rank(best.tier):
                best = ev
    return best


# ------------------------------------------------------------------ C: time-to-threshold forecast
@dataclass(frozen=True)
class HoltFit:
    level: float
    trend_per_h: float
    trend_se: float
    resid_sd: float
    t_last: float


def holt_irregular(s: Series, alpha: float, beta: float, half_life_h: float) -> HoltFit:
    """Holt's linear method on irregular samples (trend per hour); the slope SE comes from a WLS fit with the
    memory expressed in machine hours (`half_life_h`), so sparse or bursty sampling does not shrink the evidence."""
    level, trend = float(s.v[0]), 0.0
    errs = []
    for i in range(1, len(s)):
        dt = max((s.t[i] - s.t[i - 1]) / SECONDS_PER_HOUR, 1e-6)
        pred = level + trend * dt
        errs.append(float(s.v[i]) - pred)
        new_level = alpha * float(s.v[i]) + (1 - alpha) * pred
        trend = beta * (new_level - level) / dt + (1 - beta) * trend
        level = new_level
    hours = (s.t - s.t[-1]) / SECONDS_PER_HOUR
    w = 0.5 ** (-hours / half_life_h)
    X = np.vstack([np.ones_like(hours), hours]).T
    W = np.diag(w)
    try:
        cov = np.linalg.inv(X.T @ W @ X)
        coef = cov @ X.T @ W @ s.v
        resid = s.v - X @ coef
        dof = max(len(s) - 2, 1)
        sigma2 = float((w * resid**2).sum() / (w.sum() * dof / len(s)))
        se = math.sqrt(max(sigma2 * cov[1, 1], 0.0))
    except np.linalg.LinAlgError:
        se = math.inf
    sd = float(np.std(errs[-min(len(errs), 50) :])) if errs else 0.0
    return HoltFit(level, trend, se, sd, float(s.t[-1]))


def forecast_layer(
    s: Series,
    limit: dict[str, Any],
    machine_id: str,
    component: str,
    sensor_id: str,
    fcfg: dict[str, Any],
    lead_time_h: float,
    coverage: float = 0.0,
) -> tuple[EvidenceItem | None, dict[str, Any] | None]:
    fc = limit.get("forecast")
    if not fc or len(s) < int(fcfg["min_points"]):
        return None, None
    span = float(fcfg["min_span_h"]) * SECONDS_PER_HOUR
    w = s.window(float(s.t[-1]) - float(fcfg["lookback_h"]) * SECONDS_PER_HOUR)
    if len(w) < int(fcfg["min_points"]) or not _covered(w, span, 1.0):
        return None, None
    fit = holt_irregular(w, float(fcfg["alpha"]), float(fcfg["beta"]), float(fcfg["trend_half_life_h"]))
    sign = bad_sign(limit)
    horizon = float(fc["horizon_h"])
    z = stats.norm.ppf(1 - float(fcfg["eta_quantiles"][0]))
    current = band_tier(limit, fit.level)
    etas: dict[str, dict[str, Any]] = {}
    for tier in TIERS[tier_rank(current) + 1 :]:
        thr = threshold(limit, tier)
        if thr is None:
            continue
        gap = (thr - fit.level) * sign  # distance still to go, in the bad direction
        b = fit.trend_per_h * sign
        if gap <= 0:
            continue
        if b <= 0 or b / max(fit.trend_se, 1e-12) < float(fcfg["min_trend_z"]):
            continue
        fast, slow = b + z * fit.trend_se, b - z * fit.trend_se
        p50 = gap / b
        p10 = max(gap - z * fit.resid_sd, 0.0) / fast
        p90 = (gap + z * fit.resid_sd) / slow if slow > 0 else math.inf
        need = gap / horizon
        p_cross = float(1 - stats.norm.cdf((need - b) / max(fit.trend_se, 1e-12)))
        etas[tier] = {
            "threshold": thr,
            "eta_h_p10": round(p10, 2),
            "eta_h_p50": round(p50, 2),
            "eta_h_p90": None if math.isinf(p90) else round(p90, 2),
            "p_cross_within_horizon": round(p_cross, 3),
        }
    curve = {
        "level": round(fit.level, 4),
        "trend_per_h": round(fit.trend_per_h, 5),
        "trend_se": round(fit.trend_se, 5),
        "resid_sd": round(fit.resid_sd, 4),
        "t_last": fit.t_last,
        "horizon_h": horizon,
        "z": round(float(z), 4),
        "etas": etas,
    }
    if not etas:
        return None, curve
    target = min(etas, key=lambda t: etas[t]["eta_h_p50"])
    e = etas[target]
    if e["eta_h_p10"] <= lead_time_h:
        tier = target if target != "stop" else "service_soon"  # a forecast alone never stops a machine
    elif e["eta_h_p50"] <= horizon:
        tier = "monitor"
    else:
        return None, curve
    return (
        EvidenceItem(
            "forecast",
            machine_id,
            component,
            tier,
            _ts(s.t[-1]),
            sensor_id,
            round(float(s.v[-1]), 3),
            {"target_tier": target, **e, "lead_time_h": round(lead_time_h, 1), "trend_per_h": curve["trend_per_h"]},
        ),
        curve,
    )


# ------------------------------------------------------------------ F: service-interval counters
def interval_layer(
    due: list[dict[str, Any]], machine_id: str, now: datetime, cfg: dict[str, Any]
) -> list[EvidenceItem]:
    out = []
    for d in due:
        if d["remaining_h"] < 0:
            tier = str(cfg["overdue_tier"])
        elif d["remaining_h"] <= float(cfg["due_within_h"]):
            tier = str(cfg["due_tier"])
        else:
            continue
        out.append(
            EvidenceItem(
                "interval",
                machine_id,
                "service",
                tier,
                now,
                None,
                d["remaining_h"],
                {
                    "item": d["item"],
                    "remaining_h": d["remaining_h"],
                    "severity_factor": d["severity_factor"],
                    "work": d["work"],
                },
            )
        )
    return out


# ------------------------------------------------------------------ H: fault codes
def fault_layer(
    events: list[dict[str, Any]], machine_id: str, now: datetime, catalogue: dict[str, Any], active_h: float
) -> list[EvidenceItem]:
    out = []
    for ev in events:
        ts = ev["ts"]
        cleared = ev.get("cleared_ts")
        if cleared is not None and cleared <= now:
            continue
        if now - ts > timedelta(hours=active_h):
            continue
        entry = catalogue.get(ev["code"])
        if entry is None:
            continue
        out.append(
            EvidenceItem(
                "fault_code",
                machine_id,
                entry.component,
                entry.severity,
                ts,
                None,
                None,
                {"code": ev["code"], "occurrences": ev.get("occurrences")},
                ev["code"],
            )
        )
    return out
