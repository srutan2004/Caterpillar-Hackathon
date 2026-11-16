"""Machine simulator + scenario timeline player (§7.6).

Excavator motion is produced by inverse kinematics on bucket-tip keyframes, so the edge's forward
kinematics, grade and geofence maths see physically consistent inputs. Scenario events (`set`, `inject`,
`spawn_person`, `weather`) layer on top of the baseline generator.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

import numpy as np

from terrapilot.core.config import ConfigBundle
from terrapilot.domain.models import RawFrame
from terrapilot.sim.world import WorldContext
from terrapilot.twin.geometry import polyline_distance3, rotate2

SECONDS_PER_HOUR = 3600.0
KPH_PER_MS = 3.6


def excavator_ik(specs: dict[str, Any], r: float, z: float, bucket_abs_deg: float) -> tuple[float, float, float]:
    """(boom, stick-rel, bucket-rel) degrees that put the bucket tip at (r, z) with the given absolute bucket angle."""
    px, pz = (float(v) for v in specs["boom"]["pivot"])
    lb, ls, lk = float(specs["boom"]["length_m"]), float(specs["stick"]["length_m"]), float(specs["bucket"]["length_m"])
    a3 = math.radians(bucket_abs_deg)
    bx, bz = r - lk * math.cos(a3) - px, z - lk * math.sin(a3) - pz
    d = min(math.hypot(bx, bz), lb + ls - 1e-6)
    cos_s = max(-1.0, min(1.0, (d * d - lb * lb - ls * ls) / (2 * lb * ls)))
    a2 = -math.acos(cos_s)
    a1 = math.atan2(bz, bx) - math.atan2(ls * math.sin(a2), lb + ls * math.cos(a2))
    return math.degrees(a1), math.degrees(a2), math.degrees(a3 - a1 - a2)


@dataclass
class Injection:
    kind: str
    start: float
    end: float
    params: dict[str, Any]


@dataclass
class Person:
    id: str
    pos: tuple[float, float]  # site frame
    vel: tuple[float, float]
    ppe: dict[str, bool]
    spawned: float


@dataclass
class MachineSim:
    cfg: ConfigBundle
    world: WorldContext
    scenario: dict[str, Any] | None = None
    seed: int = 0
    start: datetime = field(default_factory=lambda: datetime.now().astimezone())

    def __post_init__(self) -> None:
        m = self.world.machine
        self.manifest = self.cfg.manifests[m["manifest_id"]]
        self.specs = self.cfg.manifests_raw[m["manifest_id"]]["specs"]
        sim_cfg = self.cfg.sim["generators"]
        self.gen = sim_cfg[sim_cfg["by_class"][self.manifest.class_]]
        self.inj_cfg = sim_cfg["injections"]
        self.rng = np.random.default_rng(self.seed)
        skill = float((self.scenario or {}).get("baseline", {}).get("skill", 0.5))
        self.cycle_s = float(self.gen["cycle_s"]) * (1 - float(self.gen.get("skill_speed_k", 0.0)) * (skill - 0.5))
        self.depth = float((self.world.task or {}).get("depth_m") or 2.0)
        self.overrides: dict[str, Any] = {}
        self.weather = dict(self.world.weather)
        self.injections: list[Injection] = []
        self.persons: list[Person] = []
        self.pose_xy = self._spawn_position()
        self.drive_speed_kph = 0.0
        self.heading = 0.0
        self.roll_target = float(self.gen.get("steady", {}).get("imu.roll_deg", 0.0))
        self.roll = self.roll_target
        self.prev_swing = 0.0
        self.prev_rate = 0.0
        self.cycles = 0
        self.progress = 0.0
        self.fuel_l = float(self.manifest.energy.get("tank_l", 0)) * 0.8
        self.soc = float((self.scenario or {}).get("initial_state", {}).get("battery.soc", 0.9))
        self.seq = 0
        self.time_scale = float((self.scenario or {}).get("time_scale", 1.0))
        self._timeline = sorted((self.scenario or {}).get("timeline", []), key=lambda e: e["t"])
        self._next_event = 0
        self.utility_state: dict[str, Any] | None = None
        self.tip_machine: tuple[float, float, float] = (0.0, 0.0, 0.0)

    # ------------------------------------------------------------------ setup
    def _spawn_position(self) -> tuple[float, float]:
        """A dig position well clear of buried utilities so baseline scenarios stay quiet."""
        clearance = float(self.cfg.sim["generators"]["spawn_clearance_from_utilities_m"])
        utils = [g for g in self.world.geofences if g.kind in ("utility_buried", "overhead_line")]
        for radius in range(0, 400, 10):
            for k in range(12):
                a = 2 * math.pi * k / 12
                p = (radius * math.cos(a), radius * math.sin(a))
                if all(
                    polyline_distance3((p[0], p[1], g.points[0][2]), [(q[0], q[1], g.points[0][2]) for q in g.points])[
                        0
                    ]
                    > clearance
                    for g in utils
                ):
                    return p
        return (0.0, 0.0)

    # ------------------------------------------------------------------ scenario events
    def _apply_events(self, t: float) -> None:
        while self._next_event < len(self._timeline) and self._timeline[self._next_event]["t"] <= t + 1e-9:
            ev = self._timeline[self._next_event]
            self._next_event += 1
            if "set" in ev:
                self.overrides.update(ev["set"])
            if "drive" in ev:
                # place the machine and set it travelling along its heading (negative speed = reversing)
                dv = ev["drive"]
                if "at_xy" in dv:
                    self.pose_xy = (float(dv["at_xy"][0]), float(dv["at_xy"][1]))
                if "heading_deg" in dv:
                    self.heading = float(dv["heading_deg"])
                self.drive_speed_kph = float(dv.get("speed_kph", 0.0))
            if "weather" in ev:
                self.weather.update({k: float(v) for k, v in ev["weather"].items()})
            if "spawn_person" in ev:
                sp = ev["spawn_person"]
                rel = rotate2((float(sp["from"][0]), float(sp["from"][1])), math.radians(self.heading))
                vel = rotate2((float(sp["velocity_ms"][0]), float(sp["velocity_ms"][1])), math.radians(self.heading))
                self.persons.append(
                    Person(
                        f"P{len(self.persons) + 1}",
                        (self.pose_xy[0] + rel[0], self.pose_xy[1] + rel[1]),
                        vel,
                        dict(sp.get("ppe", {})),
                        t,
                    )
                )
            if "inject" in ev:
                kind = ev["inject"]
                params = {**self.inj_cfg.get(kind, {}), **(ev.get("params") or {})}
                duration = float(params.get("duration_s", 1e9))  # ramp_s shapes the transition, not the duration
                self.injections.append(Injection(kind, t, t + duration, params))
                if kind == "side_slope":
                    self.roll_target = float(params["roll_deg"])
                    self.injections = [
                        i for i in self.injections if not (i.kind == "side_slope" and i is not self.injections[-1])
                    ]
                if kind == "approach_buried_utility":
                    self._start_utility_approach(params)

    def _start_utility_approach(self, params: dict[str, Any]) -> None:
        target = next((g for g in self.world.geofences if g.id == params.get("utility_id")), None)
        if target is None:
            return
        a, b = target.points[0], target.points[-1]
        others = [g for g in self.world.geofences if g.kind == "utility_buried" and g.id != target.id]

        def isolation(f: float) -> float:
            q = (a[0] + (b[0] - a[0]) * f, a[1] + (b[1] - a[1]) * f, a[2])
            return min((polyline_distance3(q, g.points)[0] for g in others), default=1e9)

        best_f = max((i / 20 for i in range(2, 19)), key=isolation)  # approach where U-x is clear of other utilities
        mid = (a[0] + (b[0] - a[0]) * best_f, a[1] + (b[1] - a[1]) * best_f)
        seg = (b[0] - a[0], b[1] - a[1])
        normal = (-seg[1], seg[0])
        n = math.hypot(*normal) or 1.0
        normal = (normal[0] / n, normal[1] / n)
        start_gap = target.clearance_m * float(params["start_clearance_multiple"]) + float(params["extra_start_m"])
        dig_r = float(self.gen["phases"][0]["from"]["r"])
        # machine faces the utility; its dig point starts `start_gap` from the line
        self.heading = math.degrees(math.atan2(-normal[1], -normal[0]))
        self.pose_xy = (mid[0] + normal[0] * (start_gap + dig_r), mid[1] + normal[1] * (start_gap + dig_r))
        self.utility_state = {
            "normal": normal,
            "speed": float(params["closing_speed_ms"]),
            "stop": target.clearance_m * float(params["stop_clearance_fraction"]),
            "fence": target,
        }

    def _active(self, kind: str, t: float) -> Injection | None:
        return next((i for i in reversed(self.injections) if i.kind == kind and i.start <= t < i.end), None)

    # ------------------------------------------------------------------ tick
    def _tick(self, t: float, dt: float) -> RawFrame:
        self._apply_events(t)
        sig: dict[str, Any] = dict(self.gen.get("steady", {}))
        phase_name, target = self._phase(t)
        for key, by_phase in self.gen.get("signals", {}).items():
            sig[key] = by_phase.get(phase_name, 0)
        for key, sd in self.gen.get("noise_sd", {}).items():
            if key in sig:
                sig[key] = float(sig[key]) + float(self.rng.normal(0, sd))
        sig.update(
            {
                "seat.occupied": True,
                "seat.belt_fastened": True,
                "engine.running": True,
                "controls.neutral": False,
                "motion.ground_speed_kph": sig.get("motion.ground_speed_kph", 0.0),
            }
        )
        if self.manifest.class_ == "excavator" and target is not None:
            self._excavator_pose(sig, target, t, dt)
        # injections
        idle = self._active("idle", t)
        if idle:
            p = idle.params
            sig.update(
                {
                    "engine.rpm": float(p.get("rpm", 900)),
                    "hydraulic.pump_pressure": float(p.get("pressure", 20)),
                    "engine.load_pct": float(p.get("load_pct", 18)),
                    "controls.neutral": True,
                    "motion.ground_speed_kph": 0.0,
                    "swing.rate_deg_s": 0.0,
                    "swing.accel_deg_s2": 0.0,
                }
            )
            phase_name = "idle"
        cav = self._active("cavitation", t)
        if cav:
            sev = float(cav.params.get("severity", 1.0))
            sig["hydraulic.pressure_ripple"] = float(cav.params["ripple"]) * (0.8 + 0.2 * sev)
            sig["engine.load_pct"] = float(cav.params["load_pct"])
        spike = self._active("g_spike", t)
        sig["imu.accel_g"] = float(spike.params["accel_g"]) if spike else 1.0 + float(self.rng.normal(0, 0.03))
        self.roll += (self.roll_target - self.roll) * min(1.0, dt / float(self.inj_cfg["side_slope"]["ramp_s"]))
        sig["imu.roll_deg"] = self.roll + float(self.rng.normal(0, 0.1))
        fm = self._active("fault_mode", t)
        if fm:
            prog = float(fm.params["progress_from"]) + (
                float(fm.params["progress_to"]) - float(fm.params["progress_from"])
            ) * ((t - fm.start) / max(float(fm.params.get("over_s", 1)), 1e-6))
            mode = self.cfg.datagen["degradation"]["fault_modes"][fm.params["mode"]]
            frac = (math.exp(3 * prog) - 1) / (math.e**3 - 1) if mode["shape"] == "exponential" else prog
            sig[mode["sensor"]] = float(sig.get(mode["sensor"], 0.0)) + float(mode["magnitude"]) * frac
            for k, v in (mode.get("also") or {}).items():
                sig[k] = float(sig.get(k, 0.0)) + float(v) * frac
        self._drive(dt, sig)
        self._utility_motion(dt)
        self._energy(sig, dt)
        sig.update({k: v for k, v in self.overrides.items()})
        sig["task.phase"] = phase_name
        sig["task.cycles"] = self.cycles
        sig["task.progress_qty"] = round(self.progress, 2)
        sig["pose.x"], sig["pose.y"], sig["pose.heading_deg"] = self.pose_xy[0], self.pose_xy[1], self.heading
        detections = self._persons(t, dt)
        self.seq += 1
        env = {k: float(v) for k, v in self.weather.items()}
        return RawFrame(
            machine_id=str(self.world.machine["id"]),
            ts=self.start + timedelta(seconds=t),
            seq=self.seq,
            signals={k: (round(v, 4) if isinstance(v, float) else v) for k, v in sig.items()},
            detections=detections,
            env=env,
        )

    def _phase(self, t: float) -> tuple[str, dict[str, float] | None]:
        cyc_t = (t % self.cycle_s) / self.cycle_s
        n = int(t // self.cycle_s)
        if n > self.cycles and not self._active("idle", t):
            self.cycles = n
            self.progress += float(self.gen.get("payload_t_per_cycle", 1.0)) / max(
                1.0, float(self.cfg.datagen["cycles"]["material_density_t_m3"].get(self.world.zone_soil, 1.8))
            )
        start = 0.0
        for ph in self.gen["phases"]:
            if cyc_t < float(ph["until"]):
                if "from" not in ph:
                    return ph["name"], None
                f = (cyc_t - start) / (float(ph["until"]) - start)
                ease = 0.5 - 0.5 * math.cos(math.pi * f)
                a, b = ph["from"], ph["to"]
                vals = {
                    k: self._kf(a[k]) + (self._kf(b[k]) - self._kf(a[k])) * ease for k in ("r", "z", "bucket", "swing")
                }
                return ph["name"], vals
            start = float(ph["until"])
        return self.gen["phases"][-1]["name"], None

    def _kf(self, v: Any) -> float:
        if v == "dig_depth":
            od = self._active_now("over_dig")
            return -self.depth - (float(od.params.get("depth_cm", 0)) / 100 if od else 0.0)
        if v == "swing_deg":
            return float(self.gen["swing_deg"])
        return float(v)

    def _active_now(self, kind: str) -> Injection | None:
        return next((i for i in reversed(self.injections) if i.kind == kind and i.start <= self._now < i.end), None)

    def _excavator_pose(self, sig: dict[str, Any], target: dict[str, float], t: float, dt: float) -> None:
        ext = self._active("extend_reach", t)
        if ext:
            f = min(1.0, (t - ext.start) / float(ext.params.get("ramp_s", 6.0)))
            ease = 0.5 - 0.5 * math.cos(math.pi * f)
            goal = {k: float(ext.params[k]) for k in ("r", "z", "bucket", "swing")}
            target = {k: target[k] + (goal[k] - target[k]) * ease for k in goal}
            sig["payload.weight_t"] = float(ext.params.get("payload_t", 2.0))
        boom, stick, bucket = excavator_ik(self.specs, target["r"], target["z"], target["bucket"])
        swing = target["swing"]
        rate = (swing - self.prev_swing) / dt if dt > 0 else 0.0
        accel = (rate - self.prev_rate) / dt if dt > 0 else 0.0
        self.prev_swing, self.prev_rate = swing, rate
        tip_xy = rotate2((target["r"], 0.0), math.radians(swing))
        self.tip_machine = (tip_xy[0], tip_xy[1], target["z"])
        sig.update(
            {
                "boom.angle_deg": boom,
                "stick.angle_deg": stick,
                "bucket.angle_deg": bucket,
                "swing.angle_deg": swing,
                "swing.rate_deg_s": rate,
                "swing.accel_deg_s2": accel,
            }
        )
        sig.setdefault("payload.weight_t", float(self.gen.get("payload_t_per_cycle", 1.0)) if target["z"] > 0 else 0.3)

    def _utility_motion(self, dt: float) -> None:
        us = self.utility_state
        if not us:
            return
        inj = self._active_now("approach_buried_utility")
        n = us["normal"]
        if inj:
            fence = us["fence"]
            rel = rotate2((self.tip_machine[0], self.tip_machine[1]), math.radians(self.heading))
            tip = (self.pose_xy[0] + rel[0], self.pose_xy[1] + rel[1], self.tip_machine[2])
            us["closest"] = min(
                us.get("closest", 1e9), polyline_distance3(tip, fence.points)[0] - fence.depth_uncertainty_m
            )
            if us["closest"] > us["stop"]:  # keep inching forward until the bucket has come this close once
                self.pose_xy = (self.pose_xy[0] - n[0] * us["speed"] * dt, self.pose_xy[1] - n[1] * us["speed"] * dt)
        else:  # injection over: back away to a safe position
            self.pose_xy = (self.pose_xy[0] + n[0] * 5.0, self.pose_xy[1] + n[1] * 5.0)
            if all(
                polyline_distance3((self.pose_xy[0], self.pose_xy[1], 0.0), g.points)[0] > 12
                for g in self.world.geofences
                if g.kind == "utility_buried"
            ):
                self.utility_state = None

    def _drive(self, dt: float, sig: dict[str, Any]) -> None:
        """Travel along the heading at the scenario's drive speed; reversing is a negative speed."""
        if not self.drive_speed_kph:
            return
        v = self.drive_speed_kph / KPH_PER_MS
        rad = math.radians(self.heading)
        self.pose_xy = (self.pose_xy[0] + v * math.cos(rad) * dt, self.pose_xy[1] + v * math.sin(rad) * dt)
        sig["motion.ground_speed_kph"] = self.drive_speed_kph

    def _energy(self, sig: dict[str, Any], dt: float) -> None:
        h = dt * self.time_scale / SECONDS_PER_HOUR
        if self.manifest.powertrain == "electric":
            cons = self.specs.get("consumption_kw", {})
            kw = (
                float(cons.get("idle", 2.0))
                if sig.get("controls.neutral")
                else float(np.mean(list(cons.values()) or [60.0]))
            )
            heavy = self._active_now("heavy_digging")
            if heavy:
                kw *= float(heavy.params["consumption_factor"])
            cap = float(self.manifest.energy["battery_kwh"]) * float(self.manifest.energy.get("usable_fraction", 1.0))
            charging = self._active_now("park_at_charger")
            if charging:
                station = next(iter(self.manifest.energy.get("charge_power_kw_by_station", {}).values()), 50.0)
                self.soc = min(1.0, self.soc + float(station) * h / cap)
                sig["motor.power_kw"] = 0.0
            else:
                self.soc = max(0.0, self.soc - kw * h / cap)
                sig["motor.power_kw"] = kw
            sig["battery.soc"] = self.soc
            for k in ("engine.rpm", "engine.coolant_temp", "engine.oil_pressure", "engine.fan_speed_pct"):
                sig.pop(k, None)
        else:
            lph = (
                float(self.specs.get("idle_fuel_lph", 3.0))
                if sig.get("controls.neutral")
                else float(self.specs.get("work_fuel_lph", {}).get("standard", 15.0))
            )
            self.fuel_l = max(0.0, self.fuel_l - lph * h)
            tank = float(self.manifest.energy.get("tank_l", 1)) or 1.0
            sig["fuel.level_pct"] = 100 * self.fuel_l / tank

    def _persons(self, t: float, dt: float) -> list[dict[str, Any]]:
        pc = self.inj_cfg["person"]
        out, keep = [], []
        for p in self.persons:
            p.pos = (p.pos[0] + p.vel[0] * dt, p.pos[1] + p.vel[1] * dt)
            dist = math.hypot(p.pos[0] - self.pose_xy[0], p.pos[1] - self.pose_xy[1])
            if t - p.spawned > float(pc["drop_after_s"]) or dist > float(pc["drop_distance_m"]):
                continue
            keep.append(p)
            out.append({"id": p.id, "kind": "person", "x": round(p.pos[0], 3), "y": round(p.pos[1], 3), "ppe": p.ppe})
        self.persons = keep
        return out

    _now: float = 0.0

    def step(self, t: float, dt: float) -> RawFrame:
        """Advance to scenario time t (seconds) and return the frame the machine publishes."""
        self._now = t
        return self._tick(t, dt)
