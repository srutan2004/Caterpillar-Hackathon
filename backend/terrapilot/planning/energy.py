"""Energy/fuel per task, "can I finish on this charge?" and recharge/refuel time (§10.15.3)."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

import numpy as np
import pandas as pd

from terrapilot.core.refs import get_path
from terrapilot.planning.context import PlanningContext

MINUTES_PER_HOUR = 60.0
SOC_STEP = 0.005


def charge_minutes(energy_cfg: dict[str, Any], soc_from: float, soc_to: float, station_kw: float) -> float:
    """Minutes to charge from `soc_from` to `soc_to` with the manifest's taper (power falls linearly above
    `taper.start_soc` to `power_fraction_at_full` × P at 100%)."""
    if soc_to <= soc_from:
        return 0.0
    cap = float(energy_cfg["battery_kwh"]) * float(energy_cfg.get("usable_fraction", 1.0))
    eff = float(energy_cfg.get("charge_efficiency", 1.0))
    taper = energy_cfg.get("charge_taper") or {}
    t0, frac = float(taper.get("start_soc", 1.0)), float(taper.get("power_fraction_at_full", 1.0))
    minutes = 0.0
    soc = soc_from
    while soc < soc_to - 1e-9:
        step = min(SOC_STEP, soc_to - soc)
        mid = soc + step / 2
        p = station_kw if mid <= t0 else station_kw * (1 - (1 - frac) * (mid - t0) / max(1 - t0, 1e-9))
        minutes += step * cap / (p * eff) * MINUTES_PER_HOUR
        soc += step
    return minutes


def soc_floor(ctx: PlanningContext, raw: dict[str, Any]) -> float:
    ref = (raw.get("energy") or {}).get("soc_floor_ref")
    if isinstance(ref, str) and ref.startswith("app."):
        return float(get_path(ctx.cfg.app_dict(), ref[len("app.") :]))
    return float(ctx.cfg.app.energy["soc_floor"])


def per_unit_energy(ctx: PlanningContext, task: dict[str, Any], machine_id: str) -> tuple[np.ndarray, str] | None:
    """Historical energy per unit quantity for this task type on machines of the same manifest."""
    ecfg = ctx.cfg.planning.energy_per_task
    manifest_id = ctx.manifest_id(machine_id)
    same = ctx.machines[ctx.machines["manifest_id"] == manifest_id].index.tolist()
    t = ctx.tasks
    hist = t[
        (t["status"] == "completed")
        & (t["type"] == task["type"])
        & (t["assigned_machine_id"].isin(same))
        & (t["actual_start"] >= pd.Timestamp(ctx.now - timedelta(days=int(ecfg["lookback_days"]))))
        & (t["quantity"] > 0)
    ]
    if len(hist) < int(ecfg["min_history_tasks"]):
        return None
    electric = str(ctx.machines.loc[machine_id, "powertrain"]) == "electric"
    col = "kwh" if electric else "fuel_l"
    ids = hist["id"].tolist()
    if ctx.t.source == "db":
        agg = ctx.t.get(
            "cycles",
            f"SELECT task_id, SUM({col}) AS e FROM cycles WHERE task_id IN :ids GROUP BY task_id",
            {"ids": tuple(ids)},
        )
        per_task = agg.set_index("task_id")["e"]
    else:
        cyc = ctx.t.get("cycles")
        per_task = cyc[cyc["task_id"].isin(ids)].groupby("task_id")[col].sum()
    qty = hist.set_index("id")["quantity"].reindex(per_task.index)
    vals = (per_task / qty).dropna().to_numpy()
    vals = vals[vals > 0]
    if len(vals) < int(ecfg["min_history_tasks"]):
        return None
    return vals, ("kWh" if electric else "L")


def energy_estimate(
    ctx: PlanningContext, task: dict[str, Any], machine_id: str, duration_min: dict[str, float] | None = None
) -> dict[str, Any]:
    raw = ctx.manifest_raw(machine_id)
    energy = raw.get("energy") or {}
    ecfg = ctx.cfg.planning.energy_per_task
    qs = [float(q) for q in ecfg["quantiles"]]
    qty = float(task["quantity"]) - float(task.get("progress_qty") or 0.0) * (task.get("status") == "in_progress")
    idle = 1 + float(ecfg["idle_allowance_fraction"])
    electric = str(ctx.machines.loc[machine_id, "powertrain"]) == "electric"
    hist = per_unit_energy(ctx, task, machine_id)
    if hist is not None:
        vals, unit = hist
        e = [float(np.quantile(vals, q)) * qty * idle for q in qs]
        method = "history"
    else:  # thin history: manifest power/fuel rate × duty × predicted duration
        unit = "kWh" if electric else "L"
        specs = raw["specs"]
        rate_h = (
            float(np.mean(list((specs.get("consumption_kw") or {}).values()) or [0.0]))
            if electric
            else float((specs.get("work_fuel_lph") or {}).get("standard", 0.0))
        ) * float(ecfg["fallback_duty"])
        d = duration_min or {}
        e = [rate_h * float(d.get(k, 0.0)) / MINUTES_PER_HOUR * idle for k in ("p10_min", "p50_min", "p90_min")]
        method = "manifest_rate"
    state = ctx.energy_state(machine_id)
    floor = soc_floor(ctx, raw)
    out: dict[str, Any] = {
        "task_id": task["id"],
        "machine_id": machine_id,
        "unit": unit,
        "p10": round(e[0], 1),
        "p50": round(e[1], 1),
        "p90": round(e[-1], 1),
        "method": method,
        "floor": floor,
        "state": state,
    }
    if electric:
        cap = float(energy["battery_kwh"]) * float(energy.get("usable_fraction", 1.0))
        soc = state.get("soc")
        need = e[-1] / cap
        if soc is None:
            out.update({"can_finish": None})
            return out
        margin = soc - need - floor
        target = min(
            1.0, floor + need + float(ctx.cfg.planning.start_time["preconditions"]["charge_target_soc_margin"])
        )
        stations = charger_options(ctx, machine_id, energy)
        best = max(stations, key=lambda s: s["power_kw"]) if stations else None
        mins = charge_minutes(energy, soc, target, float(best["power_kw"])) if best and margin < 0 else 0.0
        out.update(
            {
                "soc_now": round(soc, 3),
                "avail_frac": round(soc - floor, 4),
                "need_frac": round(need, 4),
                "soc_after_p90": round(soc - need, 3),
                "can_finish": margin >= 0,
                "margin": round(margin, 3),
                "charge_target_soc": round(target, 3),
                "recharge_min": round(mins, 0),
                "station": best,
            }
        )
    else:
        tank = float(energy.get("tank_l", 0.0))
        pct = state.get("fuel_pct")
        if pct is None or tank <= 0:
            out.update({"can_finish": None})
            return out
        litres = pct / 100 * tank
        margin_l = litres - e[-1] - floor * tank
        refuel_below = float(ctx.cfg.planning.start_time["preconditions"]["refuel_if_below_pct"])
        needs_refuel = margin_l < 0 or pct < refuel_below
        out.update(
            {
                "fuel_pct_now": round(pct, 1),
                "avail_frac": round(litres / tank - floor, 4),
                "need_frac": round(e[-1] / tank, 4),
                "can_finish": margin_l >= 0,
                "margin": round(margin_l / tank, 3),
                "refuel_min": round((tank - litres) / float(energy.get("refuel_rate_lpm", 1.0)), 0)
                if needs_refuel
                else 0.0,
            }
        )
    return out


def charger_options(ctx: PlanningContext, machine_id: str, energy: dict[str, Any]) -> list[dict[str, Any]]:
    site = str(ctx.machines.loc[machine_id, "site_id"])
    st = ctx.t.get("charging_stations")
    st = st[st["site_id"] == site]
    powers = energy.get("charge_power_kw_by_station") or {}
    out = []
    for r in st.to_dict("records"):
        kw = min(float(r["power_kw"]), float(powers.get(r["kind"], r["power_kw"])))
        out.append({"station_id": r["id"], "kind": r["kind"], "power_kw": kw})
    return out
