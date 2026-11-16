"""Maintenance window recommendation (§10.15.1) and the 7-day availability forecast (§10.15.8).

For each open alert and due service item, pick a window that is before the failure ETA (p10), after parts
arrive, inside technician availability, and preferably in predicted idle / weather-stop / low-priority periods.
Other items due within `bundle_within_h` are bundled into the same stop. Greedy over scored candidate slots:
the objective is production impact (lost task hours × priority) + failure-risk cost.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

import pandas as pd

from terrapilot.maintenance.repair import estimate
from terrapilot.planning.context import PlanningContext
from terrapilot.planning.service_due import service_due
from terrapilot.planning.start_time import _forecast_frame, stop_probabilities

HOURS_PER_DAY = 24.0


@dataclass
class Item:
    """One thing to fix in a window: an open alert or a due service item."""

    key: str
    machine_id: str
    component: str
    tier: str
    hours: float
    deadline: datetime | None  # failure ETA p10 or the tier deadline
    ready_at: datetime  # parts on hand
    parts: list[str] = field(default_factory=list)
    alert_id: str | None = None
    service_item: str | None = None
    cost: dict[str, Any] = field(default_factory=dict)


def _items_for(ctx: PlanningContext, machine_id: str) -> list[Item]:
    out: list[Item] = []
    for a in ctx.open_maintenance_alerts(machine_id):
        if a["state"] in ("in_service",):
            continue
        est = estimate(ctx.cfg, ctx.t, a["component"], a["tier"], machine_id, list(a.get("parts") or []))
        eta = a.get("eta") or {}
        deadline = None
        if eta.get("eta_h_p10") is not None:
            base = pd.Timestamp(eta.get("from") or a["updated_at"]).to_pydatetime()
            deadline = base + timedelta(hours=float(eta["eta_h_p10"]))
        out.append(
            Item(
                key=f"alert:{a['id']}",
                machine_id=machine_id,
                component=a["component"],
                tier=a["tier"],
                hours=float(est["hours_p50"]),
                deadline=deadline,
                ready_at=ctx.now + timedelta(hours=float(est["parts_lead_time_h"])),
                parts=list(a.get("parts") or []),
                alert_id=a["id"],
                cost=est,
            )
        )
    for d in service_due(ctx, machine_id):
        if not (d["due_soon"] or d["overdue"]):
            continue
        est = estimate(ctx.cfg, ctx.t, "service", "minor", machine_id)
        hours = float(d.get("est_h") or est["hours_p50"])
        out.append(
            Item(
                key=f"service:{d['item']}",
                machine_id=machine_id,
                component="service",
                tier="service_soon" if d["overdue"] else "monitor",
                hours=hours,
                deadline=pd.Timestamp(d["eta"]).to_pydatetime(),
                ready_at=ctx.now,
                service_item=d["item"],
                cost={**est, "hours_p50": hours},
            )
        )
    return out


def _technician_slots(ctx: PlanningContext, site_id: str, horizon: datetime) -> list[tuple[datetime, datetime, str]]:
    ts = ctx.t.get("technician_slots")
    if ts.empty:
        return []
    rows = ts[(ts["site_id"] == site_id) & (ts["end"] > pd.Timestamp(ctx.now)) & (ts["start"] < pd.Timestamp(horizon))]
    return [
        (pd.Timestamp(r["start"]).to_pydatetime(), pd.Timestamp(r["end"]).to_pydatetime(), str(r["id"]))
        for r in rows.sort_values("start").to_dict("records")
    ]


def _planned_load(ctx: PlanningContext, machine_id: str, start: datetime, end: datetime) -> float:
    """Lost production if the machine is down over [start, end): planned task hours × priority weight."""
    t = ctx.tasks
    rows = t[
        (t["assigned_machine_id"] == machine_id)
        & (t["planned_end"] > pd.Timestamp(start))
        & (t["planned_start"] < pd.Timestamp(end))
    ]
    total = 0.0
    for r in rows.to_dict("records"):
        overlap = min(pd.Timestamp(r["planned_end"]), pd.Timestamp(end)) - max(
            pd.Timestamp(r["planned_start"]), pd.Timestamp(start)
        )
        hours = max(overlap.total_seconds(), 0) / 3600.0
        weight = 1.0 / max(float(r.get("priority") or 3), 1.0)
        total += hours * (1 + weight)
    return total


def plan_windows(ctx: PlanningContext, machine_ids: list[str] | None = None) -> list[dict[str, Any]]:
    mw = ctx.cfg.planning.maintenance_window
    horizon = ctx.now + timedelta(days=float(mw["horizon_days"]))
    bundle_h = float(mw["bundle_within_h"])
    out = []
    for machine_id in machine_ids or list(ctx.machines.index):
        items = _items_for(ctx, machine_id)
        if not items:
            continue
        site = str(ctx.machines.loc[machine_id, "site_id"])
        slots = _technician_slots(ctx, site, horizon)
        p_stop = stop_probabilities(ctx, _forecast_frame(ctx, site))
        items.sort(key=lambda i: i.deadline or horizon)
        planned: list[dict[str, Any]] = []
        done: set[str] = set()
        for item in items:
            if item.key in done:
                continue
            bundle = [item] + [
                other
                for other in items
                if other.key not in done
                and other.key != item.key
                and abs(((other.deadline or horizon) - (item.deadline or horizon)).total_seconds()) / 3600.0 <= bundle_h
            ]
            hours = sum(b.hours for b in bundle)
            ready = max(b.ready_at for b in bundle)
            deadline = min([b.deadline for b in bundle if b.deadline] or [horizon])
            best = _best_slot(ctx, machine_id, slots, ready, deadline, hours, p_stop, horizon)
            if best is None:
                continue
            start, end, slot_id, score, reasons = best
            for b in bundle:
                done.add(b.key)
            planned.append(
                {
                    "id": f"MW-{machine_id}-{int(start.timestamp())}",
                    "machine_id": machine_id,
                    "alert_ids": [b.alert_id for b in bundle if b.alert_id],
                    "service_items": [b.service_item for b in bundle if b.service_item],
                    "start": start.isoformat(),
                    "end": end.isoformat(),
                    "est_duration": {"hours": round(hours, 1), "items": len(bundle)},
                    "est_cost": {
                        "labour": round(sum(float(b.cost.get("labour_cost", 0)) for b in bundle), 0),
                        "parts": round(sum(float(b.cost.get("parts_cost", 0)) for b in bundle), 0),
                        "currency": ctx.cfg.app.costs["currency"],
                    },
                    "production_impact": {
                        "lost_task_hours": round(_planned_load(ctx, machine_id, start, end), 1),
                        "avoided_vs_run_to_failure": round(
                            sum(float(b.cost.get("downtime_cost_per_h", 0)) * b.hours for b in bundle), 0
                        ),
                    },
                    "technician_slot_id": slot_id,
                    "status": "planned",
                    "rationale": {
                        "score": round(score, 2),
                        "reasons": reasons,
                        "deadline": deadline.isoformat(),
                        "parts_ready": ready.isoformat(),
                    },
                }
            )
        out += planned
    return out


def _best_slot(
    ctx: PlanningContext,
    machine_id: str,
    slots: list[tuple[datetime, datetime, str]],
    ready: datetime,
    deadline: datetime,
    hours: float,
    p_stop: pd.Series,
    horizon: datetime,
) -> tuple[datetime, datetime, str | None, float, list[str]] | None:
    """Lowest production impact among technician slots that fit before the deadline; weather stops are free time."""
    best: tuple[datetime, datetime, str | None, float, list[str]] | None = None
    candidates: list[tuple[datetime, datetime, str | None]] = []
    for s_start, s_end, slot_id in slots:
        start = max(s_start, ready)
        if start + timedelta(hours=hours) <= min(s_end, deadline):
            candidates.append((start, start + timedelta(hours=hours), slot_id))
    if not candidates and ready + timedelta(hours=hours) <= min(deadline, horizon):
        candidates.append((ready, ready + timedelta(hours=hours), None))  # no technician slot: still propose a time
    for start, end, cand_slot in candidates:
        lost = _planned_load(ctx, machine_id, start, end)
        weather = float(p_stop.loc[pd.Timestamp(start).floor("h") : pd.Timestamp(end)].mean()) if len(p_stop) else 0.0
        urgency = max(0.0, (deadline - end).total_seconds() / 3600.0)
        score = lost * (1 - weather) + 0.01 * urgency
        reasons = []
        if weather > 0.3:
            reasons.append("weather_stop_likely")
        if lost == 0:
            reasons.append("no_planned_work")
        if cand_slot:
            reasons.append("technician_available")
        if best is None or score < best[3]:
            best = (start, end, cand_slot, score, reasons)
    return best


def availability_forecast(ctx: PlanningContext, site_id: str | None = None, days: int = 7) -> list[dict[str, Any]]:
    """P(available) per machine per day (§10.15.8): planned windows + open-alert failure risk + charging."""
    from terrapilot.maintenance.advanced import risk_index

    machines = ctx.machines
    ids = [m for m in machines.index if site_id is None or machines.loc[m, "site_id"] == site_id]
    windows = {w["machine_id"]: w for w in plan_windows(ctx, ids)}
    shift_h = float(ctx.cfg.app.site_calendar["shift"]["length_h"])
    out = []
    for mid in ids:
        alerts = ctx.open_maintenance_alerts(str(mid))
        components = {a["component"] for a in alerts} or {"engine"}
        p_fail_day = 1 - math.prod(
            1 - risk_index(ctx.cfg, str(mid), c, ctx.t, ctx.now, HOURS_PER_DAY)["p_fail"] for c in components
        )
        w = windows.get(str(mid))
        for d in range(days):
            day = (ctx.now + timedelta(days=d)).date()
            planned_h = 0.0
            if w is not None and pd.Timestamp(w["start"]).date() == day:
                planned_h = float(w["est_duration"]["hours"])
            risk_h = p_fail_day * shift_h
            available = max(0.0, 1 - (planned_h + risk_h) / shift_h)
            out.append(
                {
                    "date": day.isoformat(),
                    "machine_id": str(mid),
                    "p_available": round(min(1.0, available), 3),
                    "planned_downtime_h": round(planned_h, 1),
                    "risk_downtime_h": round(risk_h, 2),
                }
            )
    return out
