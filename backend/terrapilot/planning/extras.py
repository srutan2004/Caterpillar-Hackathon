"""Weather windows (§10.15.6), machine selection (§10.15.7) and task wear/cost (§10.15.4)."""

from __future__ import annotations

from typing import Any

import pandas as pd

from terrapilot.core.refs import load_ref_cached
from terrapilot.planning.context import PlanningContext
from terrapilot.planning.energy import energy_estimate
from terrapilot.planning.estimate import estimate_starts, estimate_task
from terrapilot.planning.readiness import readiness
from terrapilot.planning.start_time import _forecast_frame

MINUTES_PER_HOUR = 60.0


# ------------------------------------------------------------------ weather windows
def weather_windows(
    ctx: PlanningContext, site_id: str, task_type: str, hours: int = 36, need_minutes: float | None = None
) -> dict[str, Any]:
    """Contiguous workable windows for a weather-sensitive task type, with a confidence from forecast spread."""
    rules = ctx.cfg.planning.weather_windows["task_types"].get(task_type)
    if rules is None:
        return {"task_type": task_type, "workable": True, "windows": [], "note": "not weather sensitive"}
    fc = _forecast_frame(ctx, site_id)
    if fc.empty:
        return {"task_type": task_type, "windows": [], "note": "no forecast"}
    fc = fc.loc[pd.Timestamp(ctx.now).floor("h") : pd.Timestamp(ctx.now) + pd.Timedelta(hours=hours)]
    soils = load_ref_cached(ctx.cfg.root, "datagen/ground.yaml#soils")
    moisture = _zone_moisture(ctx, site_id)
    dry_needed = float(rules["dry_hours_before"])
    ok_rows, dry_run = [], 0.0
    for ts, row in fc.iterrows():
        rain = float(row.get("rain_mm", 0) or 0)
        dry_run = dry_run + 1 if rain <= float(rules["max_rain_mm_h"]) else 0.0
        ok = (
            float(row.get("gust_ms", 0) or 0) <= float(rules["max_gust_ms"])
            and rain <= float(rules["max_rain_mm_h"])
            and dry_run >= dry_needed
            and moisture <= float(rules["max_moisture"])
        )
        spread = float(row.get("gust_ms_spread", 0) or 0) + float(row.get("rain_mm_spread", 0) or 0)
        ok_rows.append((pd.Timestamp(ts), ok, spread))
    windows, start, spreads = [], None, []
    for ts, ok, spread in [*ok_rows, (None, False, 0.0)]:
        if ok and start is None:
            start, spreads = ts, [spread]
        elif ok:
            spreads.append(spread)
        elif start is not None:
            end = ts if ts is not None else ok_rows[-1][0] + pd.Timedelta(hours=1)
            minutes = (end - start).total_seconds() / 60
            if need_minutes is None or minutes >= need_minutes:
                confidence = round(max(0.0, 1 - (sum(spreads) / len(spreads)) / 5.0), 2)
                windows.append(
                    {
                        "start": start.isoformat(),
                        "end": end.isoformat(),
                        "minutes": round(minutes),
                        "confidence": confidence,
                    }
                )
            start = None
    _ = soils
    return {
        "task_type": task_type,
        "site_id": site_id,
        "rules": rules,
        "moisture": round(moisture, 3),
        "windows": windows,
    }


def _zone_moisture(ctx: PlanningContext, site_id: str) -> float:
    gc = ctx.t.get("ground_conditions")
    zones = ctx.features.zones
    site_zones = [z for z in zones.index if zones.loc[z, "site_id"] == site_id]
    rows = gc[gc["zone_id"].isin(site_zones)] if not gc.empty else gc
    return float(rows.sort_values("date").iloc[-1]["moisture"]) if not rows.empty else 0.0


# ------------------------------------------------------------------ task wear and cost
def task_cost_estimate(ctx: PlanningContext, task: dict[str, Any], machine_id: str) -> dict[str, Any]:
    """Fuel/energy + GET wear + undercarriage/tyre hours + maintenance accrual → cost per unit (§10.15.4)."""
    costs = ctx.cfg.costs
    est = estimate_task(ctx, task).estimate.as_dict()
    energy = energy_estimate(ctx, task, machine_id, est)
    machine_class = str(ctx.machines.loc[machine_id, "machine_class"])
    electric = str(ctx.machines.loc[machine_id, "powertrain"]) == "electric"
    price = float(ctx.cfg.app.costs["electricity_price_per_kwh" if electric else "diesel_price_per_l"])
    energy_cost = float(energy["p50"]) * price
    hours = float(est["p50_min"]) / MINUTES_PER_HOUR
    accrual = costs.get("maintenance_accrual_per_h", {}).get(machine_class, {})
    accrual_cost = float(sum(accrual.values())) * hours
    get_cfg = costs.get("get_wear", {})
    soil = ctx.features.soil_of(task.get("zone_id"))
    abrasive = float(get_cfg.get("abrasiveness_by_soil", {}).get(soil, 1.0))
    quantity = float(task["quantity"])
    # tooth-set life scales inversely with abrasiveness × dig energy; expressed as the share consumed
    tooth_cost = float(get_cfg.get("cost_per_tooth_set", 0)) * (
        abrasive * hours / float(get_cfg.get("tooth_set_life_h", 800))
    )
    unit = str(task.get("unit") or "unit")
    total = energy_cost + accrual_cost + tooth_cost
    return {
        "task_id": task["id"],
        "machine_id": machine_id,
        "duration_h": round(hours, 2),
        "energy": {"unit": energy["unit"], "p50": energy["p50"], "cost": round(energy_cost, 0)},
        "get_wear": {"soil": soil, "abrasiveness": abrasive, "cost": round(tooth_cost, 0)},
        "undercarriage_hours": round(hours, 2) if machine_class == "excavator" else 0.0,
        "tyre_hours": round(hours, 2) if machine_class in ("wheel_loader", "adt") else 0.0,
        "maintenance_accrual": round(accrual_cost, 0),
        "total_cost": round(total, 0),
        "cost_per_unit": round(total / quantity, 2) if quantity else None,
        "unit": unit,
        "currency": ctx.cfg.app.costs["currency"],
    }


# ------------------------------------------------------------------ machine selection
def machine_options(ctx: PlanningContext, task_id: str, limit: int = 5) -> dict[str, Any]:
    """Rank available machines for a task by expected completion, readiness, energy and cost per unit."""
    task = ctx.task(task_id)
    site, cls = str(task["site_id"]), str(task["machine_class"])
    machines = ctx.machines
    candidates = [
        m
        for m in machines.index
        if machines.loc[m, "machine_class"] == cls
        and machines.loc[m, "site_id"] == site
        and machines.loc[m, "status"] != "down"
    ]
    rows = []
    for mid in candidates:
        est = estimate_starts(ctx, task, [ctx.now], machine_id=str(mid), explain=False)[0].estimate
        energy = energy_estimate(ctx, task, str(mid), est.as_dict())
        ready = readiness(ctx, str(mid), task.get("assigned_operator_id"), task)
        cost = task_cost_estimate(ctx, task, str(mid))
        rows.append(
            {
                "machine_id": str(mid),
                "current": str(mid) == task.get("assigned_machine_id"),
                "duration_p50_min": round(est.p50, 1),
                "readiness": ready["score"],
                "readiness_band": ready["band"],
                "can_finish": energy.get("can_finish"),
                "cost_per_unit": cost["cost_per_unit"],
                "status": str(machines.loc[mid, "status"]),
            }
        )
    best = min((r["duration_p50_min"] for r in rows), default=1.0) or 1.0
    cheap = min((r["cost_per_unit"] or 0 for r in rows), default=1.0) or 1.0
    for r in rows:
        r["score"] = round(
            (best / max(r["duration_p50_min"], 1e-6)) * 0.4
            + (r["readiness"] / 100) * 0.3
            + (1.0 if r["can_finish"] is not False else 0.0) * 0.15
            + (cheap / max(r["cost_per_unit"] or cheap, 1e-6)) * 0.15,
            3,
        )
    rows.sort(key=lambda r: -r["score"])
    return {"task_id": task_id, "machine_class": cls, "options": rows[:limit], "unit": task.get("unit")}
