"""Causal task-execution model (§7.4). Pure: (task, machine, operator, start, world view, rng) → result.

Used by the history generator and by the start-time oracle (`oracle.simulate_task`, §7.4b), so the
optimiser is evaluated against exactly the process that generated the training data.
All timestamps inside are float seconds since the Unix epoch (UTC) for speed.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

import numpy as np

from terrapilot.datagen.weather import HourlyWeather

HOUR_S = 3600.0
EPS = 1e-9


@dataclass
class TaskSpec:
    id: str
    type: str
    machine_class: str
    quantity: float
    unit: str
    soil: str
    depth_m: float = 0.0
    haul_distance_m: float = 0.0
    grade_pct: float = 0.0
    planned_duration_s: float = HOUR_S


@dataclass
class MachineView:
    manifest: Any  # core.config_schema.Manifest
    health: dict[str, float]  # component → health at task start
    soc: float | None = None
    power_mode: str = "standard"


@dataclass
class OperatorView:
    skill: float
    idle_propensity: float
    aggression: float
    fatigue_susceptibility: float


@dataclass
class WorldView:
    wx: HourlyWeather
    moisture: np.ndarray  # hourly, same grid as wx
    trucks_missing: int
    shift_start_s: float
    shift_end_s: float
    overtime_max_s: float
    breaks: list[tuple[float, float]]
    charger_kw: float  # 0 when the site has no charger
    t0_s: float  # epoch seconds of wx.t0

    def hour_idx(self, t: float) -> int:
        return min(max(int((t - self.t0_s) // HOUR_S), 0), len(self.moisture) - 1)


@dataclass
class ExecResult:
    start_s: float
    end_s: float
    completed: bool
    progress_qty: float
    cycles: dict[str, np.ndarray]
    intervals: list[tuple[float, float, int]] = field(default_factory=list)  # (t0, t1, state) 1=idle 2=work 3=charge
    idle_episodes: list[tuple[float, float, bool, float]] = field(default_factory=list)  # t0, t1, high_rpm, fuel_l
    waits: list[tuple[float, float, str]] = field(default_factory=list)
    unsafe: list[tuple[float, float, str]] = field(default_factory=list)
    stoppage_s: float = 0.0
    wait_s: float = 0.0
    charge_stop_s: float = 0.0
    fuel_l: float = 0.0
    idle_fuel_l: float = 0.0
    kwh: float = 0.0
    soc_end: float | None = None
    soc_points: list[tuple[float, float]] = field(default_factory=list)
    charge_sessions: list[tuple[float, float, float, float, float]] = field(default_factory=list)
    fatigue_samples: list[tuple[float, float]] = field(default_factory=list)
    active_s: float = 0.0
    n_cycles: int = 0

    @property
    def duration_min(self) -> float:
        return (self.end_s - self.start_s) / 60.0


def fatigue_at(
    t: float, shift_start_s: float, shift_len_s: float, op: OperatorView, heat_index: float, fcfg: dict[str, Any]
) -> float:
    hours_frac = max(0.0, (t - shift_start_s) / shift_len_s)
    f = (
        op.fatigue_susceptibility
        * hours_frac ** fcfg["hours_exponent"]
        * (1 + fcfg["heat_k"] * max(0.0, heat_index - fcfg["heat_ref_c"]))
    )
    return float(min(max(f, 0.0), 1.0))


def _sigmoid(x: np.ndarray | float) -> np.ndarray | float:
    return 1 / (1 + np.exp(-x))


def cycle_multiplier(
    cls_cfg: dict[str, Any],
    soil: str,
    moisture: float,
    m_field: float,
    wxh: dict[str, float],
    op: OperatorView,
    fatigue: float,
    health: float,
) -> float:
    c = cls_cfg["t_cycle"]
    return float(
        c["soil_factor"][soil]
        * (1 + c["k_moist"] * c["soil_moisture_sensitivity"][soil] * max(0.0, moisture - m_field))
        * (1 + c["k_temp"] * max(0.0, wxh["temp_c"] - c["t_comfort_c"]))
        * (1 + c["k_rain"] * wxh["rain_mm"])
        * (1 + c["k_vis"] * (wxh["visibility_m"] < c["v_thresh_m"]))
        * (1 - c["k_skill"] * op.skill)
        * (1 + c["k_fatigue"] * fatigue)
        * (1 + c["k_health"] * (1 - health))
    )


def execute_task(
    task: TaskSpec,
    start_s: float,
    machine: MachineView,
    op: OperatorView,
    world: WorldView,
    dg: dict[str, Any],
    rng: np.random.Generator,
) -> ExecResult:
    cyc = dg["cycles"]
    beh = dg["behavior"]
    soils = dg["ground"]["soils"]
    m_field = soils[task.soil]["m_field"]
    density = cyc["material_density_t_m3"][task.soil]
    specs = machine.manifest.specs
    energy = machine.manifest.energy
    electric = machine.manifest.powertrain == "electric"
    cls = task.machine_class
    cls_cfg = cyc[cls]
    health = machine.health.get(cls_cfg["health_component"], 1.0)
    shift_len_s = world.shift_end_s - world.shift_start_s
    hard_end = world.shift_end_s + world.overtime_max_s
    hard = cyc["stoppages"]["hard_stop"]
    waits_cfg = cyc["waits"]
    idle_cfg = beh["idle"]
    floor = float(dg.get("_soc_floor", 0.15))
    batt_kwh = float(energy.get("battery_kwh", 0)) * float(energy.get("usable_fraction", 1.0))
    work_lph = float(specs.get("work_fuel_lph", {}).get(machine.power_mode, 0.0)) if not electric else 0.0
    idle_lph = float(specs.get("idle_fuel_lph", 0.0))
    cons = specs.get("consumption_kw", {})
    idle_kw = float(cons.get("idle", 0.0))

    # cycle kWh for electric machines from load-state shares
    shares = cyc.get(cls, {}).get("load_state_share", {"dig": 0.4, "swing": 0.4, "lift": 0.2})
    work_kw = sum(float(cons.get(k, 0.0)) * v for k, v in shares.items()) if electric else 0.0

    unsafe_cfg = {k: v for k, v in beh["unsafe_patterns"].items() if cls in v["classes"]}

    res = ExecResult(start_s=start_s, end_s=start_s, completed=False, progress_qty=0.0, cycles={})
    soc = machine.soc
    t = start_s
    remaining = task.quantity
    cols: dict[str, list[np.ndarray]] = {k: [] for k in ("ts", "cycle_s", "payload_t", "fill_factor", "fuel_l", "kwh")}
    fatigue_acc: list[float] = []

    # per-task invariants
    if cls == "excavator":
        base_s = cls_cfg["t_cycle"]["base_s"][task.type]
        swing = cls_cfg["swing_angle_deg"].get(task.type, 90)
        base_s *= 1 + cls_cfg["t_cycle"]["swing_k"] * (swing - 90)
        base_s *= 1 + cls_cfg["t_cycle"]["depth_k"] * max(0.0, task.depth_m - cls_cfg["t_cycle"]["depth_free_m"])
    elif cls == "wheel_loader":
        base_s = cls_cfg["t_cycle"]["base_s"][task.type]
    else:
        base_s = 0.0
    bucket_m3 = float(specs.get("bucket", {}).get("capacity_m3", 0.0))
    truck_waits = cls in ("excavator", "wheel_loader") and task.type in waits_cfg["truck"]["applies_to_types"]
    p_truck_wait = min(
        0.95,
        waits_cfg["truck"]["prob_wait_after_truck"]["base"]
        + waits_cfg["truck"]["prob_wait_after_truck"]["per_missing_truck"] * world.trucks_missing,
    )

    while remaining > EPS:
        if t >= hard_end:
            break
        # scheduled breaks: engine off, charge if possible
        brk = next(((b0, b1) for b0, b1 in world.breaks if b0 <= t < b1), None)
        if brk:
            res.waits.append((t, brk[1], "break"))
            if (
                electric
                and world.charger_kw > 0
                and soc is not None
                and (brk[1] - t) >= 60 * dg["cycles"]["electric"]["charge_at_breaks_min_break"]
            ):
                soc = _charge(res, t, brk[1], soc, world.charger_kw, energy, batt_kwh)
            t = brk[1]
            continue
        hi = world.hour_idx(t)
        wxh = {k: float(v[hi]) for k, v in world.wx.data.items()}
        if (
            wxh["lightning_km"] < hard["lightning_km_lt"]
            or wxh["gust_ms"] > hard["gust_ms_gt"]
            or wxh["rain_mm"] > hard["rain_mm_h_gt"]
        ):
            nxt = world.t0_s + (hi + 1) * HOUR_S + 60 * cyc["stoppages"]["resume_after_clear_min"] * 0.5
            res.stoppage_s += nxt - t
            res.waits.append((t, nxt, "weather_stop"))
            t = nxt
            continue
        next_break = min((b0 for b0, _ in world.breaks if b0 > t), default=math.inf)
        block_end = min(world.t0_s + (hi + 1) * HOUR_S, next_break, hard_end)
        fatigue = fatigue_at(t, world.shift_start_s, shift_len_s, op, wxh["heat_index"], cyc["fatigue"])
        fatigue_acc.append(fatigue)
        res.fatigue_samples.append((t, fatigue))
        moisture = float(world.moisture[hi])

        # electric: stop to charge if the next block would breach the floor
        if electric and soc is not None:
            block_kwh = work_kw * (block_end - t) / HOUR_S
            if soc - block_kwh / batt_kwh < floor and world.charger_kw > 0:
                dur = 60 * rng.uniform(
                    cyc["electric"]["mid_task_charge_min"]["min"], cyc["electric"]["mid_task_charge_min"]["max"]
                )
                soc = _charge(res, t, t + dur, soc, world.charger_kw, energy, batt_kwh)
                res.charge_stop_s += dur
                t += dur
                continue

        # ---- draw a batch of cycles for this block
        n = 64
        if cls == "adt":
            a = cls_cfg
            speed_mult = (
                (1 + a["road_moisture_k"] * a["road_soil_sensitivity"][task.soil] * max(0.0, moisture - m_field))
                * (1 + a["k_rain"] * wxh["rain_mm"])
                * (1 + a["k_vis"] * (wxh["visibility_m"] < a["v_thresh_m"]))
                * (1 - a["k_skill"] * op.skill)
                * (1 + a["k_fatigue"] * fatigue)
                * (1 + a["k_health"] * (1 - health))
            )
            v_loaded = a["speed_kph"]["loaded"] / 3.6 * (1 - a["grade_speed_k"] * task.grade_pct) / speed_mult
            v_empty = a["speed_kph"]["empty"] / 3.6 / speed_mult
            load = np.clip(rng.normal(a["load_time_s"]["mean"], a["load_time_s"]["sd"], n), 60, None)
            ct = (
                load + task.haul_distance_m / v_loaded + a["dump_time_s"] + task.haul_distance_m / v_empty
            ) * rng.lognormal(0, a["sigma"], n)
            payload_t = (
                np.clip(rng.normal(a["payload_t"]["mean_fraction_of_rated"], a["payload_t"]["sd"], n), 0.6, 1.15)
                * specs["rated_payload_t"]
            )
            qty = np.ones(n)
            fill = payload_t / specs["rated_payload_t"]
            gaps = np.zeros(n)
        else:
            mult = cycle_multiplier(cls_cfg, task.soil, moisture, m_field, wxh, op, fatigue, health)
            ct = base_s * mult * rng.lognormal(0, cls_cfg["t_cycle"]["sigma"], n)
            if cls == "wheel_loader":
                sp = cls_cfg["t_cycle"]["carry_speed_kph"]
                ct = ct + task.haul_distance_m / (sp["loaded"] / 3.6) + task.haul_distance_m / (sp["empty"] / 3.6)
            ff = cls_cfg["fill_factor"]
            fill = np.clip(
                ff["base"][task.soil] * (1 + ff["skill_k"] * (op.skill - 0.5)) * rng.normal(1, ff["sigma"], n), 0.4, 1.3
            )
            qty = bucket_m3 * fill
            payload_t = qty * density
            gaps = np.zeros(n)
            rep = cls_cfg.get("reposition")
            if rep:
                idx = np.arange(res.n_cycles + 1, res.n_cycles + n + 1)
                gaps += np.where(idx % rep["every_cycles"] == 0, rep["duration_s"], 0.0)
        # waits: trucks and radio calls; operator idles or shuts down
        wait = np.zeros(n)
        if truck_waits:
            passes = max(1, round(waits_cfg["truck"]["truck_payload_t"] / max(float(np.mean(payload_t)), 0.1)))
            idx = np.arange(res.n_cycles + 1, res.n_cycles + n + 1)
            after_truck = (idx % passes == 0) & (rng.random(n) < p_truck_wait)
            wait += np.where(
                after_truck,
                rng.lognormal(
                    waits_cfg["truck"]["wait_s"]["lognormal_mu"], waits_cfg["truck"]["wait_s"]["lognormal_sigma"], n
                ),
                0.0,
            )
        radio_p = waits_cfg["radio_call"]["per_hour"] * float(np.mean(ct)) / HOUR_S
        wait += np.where(
            rng.random(n) < radio_p,
            rng.uniform(waits_cfg["radio_call"]["wait_s"]["min"], waits_cfg["radio_call"]["wait_s"]["max"], n),
            0.0,
        )
        idles = (wait > 0) & (rng.random(n) < op.idle_propensity)
        tail = np.where(
            idles, rng.lognormal(idle_cfg["tail_s"]["lognormal_mu"], idle_cfg["tail_s"]["lognormal_sigma"], n), 0.0
        )
        gaps = gaps + wait + tail

        starts = t + np.concatenate([[0.0], np.cumsum(ct + gaps)[:-1]])
        cum_qty = np.cumsum(qty)
        keep = starts < block_end
        done_idx = np.searchsorted(cum_qty, remaining - EPS)
        if done_idx < n:
            keep &= np.arange(n) <= done_idx
        k = int(keep.sum())
        if k == 0:
            t = block_end
            continue
        ct, gaps, wait, tail, idles = ct[:k], gaps[:k], wait[:k], tail[:k], idles[:k]
        starts, qty, payload_t, fill = starts[:k], qty[:k], payload_t[:k], fill[:k]
        fuel = ct / HOUR_S * work_lph * cyc["fuel"]["load_factor_working"] if not electric else np.zeros(k)
        kwh = ct / HOUR_S * work_kw * _temp_factor(specs, wxh["temp_c"]) if electric else np.zeros(k)

        # idle/wait episodes (after each cycle)
        ends = starts + ct
        for i in np.flatnonzero(wait > 0):
            w0, w1 = float(ends[i]), float(ends[i] + wait[i] + tail[i])
            res.waits.append((w0, float(ends[i] + wait[i]), "truck_wait" if truck_waits else "radio"))
            res.wait_s += w1 - w0
            if idles[i]:
                high = bool(rng.random() < idle_cfg["high_rpm_prob"])
                ifuel = (w1 - w0) / HOUR_S * idle_lph * (idle_cfg["high_rpm_fuel_factor"] if high else 1.0)
                res.idle_episodes.append((w0, w1, high, ifuel))
                res.idle_fuel_l += ifuel
                res.intervals.append((w0, w1, 1))
                if electric and soc is not None:
                    soc -= idle_kw * (w1 - w0) / HOUR_S / batt_kwh
        res.intervals.append((float(starts[0]), float(ends[-1]), 2))

        # unsafe patterns per cycle: P = sigmoid(a + b·aggression + c·time_pressure)
        time_pressure = max(0.0, (t - start_s) / max(task.planned_duration_s, 1.0) - 1.0)
        for kind, u in unsafe_cfg.items():
            logit = u["a"] + u["b"] * op.aggression + u["c"] * time_pressure
            if kind == "relief_stall" and task.soil == "rock":
                logit += u.get("soil_rock_bonus", 0.0)
            if kind == "cavitation" and wxh["temp_c"] < 10:
                logit += u.get("cold_oil_bonus", 0.0)
            p = float(_sigmoid(logit))
            hits = np.flatnonzero(rng.random(k) < p)
            for i in hits:
                res.unsafe.append((float(starts[i]), float(starts[i] + u["duration_s"]), kind))

        for key, arr in (
            ("ts", starts),
            ("cycle_s", ct),
            ("payload_t", payload_t),
            ("fill_factor", fill),
            ("fuel_l", fuel),
            ("kwh", kwh),
        ):
            cols[key].append(arr)
        res.n_cycles += k
        res.fuel_l += float(fuel.sum())
        res.kwh += float(kwh.sum())
        res.active_s += float(ct.sum())
        if electric and soc is not None:
            soc -= float(kwh.sum()) / batt_kwh
            res.soc_points.append((float(ends[-1]), soc))
        done_qty = float(qty.sum())
        remaining -= done_qty
        res.progress_qty += done_qty
        t = float(starts[-1] + ct[-1] + gaps[-1])

    res.end_s = t
    res.completed = remaining <= EPS
    res.progress_qty = min(res.progress_qty, task.quantity)
    res.cycles = {k: (np.concatenate(v) if v else np.zeros(0)) for k, v in cols.items()}
    res.soc_end = soc
    res.fuel_l += res.idle_fuel_l
    return res


def _temp_factor(specs: dict[str, Any], temp_c: float) -> float:
    tc = specs.get("consumption_temp_coeff")
    if not tc:
        return 1.0
    delta = temp_c - tc["ref_c"]
    return float(1 + (tc["per_deg_below"] * -delta if delta < 0 else tc["per_deg_above"] * delta))


def _charge(
    res: ExecResult, t0: float, t1: float, soc: float, charger_kw: float, energy: dict[str, Any], batt_kwh: float
) -> float:
    """Charge with taper above `start_soc`; returns the new SoC and records the session."""
    taper = energy.get("charge_taper", {"start_soc": 0.8, "power_fraction_at_full": 0.25})
    eff = float(energy.get("charge_efficiency", 0.93))
    soc0 = soc
    steps = max(1, int((t1 - t0) // 60))
    dt_h = (t1 - t0) / steps / HOUR_S
    for _ in range(steps):
        frac = (
            1.0
            if soc < taper["start_soc"]
            else 1 - (1 - taper["power_fraction_at_full"]) * (soc - taper["start_soc"]) / (1 - taper["start_soc"])
        )
        soc = min(1.0, soc + charger_kw * frac * eff * dt_h / batt_kwh)
    res.charge_sessions.append((t0, t1, (soc - soc0) * batt_kwh, soc0, soc))
    res.intervals.append((t0, t1, 3))
    res.soc_points.append((t1, soc))
    return soc


def charge_minutes_to(soc0: float, target: float, charger_kw: float, energy: dict[str, Any], batt_kwh: float) -> float:
    """Minutes to charge from soc0 to target with the manifest's taper curve (§10.15.3)."""
    if target <= soc0:
        return 0.0
    taper = energy.get("charge_taper", {"start_soc": 0.8, "power_fraction_at_full": 0.25})
    eff = float(energy.get("charge_efficiency", 0.93))
    soc, minutes = soc0, 0
    while soc < target and minutes < 24 * 60:
        frac = (
            1.0
            if soc < taper["start_soc"]
            else 1 - (1 - taper["power_fraction_at_full"]) * (soc - taper["start_soc"]) / (1 - taper["start_soc"])
        )
        soc += charger_kw * frac * eff / 60 / batt_kwh
        minutes += 1
    return float(minutes)
