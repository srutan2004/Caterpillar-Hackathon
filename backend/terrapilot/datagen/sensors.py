"""Maintenance sensors, minute telemetry and battery logs (§7.3 Maintenance sensors, §7.5).

s(t) = baseline(ambient, load, rpm; θ) + g_c(1 − h_c(t)) + fault_mode_k(t − onset_k) + ε(t)
`resid` = value − baseline, i.e. what a healthy machine would not show (used for drift/peer layers).
"""

from __future__ import annotations

from datetime import date, timedelta
from itertools import pairwise
from typing import Any

import numpy as np
import pandas as pd

from terrapilot.datagen.context import GenContext
from terrapilot.datagen.fleet import STATE_CHARGE, STATE_IDLE, STATE_WORK, MachineRt
from terrapilot.datagen.history import FaultModeRt, symptom_fraction
from terrapilot.datagen.weather import HourlyWeather


def _state_at(times: np.ndarray, m: MachineRt) -> np.ndarray:
    """Priority idle > charge > work > off for each timestamp."""
    state = np.zeros(len(times), dtype=np.int8)
    for code in (STATE_WORK, STATE_CHARGE, STATE_IDLE):
        iv = sorted((a, b) for a, b, s in m.activity if s == code)
        if not iv:
            continue
        starts = np.array([a for a, _ in iv])
        ends = np.array([b for _, b in iv])
        i = np.searchsorted(starts, times, side="right") - 1
        inside = (i >= 0) & (times < ends[np.clip(i, 0, None)])
        state[inside] = code
    return state


def _step_grid(ctx: GenContext, m: MachineRt, step_s: float, days: list[date]) -> np.ndarray:
    overtime = float(ctx.world["shift"]["overtime_max_h"]) * 3600
    chunks = [
        np.arange(ctx.shift_start(d).timestamp(), ctx.shift_end(d).timestamp() + overtime, step_s)
        for d in days
        if ctx.is_workday(d)
    ]
    return np.concatenate(chunks) if chunks else np.zeros(0)


def _health_lookup(ctx: GenContext, m: MachineRt) -> tuple[list[date], dict[str, np.ndarray]]:
    hd: pd.DataFrame = ctx.state["health_daily"]
    sub = hd[hd["machine_id"] == m.id]
    piv = sub.pivot(index="date", columns="component", values="health").sort_index()
    return list(piv.index), {c: piv[c].to_numpy() for c in piv.columns}


def generate_sensors(ctx: GenContext) -> None:
    degr = ctx.dg["degradation"]
    sensor_models = degr["sensors"]
    step_s = float(ctx.world["resolution"]["sensor_step_min"]) * 60
    days = ctx.history_dates()
    frames = []
    for m in ctx.state["machines"].values():
        rng = ctx.rng(f"sensors:{m.id}")
        times = _step_grid(ctx, m, step_s, days)
        state = _state_at(times, m)
        keep = (state == STATE_WORK) | (state == STATE_IDLE)
        times, state = times[keep], state[keep]
        if not len(times):
            continue
        n = len(times)
        working = state == STATE_WORK
        wx: HourlyWeather = ctx.state["wx"][m.site_id]
        hidx = np.clip(((times - wx.t0.timestamp()) // 3600).astype(int), 0, len(wx.data["temp_c"]) - 1)
        ambient = wx.data["temp_c"][hidx]
        pm10 = wx.data["pm10"][hidx]
        load = np.where(working, np.clip(rng.normal(0.68, 0.1, n), 0.2, 1.0), 0.15)
        high_idle = (~working) & (rng.random(n) < ctx.dg["behavior"]["idle"]["high_rpm_prob"])
        rpm = np.where(working, rng.normal(1800, 80, n), np.where(high_idle, 1300.0, 900.0))
        dates = pd.to_datetime(times, unit="s", utc=True).tz_convert(ctx.tz).date
        h_days, h_vals = _health_lookup(ctx, m)
        didx = np.clip(np.searchsorted(np.array(h_days), dates), 0, len(h_days) - 1)
        hours_since = _hours_since_service(ctx, m, times, dates, working, step_s)
        fms = [fm for fm in ctx.state["fault_modes"] if fm.machine_id == m.id]

        wanted = {ms.id for ms in m.manifest.maintenance_sensors}
        wanted |= {sid for sid, sm in sensor_models.items() if sm.get("auxiliary") and m.manifest.sensor(sid)}
        for sid in sorted(wanted):
            sm = sensor_models[sid]
            if sm.get("derived") == "load_pct":
                value, resid = np.round(load * 100, 1), np.zeros(n)
            elif sm.get("derived") == "rpm":
                value, resid = np.round(rpm, 0), np.zeros(n)
            elif sm.get("boolean"):
                value = _fault_offset(fms, sid, times, degr).clip(0, 1).round()
                resid = value.copy()
            elif "sawtooth" in sm:
                value, resid = _sawtooth(sm, times, working, step_s, rng)
                comp = sm["component"]
                if comp in h_vals:
                    wear = sm["wear_gain"] * (1 - h_vals[comp][didx])
                    value, resid = value + wear, resid + wear
            else:
                base = sm.get("base_by_class", {}).get(m.cls, sm.get("base", 0.0))
                baseline = (
                    base
                    + sm.get("amb_k", 0.0) * (ambient - 25)
                    + sm.get("load_k", 0.0) * load
                    + sm.get("rpm_k", 0.0) * rpm
                    + np.where(working, 0.0, sm.get("idle_offset", 0.0))
                )
                comp = sm.get("component")
                wear = sm.get("wear_gain", 0.0) * (1 - h_vals[comp][didx]) if comp in h_vals else 0.0
                consumable = 0.0
                if "per_h_since_service" in sm:
                    ps = sm["per_h_since_service"]
                    consumable = ps["k"] * hours_since.get(ps["item"], np.zeros(n))
                    if ps.get("dust_scaled"):
                        consumable = consumable * pm10 / degr["acceleration"]["pm10_norm"]
                fault = _fault_offset(fms, sid, times, degr)
                noise = rng.normal(0, sm.get("noise_sd", 0.0), n)
                value = baseline + wear + consumable + fault + noise
                lo, hi = sm.get("clip", [None, None])
                value = np.clip(value, lo if lo is not None else -np.inf, hi if hi is not None else np.inf)
                resid = value - baseline
            frames.append(
                pd.DataFrame(
                    {
                        "ts": pd.to_datetime(times, unit="s", utc=True),
                        "machine_id": m.id,
                        "sensor_id": sid,
                        "value": np.round(value.astype(float), 3),
                        "resid": np.round(np.asarray(resid, dtype=float), 3),
                    }
                )
            )
    if frames:
        ctx.emit("sensor_1min", pd.concat(frames, ignore_index=True))


def _hours_since_service(
    ctx: GenContext, m: MachineRt, times: np.ndarray, dates: np.ndarray, working: np.ndarray, step_s: float
) -> dict[str, np.ndarray]:
    hm_daily = ctx.state["hour_meter_daily"][m.id]
    step_h = step_s / 3600
    # hour meter at each (operating) step: start-of-day meter + operating steps so far that day
    day_series = pd.Series(dates)
    hm = (
        day_series.map(lambda d: hm_daily.get(d, 0.0)).to_numpy(dtype=float)
        + day_series.groupby(day_series).cumcount().to_numpy() * step_h
    )
    out: dict[str, np.ndarray] = {}
    for item in ctx.cfg.service_intervals.get(m.manifest.id, []):
        key = item["item"]
        events = sorted(ctx.state["service_events"].get((m.id, key), []))
        initial = ctx.state["service_initial"].get((m.id, key), hm[0] if len(hm) else 0.0)
        ev_t = np.array([t for t, _ in events])
        ev_h = np.array([initial] + [h for _, h in events])
        last = ev_h[np.searchsorted(ev_t, times, side="right")] if len(ev_t) else np.full(len(times), initial)
        out[key] = np.clip(hm - last, 0, None)
    return out


def _fault_offset(fms: list[FaultModeRt], sensor_id: str, times: np.ndarray, degr: dict[str, Any]) -> np.ndarray:
    out = np.zeros(len(times))
    for fm in fms:
        mag = None
        if fm.sensor_id == sensor_id:
            mag = float(fm.cfg["magnitude"])
        elif sensor_id in (fm.cfg.get("also") or {}):
            mag = float(fm.cfg["also"][sensor_id])
        if mag is None:
            continue
        end = fm.resolved_s if fm.resolved_s else np.inf
        active = (times >= fm.onset_s) & (times < end)
        x = (times - fm.onset_s) / fm.ttf_s
        out += np.where(active, mag * symptom_fraction(fm.cfg["shape"], x), 0.0)
    return out


def _sawtooth(
    sm: dict[str, Any], times: np.ndarray, working: np.ndarray, step_s: float, rng: np.random.Generator
) -> tuple[np.ndarray, np.ndarray]:
    st = sm["sawtooth"]
    value = np.empty(len(times))
    soot = st["regen_to"] + (st["regen_at"] - st["regen_to"]) * rng.random()
    for i in range(len(times)):
        rate = st["rate_per_h"] * (1.0 if working[i] else st["idle_rate_factor"])
        soot += rate * step_s / 3600
        if soot >= st["regen_at"]:
            soot = st["regen_to"]
        value[i] = soot
    value = value + rng.normal(0, sm["noise_sd"], len(times))
    return value, np.zeros(len(times))


# ------------------------------------------------------------------------------------------ telemetry & battery
def generate_telemetry(ctx: GenContext) -> None:
    days_n = int(ctx.world["resolution"]["telemetry_1min_days"])
    days = [d for d in ctx.history_dates() if d >= ctx.anchor - timedelta(days=days_n)]
    frames = []
    for m in ctx.state["machines"].values():
        rng = ctx.rng(f"telemetry:{m.id}")
        times = _step_grid(ctx, m, 60.0, days)
        if not len(times):
            continue
        state = _state_at(times, m)
        n = len(times)
        working, idle = state == STATE_WORK, state == STATE_IDLE
        specs = m.manifest.specs
        electric = m.powertrain == "electric"
        label = np.select([working, idle, state == STATE_CHARGE], ["work", "idle", "charge"], "off")
        load = np.where(working, np.clip(rng.normal(0.68, 0.1, n), 0.2, 1.0), np.where(idle, 0.15, 0.0))
        rpm = (
            np.where(working, rng.normal(1800, 80, n), np.where(idle, 900.0, 0.0))
            if not electric
            else np.full(n, np.nan)
        )
        work_lph = float(specs.get("work_fuel_lph", {}).get("standard", 0.0))
        fuel_rate = (
            np.where(working, work_lph * load / 0.68, np.where(idle, float(specs.get("idle_fuel_lph", 0.0)), 0.0))
            if not electric
            else np.full(n, np.nan)
        )
        cons = specs.get("consumption_kw", {})
        power = (
            np.where(
                working,
                float(np.mean(list(cons.values()) or [0])) * load / 0.68,
                np.where(idle, float(cons.get("idle", 0.0)), 0.0),
            )
            if electric
            else np.full(n, np.nan)
        )
        cruise = {"excavator": 0.6, "wheel_loader": 9.0, "adt": 22.0}.get(m.cls, 1.0)
        speed = np.where(working, np.abs(rng.normal(cruise, cruise * 0.4, n)), 0.0)
        hyd = (
            np.where(working, rng.normal(230, 40, n), np.where(idle, 20.0, 0.0))
            if m.manifest.sensor("hydraulic.pump_pressure")
            else np.full(n, np.nan)
        )
        soc = _interp_points(m.soc_points, times) if electric else np.full(n, np.nan)
        frames.append(
            pd.DataFrame(
                {
                    "ts": pd.to_datetime(times, unit="s", utc=True),
                    "machine_id": m.id,
                    "state": label,
                    "rpm": np.round(rpm, 0),
                    "load_pct": np.round(load * 100, 1),
                    "fuel_rate_lph": np.round(fuel_rate, 2),
                    "power_kw": np.round(power, 1),
                    "speed_kph": np.round(speed, 2),
                    "hyd_pressure_bar": np.round(hyd, 1),
                    "fuel_pct": np.nan,
                    "soc": np.round(soc, 4),
                }
            )
        )
    if frames:
        ctx.emit("telemetry_1min", pd.concat(frames, ignore_index=True))


def _interp_points(points: list[tuple[float, float]], times: np.ndarray) -> np.ndarray:
    if not points:
        return np.full(len(times), np.nan)
    pts = sorted(points)
    out: np.ndarray = np.interp(times, [p[0] for p in pts], [p[1] for p in pts])
    return out


def generate_battery_log(ctx: GenContext) -> None:
    step_s = float(ctx.world["resolution"]["battery_step_min"]) * 60
    frames = []
    for m in ctx.state["machines"].values():
        if m.powertrain != "electric" or not m.soc_points:
            continue
        rng = ctx.rng(f"battery:{m.id}")
        times = _step_grid(ctx, m, step_s, ctx.history_dates())
        state = _state_at(times, m)
        keep = state != 0
        times, state = times[keep], state[keep]
        soc = _interp_points(m.soc_points, times)
        cap = float(m.manifest.energy["battery_kwh"])
        cons = m.manifest.specs.get("consumption_kw", {})
        power = np.select(
            [state == STATE_WORK, state == STATE_IDLE, state == STATE_CHARGE],
            [float(np.mean(list(cons.values()))), float(cons.get("idle", 0.0)), -120.0],
            0.0,
        )
        wx: HourlyWeather = ctx.state["wx"][m.site_id]
        hidx = np.clip(((times - wx.t0.timestamp()) // 3600).astype(int), 0, len(wx.data["temp_c"]) - 1)
        temp = (
            wx.data["temp_c"][hidx] * 0.45
            + 16
            + np.where(state == STATE_WORK, 6.0, 1.0)
            + rng.normal(0, 0.4, len(times))
        )
        frames.append(
            pd.DataFrame(
                {
                    "ts": pd.to_datetime(times, unit="s", utc=True),
                    "machine_id": m.id,
                    "soc": np.round(soc, 4),
                    "kwh": np.round(soc * cap, 2),
                    "power_kw": np.round(power, 1),
                    "temp_c": np.round(temp, 2),
                }
            )
        )
        # the machine's current (parked) state at `now`, so serving reads today's SoC from data
        now_s = ctx.now.timestamp()
        soc_now = float(_interp_points(m.soc_points, np.array([now_s]))[0])
        frames.append(
            pd.DataFrame(
                {
                    "ts": [pd.Timestamp(ctx.now).tz_convert("UTC")],
                    "machine_id": [m.id],
                    "soc": [round(soc_now, 4)],
                    "kwh": [round(soc_now * cap, 2)],
                    "power_kw": [0.0],
                    "temp_c": [round(float(temp[-1]) if len(temp) else 25.0, 2)],
                }
            )
        )
    if frames:
        ctx.emit("battery_log", pd.concat(frames, ignore_index=True))


# ------------------------------------------------------------------------------------------ maintenance side tables
def generate_maintenance_tables(ctx: GenContext) -> None:
    degr = ctx.dg["degradation"]
    limits = ctx.cfg.sensor_limits.get("fluid_limits", {})
    fcfg = degr["fluid_samples"]
    hd: pd.DataFrame = ctx.state["health_daily"]
    samples, counters = [], []
    tiers = ["monitor", "service_soon", "stop"]
    for m in ctx.state["machines"].values():
        rng = ctx.rng(f"fluids:{m.id}")
        hm_daily = ctx.state["hour_meter_daily"][m.id]
        days = sorted(hm_daily)
        wx: HourlyWeather = ctx.state["wx"][m.site_id]
        pm_mean = float(np.mean(wx.data["pm10"]))
        for comp_name, comp in fcfg["compartments"].items():
            if m.powertrain not in comp["powertrains"] or comp["component"] not in m.eff_age_h:
                continue
            for d0, d1 in pairwise(days):
                if int(hm_daily[d0] // fcfg["every_h"]) == int(hm_daily[d1] // fcfg["every_h"]):
                    continue
                h = hd[(hd["machine_id"] == m.id) & (hd["date"] == d1)].set_index("component")["health"].to_dict()
                wear = 1 - h.get(comp["component"], 1.0)
                cool = 1 - h.get("cooling", 1.0)
                dpf = 1 - h.get("dpf", 1.0)
                noise = iter(rng.lognormal(0, fcfg["noise_sd_frac"], 5)).__next__  # one draw per metric below

                vals = {
                    "fe_ppm": (comp["fe_ppm"]["base"] + comp["fe_ppm"]["wear_k"] * wear) * noise(),
                    "cu_ppm": (comp["cu_ppm"]["base"] + comp["cu_ppm"]["wear_k"] * wear) * noise(),
                    "si_ppm": (comp["si_ppm"]["base"] + comp["si_ppm"]["dust_k"] * pm_mean / 100) * noise(),
                    "na_ppm": (comp["na_ppm"]["base"] + comp["na_ppm"]["coolant_leak_k"] * max(0.0, cool - 0.5))
                    * noise(),
                    "soot_pct": (comp["soot_pct"]["base"] + comp["soot_pct"]["dpf_k"] * dpf) * noise(),
                }
                visc = comp["viscosity_cst"]["base"] * (1 + comp["viscosity_cst"]["change_k"] / 100 * wear * 10)
                lim = limits.get(comp_name, {})
                rating = "normal"
                for metric, v in vals.items():
                    tl = lim.get(metric)
                    if isinstance(tl, dict):
                        for tier in tiers:
                            if v >= tl[tier] and tiers.index(tier) >= (tiers.index(rating) if rating in tiers else -1):
                                rating = tier
                iso = fcfg["iso_4406"]["bad" if wear > 0.6 else "worn" if wear > 0.35 else "healthy"]
                ts_ = ctx.shift_end(d1)
                samples.append(
                    {
                        "id": f"FS-{m.id}-{comp_name}-{d1.isoformat()}",
                        "machine_id": m.id,
                        "compartment": comp_name,
                        "ts": ts_,
                        **{k: round(v, 2) for k, v in vals.items()},
                        "iso_4406": iso,
                        "viscosity_cst": round(visc, 2),
                        "lab_rating": rating,
                    }
                )
        # service counters as of "now"
        climate = ctx.site(m.site_id)["climate"]
        sev = ctx.cfg.service_intervals.get("severity_factors", {})
        severity = float(sev.get(climate, 1.0)) + float(sev.get("dusty_bonus_per_100_pm10", 0.0)) * max(
            0.0, pm_mean / 100 - 1
        )
        recent = [hm_daily[d] for d in days[-30:]]
        per_day = max((recent[-1] - recent[0]) / max(len(recent) - 1, 1), 0.5) if len(recent) > 1 else 6.0
        pinned = (ctx.dg.get("demo_fixtures") or {}).get("service_due", {}).get(m.id)
        for item in ctx.cfg.service_intervals.get(m.manifest.id, []):
            last = m.service_last_h.get(item["item"], m.hour_meter)
            if pinned and pinned["item"] == item["item"]:
                last = m.hour_meter + float(pinned["due_in_h"]) - item["every_h"]
            due = last + item["every_h"]
            remaining_h = (due - m.hour_meter) / severity
            counters.append(
                {
                    "machine_id": m.id,
                    "item": item["item"],
                    "last_done_hours": round(last, 1),
                    "due_hours": round(due, 1),
                    "severity_factor": round(severity, 3),
                    "due_eta": ctx.now
                    + timedelta(days=max(remaining_h, 0) / per_day * 7 / len(ctx.world["shift"]["workdays"])),
                }
            )
    ctx.emit("fluid_samples", pd.DataFrame(samples))
    ctx.emit("service_counters", pd.DataFrame(counters))

    slots = []
    rng = ctx.rng("technician_slots")
    comps = sorted(degr["components"])
    users = ctx.tables["users"].set_index("id")
    for tech in sorted(ctx.state["technicians"]):
        skills = [str(c) for c in rng.choice(comps, size=6, replace=False)]
        for off in range(-14, 15):
            d = ctx.anchor + timedelta(days=off)
            if not ctx.is_workday(d):
                continue
            slots.append(
                {
                    "id": f"TS-{tech}-{d.isoformat()}",
                    "technician_id": tech,
                    "site_id": users.loc[tech, "site_id"],
                    "start": ctx.local_dt(d, "08:00"),
                    "end": ctx.local_dt(d, "17:00"),
                    "skills": skills,
                }
            )
    ctx.emit("technician_slots", pd.DataFrame(slots))
