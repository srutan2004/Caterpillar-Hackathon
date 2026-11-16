"""Shift pacing (§10.3.2): actual cumulative output vs a benchmark curve.

The benchmark spreads the planned work (in planned minutes) across the shift's working time, so breaks are
flat. Output from tasks with different units is compared as "share of planned work done".
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

import pandas as pd

from terrapilot.planning.context import PlanningContext


def _work_minutes(ctx: PlanningContext, a: datetime, b: datetime) -> float:
    if b <= a:
        return 0.0
    total = (b - a).total_seconds() / 60
    for b0, b1 in ctx.breaks(a):
        total -= max(0.0, (min(b1, b) - max(b0, a)).total_seconds() / 60)
    return max(total, 0.0)


def pacing(ctx: PlanningContext, tasks: list[dict[str, Any]], live_progress: dict[str, float]) -> dict[str, Any]:
    start, end = ctx.shift_bounds()
    shift_work = _work_minutes(ctx, start, end)
    planned = {t["id"]: max(_planned_min(t), 1e-6) for t in tasks}
    total_plan = sum(planned.values()) or 1.0
    step = timedelta(minutes=float(ctx.cfg.planning.shift_view["pacing_step_min"]))
    bench, t = [], start
    while t <= end:
        frac = min(1.0, _work_minutes(ctx, start, t) / shift_work) if shift_work else 0.0
        bench.append({"ts": t.isoformat(), "pct": round(100 * frac, 1)})
        t += step
    # actual: cumulative quantity from today's cycles (history) + live progress for running tasks
    ids = [t["id"] for t in tasks]
    actual_pts: list[dict[str, Any]] = [{"ts": start.isoformat(), "pct": 0.0}]
    done_share = 0.0
    cyc = _cycles_today(ctx, ids, start, min(ctx.now, end))
    if not cyc.empty:
        # each logged cycle carries an equal share of the progress its task has reached so far
        qty = {t["id"]: float(t["quantity"]) for t in tasks}
        prog = {t["id"]: float(t.get("progress_qty") or 0.0) for t in tasks}
        share = []
        for tid, g in cyc.sort_values("ts").groupby("task_id"):
            task_share = (prog[tid] / qty[tid] if qty[tid] else 0.0) * planned[tid] / total_plan
            share.append(pd.Series(task_share / len(g), index=g["ts"]))
        s = pd.concat(share).sort_index().cumsum()
        for ts, v in s.resample(step).last().ffill().items():
            actual_pts.append({"ts": pd.Timestamp(ts).isoformat(), "pct": round(100 * float(v), 1)})
        done_share = float(s.iloc[-1])
    live_share = sum(
        (live_progress.get(t["id"], 0.0) / float(t["quantity"]) if float(t["quantity"]) else 0.0)
        * planned[t["id"]]
        / total_plan
        for t in tasks
        if t["id"] in live_progress
    )
    done_share = max(
        done_share, live_share + sum(planned[t["id"]] / total_plan for t in tasks if t.get("status") == "completed")
    )
    now_c = min(max(ctx.now, start), end)
    actual_pts.append({"ts": now_c.isoformat(), "pct": round(100 * done_share, 1)})
    expected_now = min(1.0, _work_minutes(ctx, start, now_c) / shift_work) if shift_work else 0.0
    gap = done_share - expected_now
    return {
        "shift_start": start.isoformat(),
        "shift_end": end.isoformat(),
        "benchmark": bench,
        "actual": actual_pts,
        "done_pct": round(100 * done_share, 1),
        "expected_pct": round(100 * expected_now, 1),
        "gap_pct": round(100 * gap, 1),
        "planned_minutes": round(total_plan, 0),
    }


def _planned_min(t: dict[str, Any]) -> float:
    ps, pe = t.get("planned_start"), t.get("planned_end")
    if ps is None or pe is None:
        return 60.0
    return float((pd.Timestamp(pe) - pd.Timestamp(ps)).total_seconds()) / 60


def _cycles_today(ctx: PlanningContext, task_ids: list[str], a: datetime, b: datetime) -> pd.DataFrame:
    if not task_ids:
        return pd.DataFrame()
    if ctx.t.source == "db":
        return ctx.t.get(
            "cycles",
            "SELECT ts, task_id, payload_t FROM cycles WHERE task_id IN :ids AND ts >= :a AND ts <= :b",
            {"ids": tuple(task_ids), "a": a, "b": b},
        )
    c = ctx.t.get("cycles")
    return c[c["task_id"].isin(task_ids) & (c["ts"] >= pd.Timestamp(a)) & (c["ts"] <= pd.Timestamp(b))]
