"""Backward scheduling (§10.6): the latest safe start for a deadline, through the dependency DAG.

For each task the duration at the configured confidence (default p90) is inverted from the deadline;
predecessors must finish before their successors' latest start (critical path, longest chain wins).
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from terrapilot.planning.context import PlanningContext
from terrapilot.planning.estimate import estimate_task

QUANTILE_KEYS = {"p10": "p10_min", "p50": "p50_min", "p90": "p90_min"}


def backschedule(
    ctx: PlanningContext, task_ids: list[str], deadline: datetime, quantile: str | None = None
) -> dict[str, Any]:
    q = quantile or str(ctx.cfg.planning.start_time["quantile_for_deadline"])
    key = QUANTILE_KEYS[q]
    tasks = {tid: ctx.task(tid) for tid in task_ids}
    # include predecessors named in depends_on so the chain is complete
    frontier = list(tasks)
    while frontier:
        tid = frontier.pop()
        for dep in tasks[tid].get("depends_on") or []:
            if dep not in tasks:
                try:
                    tasks[dep] = ctx.task(dep)
                    frontier.append(dep)
                except KeyError:
                    continue
    durations = {tid: estimate_task(ctx, t).estimate.as_dict()[key] for tid, t in tasks.items()}
    successors: dict[str, list[str]] = {tid: [] for tid in tasks}
    for tid, t in tasks.items():
        for dep in t.get("depends_on") or []:
            if dep in successors:
                successors[dep].append(tid)
    latest_finish: dict[str, datetime] = {}

    def lf(tid: str, trail: tuple[str, ...] = ()) -> datetime:
        if tid in latest_finish:
            return latest_finish[tid]
        if tid in trail:
            raise ValueError(f"dependency cycle through {tid}")
        own = min(deadline, _deadline(tasks[tid]) or deadline)
        succ = [lf(s, (*trail, tid)) - timedelta(minutes=durations[s]) for s in successors[tid]]
        latest_finish[tid] = min([own, *succ])
        return latest_finish[tid]

    out = []
    for tid in tasks:
        finish = lf(tid)
        start = finish - timedelta(minutes=durations[tid])
        out.append(
            {
                "task_id": tid,
                "duration_min": round(durations[tid], 1),
                "latest_start": start.isoformat(),
                "latest_finish": finish.isoformat(),
                "feasible": start >= ctx.now,
                "slack_min": round((start - ctx.now).total_seconds() / 60, 1),
            }
        )
    out.sort(key=lambda r: r["latest_start"])
    return {"quantile": q, "deadline": deadline.isoformat(), "tasks": out, "feasible": all(r["feasible"] for r in out)}


def _deadline(task: dict[str, Any]) -> datetime | None:
    d = task.get("deadline")
    return d if isinstance(d, datetime) else None
