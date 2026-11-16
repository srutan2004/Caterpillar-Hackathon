"""Service-due countdowns (§10.15.9) from the severity-adjusted interval counters (§10.13 layer F)."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from terrapilot.core.refs import load_ref_cached
from terrapilot.planning.context import PlanningContext


def service_due(ctx: PlanningContext, machine_id: str) -> list[dict[str, Any]]:
    sd = ctx.cfg.planning.service_due
    hours_per_day = float(load_ref_cached(ctx.cfg.root, sd["hours_per_day_ref"]))
    warn = float(sd["warn_within_h"])
    counters = ctx.t.get("service_counters")
    rows = counters[counters["machine_id"] == machine_id]
    hour_meter = float(ctx.machines.loc[machine_id, "hour_meter"])
    items = {i["item"]: i for i in ctx.cfg.service_intervals.get(ctx.manifest_id(machine_id), [])}
    out = []
    for r in rows.to_dict("records"):
        sev = float(r["severity_factor"] or 1.0)
        remaining = (float(r["due_hours"]) - hour_meter) / sev
        spec = items.get(r["item"], {})
        out.append(
            {
                "machine_id": machine_id,
                "item": r["item"],
                "remaining_h": round(remaining, 1),
                "severity_factor": round(sev, 2),
                "due_hours": r["due_hours"],
                "eta": (ctx.now + timedelta(days=max(remaining, 0.0) / hours_per_day)).isoformat(),
                "overdue": remaining < 0,
                "due_soon": remaining <= warn,
                "work": spec.get("work", []),
                "est_h": spec.get("est_h"),
            }
        )
    return sorted(out, key=lambda x: x["remaining_h"])
