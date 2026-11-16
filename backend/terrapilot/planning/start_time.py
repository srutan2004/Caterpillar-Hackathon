"""Optimal job start-time recommendation (§10.14, P0 single task).

For each candidate start t on a grid over the horizon:
  duration  D(t)  — task_duration with covariates averaged over [t, t + D] (fixed point), p10/p50/p90
  pre-work        — charge/refuel needed so SoC(t) − E_p90 ≥ floor (charging while waiting is free), or a
                    mid-task charge stop when that is quicker
  stop risk       — E[delay] from P(weather hard stop) per hour, using forecast spread
  safety risk     — ground (moisture over field capacity), visibility, fatigue late in the shift
  maintenance     — open alerts forecast to cross service_soon during the window
Hard constraints: deadline at `quantile_for_deadline`, SoC floor, maintenance windows, no start into a likely
hard stop, readiness ≥ caution. Score J(t) (weights in config) picks t*; "usual" is the kNN baseline.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

import numpy as np
import pandas as pd
from scipy import stats

from terrapilot.core.refs import load_ref_cached
from terrapilot.ml.explain import factor_deltas
from terrapilot.planning.context import PlanningContext
from terrapilot.planning.energy import charge_minutes, charger_options, energy_estimate
from terrapilot.planning.estimate import TaskEstimate, estimate_starts, usual_duration
from terrapilot.planning.readiness import readiness

MINUTES_PER_HOUR = 60.0
QKEY = {"p10": "p10", "p50": "p50", "p90": "p90"}


@dataclass
class Candidate:
    start: datetime
    est: TaskEstimate
    prework_min: float = 0.0
    midstop_min: float = 0.0
    charge_before: dict[str, Any] | None = None
    stop_delay_min: float = 0.0
    p_stop_at_start: float = 0.0
    safety_risk: float = 0.0
    maint_conflict: list[dict[str, Any]] = field(default_factory=list)
    violations: list[str] = field(default_factory=list)
    score: float = math.inf

    def d(self, q: str) -> float:
        e = self.est.estimate
        base = {"p10": e.p10, "p50": e.p50, "p90": e.p90}[q]
        return base + self.prework_min + self.midstop_min

    @property
    def feasible(self) -> bool:
        return not self.violations

    def finish(self, q: str) -> datetime:
        return self.start + timedelta(minutes=self.d(q))


def _grid(ctx: PlanningContext, task: dict[str, Any]) -> list[datetime]:
    st = ctx.cfg.planning.start_time
    step = timedelta(minutes=float(st["step_min"]))
    horizon = timedelta(hours=float(st["horizon_h"]))
    t0 = pd.Timestamp(ctx.now).ceil(f"{int(st['step_min'])}min").to_pydatetime()
    earliest = _deps_done(ctx, task)
    out, t = [], t0
    while t <= ctx.now + horizon:
        if t >= earliest and (not st["candidates"]["within_shift"] or _in_shift(ctx, t)):
            out.append(t)
        t += step
    return out


def _in_shift(ctx: PlanningContext, t: datetime) -> bool:
    start, end = ctx.shift_bounds(t)
    if not (start <= t < end):
        return False
    return not any(b0 <= t < b1 for b0, b1 in ctx.breaks(t))


def _deps_done(ctx: PlanningContext, task: dict[str, Any]) -> datetime:
    latest = ctx.now
    for dep in task.get("depends_on") or []:
        try:
            d = ctx.task(dep)
        except KeyError:
            continue
        if d.get("status") == "completed":
            continue
        from terrapilot.planning.estimate import estimate_task

        est = estimate_task(ctx, d)
        latest = max(latest, est.start + timedelta(minutes=est.estimate.p50))
    return latest


# ------------------------------------------------------------------ risks
def _forecast_frame(ctx: PlanningContext, site: str) -> pd.DataFrame:
    fc = ctx.t.get("weather_forecast")
    fc = fc[(fc["site_id"] == site) & (fc["issued_at"] <= pd.Timestamp(ctx.now))]
    if fc.empty:
        return pd.DataFrame()
    latest = fc.sort_values("issued_at").groupby(["valid_at", "var"]).tail(1)
    mean = latest.pivot_table(index="valid_at", columns="var", values="value", aggfunc="last")
    spread = latest.pivot_table(index="valid_at", columns="var", values="spread", aggfunc="last").add_suffix("_spread")
    return mean.join(spread).sort_index()


def stop_probabilities(ctx: PlanningContext, fc: pd.DataFrame) -> pd.Series:
    """P(hard stop) per forecast hour: gust, rain or lightning beyond the site thresholds (independent)."""
    sr = ctx.cfg.planning.start_time["stop_risk"]
    hs = load_ref_cached(ctx.cfg.root, sr["hard_stop_ref"])
    ms = sr["min_spread"]
    if fc.empty:
        return pd.Series(dtype=float)

    def col(name: str) -> pd.Series:
        return fc[name] if name in fc else pd.Series(np.nan, index=fc.index)

    def sd(name: str) -> pd.Series:
        return np.maximum(col(f"{name}_spread").fillna(0.0), float(ms[name]))

    p_gust = 1 - stats.norm.cdf((hs["gust_ms_gt"] - col("gust_ms")) / sd("gust_ms"))
    p_rain = 1 - stats.norm.cdf((hs["rain_mm_h_gt"] - col("rain_mm")) / sd("rain_mm"))
    p_light = stats.norm.cdf((hs["lightning_km_lt"] - col("lightning_km")) / sd("lightning_km"))
    p = 1 - (1 - np.nan_to_num(p_gust)) * (1 - np.nan_to_num(p_rain)) * (1 - np.nan_to_num(p_light))
    return pd.Series(p, index=fc.index)


def _window_stop(ctx: PlanningContext, p_stop: pd.Series, t: datetime, minutes: float) -> tuple[float, float]:
    if p_stop.empty:
        return 0.0, 0.0
    sr = ctx.cfg.planning.start_time["stop_risk"]
    resume = float(load_ref_cached(ctx.cfg.root, sr["resume_after_clear_ref"]))
    t0, t1 = pd.Timestamp(t).floor("h"), pd.Timestamp(t) + pd.Timedelta(minutes=minutes)
    w = p_stop.loc[t0:t1]
    delay = float((w * (MINUTES_PER_HOUR + resume)).sum()) if len(w) else 0.0
    at_start = float(p_stop.loc[: pd.Timestamp(t)].iloc[-1]) if len(p_stop.loc[: pd.Timestamp(t)]) else 0.0
    return delay, at_start


def _safety(ctx: PlanningContext, c: Candidate) -> float:
    sr = ctx.cfg.planning.start_time["safety_risk"]
    w = sr["weights"]
    row = c.est.row
    ground = min(1.0, float(row.get("moisture_excess") or 0.0) / float(sr["moisture_excess_full"]))
    vis = float(row.get("visibility_low") or 0.0)
    shift_start, _ = ctx.shift_bounds(c.start)
    hours_at_end = (c.finish("p50") - shift_start).total_seconds() / 3600
    length = float(ctx.cfg.app.site_calendar["shift"]["length_h"])
    fatigue = max(0.0, hours_at_end - float(sr["fatigue_after_h"])) / max(length - float(sr["fatigue_after_h"]), 1e-6)
    return float(w["ground"]) * ground + float(w["visibility"]) * vis + float(w["fatigue"]) * min(1.0, fatigue)


# ------------------------------------------------------------------ energy pre-work
def _energy_plan(ctx: PlanningContext, c: Candidate, machine_id: str, energy_est: dict[str, Any]) -> None:
    """Charge while waiting (free), else before start (pre-work) or at a mid-task stop (whichever is quicker)."""
    if energy_est.get("can_finish") is None:
        return
    raw = ctx.manifest_raw(machine_id)
    energy = raw.get("energy") or {}
    st = ctx.cfg.planning.start_time
    if "soc_now" not in energy_est:  # fuel: refuel when below the threshold or short
        if energy_est.get("refuel_min"):
            c.prework_min = float(energy_est["refuel_min"])
            c.charge_before = {"kind": "refuel", "minutes": c.prework_min}
        return
    stations = charger_options(ctx, machine_id, energy)
    if not stations:
        if not energy_est["can_finish"]:
            c.violations.append("energy")
        return
    best = max(stations, key=lambda s: s["power_kw"])
    kw = float(best["power_kw"])
    floor, need = float(energy_est["floor"]), float(energy_est["need_frac"])
    soc = float(energy_est["soc_now"])
    target = min(1.0, float(energy_est["charge_target_soc"]))
    if soc - need >= floor:
        return
    wait_min = max((c.start - ctx.now).total_seconds() / 60, 0.0)
    soc_at_t = soc
    if st["energy"]["charge_while_waiting"] and wait_min > 0:
        soc_at_t = _soc_after(energy, soc, wait_min, kw, target)
    if soc_at_t - need >= floor:
        c.charge_before = {
            "kind": "charge",
            "station": best,
            "from_soc": round(soc, 3),
            "target_soc": round(max(soc_at_t, floor + need), 3),
            "minutes": round(charge_minutes(energy, soc, max(soc_at_t, floor + need), kw), 0),
            "during_wait": True,
        }
        return
    pre = charge_minutes(energy, soc_at_t, target, kw)
    short = floor + need - soc_at_t
    mid = charge_minutes(energy, floor, floor + short, kw) + float(st["energy"]["mid_task_charge_overhead_min"])
    if pre <= mid:
        c.prework_min = pre
        c.charge_before = {
            "kind": "charge",
            "station": best,
            "from_soc": round(soc_at_t, 3),
            "target_soc": round(target, 3),
            "minutes": round(pre + (charge_minutes(energy, soc, soc_at_t, kw) if wait_min > 0 else 0.0), 0),
            "during_wait": False,
        }
    else:
        c.midstop_min = mid
        c.charge_before = {"kind": "mid_task_charge", "station": best, "minutes": round(mid, 0)}


def _soc_after(energy: dict[str, Any], soc: float, minutes: float, kw: float, cap_soc: float) -> float:
    lo, hi = soc, cap_soc
    if charge_minutes(energy, soc, hi, kw) <= minutes:
        return hi
    for _ in range(30):  # invert the taper curve by bisection
        mid = (lo + hi) / 2
        if charge_minutes(energy, soc, mid, kw) <= minutes:
            lo = mid
        else:
            hi = mid
    return lo


# ------------------------------------------------------------------ maintenance conflicts
def _maint_conflicts(ctx: PlanningContext, machine_id: str, c: Candidate) -> list[dict[str, Any]]:
    out = []
    end = c.finish("p90")
    for a in ctx.open_maintenance_alerts(machine_id):
        eta = a.get("eta") or {}
        tier = a.get("tier")
        opened = a.get("updated_at") or a.get("opened_at")
        crossing = None
        if eta.get("eta_h_p10") is not None and opened is not None:
            crossing = pd.Timestamp(eta["from"] if eta.get("from") else opened).to_pydatetime() + timedelta(
                hours=float(eta["eta_h_p10"])
            )
        mid_task = crossing is not None and c.start <= crossing <= end
        if tier == "service_soon" or mid_task:
            out.append(
                {
                    "alert_id": a["id"],
                    "component": a["component"],
                    "tier": tier,
                    "sensor_ids": a.get("sensor_ids") or [],
                    "crossing": None if crossing is None else crossing.isoformat(),
                    "mid_task": mid_task,
                }
            )
    return out


def _maintenance_windows(ctx: PlanningContext, machine_id: str) -> list[tuple[datetime, datetime]]:
    mw = ctx.t.get("maintenance_windows")
    if mw.empty:
        return []
    rows = mw[(mw["machine_id"] == machine_id) & (mw["status"].isin(["planned", "scheduled"]))]
    return [
        (pd.Timestamp(r["start"]).to_pydatetime(), pd.Timestamp(r["end"]).to_pydatetime())
        for r in rows.to_dict("records")
    ]


# ------------------------------------------------------------------ main
def recommend(ctx: PlanningContext, task_id: str) -> dict[str, Any]:
    st = ctx.cfg.planning.start_time
    obj = st["objective"]
    task = ctx.task(task_id)
    machine_id = task.get("assigned_machine_id")
    if not machine_id:
        raise ValueError("task has no assigned machine")
    grid = _grid(ctx, task)
    now_start = max(pd.Timestamp(ctx.now).to_pydatetime(), _deps_done(ctx, task))
    starts = sorted({now_start, *grid})
    ests = estimate_starts(ctx, task, starts, machine_id=machine_id)
    fc = _forecast_frame(ctx, str(task["site_id"]))
    p_stop = stop_probabilities(ctx, fc)
    q = str(st["quantile_for_deadline"])
    deadline = task.get("deadline")
    windows = _maintenance_windows(ctx, machine_id)
    rd = readiness(ctx, machine_id, task.get("assigned_operator_id"), task)
    caution = float(ctx.cfg.planning.readiness["bands"]["caution"])
    base_energy = energy_estimate(ctx, task, machine_id)
    cands: list[Candidate] = []
    for e in ests:
        c = Candidate(e.start, e)
        _energy_plan(ctx, c, machine_id, base_energy)
        c.stop_delay_min, c.p_stop_at_start = _window_stop(ctx, p_stop, c.start, c.d("p50"))
        c.safety_risk = _safety(ctx, c)
        c.maint_conflict = _maint_conflicts(ctx, machine_id, c)
        if deadline is not None and c.finish(q) > deadline:
            c.violations.append("deadline")
        if c.p_stop_at_start > float(st["stop_risk"]["block_start_if_p_above"]):
            c.violations.append("weather")
        if any(w0 < c.finish("p90") and c.start < w1 for w0, w1 in windows):
            c.violations.append("maintenance_window")
        if rd["score"] < caution or rd["blocks_start"]:
            c.violations.append("readiness")
        maint_pen = (
            float(st["maintenance_conflict"]["penalty_min"]) if any(m["mid_task"] for m in c.maint_conflict) else 0.0
        )
        c.score = (
            float(obj["w_p50"]) * c.d("p50")
            + float(obj["w_spread"]) * (c.d("p90") - c.d("p50"))
            + float(obj["w_stop_risk"]) * c.stop_delay_min
            + float(obj["w_safety_risk"]) * c.safety_risk * float(st["safety_risk"]["minutes_per_unit"])
            + float(obj["w_wait"]) * max((c.start - ctx.now).total_seconds() / 60, 0.0)
            + maint_pen
        )
        cands.append(c)
    now_c = next(c for c in cands if c.start == now_start)
    feasible = [c for c in cands if c.feasible]
    best = min(feasible, key=lambda c: c.score) if feasible else min(cands, key=lambda c: (len(c.violations), c.score))
    usual = usual_duration(ctx, task)
    saving_now = now_c.finish("p50") - best.finish("p50") if best is not now_c else timedelta(0)
    saving_now_min = round(saving_now.total_seconds() / 60, 1)
    saving_vs_usual = round(usual["p50_min"] - best.d("p50"), 1) if usual else None
    min_saving = float(st["min_saving_to_recommend_min"])
    duration_saving_min = round(now_c.d("p50") - best.d("p50"), 1)
    recommend_change = best is not now_c and duration_saving_min >= min_saving
    chosen = best if recommend_change or not now_c.feasible else now_c
    fcfg = ctx.cfg.models["models"]["task_duration"]["factors"]
    why = []
    if chosen is not now_c and chosen.est.estimate.contrib is not None and now_c.est.estimate.contrib is not None:
        feats = list(ctx.features.mcfg["features"])
        why = [
            f.as_dict()
            for f in factor_deltas(
                feats,
                now_c.est.estimate.contrib,
                chosen.est.estimate.contrib,
                chosen.est.estimate.p50,
                float(fcfg["min_abs_min"]),
                int(fcfg["top_n"]) + 1,
                frozenset(fcfg.get("exclude", [])),
            )
        ]
    energy_delta = (now_c.prework_min + now_c.midstop_min) - (chosen.prework_min + chosen.midstop_min)
    if abs(energy_delta) >= float(fcfg["min_abs_min"]):
        why.append(
            {
                "feature": "energy_prework",
                "key": "factor.energy_prework",
                "minutes": round(-energy_delta, 1),
                "value": None,
            }
        )
    return {
        "task_id": task_id,
        "machine_id": machine_id,
        "computed_at": ctx.now.isoformat(),
        "recommended_start": chosen.start.isoformat(),
        "recommend_change": recommend_change,
        "feasible": chosen.feasible,
        "binding": chosen.violations or _binding(cands, chosen),
        "duration": _dur(chosen),
        "now": {
            "start": now_c.start.isoformat(),
            **_dur(now_c),
            "feasible": now_c.feasible,
            "violations": now_c.violations,
        },
        "usual_duration": usual,
        "finish_delta_vs_now_min": -saving_now_min,  # >0: finishes later than starting now
        "duration_saving_vs_now_min": duration_saving_min,
        "saving_vs_usual_min": saving_vs_usual,
        "preconditions": _preconditions(ctx, chosen, machine_id),
        "factors": why,
        "energy": {
            k: base_energy.get(k)
            for k in ("unit", "p10", "p50", "p90", "can_finish", "soc_now", "fuel_pct_now", "margin")
        },
        "readiness": {"score": rd["score"], "band": rd["band"]},
        "curve": [_point(c, ctx) for c in _thin(cands, int(st["curve_points_max"]))],
        "deadline": None if deadline is None else deadline.isoformat(),
        "quantile_for_deadline": q,
        "explanation": {
            "source": "template",
            "key": "plan.start_time.summary" if recommend_change else "plan.start_time.keep",
        },
    }


def _dur(c: Candidate) -> dict[str, Any]:
    return {
        "p10_min": round(c.d("p10"), 1),
        "p50_min": round(c.d("p50"), 1),
        "p90_min": round(c.d("p90"), 1),
        "work_p50_min": round(c.est.estimate.p50, 1),
        "prework_min": round(c.prework_min, 1),
        "midstop_min": round(c.midstop_min, 1),
        "stop_delay_min": round(c.stop_delay_min, 1),
        "safety_risk": round(c.safety_risk, 3),
        "finish_p50": c.finish("p50").isoformat(),
        "finish_p90": c.finish("p90").isoformat(),
        "score": round(c.score, 2),
    }


def _point(c: Candidate, ctx: PlanningContext) -> dict[str, Any]:
    return {"start": c.start.isoformat(), **_dur(c), "feasible": c.feasible, "violations": c.violations}


def _thin(cands: list[Candidate], n: int) -> list[Candidate]:
    if len(cands) <= n:
        return cands
    idx = np.linspace(0, len(cands) - 1, n).round().astype(int)
    return [cands[i] for i in sorted(set(idx))]


def _binding(cands: list[Candidate], chosen: Candidate) -> list[str]:
    """Constraints that rule out the candidates that would otherwise score better."""
    better = [c for c in cands if c.score < chosen.score and c.violations]
    return sorted({v for c in better for v in c.violations})


def _preconditions(ctx: PlanningContext, c: Candidate, machine_id: str) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    cb = c.charge_before
    if cb and cb["kind"] == "charge":
        start = c.start - timedelta(minutes=float(cb["minutes"])) if cb.get("during_wait") else c.start
        out.append(
            {
                "kind": "charge",
                "key": "precondition.charge",
                "target_soc": cb["target_soc"],
                "minutes": cb["minutes"],
                "station_id": cb["station"]["station_id"],
                "station_kind": cb["station"]["kind"],
                "start": max(start, ctx.now).isoformat(),
                "end": (max(start, ctx.now) + timedelta(minutes=float(cb["minutes"]))).isoformat(),
                "during": _during(ctx, max(start, ctx.now), float(cb["minutes"])),
            }
        )
    elif cb and cb["kind"] == "mid_task_charge":
        out.append(
            {
                "kind": "mid_task_charge",
                "key": "precondition.mid_task_charge",
                "minutes": cb["minutes"],
                "station_id": cb["station"]["station_id"],
            }
        )
    elif cb and cb["kind"] == "refuel":
        out.append({"kind": "refuel", "key": "precondition.refuel", "minutes": cb["minutes"]})
    if ctx.cfg.planning.start_time["maintenance_conflict"]["precheck_before_start"]:
        slot = _technician_slot(ctx, machine_id, c.start)
        for m in c.maint_conflict:
            out.append(
                {
                    "kind": "maintenance_check",
                    "key": "precondition.maintenance_check",
                    "alert_id": m["alert_id"],
                    "component": m["component"],
                    "sensor_ids": m["sensor_ids"],
                    "tier": m["tier"],
                    "mid_task": m["mid_task"],
                    "technician_slot": slot,
                }
            )
    return out


def _during(ctx: PlanningContext, start: datetime, minutes: float) -> str | None:
    """Name the shift activity the precondition overlaps (pre-shift toolbox talk or a break)."""
    shift_start, _ = ctx.shift_bounds(start)
    end = start + timedelta(minutes=minutes)
    if (
        start < shift_start + timedelta(minutes=minutes)
        and end <= shift_start + timedelta(hours=1)
        and start <= shift_start
    ):
        return "toolbox_talk"
    for b0, b1 in ctx.breaks(start):
        if start < b1 and end > b0:
            return "break"
    return None


def _technician_slot(ctx: PlanningContext, machine_id: str, before: datetime) -> dict[str, Any] | None:
    ts = ctx.t.get("technician_slots")
    if ts.empty:
        return None
    site = str(ctx.machines.loc[machine_id, "site_id"])
    rows = ts[(ts["site_id"] == site) & (ts["end"] > pd.Timestamp(ctx.now))].sort_values("start")
    if rows.empty:
        return None
    r = rows.iloc[0]
    return {
        "slot_id": r["id"],
        "technician_id": r["technician_id"],
        "start": pd.Timestamp(r["start"]).isoformat(),
        "end": pd.Timestamp(r["end"]).isoformat(),
    }
