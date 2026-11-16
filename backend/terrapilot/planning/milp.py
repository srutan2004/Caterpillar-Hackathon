"""MILP planners (PuLP): the battery charge plan (§10.9) and the day plan (§10.14 P1).

Both are small time-indexed models. Infeasible cases are re-solved with the soft constraints relaxed so the
UI can name the binding constraint instead of showing "no plan".
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

import pandas as pd
import pulp

from terrapilot.planning.context import PlanningContext
from terrapilot.planning.energy import charger_options, energy_estimate, soc_floor

MINUTES_PER_HOUR = 60.0


@dataclass
class Slot:
    index: int
    start: datetime
    end: datetime

    @property
    def hours(self) -> float:
        return (self.end - self.start).total_seconds() / 3600.0


def _slots(ctx: PlanningContext, horizon_h: float, step_min: float) -> list[Slot]:
    step = timedelta(minutes=step_min)
    out, t, i = [], ctx.now.replace(second=0, microsecond=0), 0
    while t < ctx.now + timedelta(hours=horizon_h):
        out.append(Slot(i, t, t + step))
        t, i = t + step, i + 1
    return out


# ------------------------------------------------------------------ charge plan (§10.9)
def charge_plan(ctx: PlanningContext, site_id: str, horizon_h: float | None = None) -> dict[str, Any]:
    """Slot-indexed MILP: keep every electric machine above the SoC floor, charge inside idle windows,
    respect charger capacity, and never charge and work in the same slot."""
    mc = ctx.cfg.models["models"].get("charge_plan", {})
    horizon = float(horizon_h or mc.get("horizon_h", 12))
    step_min = float(mc.get("step_min", 30))
    slots = _slots(ctx, horizon, step_min)
    machines = ctx.machines
    electric = [
        m
        for m in machines.index
        if machines.loc[m, "powertrain"] == "electric" and machines.loc[m, "site_id"] == site_id
    ]
    stations = ctx.t.get("charging_stations")
    stations = stations[stations["site_id"] == site_id]
    if not electric or stations.empty:
        return {
            "site_id": site_id,
            "status": "skipped",
            "machines": len(electric),
            "plan": [],
            "note": "no electric machines or chargers",
        }
    capacity = len(stations)
    prob = pulp.LpProblem("charge_plan", pulp.LpMaximize)
    work, charge, soc, short = {}, {}, {}, {}
    tasks_by_machine = {m: _open_tasks(ctx, str(m)) for m in electric}
    for m in electric:
        raw = ctx.manifest_raw(str(m))
        energy = raw["energy"]
        cap_kwh = max(_finite(energy["battery_kwh"], 1.0) * _finite(energy.get("usable_fraction", 1.0), 1.0), 1e-6)
        floor = soc_floor(ctx, raw)
        power = max((_finite(o["power_kw"]) for o in charger_options(ctx, str(m), energy)), default=0.0)
        eff = float(energy.get("charge_efficiency", 1.0))
        state = ctx.energy_state(str(m))
        soc0 = _finite(state.get("soc"), floor)
        need_kwh = sum(_finite(energy_estimate(ctx, t, str(m)).get("p50")) for t in tasks_by_machine[m])
        # a working slot drains at the machine's own rate, so work and charge slots compete for the horizon
        draw_kw = _finite(pd.Series(list((raw["specs"].get("consumption_kw") or {}).values())).mean(), 1.0)
        per_slot_kwh = max(draw_kw * slots[0].hours, 1e-6)
        short[m] = pulp.LpVariable(f"short_{m}", lowBound=0)
        for s in slots:
            work[m, s.index] = pulp.LpVariable(f"w_{m}_{s.index}", cat="Binary")
            charge[m, s.index] = pulp.LpVariable(f"c_{m}_{s.index}", cat="Binary")
            soc[m, s.index] = pulp.LpVariable(f"soc_{m}_{s.index}", lowBound=0, upBound=1)
            prob += work[m, s.index] + charge[m, s.index] <= 1
        for s in slots:
            gain = power * eff * s.hours / cap_kwh
            drain = per_slot_kwh / cap_kwh
            prev = soc0 if s.index == 0 else soc[m, s.index - 1]
            prob += soc[m, s.index] == prev + gain * charge[m, s.index] - drain * work[m, s.index]
            prob += soc[m, s.index] >= floor - short[m]  # soft floor: `short` names the violation
        # deliver the task energy (or say by how much the horizon falls short)
        prob += pulp.lpSum(work[m, s.index] * per_slot_kwh for s in slots) + short[m] * cap_kwh >= min(
            need_kwh, per_slot_kwh * len(slots)
        )
    for s in slots:
        prob += pulp.lpSum(charge[m, s.index] for m in electric) <= capacity
    util = pulp.lpSum(work[m, s.index] for m in electric for s in slots)
    prob += (
        util
        - float(mc.get("lambda_floor", 100)) * pulp.lpSum(short.values())
        - float(mc.get("lambda_charge", 0.05)) * pulp.lpSum(charge.values())
    )
    prob.solve(pulp.PULP_CBC_CMD(msg=False, timeLimit=float(mc.get("time_limit_s", 20))))
    status = pulp.LpStatus[prob.status]
    plan = []
    for m in electric:
        for s in slots:
            w, c = pulp.value(work[m, s.index]) or 0, pulp.value(charge[m, s.index]) or 0
            if w < 0.5 and c < 0.5:
                continue
            plan.append(
                {
                    "machine_id": str(m),
                    "start": s.start.isoformat(),
                    "end": s.end.isoformat(),
                    "mode": "charge" if c >= 0.5 else "work",
                    "soc": round(float(pulp.value(soc[m, s.index]) or 0), 3),
                }
            )
    binding = [str(m) for m in electric if (pulp.value(short[m]) or 0) > 1e-6]
    return {
        "site_id": site_id,
        "status": status,
        "feasible": status == "Optimal" and not binding,
        "objective": round(float(pulp.value(prob.objective) or 0), 2),
        "chargers": capacity,
        "plan": sorted(plan, key=lambda p: (p["machine_id"], p["start"])),
        "binding_constraint": "soc_floor" if binding else None,
        "binding_machines": binding,
    }


def _finite(value: Any, default: float = 0.0) -> float:
    try:
        f = float(value)
    except (TypeError, ValueError):
        return default
    return default if math.isnan(f) or math.isinf(f) else f


def _open_tasks(ctx: PlanningContext, machine_id: str) -> list[dict[str, Any]]:
    t = ctx.tasks
    open_states = ctx.cfg.planning.shift_view["statuses_open"]
    start, end = ctx.shift_bounds()
    carry = pd.Timedelta(days=float(ctx.cfg.planning.shift_view["carryover_days"]))
    rows = t[
        (t["assigned_machine_id"] == machine_id)
        & t["status"].isin(open_states)
        & (t["planned_start"] <= pd.Timestamp(end))
        & (t["planned_start"] >= pd.Timestamp(start) - carry)
    ]
    return [dict(r) for r in rows.to_dict("records")]


# ------------------------------------------------------------------ day plan (§10.14 P1)
def day_plan(ctx: PlanningContext, site_id: str, date: str | None = None) -> dict[str, Any]:
    """Assign each open task a start slot on its machine. Slot-dependent durations come from task_duration, so
    the plan prefers the hours where the task is genuinely faster. Minimises completion + lateness."""
    mc = ctx.cfg.models["models"].get("day_plan", {})
    step_min = float(mc.get("step_min", 30))
    shift_start, shift_end = ctx.shift_bounds(pd.Timestamp(date).to_pydatetime() if date else None)
    horizon_h = (shift_end - max(ctx.now, shift_start)).total_seconds() / 3600.0
    if horizon_h <= 0:
        return {"site_id": site_id, "status": "outside_shift", "tasks": []}
    slots = [s for s in _slots(ctx, horizon_h, step_min) if shift_start <= s.start < shift_end]
    t = ctx.tasks
    open_states = ctx.cfg.planning.shift_view["statuses_open"]
    carry = pd.Timedelta(days=float(ctx.cfg.planning.shift_view["carryover_days"]))
    rows = t[
        (t["site_id"] == site_id)
        & t["status"].isin(open_states)
        & t["assigned_machine_id"].notna()
        & (t["planned_start"] < pd.Timestamp(shift_end))
        & (t["planned_start"] >= pd.Timestamp(shift_start) - carry)
    ]
    tasks = [dict(r) for r in rows.to_dict("records")][: int(mc.get("max_tasks", 12))]
    if not tasks or not slots:
        return {"site_id": site_id, "status": "nothing_to_plan", "tasks": []}
    # slot-dependent durations d[j, t] from the duration model
    durations: dict[tuple[str, int], float] = {}
    for task in tasks:
        starts = [s.start for s in slots]
        from terrapilot.planning.estimate import estimate_starts

        ests = estimate_starts(ctx, task, starts, machine_id=str(task["assigned_machine_id"]), explain=False)
        for s, e in zip(slots, ests, strict=True):
            durations[task["id"], s.index] = e.estimate.p50
    prob = pulp.LpProblem("day_plan", pulp.LpMinimize)
    assign = {
        (task["id"], s.index): pulp.LpVariable(f"a_{task['id']}_{s.index}", cat="Binary")
        for task in tasks
        for s in slots
    }
    late = {task["id"]: pulp.LpVariable(f"late_{task['id']}", lowBound=0) for task in tasks}
    for task in tasks:
        prob += pulp.lpSum(assign[task["id"], s.index] for s in slots) == 1
        deadline = task.get("deadline")
        for s in slots:
            finish_h = (s.start - shift_start).total_seconds() / 3600.0 + durations[
                task["id"], s.index
            ] / MINUTES_PER_HOUR
            if deadline is not None and not pd.isna(deadline):
                allowed_h = (pd.Timestamp(deadline).to_pydatetime() - shift_start).total_seconds() / 3600.0
                prob += late[task["id"]] >= (finish_h - allowed_h) * assign[task["id"], s.index]
    # one task at a time per machine: overlapping (task, slot) pairs are mutually exclusive
    by_machine: dict[str, list[dict[str, Any]]] = {}
    for task in tasks:
        by_machine.setdefault(str(task["assigned_machine_id"]), []).append(task)
    for machine_tasks in by_machine.values():
        for s in slots:
            overlapping = []
            for task in machine_tasks:
                for s2 in slots:
                    span = durations[task["id"], s2.index] / MINUTES_PER_HOUR
                    if s2.start <= s.start < s2.start + timedelta(hours=span):
                        overlapping.append(assign[task["id"], s2.index])
            if overlapping:
                prob += pulp.lpSum(overlapping) <= 1
    completion = pulp.lpSum(
        assign[task["id"], s.index]
        * ((s.start - shift_start).total_seconds() / 3600.0 + durations[task["id"], s.index] / MINUTES_PER_HOUR)
        for task in tasks
        for s in slots
    )
    prob += completion + float(mc.get("lambda_lateness", 5)) * pulp.lpSum(late.values())
    prob.solve(pulp.PULP_CBC_CMD(msg=False, timeLimit=float(mc.get("time_limit_s", 30))))
    out = []
    for task in tasks:
        chosen = next((s for s in slots if (pulp.value(assign[task["id"], s.index]) or 0) >= 0.5), None)
        if chosen is None:
            continue
        minutes = durations[task["id"], chosen.index]
        out.append(
            {
                "task_id": task["id"],
                "machine_id": str(task["assigned_machine_id"]),
                "operator_id": task.get("assigned_operator_id"),
                "start": chosen.start.isoformat(),
                "end": (chosen.start + timedelta(minutes=minutes)).isoformat(),
                "duration_min": round(minutes, 1),
                "late_h": round(float(pulp.value(late[task["id"]]) or 0), 2),
            }
        )
    return {
        "site_id": site_id,
        "date": (date or ctx.now.date().isoformat()),
        "status": pulp.LpStatus[prob.status],
        "objective": round(float(pulp.value(prob.objective) or 0), 2),
        "tasks": sorted(out, key=lambda r: r["start"]),
        "shift": {"start": shift_start.isoformat(), "end": shift_end.isoformat()},
    }


def power_mode(ctx: PlanningContext, machine_id: str) -> dict[str, Any]:
    """Eco / Standard / High recommendation from the digging-resistance proxy (§10.10)."""
    mc = ctx.cfg.copilot["generators"]["power_mode"]
    live = ctx._live(machine_id)
    load = live.get("engine.load_pct")
    if load is None:
        tel = ctx.t.get("telemetry_1min")
        rows = tel[tel["machine_id"] == machine_id] if not tel.empty else tel
        load = float(rows.sort_values("ts").iloc[-1]["load_pct"]) if not rows.empty else None
    if load is None:
        return {"machine_id": machine_id, "mode": None, "note": "no telemetry"}
    band = next((m for m, (lo, hi) in mc["load_bands"].items() if lo <= float(load) < hi), "standard")
    specs = ctx.manifest_raw(machine_id).get("specs", {})
    fuel = specs.get("work_fuel_lph") or {}
    saving = None
    if band == "eco" and fuel.get("standard") and fuel.get("eco"):
        saving = round(float(fuel["standard"]) - float(fuel["eco"]), 1)
    return {
        "machine_id": machine_id,
        "mode": band,
        "load_pct": round(float(load), 1),
        "fuel_saving_lph": saving,
        "dwell_s": mc["dwell_s"],
    }
