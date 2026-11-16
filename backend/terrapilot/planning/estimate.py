"""Task duration estimates for any start time (§10.6), plus the `usual_duration` kNN baseline (§10.14 step 5).

Covariates are averaged over the expected work window [t, t + D]; because the window depends on D, the
estimate is iterated to a fixed point (`planning.start_time.fixed_point_iterations`).
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

import numpy as np
import pandas as pd

from terrapilot.ml.features import model_cfg, planned_minutes
from terrapilot.ml.task_duration import Estimate, ModelNotTrainedError, load_model, physics_baseline_min
from terrapilot.planning.context import PlanningContext


@dataclass
class TaskEstimate:
    start: datetime
    estimate: Estimate
    row: dict[str, Any]
    source: str  # model | plan

    def as_dict(self) -> dict[str, Any]:
        return {"start": self.start.isoformat(), "source": self.source, **self.estimate.as_dict()}


def estimate_starts(
    ctx: PlanningContext,
    task: dict[str, Any],
    starts: list[datetime],
    overrides: list[dict[str, Any]] | None = None,
    machine_id: str | None = None,
    explain: bool = True,
) -> list[TaskEstimate]:
    """Estimate the task for each candidate start (batched through the fixed-point iterations)."""
    iters = int(ctx.cfg.planning.start_time["fixed_point_iterations"])
    fcfg = model_cfg(ctx.cfg, "task_duration")["factors"]
    qty = float(task["quantity"])
    remaining = max(qty - float(task.get("progress_qty") or 0.0), 0.0) if task.get("status") == "in_progress" else qty
    ovs = overrides or [{} for _ in starts]
    try:
        model = load_model(ctx.cfg, ctx.data_dir)
    except ModelNotTrainedError:
        return [_plan_estimate(ctx, task, s) for s in starts]
    durations = [planned_minutes(task)] * len(starts)
    rows: list[dict[str, Any]] = []
    ests: list[Estimate] = []
    for it in range(max(iters, 1)):
        rows = [
            ctx.features.for_task(task, s, d, ctx.now, overrides=o, machine_id=machine_id)
            for s, d, o in zip(starts, durations, ovs, strict=True)
        ]
        last = it == max(iters, 1) - 1
        ests = model.predict(
            rows,
            [remaining] * len(starts),
            explain=explain and last,
            top_n=int(fcfg["top_n"]),
            min_abs_min=float(fcfg["min_abs_min"]),
            exclude=frozenset(fcfg.get("exclude", [])),
        )
        durations = [e.p50 for e in ests]
    cap = ctx.features.capacity_m3(str(task["machine_class"]))
    base = physics_baseline_min(ctx.cfg, {**task, "quantity": remaining}, cap)
    out = []
    for s, e, r in zip(starts, ests, rows, strict=True):
        e.baseline_min = base
        out.append(TaskEstimate(s, e, r, "model"))
    return out


def estimate_task(ctx: PlanningContext, task: dict[str, Any], start: datetime | None = None) -> TaskEstimate:
    s = start or _default_start(ctx, task)
    return estimate_starts(ctx, task, [s])[0]


def _default_start(ctx: PlanningContext, task: dict[str, Any]) -> datetime:
    if task.get("actual_start") is not None and task.get("status") == "in_progress":
        return ctx.now
    ps = task.get("planned_start")
    return max(pd.Timestamp(ps).to_pydatetime(), ctx.now) if ps is not None else ctx.now


def _plan_estimate(ctx: PlanningContext, task: dict[str, Any], start: datetime) -> TaskEstimate:
    hw = float(model_cfg(ctx.cfg, "live_etc")["plan_prior_log_half_width"])
    d = planned_minutes(task)
    return TaskEstimate(start, Estimate(d * math.exp(-hw), d, d * math.exp(hw)), {}, "plan")


# ------------------------------------------------------------------ usual duration (kNN)
NUMERIC_KNN = ["log_quantity", "depth_m", "haul_km"]


def usual_duration(ctx: PlanningContext, task: dict[str, Any]) -> dict[str, Any] | None:
    """Median per-unit duration of the k most similar completed tasks (same type/class, nearest in
    size/depth/haul, same soil preferred), scaled to this task's quantity."""
    cfg = ctx.cfg.planning.start_time["usual_duration"]
    k, lookback = int(cfg["k"]), int(cfg["lookback_days"])
    t = ctx.tasks
    hist = t[
        (t["status"] == "completed")
        & t["duration_min"].notna()
        & (t["type"] == task["type"])
        & (t["machine_class"] == task["machine_class"])
        & (t["actual_start"] >= pd.Timestamp(ctx.now - timedelta(days=lookback)))
        & (t["quantity"] > 0)
    ].copy()
    if hist.empty:
        return None
    zones = ctx.features.zones
    hist["soil"] = hist["zone_id"].map(lambda z: zones.loc[z, "soil"] if z in zones.index else None)
    hist["log_quantity"] = np.log(hist["quantity"])
    hist["depth_m"] = hist["depth_m"].fillna(0.0)
    hist["haul_km"] = hist["haul_distance_m"].fillna(0.0) / 1000
    q = {
        "log_quantity": math.log(float(task["quantity"])),
        "depth_m": float(task.get("depth_m") or 0.0),
        "haul_km": float(task.get("haul_distance_m") or 0.0) / 1000,
    }
    X = hist[NUMERIC_KNN].to_numpy(dtype=float)
    sd = X.std(axis=0)
    sd[sd == 0] = 1.0
    d = np.sqrt((((X - np.array([q[c] for c in NUMERIC_KNN])) / sd) ** 2).sum(axis=1))
    soil = ctx.features.soil_of(task.get("zone_id"))
    d = d + np.where(hist["soil"].to_numpy() == soil, 0.0, 1.0)  # different soil counts as one SD away
    nn = hist.iloc[np.argsort(d)[:k]]
    per_unit = (nn["duration_min"] / nn["quantity"]).to_numpy()
    qty = float(task["quantity"])
    return {
        "p50_min": round(float(np.median(per_unit)) * qty, 1),
        "p25_min": round(float(np.quantile(per_unit, 0.25)) * qty, 1),
        "p75_min": round(float(np.quantile(per_unit, 0.75)) * qty, 1),
        "neighbours": len(nn),
        "method": cfg["method"],
    }
