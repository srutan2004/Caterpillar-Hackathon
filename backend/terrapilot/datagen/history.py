"""History simulation (§7.3–§7.5): one pass over every workday, machine by machine.

Per machine-day: pick the operator → plan tasks → execute them with the causal model → accumulate
operating hours → degrade components (Weibull × acceleration factor) → faults, repairs, services →
derive behaviour/safety/energy records. Injected fault modes (with truth onset/detectable/failure)
are sampled up front and can break a machine down mid-history.
"""

from __future__ import annotations

import json
import math
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from typing import Any

import numpy as np
import pandas as pd

from terrapilot.datagen.context import GenContext
from terrapilot.datagen.execution import ExecResult, MachineView, OperatorView, TaskSpec, WorldView, execute_task
from terrapilot.datagen.fleet import MachineRt, age_for_health, health
from terrapilot.datagen.ground import rain_last_hours
from terrapilot.datagen.people import OperatorRt
from terrapilot.datagen.weather import HourlyWeather


def ts(t: float) -> pd.Timestamp:
    return pd.Timestamp(t, unit="s", tz="UTC")


def dt_utc(t: float) -> datetime:
    return datetime.fromtimestamp(t, UTC)


def epoch(dt: datetime) -> float:
    return dt.timestamp()


def sigmoid(x: float) -> float:
    return 1 / (1 + math.exp(-x))


@dataclass
class FaultModeRt:
    id: str
    machine_id: str
    mode: str
    component: str
    sensor_id: str
    onset_s: float
    ttf_s: float
    first_detectable_s: float | None
    failure_s: float
    resolved_s: float | None = None
    outcome: str = "active"
    cfg: dict[str, Any] = field(default_factory=dict)


def symptom_fraction(shape: str, x: np.ndarray | float) -> np.ndarray | float:
    x = np.clip(x, 0.0, 1.0)
    if shape == "ramp":
        return x
    if shape == "exponential":
        return (np.exp(3 * x) - 1) / (math.e**3 - 1)
    return np.where(np.asarray(x) > 0, 1.0, 0.0)


def _first_detectable(shape: str, magnitude: float, noise_sd: float, snr: float) -> float | None:
    target = snr * noise_sd / max(abs(magnitude), 1e-9)
    if target >= 1:
        return None
    if shape == "ramp":
        return target
    if shape == "exponential":
        return math.log(target * (math.e**3 - 1) + 1) / 3
    return 0.0


class History:
    def __init__(self, ctx: GenContext):
        self.ctx = ctx
        self.dg = ctx.dg
        self.cfg = ctx.cfg
        self.rng = ctx.rng("history")
        self.machines: dict[str, MachineRt] = ctx.state["machines"]
        self.operators: dict[str, OperatorRt] = ctx.state["operators"]
        self.primary: dict[str, str] = ctx.state["primary_operator"]
        self.dg["_soc_floor"] = float(ctx.cfg.app.energy["soc_floor"])
        self.rows: dict[str, list[dict[str, Any]]] = defaultdict(list)
        self.cycle_parts: list[pd.DataFrame] = []
        self.task_counter = 10000
        self.event_counter = 0
        self.pending_repairs: list[tuple[date, str, str, str]] = []  # (day, machine, component, fault code)
        self.failures: set[tuple[str, str, date]] = set()  # breakdowns, recorded in the truth table
        self.fault_modes: list[FaultModeRt] = []
        self.hour_meter_daily: dict[str, dict[date, float]] = defaultdict(dict)
        self.service_events: dict[tuple[str, str], list[tuple[float, float]]] = defaultdict(list)
        self.projects = self._projects()
        self.shift_cfg = ctx.world["shift"]
        self.breaks = [(float(b["at_h"]), float(b["minutes"])) for b in self.shift_cfg["breaks"]]
        self.utilisation = float(self.shift_cfg["length_h"]) / 24 * len(self.shift_cfg["workdays"]) / 7

    # ------------------------------------------------------------------ helpers
    def next_id(self, prefix: str) -> str:
        self.event_counter += 1
        return f"{prefix}-{self.event_counter:07d}"

    def _projects(self) -> dict[str, list[str]]:
        cfg = self.dg["tasks"]
        out: dict[str, list[str]] = {}
        rows = []
        for s in self.ctx.world["sites"]:
            n = int(self.rng.integers(cfg["projects_per_site"]["min"], cfg["projects_per_site"]["max"] + 1))
            ids = [cfg["id_format"]["project"].format(site=s["id"].removeprefix("site_"), n=i) for i in range(1, n + 1)]
            out[s["id"]] = ids
            rows += [
                {"id": pid, "site_id": s["id"], "name": f"{s['name']} — package {i}"} for i, pid in enumerate(ids, 1)
            ]
        self.ctx.emit("projects", pd.DataFrame(rows))
        return out

    def world_view(self, m: MachineRt, day: date, zone_id: str) -> WorldView:
        wx: HourlyWeather = self.ctx.state["wx"][m.site_id]
        start = self.ctx.shift_start(day)
        breaks = [
            (epoch(start + timedelta(hours=h)), epoch(start + timedelta(hours=h, minutes=mins)))
            for h, mins in self.breaks
        ]
        chargers = self.ctx.state["chargers_by_site"].get(m.site_id, [])
        kw_by_kind = m.manifest.energy.get("charge_power_kw_by_station", {})
        charger_kw = max((float(kw_by_kind.get(c["kind"], 0.0)) for c in chargers), default=0.0)
        return WorldView(
            wx=wx,
            moisture=self.ctx.state["moist"][zone_id],
            trucks_missing=self.ctx.state["trucks_missing"].get((m.site_id, day), 0),
            shift_start_s=epoch(start),
            shift_end_s=epoch(self.ctx.shift_end(day)),
            overtime_max_s=float(self.shift_cfg["overtime_max_h"]) * 3600,
            breaks=breaks,
            charger_kw=charger_kw,
            t0_s=epoch(wx.t0),
        )

    def health_now(self, m: MachineRt) -> dict[str, float]:
        return {c: health(self.ctx, c, a) for c, a in m.eff_age_h.items()}

    # ------------------------------------------------------------------ fault modes (sampled up front)
    def sample_fault_modes(self) -> None:
        degr = self.dg["degradation"]
        rng = self.ctx.rng("fault_modes")
        start = epoch(self.ctx.shift_start(self.ctx.first_day))
        end = epoch(self.ctx.now)
        op_hours = self.ctx.history_days * float(self.shift_cfg["length_h"]) * len(self.shift_cfg["workdays"]) / 7
        for m in self.machines.values():
            wx: HourlyWeather = self.ctx.state["wx"][m.site_id]
            pm_norm = degr["acceleration"]["pm10_norm"]
            dust = max(0.0, float(np.mean(wx.data["pm10"])) - pm_norm) / pm_norm
            for mode, mc in degr["fault_modes"].items():
                if m.cls not in mc["classes"] or m.powertrain not in mc["powertrains"]:
                    continue
                if not m.manifest.sensor(mc["sensor"]):
                    continue
                rate = mc["rate_per_1000h"] / 1000 * op_hours * (1 + mc.get("dust_rate_k", 0) * dust)
                for _ in range(int(rng.poisson(rate))):
                    onset = float(rng.uniform(start, end))
                    ttf_h = (
                        float(rng.uniform(mc["time_to_failure_h"]["min"], mc["time_to_failure_h"]["max"]))
                        / self.utilisation
                    )
                    self._add_fault_mode(m, mode, mc, onset, ttf_h * 3600, rng)
        for fx in (self.dg.get("demo_fixtures") or {}).get("active_fault_modes", []):
            pinned_m = self.machines.get(fx["machine"])
            if pinned_m is None:
                continue
            m = pinned_m
            mc = degr["fault_modes"][fx["mode"]]
            onset = epoch(self.ctx.now) - fx["onset_h_ago"] * 3600
            fm = self._add_fault_mode(m, fx["mode"], mc, onset, fx["time_to_failure_h"] * 3600, rng, pinned=True)
            fm.failure_s = max(fm.failure_s, epoch(self.ctx.now) + 3600)

    def _add_fault_mode(
        self,
        m: MachineRt,
        mode: str,
        mc: dict[str, Any],
        onset: float,
        ttf_s: float,
        rng: np.random.Generator,
        pinned: bool = False,
    ) -> FaultModeRt:
        degr = self.dg["degradation"]
        noise = degr["sensors"][mc["sensor"]].get("noise_sd", 0.5)
        x_det = _first_detectable(mc["shape"], float(mc["magnitude"]), float(noise), float(degr["detection_snr"]))
        det = onset + x_det * ttf_s if x_det is not None else None
        fm = FaultModeRt(
            id=self.next_id("FM"),
            machine_id=m.id,
            mode=mode,
            component=mc["component"],
            sensor_id=mc["sensor"],
            onset_s=onset,
            ttf_s=ttf_s,
            first_detectable_s=det,
            failure_s=onset + ttf_s,
            cfg=mc,
        )
        if not pinned and det is not None and rng.random() < degr["historical_fix_prob_before_failure"]:
            fix = det + 3600 * rng.uniform(
                degr["historical_fix_delay_h_after_detectable"]["min"],
                degr["historical_fix_delay_h_after_detectable"]["max"],
            )
            if fix < fm.failure_s:
                fm.resolved_s, fm.outcome = fix, "fixed_before_failure"
        self.fault_modes.append(fm)
        return fm

    # ------------------------------------------------------------------ task planning
    def plan_day(
        self, m: MachineRt, day: date, rng: np.random.Generator, planned_only: bool = False
    ) -> list[dict[str, Any]]:
        tcfg = self.dg["tasks"]
        site = self.ctx.site(m.site_id)
        choices = tcfg["task_types"][site["type"]].get(m.cls, [])
        if not choices:
            return []
        n = int(rng.integers(tcfg["tasks_per_machine_day"]["min"], tcfg["tasks_per_machine_day"]["max"] + 1))
        start = self.ctx.shift_start(day) + timedelta(minutes=15)
        latest_start = self.ctx.shift_end(day) - timedelta(
            hours=float(tcfg["start_variation"]["min_start_before_shift_end_h"])
        )
        zones = self.ctx.state["zones_by_site"][m.site_id]
        plan: list[dict[str, Any]] = []
        prev_id = None
        for _ in range(n):
            if start > latest_start:
                break
            w = np.array([c["w"] for c in choices], dtype=float)
            ttype = str(rng.choice([c["type"] for c in choices], p=w / w.sum()))
            q = tcfg["quantity"][ttype]
            qty = float(rng.integers(int(q["min"]), int(q["max"]) + 1))
            zone = (
                str(rng.choice(zones.get("haul") or zones["dig"])) if ttype == "haul" else str(rng.choice(zones["dig"]))
            )
            depth = float(rng.uniform(q["depth_m"]["min"], q["depth_m"]["max"])) if "depth_m" in q else None
            haul = (
                float(rng.uniform(q["haul_distance_m"]["min"], q["haul_distance_m"]["max"]))
                if "haul_distance_m" in q
                else None
            )
            grade = float(rng.uniform(q["grade_pct"]["min"], q["grade_pct"]["max"])) if "grade_pct" in q else None
            if ttype == "haul":
                rate = tcfg["planned_rate_per_h"]["haul_loads_per_h_per_km"] / max((haul or 1000) / 1000, 0.3)
            else:
                rate = tcfg["planned_rate_per_h"][ttype]
            planned_h = qty / rate * tcfg["planning_buffer"]
            end = start + timedelta(hours=planned_h)
            slack = float(rng.uniform(tcfg["deadline_slack_h"]["min"], tcfg["deadline_slack_h"]["max"]))
            pr = tcfg["priority"]
            self.task_counter += 1
            tid = tcfg["id_format"]["history"].format(n=self.task_counter)
            plan.append(
                {
                    "id": tid,
                    "project_id": str(rng.choice(self.projects[m.site_id])),
                    "site_id": m.site_id,
                    "zone_id": zone,
                    "machine_class": m.cls,
                    "type": ttype,
                    "quantity": qty,
                    "unit": q["unit"],
                    "depth_m": depth,
                    "haul_distance_m": haul,
                    "grade_pct": grade,
                    "design_ref": self.ctx.state["design_surface_by_zone"].get(zone),
                    "planned_start": start,
                    "planned_end": end,
                    "deadline": end + timedelta(hours=slack),
                    "priority": int(rng.choice(pr["values"], p=np.array(pr["weights"]) / sum(pr["weights"]))),
                    "depends_on": [prev_id] if prev_id and rng.random() < tcfg["dependency_prob"] else [],
                    "status": "planned",
                    "assigned_operator_id": None,
                    "assigned_machine_id": m.id,
                }
            )
            prev_id = tid
            start = end + timedelta(
                minutes=float(
                    rng.uniform(
                        self.dg["cycles"]["waits"]["changeover_min"]["min"],
                        self.dg["cycles"]["waits"]["changeover_min"]["max"],
                    )
                )
            )
        return plan

    def pick_operator(self, m: MachineRt, used: set[str], rng: np.random.Generator) -> OperatorRt:
        primary = self.operators[self.primary[m.id]]
        if primary.id not in used and rng.random() < 0.85:
            return primary
        pool = [
            o for o in self.operators.values() if o.site_id == m.site_id and m.cls in o.classes and o.id not in used
        ]
        return pool[int(rng.integers(len(pool)))] if pool else primary

    # ------------------------------------------------------------------ main loop
    def run(self) -> None:
        ctx = self.ctx
        self.sample_fault_modes()
        rng_trucks = ctx.rng("trucks")
        breakdown = self.dg["forecasts"]["truck_availability"]["breakdown_prob_per_day"]
        ctx.state["trucks_missing"] = {
            (s["id"], d): int(rng_trucks.binomial(s["truck_count"], breakdown))
            for s in ctx.world["sites"]
            for d in [*ctx.history_dates(), ctx.anchor, ctx.anchor + timedelta(days=1)]
        }
        for day in ctx.history_dates():
            for m in self.machines.values():
                self.hour_meter_daily[m.id][day] = m.hour_meter
            if ctx.is_workday(day):
                used: set[str] = set()
                for mid in sorted(self.machines):
                    self.run_machine_day(self.machines[mid], day, used)
            for m in self.machines.values():
                self.record_health(m, day)
        self.plan_future()
        self.finish()

    def run_machine_day(self, m: MachineRt, day: date, used: set[str]) -> None:
        ctx = self.ctx
        rng = ctx.rng(f"day:{m.id}:{day.isoformat()}")
        shift_start = ctx.shift_start(day)
        self.apply_pending_repairs(m, day)
        self.check_fault_mode_failures(m, day)
        if m.down_until and m.down_until > shift_start + timedelta(hours=2):
            return
        op = self.pick_operator(m, used, rng)
        used.add(op.id)
        plan = self.plan_day(m, day, rng)
        if not plan:
            return
        self.rows["shift_assignments"].append(
            {
                "id": f"SA-{m.id}-{day.isoformat()}",
                "date": day,
                "operator_id": op.id,
                "machine_id": m.id,
                "site_id": m.site_id,
                "shift_start": shift_start,
                "shift_end": ctx.shift_end(day),
            }
        )
        opv = OperatorView(
            skill=op.skill,
            idle_propensity=op.idle_propensity,
            aggression=op.aggression,
            fatigue_susceptibility=op.fatigue_susceptibility,
        )
        # morning energy state
        ecfg = self.dg["cycles"]["electric"]
        refuel_l = 0.0
        fuel_start_pct = None
        if m.powertrain == "electric":
            if rng.random() < ecfg["low_soc_start_prob"]:
                m.soc = float(rng.uniform(*ecfg["low_soc_start_range"]))
            else:
                m.soc = float(ecfg["overnight_target_soc"])
            self.rows["charging_sessions"].append(
                {
                    "id": self.next_id("CS"),
                    "machine_id": m.id,
                    "station_id": None,
                    "start": shift_start - timedelta(hours=9),
                    "end": shift_start - timedelta(hours=1),
                    "kwh": None,
                    "start_soc": None,
                    "end_soc": round(m.soc, 3),
                    "planned_by_schedule_id": None,
                }
            )
        else:
            tank = float(m.manifest.energy.get("tank_l", 400))
            threshold = self.cfg.planning.start_time["preconditions"]["refuel_if_below_pct"] / 100
            if (m.fuel_l or 0) < threshold * tank:
                refuel_l = tank - (m.fuel_l or 0)
                m.fuel_l = tank
            fuel_start_pct = (m.fuel_l or 0) / tank
        mode_share = self.dg["cycles"]["fuel"]["mode_share"]
        power_mode = str(rng.choice(list(mode_share), p=np.array(list(mode_share.values())) / sum(mode_share.values())))

        t_prev_end = None
        day_fuel = day_idle_fuel = 0.0
        day_active = 0.0
        day_unsafe = 0
        day_cycles = 0
        duty: list[tuple[str, str, float]] = []
        fatigue_vals: list[float] = []
        wx: HourlyWeather = ctx.state["wx"][m.site_id]
        stop_rest = False
        for task in plan:
            task["assigned_operator_id"] = op.id
            if stop_rest:
                task["status"] = "carried_over"
                self.rows["tasks"].append(task)
                continue
            tv = self.dg["tasks"]["start_variation"]
            start = task["planned_start"] + timedelta(
                minutes=float(rng.normal(tv["normal_offset_min"]["mean"], tv["normal_offset_min"]["sd"]))
            )
            rain12 = rain_last_hours(wx, task["planned_start"], tv["rain_delay"]["lookback_h"])
            if rain12 > tv["rain_delay"]["rain_mm_threshold"] and rng.random() < tv["rain_delay"]["prob"]:
                start += timedelta(
                    minutes=float(
                        rng.uniform(tv["rain_delay"]["delay_min"]["min"], tv["rain_delay"]["delay_min"]["max"])
                    )
                )
            elif rng.random() < tv["early_start"]["prob"]:
                start -= timedelta(
                    minutes=float(
                        rng.uniform(tv["early_start"]["advance_min"]["min"], tv["early_start"]["advance_min"]["max"])
                    )
                )
            start = max(start, shift_start)
            if t_prev_end is not None:
                start = max(start, t_prev_end + timedelta(minutes=float(rng.uniform(10, 20))))
            world = self.world_view(m, day, task["zone_id"])
            hnow = self.health_now(m)
            soil = ctx.state["zone_soil"][task["zone_id"]]
            spec = TaskSpec(
                id=task["id"],
                type=task["type"],
                machine_class=m.cls,
                quantity=task["quantity"],
                unit=task["unit"],
                soil=soil,
                depth_m=task["depth_m"] or 0.0,
                haul_distance_m=task["haul_distance_m"] or 0.0,
                grade_pct=task["grade_pct"] or 0.0,
                planned_duration_s=(task["planned_end"] - task["planned_start"]).total_seconds(),
            )
            # supervisor sometimes charges a low machine before starting (natural start-time variation)
            if (
                m.powertrain == "electric"
                and m.soc is not None
                and m.soc < 0.5
                and world.charger_kw > 0
                and rng.random() < 0.5
            ):
                from terrapilot.datagen.execution import ExecResult as _ER
                from terrapilot.datagen.execution import _charge

                pre = _ER(start_s=epoch(start), end_s=epoch(start), completed=True, progress_qty=0, cycles={})
                dur = 60 * float(rng.uniform(25, 45))
                m.soc = _charge(
                    pre,
                    epoch(start),
                    epoch(start) + dur,
                    m.soc,
                    world.charger_kw,
                    m.manifest.energy,
                    float(m.manifest.energy["battery_kwh"]) * float(m.manifest.energy.get("usable_fraction", 1)),
                )
                self._record_charges(m, pre)
                start = start + timedelta(seconds=dur)
            self.rows["task_start_context"].append(
                {
                    "task_id": task["id"],
                    "soc": round(m.soc, 3) if m.soc is not None else None,
                    "fuel_pct": round(fuel_start_pct, 3) if fuel_start_pct is not None else None,
                    # estimated health index of the productivity-critical component (what a health model would report)
                    "health_index": round(
                        float(hnow.get(self.dg["cycles"][m.cls]["health_component"], 1.0)) + float(rng.normal(0, 0.02)),
                        3,
                    ),
                    "open_alerts": len(m.faults_open),
                    "ground_moisture": round(float(world.moisture[world.hour_idx(epoch(start))]), 4),
                    "rain_last_12h_mm": round(rain_last_hours(wx, start, 12), 2),
                    "forecast_ref": f"FC-{m.site_id}-{day.isoformat()}",
                }
            )
            mv = MachineView(manifest=m.manifest, health=hnow, soc=m.soc, power_mode=power_mode)
            res = execute_task(spec, epoch(start), mv, opv, world, self.dg, ctx.rng(f"exec:{task['id']}"))
            if m.powertrain == "electric":
                m.soc = res.soc_end
            else:
                m.fuel_l = max(0.0, (m.fuel_l or 0) - res.fuel_l)
            task.update(
                {
                    "actual_start": start,
                    "actual_end": dt_utc(res.end_s),
                    "duration_min": round(res.duration_min, 2),
                    "progress_qty": round(res.progress_qty, 2),
                    "status": "completed" if res.completed else "carried_over",
                }
            )
            self.rows["tasks"].append(task)
            self.rows["truth_task_execution"].append(
                {
                    "task_id": task["id"],
                    "skill": op.skill,
                    "fatigue_mean": round(float(np.mean([f for _, f in res.fatigue_samples] or [0])), 4),
                    "health_index": round(float(hnow.get(self.dg["cycles"][m.cls]["health_component"], 1.0)), 4),
                    "wait_min": round(res.wait_s / 60, 2),
                    "stoppage_min": round(res.stoppage_s / 60, 2),
                    "charge_stop_min": round(res.charge_stop_s / 60, 2),
                    "n_cycles": res.n_cycles,
                }
            )
            self._record_cycles(m, op, task, res, soil)
            self._record_behaviour(m, op, task, res)
            self._record_charges(m, res)
            m.activity.extend(res.intervals)
            m.soc_points.extend(res.soc_points)
            for t0, t1, kind in res.waits:
                if t1 - t0 >= 120:
                    self.rows["idle_windows"].append(
                        {"id": self.next_id("IW"), "machine_id": m.id, "start": ts(t0), "end": ts(t1), "kind": kind}
                    )
            fatigue_vals += [f for _, f in res.fatigue_samples]
            self.ctx.state.setdefault("fatigue_truth", []).extend((op.id, m.id, t, f) for t, f in res.fatigue_samples)
            day_fuel += res.fuel_l
            day_idle_fuel += res.idle_fuel_l
            day_active += res.active_s + sum(t1 - t0 for t0, t1, *_ in res.idle_episodes)
            day_unsafe += len(res.unsafe)
            day_cycles += res.n_cycles
            duty.append((task["type"], soil, res.active_s))
            t_prev_end = dt_utc(res.end_s)
            if not res.completed:
                stop_rest = True

        op_hours = day_active / 3600
        m.hour_meter += op_hours
        self.rows["fuel_log"].append(
            {
                "id": f"FL-{m.id}-{day.isoformat()}",
                "machine_id": m.id,
                "date": day,
                "fuel_l": round(day_fuel, 2) if m.powertrain != "electric" else None,
                "idle_fuel_l": round(day_idle_fuel, 2) if m.powertrain != "electric" else None,
                "refuel_l": round(refuel_l, 1) if m.powertrain != "electric" else None,
                "fuel_pct_start": round(fuel_start_pct, 3) if fuel_start_pct is not None else None,
                "fuel_pct_end": round((m.fuel_l or 0) / float(m.manifest.energy.get("tank_l", 400)), 3)
                if m.powertrain != "electric"
                else None,
            }
        )
        self.ctx.state.setdefault("operator_days", []).append(
            {
                "operator_id": op.id,
                "machine_id": m.id,
                "date": day,
                "active_s": day_active,
                "unsafe": day_unsafe,
                "cycles": day_cycles,
                "fatigue_mean": float(np.mean(fatigue_vals)) if fatigue_vals else 0.0,
                "site_id": m.site_id,
            }
        )
        self.degrade(m, day, op_hours, duty, day_unsafe / max(day_cycles, 1))
        self.check_health_faults(m, day, rng)
        self.check_services(m, day, rng)

    # ------------------------------------------------------------------ recorders
    def _record_cycles(self, m: MachineRt, op: OperatorRt, task: dict[str, Any], res: ExecResult, soil: str) -> None:
        c = res.cycles
        if not len(c["ts"]):
            return
        split = self.dg["cycles"].get(m.cls, {}).get("phase_split")
        phases: list[str | None]
        if split:
            phases = [json.dumps({k: round(float(v) * s, 1) for k, v in split.items()}) for s in c["cycle_s"]]
        else:
            phases = [None] * len(c["ts"])
        self.cycle_parts.append(
            pd.DataFrame(
                {
                    "ts": pd.to_datetime(c["ts"], unit="s", utc=True),
                    "machine_id": m.id,
                    "operator_id": op.id,
                    "task_id": task["id"],
                    "cycle_s": np.round(c["cycle_s"], 2),
                    "phase_durations": phases,
                    "payload_t": np.round(c["payload_t"], 3),
                    "fill_factor": np.round(c["fill_factor"], 3),
                    "fuel_l": np.round(c["fuel_l"], 4) if m.powertrain != "electric" else np.nan,
                    "kwh": np.round(c["kwh"], 4) if m.powertrain == "electric" else np.nan,
                    "soil": soil,
                    "depth_m": task["depth_m"],
                }
            )
        )

    def _record_behaviour(self, m: MachineRt, op: OperatorRt, task: dict[str, Any], res: ExecResult) -> None:
        beh = self.dg["behavior"]
        rng = self.ctx.rng(f"detect:{task['id']}")
        recall = beh["detection"]["recall"]
        costs = self.cfg.app.costs
        min_idle = float(m.manifest.idle["min_episode_s"])
        events: list[tuple[float, float, str, dict[str, Any], dict[str, Any]]] = []
        for t0, t1, high, fuel in res.idle_episodes:
            if t1 - t0 < min_idle:
                continue
            kind = "high_rpm_idle" if high else "idle"
            cost = (
                {
                    "fuel_l": round(fuel, 3),
                    "cost": round(fuel * costs["diesel_price_per_l"], 2),
                    "co2_kg": round(fuel * costs["co2_kg_per_l_diesel"], 3),
                }
                if m.powertrain != "electric"
                else {}
            )
            events.append((t0, t1, kind, {"duration_s": round(t1 - t0, 1)}, cost))
        for t0, t1, kind in res.unsafe:
            events.append((t0, t1, kind, {}, {}))
        for t0, t1, kind, metrics, cost in events:
            label_id = self.next_id("TL")
            detected_id = None
            if rng.random() < recall.get(kind, 0.9):
                detected_id = self.next_id("BE")
                self.rows["behavior_events"].append(
                    {
                        "id": detected_id,
                        "machine_id": m.id,
                        "operator_id": op.id,
                        "task_id": task["id"],
                        "kind": kind,
                        "start_ts": ts(t0),
                        "end_ts": ts(t1),
                        "metrics": json.dumps(metrics),
                        "cost": json.dumps(cost),
                        "detector": "rule",
                        "score": None,
                    }
                )
            self.rows["truth_behavior_labels"].append(
                {
                    "id": label_id,
                    "machine_id": m.id,
                    "operator_id": op.id,
                    "kind": kind,
                    "start_ts": ts(t0),
                    "end_ts": ts(t1),
                    "detected_event_id": detected_id,
                }
            )
            if kind == "over_slope":
                self.rows["alerts"].append(
                    {
                        "id": self.next_id("AL"),
                        "machine_id": m.id,
                        "rule_id": "SIDE_SLOPE",
                        "severity": "caution",
                        "opened_at": ts(t0),
                        "escalated_at": None,
                        "cleared_at": ts(t1),
                        "acked_by": op.id,
                        "context": json.dumps({"task_id": task["id"]}),
                    }
                )
        for kind, rate in beh["detection"]["false_positive_per_shift"].items():
            if (
                kind in beh["unsafe_patterns"]
                and m.cls in beh["unsafe_patterns"][kind]["classes"]
                and rng.random() < rate / 3
                and len(res.cycles["ts"])
            ):
                t0 = float(rng.choice(res.cycles["ts"]))
                self.rows["behavior_events"].append(
                    {
                        "id": self.next_id("BE"),
                        "machine_id": m.id,
                        "operator_id": op.id,
                        "task_id": task["id"],
                        "kind": kind,
                        "start_ts": ts(t0),
                        "end_ts": ts(t0 + 2),
                        "metrics": json.dumps({}),
                        "cost": json.dumps({}),
                        "detector": "rule",
                        "score": None,
                    }
                )

    def _record_charges(self, m: MachineRt, res: ExecResult) -> None:
        for t0, t1, kwh, soc0, soc1 in res.charge_sessions:
            chargers: list[dict[str, Any]] = self.ctx.state["chargers_by_site"].get(m.site_id, [])
            station = chargers[0]["id"] if chargers else None
            self.rows["charging_sessions"].append(
                {
                    "id": self.next_id("CS"),
                    "machine_id": m.id,
                    "station_id": station,
                    "start": ts(t0),
                    "end": ts(t1),
                    "kwh": round(kwh, 2),
                    "start_soc": round(soc0, 3),
                    "end_soc": round(soc1, 3),
                    "planned_by_schedule_id": None,
                }
            )
            m.activity.append((t0, t1, 3))

    # ------------------------------------------------------------------ degradation, faults, maintenance
    def degrade(
        self, m: MachineRt, day: date, op_hours: float, duty: list[tuple[str, str, float]], abuse: float
    ) -> None:
        if op_hours <= 0:
            return
        acc = self.dg["degradation"]["acceleration"]
        wx: HourlyWeather = self.ctx.state["wx"][m.site_id]
        s0, s1 = self.ctx.shift_start(day), self.ctx.shift_end(day)
        temp, pm10, rh = wx.window_mean(s0, s1, "temp_c"), wx.window_mean(s0, s1, "pm10"), wx.window_mean(s0, s1, "rh")
        total = sum(d[2] for d in duty) or 1.0
        duty_sev = sum(acc["duty_severity_by_task"].get(t, 1.0) * a for t, _, a in duty) / total
        soil_sev = sum(acc["soil_severity"].get(s, 1.0) * a for _, s, a in duty) / total
        af = (
            math.exp(acc["alpha_T"] * (temp - acc["t_ref_c"]))
            * (1 + acc["alpha_dust"] * pm10 / acc["pm10_norm"])
            * (1 + acc["alpha_hum"] * rh / 100)
            * (1 + acc["alpha_alt"] * self.ctx.site(m.site_id)["altitude_m"] / 1000)
            * duty_sev
            * soil_sev
            * (1 + acc["alpha_abuse"] * abuse * 100)
        )
        for comp in m.eff_age_h:
            m.eff_age_h[comp] += op_hours * af
        self.ctx.state.setdefault("af_daily", {})[(m.id, day)] = (af, temp, pm10)

    def record_health(self, m: MachineRt, day: date) -> None:
        af = self.ctx.state.get("af_daily", {}).get((m.id, day))
        for comp, age in m.eff_age_h.items():
            h = health(self.ctx, comp, age)
            self.rows["truth_component_health"].append(
                {
                    "date": day,
                    "machine_id": m.id,
                    "component": comp,
                    "health": round(h, 4),
                    "age_h": round(age, 1),
                    "failed": h <= self.dg["degradation"]["components"][comp]["h_fail"]
                    or (m.id, comp, day) in self.failures,
                    "temp_mean": af[1] if af else None,
                    "dust_pm10_mean": af[2] if af else None,
                }
            )

    def _fault_event(self, m: MachineRt, code: str, when: datetime) -> None:
        if code in m.faults_open:
            return
        m.faults_open.add(code)
        self.rows["fault_events"].append(
            {
                "id": self.next_id("FE"),
                "machine_id": m.id,
                "code": code,
                "ts": when,
                "cleared_ts": None,
                "occurrences": 1,
            }
        )

    def _clear_faults(self, m: MachineRt, codes: set[str], when: datetime) -> None:
        for row in reversed(self.rows["fault_events"]):
            if row["machine_id"] == m.id and row["code"] in codes and row["cleared_ts"] is None:
                row["cleared_ts"] = when
        m.faults_open -= codes

    def check_health_faults(self, m: MachineRt, day: date, rng: np.random.Generator) -> None:
        comps = self.dg["degradation"]["components"]
        maint = self.dg["degradation"]["maintenance"]
        when = self.ctx.shift_start(day) + timedelta(hours=float(rng.uniform(1, 9)))
        for comp, age in m.eff_age_h.items():
            h = health(self.ctx, comp, age)
            spec = comps[comp]
            if h <= spec["h_fail"]:
                code = spec["faults"][-1]["code"] if spec["faults"] else None
                if code:
                    self._fault_event(m, code, when)
                self.repair(m, comp, when, "major", code, rng, breakdown=True)
                continue
            for f in spec["faults"]:
                if h < f["h_below"] and f["code"] not in m.faults_open:
                    self._fault_event(m, f["code"], when)
                    if rng.random() < maint["corrective_on_fault_prob"]:
                        delay = int(
                            rng.integers(
                                maint["corrective_delay_days"]["min"], maint["corrective_delay_days"]["max"] + 1
                            )
                        )
                        self.pending_repairs.append((day + timedelta(days=delay), m.id, comp, f["code"]))

    def apply_pending_repairs(self, m: MachineRt, day: date) -> None:
        rng = self.ctx.rng(f"repair:{m.id}:{day.isoformat()}")
        due = [r for r in self.pending_repairs if r[1] == m.id and r[0] <= day]
        for r in due:
            self.pending_repairs.remove(r)
            when = self.ctx.shift_start(day) - timedelta(hours=float(rng.uniform(1, 12)))
            self.repair(m, r[2], when, "minor", r[3], rng)

    def check_fault_mode_failures(self, m: MachineRt, day: date) -> None:
        rng = self.ctx.rng(f"fm:{m.id}:{day.isoformat()}")
        day_end = epoch(self.ctx.shift_end(day))
        day_start = epoch(self.ctx.shift_start(day)) - 86400
        for fm in self.fault_modes:
            if fm.machine_id != m.id or fm.outcome != "active":
                continue
            if fm.first_detectable_s and day_start < fm.first_detectable_s + 6 * 3600 <= day_end:
                self._fault_event(m, fm.cfg["detect_code"], dt_utc(fm.first_detectable_s + 6 * 3600))
            if fm.resolved_s and fm.resolved_s <= day_end:
                self.repair(m, fm.component, dt_utc(fm.resolved_s), "minor", fm.cfg["detect_code"], rng, reset=False)
                fm.outcome = "fixed_before_failure"
            elif fm.failure_s <= day_end and fm.failure_s < epoch(self.ctx.now):
                when = dt_utc(fm.failure_s)
                self._fault_event(m, fm.cfg["failure_code"], when)
                dt = self.repair(
                    m, fm.component, when, "major", fm.cfg["failure_code"], rng, breakdown=True, reset=False
                )
                fm.resolved_s = epoch(when) + dt * 3600
                fm.outcome = "failed"

    def repair(
        self,
        m: MachineRt,
        comp: str,
        when: datetime,
        work_type: str,
        code: str | None,
        rng: np.random.Generator,
        breakdown: bool = False,
        reset: bool = True,
    ) -> float:
        costs = self.cfg.costs
        maint = self.dg["degradation"]["maintenance"]
        techs = self.ctx.state["technicians"]
        tech = sorted(techs)[int(rng.integers(len(techs)))]
        base = float(costs["repair_durations"].get(comp, {}).get(work_type, 4.0))
        duration = (
            base
            * max(0.4, 1 - maint["technician_experience_k"] * math.sqrt(techs[tech]))
            * float(rng.lognormal(0, maint["duration_noise_sigma"]))
        )
        fault = self.cfg.fault(code) if code else None
        part_nos = list(fault.part_numbers) if fault else []
        parts = {p.part_no: p for p in self.cfg.parts}
        wait_h = 0.0
        for pn in part_nos:
            p = parts.get(pn)
            if p and p.stock == 0:
                wait_h = max(wait_h, p.lead_time_days * 24 * maint["part_wait_factor"])
        travel = float(costs["site_remoteness_travel_h"].get(m.site_id, 1.0))
        downtime = duration + travel + (wait_h if breakdown else 0.0)
        self.rows["maintenance_records"].append(
            {
                "id": self.next_id("MR"),
                "machine_id": m.id,
                "component_id": f"{m.id}-{comp}",
                "component": comp,
                "ts": when,
                "kind": "corrective",
                "work_type": work_type,
                "work_done": f"{work_type} repair of {comp}" + (f" ({code})" if code else ""),
                "parts": part_nos,
                "fault_code": code,
                "technician_id": tech,
                "duration_h": round(duration, 2),
                "downtime_h": round(downtime, 2),
                "labour_cost": round(duration * costs["labour_rate_per_h"]["technician"], 0),
                "parts_cost": round(sum(parts[p].price for p in part_nos if p in parts), 0),
            }
        )
        if reset or breakdown:
            h_new = float(rng.uniform(maint["h_reset"]["min"], maint["h_reset"]["max"]))
            m.eff_age_h[comp] = age_for_health(self.ctx, comp, h_new)
        codes = {f["code"] for f in self.dg["degradation"]["components"][comp]["faults"]}
        if code:
            codes.add(code)
        self._clear_faults(m, codes, when + timedelta(hours=downtime))
        if breakdown:
            until = when + timedelta(hours=downtime)
            m.down_until = max(m.down_until or until, until)
            self.failures.add((m.id, comp, pd.Timestamp(when).tz_convert(self.ctx.tz).date()))
        return float(downtime)

    def check_services(self, m: MachineRt, day: date, rng: np.random.Generator) -> None:
        restore = self.dg["degradation"]["maintenance"]["service_restore"]
        for item in self.cfg.service_intervals.get(m.manifest.id, []):
            last = m.service_last_h.get(item["item"], 0.0)
            if m.hour_meter - last < item["every_h"]:
                continue
            when = self.ctx.shift_end(day) + timedelta(minutes=30)
            techs = sorted(self.ctx.state["technicians"])
            dur = item["est_h"] * float(rng.lognormal(0, 0.15))
            self.rows["maintenance_records"].append(
                {
                    "id": self.next_id("MR"),
                    "machine_id": m.id,
                    "component_id": None,
                    "component": None,
                    "ts": when,
                    "kind": "scheduled",
                    "work_type": item["item"],
                    "work_done": ", ".join(item["work"]),
                    "parts": [],
                    "fault_code": None,
                    "technician_id": techs[int(rng.integers(len(techs)))],
                    "duration_h": round(dur, 2),
                    "downtime_h": round(dur, 2),
                    "labour_cost": round(dur * self.cfg.costs["labour_rate_per_h"]["technician"], 0),
                    "parts_cost": None,
                }
            )
            m.service_last_h[item["item"]] = m.hour_meter
            self.service_events[(m.id, item["item"])].append((epoch(when), m.hour_meter))
            for comp, dh in restore.get(item["item"], {}).items():
                if comp in m.eff_age_h:
                    h = min(0.99, health(self.ctx, comp, m.eff_age_h[comp]) + dh)
                    m.eff_age_h[comp] = age_for_health(self.ctx, comp, h)

    # ------------------------------------------------------------------ future plan (today + tomorrow)
    def plan_future(self) -> None:
        ctx = self.ctx
        fixtures = (self.dg.get("demo_fixtures") or {}).get("today_tasks", [])
        pinned_machines = {t["machine"] for t in fixtures if t.get("machine")}
        for offset in (0, 1):
            day = ctx.anchor + timedelta(days=offset)
            if not ctx.is_workday(day):
                continue
            for mid in sorted(self.machines):
                m = self.machines[mid]
                if offset == 0 and mid in pinned_machines:
                    continue
                rng = ctx.rng(f"future:{mid}:{day.isoformat()}")
                for task in self.plan_day(m, day, rng, planned_only=True):
                    task["assigned_operator_id"] = self.primary.get(mid)
                    self.rows["tasks"].append(task)
        for t in fixtures:
            site = t["site"]
            fx_machine = self.machines.get(t["machine"]) if t.get("machine") else None
            cls = fx_machine.cls if fx_machine else "excavator"
            ttype = t["type"]
            q = self.dg["tasks"]["quantity"][ttype]
            rate = self.dg["tasks"]["planned_rate_per_h"][ttype]
            start = ctx.local_dt(ctx.anchor, t["planned_start_local"])
            zones = ctx.state["zones_by_site"][site]["dig"]
            zone = next(
                (z for z, ds in ctx.state["design_surface_by_zone"].items() if ds == t.get("design_ref")), zones[0]
            )
            self.rows["tasks"].append(
                {
                    "id": t["id"],
                    "project_id": self.projects[site][0],
                    "site_id": site,
                    "zone_id": zone,
                    "machine_class": cls,
                    "type": ttype,
                    "quantity": float(t["quantity"]),
                    "unit": q["unit"],
                    "depth_m": t.get("depth_m"),
                    "haul_distance_m": None,
                    "grade_pct": None,
                    "design_ref": t.get("design_ref"),
                    "planned_start": start,
                    "planned_end": start
                    + timedelta(hours=float(t["quantity"]) / rate * self.dg["tasks"]["planning_buffer"]),
                    "deadline": ctx.local_dt(ctx.anchor, t["deadline_local"]),
                    "priority": int(t["priority"]),
                    "depends_on": [],
                    "status": "planned",
                    "assigned_operator_id": t.get("operator"),
                    "assigned_machine_id": t.get("machine"),
                }
            )
        for mid, state in (self.dg.get("demo_fixtures") or {}).get("machine_states_now", {}).items():
            if mid in self.machines and "soc" in state:
                self.machines[mid].soc = float(state["soc"])
                self.machines[mid].soc_points.append((epoch(ctx.now), float(state["soc"])))

    # ------------------------------------------------------------------ output
    def finish(self) -> None:
        ctx = self.ctx
        if self.cycle_parts:
            ctx.emit("cycles", pd.concat(self.cycle_parts, ignore_index=True))
        for name, rows in self.rows.items():
            df = pd.DataFrame(rows)
            if name == "truth_component_health":
                ctx.state["health_daily"] = df.copy()
                df = df.drop(columns=["temp_mean", "dust_pm10_mean"])
            ctx.emit(name, df)
        fm_rows = []
        for fm in self.fault_modes:
            fm_rows.append(
                {
                    "id": fm.id,
                    "machine_id": fm.machine_id,
                    "mode": fm.mode,
                    "component": fm.component,
                    "sensor_id": fm.sensor_id,
                    "onset": ts(fm.onset_s),
                    "first_detectable": ts(fm.first_detectable_s) if fm.first_detectable_s else None,
                    "failure_time": ts(fm.failure_s),
                    "resolved_at": ts(fm.resolved_s) if fm.resolved_s else None,
                    "outcome": fm.outcome,
                }
            )
        ctx.emit(
            "truth_fault_modes",
            pd.DataFrame(
                fm_rows,
                columns=[
                    "id",
                    "machine_id",
                    "mode",
                    "component",
                    "sensor_id",
                    "onset",
                    "first_detectable",
                    "failure_time",
                    "resolved_at",
                    "outcome",
                ],
            ),
        )
        ctx.state["fault_modes"] = self.fault_modes
        ctx.state["hour_meter_daily"] = self.hour_meter_daily
        ctx.state["service_events"] = self.service_events


def simulate_history(ctx: GenContext) -> None:
    History(ctx).run()
