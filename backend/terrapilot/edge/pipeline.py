"""One live tick (§3.2): RawFrame → fused state → rules → episodes → black box → outputs.

The output (`TickOutput`) is transport-agnostic; `edge.sinks` publish it to Redis/WS and persist to the DB.
"""

from __future__ import annotations

import math
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np

from terrapilot.behavior.episodes import EpisodeDetector, idle_cost_so_far
from terrapilot.core.config import ConfigBundle
from terrapilot.core.expr import nest_dotted
from terrapilot.core.timeutil import utcnow
from terrapilot.domain.models import AlertEvent, BehaviorEvent, RawFrame
from terrapilot.edge.etc import TaskPrior, live_etc, prior_from_plan
from terrapilot.safety.blackbox import BlackBox, FinishedClip
from terrapilot.safety.fatigue import FatigueMonitor, WbvMonitor
from terrapilot.safety.p2p import P2PLink, beacon_from_state
from terrapilot.safety.rules import RulesEngine
from terrapilot.sim.world import WorldContext
from terrapilot.twin.geometry import polyline_distance3, rotate2
from terrapilot.twin.grade import grade_deviation
from terrapilot.twin.ground import ground_properties
from terrapilot.twin.kinematics import ArmPose, excavator_points, to_site
from terrapilot.twin.proximity import Track, assess
from terrapilot.twin.stability import Stability as StabilityResult
from terrapilot.twin.stability import stability, vehicle_stability

CM_PER_M = 100.0
GRAVITY = 9.80665
DEG_TO_LATERAL_MS2 = 0.02  # small-angle proxy: seat lateral acceleration per degree of roll
KPH_PER_MS = 3.6


@dataclass
class TickOutput:
    ts: datetime
    state: dict[str, Any]
    alerts: list[AlertEvent] = field(default_factory=list)
    behavior: list[BehaviorEvent] = field(default_factory=list)
    clips: list[FinishedClip] = field(default_factory=list)
    advisories: list[dict[str, Any]] = field(default_factory=list)


class EdgePipeline:
    def __init__(
        self,
        cfg: ConfigBundle,
        world: WorldContext,
        tick_hz: float,
        blackbox_dir: Path | None = None,
        advisor: Callable[[dict[str, Any], list[Any], datetime], list[dict[str, Any]]] | None = None,
        p2p_link: P2PLink | None = None,
        start_of_run: datetime | None = None,
    ):
        self.cfg = cfg
        self.world = world
        m = world.machine
        self.machine_id = str(m["id"])
        self.manifest = cfg.manifests[m["manifest_id"]]
        self.raw = cfg.manifests_raw[m["manifest_id"]]
        self.specs = self.raw["specs"]
        self.edge_cfg = cfg.app.edge
        self.rules = RulesEngine(
            self.machine_id,
            self.raw,
            cfg.app_dict(),
            cfg.safety_rules + cfg.condition_rules,
            cfg.maintenance_rules,
            cfg.sensor_limits,
            self.manifest.class_,
            self.manifest.powertrain,
        )
        self.episodes = EpisodeDetector(cfg, self.machine_id, m["manifest_id"])
        bb = cfg.app.blackbox
        self.blackbox = BlackBox(self.machine_id, tick_hz, bb["frame_hz"], bb["pre_s"], bb["post_s"], blackbox_dir)
        self.tracks: dict[str, Track] = {}
        self.track_seen: dict[str, float] = {}
        self.advisor = advisor
        self.task_id = (world.task or {}).get("id")
        self.design_depth = float((world.task or {}).get("depth_m") or 0.0)
        self._g_armed = True
        etc_cfg = cfg.models["models"]["live_etc"]
        self.etc_k = float(etc_cfg["prior_strength_k"])
        self.etc_z = float(etc_cfg["z_interval"])
        self.etc_min_cycles = int(etc_cfg["min_cycles_for_cv"])
        task = world.task or {}
        prior = world.extras.get("task_prior")
        if prior:
            self.task_prior = TaskPrior(float(prior["rate_per_min"]), float(prior["log_half_width"]), "model")
        else:
            try:
                minutes = float((task["planned_end"] - task["planned_start"]).total_seconds()) / 60
            except (KeyError, TypeError, ValueError, AttributeError):
                minutes = 0.0
            minutes = minutes if not math.isnan(minutes) and minutes > 0 else 0.0  # NaT → no plan
            self.task_prior = prior_from_plan(
                float(task.get("quantity") or 0.0), minutes or 1.0, float(etc_cfg["plan_prior_log_half_width"])
            )
        self._etc_t0: datetime | None = None
        self._etc_q0 = 0.0
        self._cycle_marks: list[datetime] = []
        self._last_cycles = -1
        self._utility_hist: deque[tuple[float, float, str, float]] = deque()
        # operator wellbeing + machine-to-machine proximity (§10.4.3, §10.4.7)
        shift_start = world.extras.get("shift_start") or start_of_run or utcnow()
        self.fatigue = FatigueMonitor(cfg.app.fatigue, shift_start)
        self.shift_length_h = float(cfg.app.site_calendar["shift"]["length_h"])
        self.derived = self.specs.get("derived", {})
        self.wbv = WbvMonitor(cfg.app.wbv)
        self.p2p = p2p_link
        self._last_ts: datetime | None = None

    # ------------------------------------------------------------------ fusion
    def fuse(self, frame: RawFrame) -> dict[str, Any]:
        sig = dict(frame.signals)
        state = nest_dotted({k: v for k, v in sig.items() if not k.startswith("pose.")})
        pose = {
            "x": float(sig.get("pose.x", 0.0) or 0.0),
            "y": float(sig.get("pose.y", 0.0) or 0.0),
            "heading_deg": float(sig.get("pose.heading_deg", 0.0) or 0.0),
        }
        state["pose"] = pose
        state["site"] = dict(frame.env)
        state["ground"] = {"risk_score": self._ground_risk()}
        payload = float(sig.get("payload.weight_t", 0.0) or 0.0)
        pitch, roll = float(sig.get("imu.pitch_deg", 0.0) or 0.0), float(sig.get("imu.roll_deg", 0.0) or 0.0)
        tip_site = None
        arm_top_site = None
        if self.manifest.kinematics == "excavator_boom_stick" and "boom.angle_deg" in sig:
            arm = ArmPose(
                float(sig["boom.angle_deg"]),  # type: ignore[arg-type]
                float(sig["stick.angle_deg"]),  # type: ignore[arg-type]
                float(sig["bucket.angle_deg"]),  # type: ignore[arg-type]
                float(sig.get("swing.angle_deg", 0.0) or 0.0),
            )
            pts = excavator_points(self.specs, arm)
            tip_site = to_site(pts.tip, (pose["x"], pose["y"]), pose["heading_deg"])
            top = max((pts.stick_pivot, pts.bucket_pivot, pts.tip), key=lambda p: p[2])
            arm_top_site = to_site(top, (pose["x"], pose["y"]), pose["heading_deg"])
            st = stability(self.specs, arm, payload, pitch, roll)
            state["bucket_tip"] = [round(v, 3) for v in pts.tip]
            state["reach_m"] = round(pts.reach_m, 2)
            if sig.get("task.phase") == "dig" and self.design_depth:
                g = grade_deviation(pts.tip[2], -self.design_depth, float(self.edge_cfg["grade_tolerance_m"]))
                state["grade"] = {
                    "deviation_m": g.deviation_m,
                    "deviation_cm": round(g.deviation_m * CM_PER_M, 1),
                    "direction": g.direction,
                    "design_z": g.design_z,
                    "tip_z": g.tip_z,
                    "active": True,
                }
            else:
                state["grade"] = {"active": False}
        else:
            rated = float(self.specs.get("rated_payload_t", 1.0)) or 1.0
            st = vehicle_stability(self.specs, roll, pitch, payload / rated)
        state["stability"] = _stab(st)
        state["proximity"] = self._proximity(frame, pose, sig)
        state["geofence"] = self._dig_line(self._geofence(tip_site, arm_top_site), frame.ts.timestamp())
        state["energy"] = self._energy(sig)
        state["task"] = {
            **state.get("task", {}),
            "task_id": self.task_id,
            "quantity": float((self.world.task or {}).get("quantity") or 0.0),
            "unit": (self.world.task or {}).get("unit"),
        }
        state["task"]["etc"] = self._etc(frame.ts, state["task"])
        state["fatigue"] = self._fatigue(frame, sig)
        state["wbv"] = self._wbv(frame, sig)
        state["p2p"] = self._p2p(frame, state, sig)
        return state

    def _fatigue(self, frame: RawFrame, sig: dict[str, Any]) -> dict[str, Any]:
        """EAR samples come from the cab camera on the edge (or the scenario); only the score leaves."""
        ear = sig.get("driver.eye_aspect_ratio")
        if ear is not None:
            self.fatigue.observe(frame.ts.timestamp(), float(ear))
        return self.fatigue.score(frame.ts, frame.env.get("heat_index")).as_dict()

    def _wbv(self, frame: RawFrame, sig: dict[str, Any]) -> dict[str, Any]:
        dt = (frame.ts - self._last_ts).total_seconds() if self._last_ts else 0.0
        self._last_ts = frame.ts
        if dt > 0:
            seat = self.raw.get("seat", {}).get("transmissibility", 1.0)
            g = float(sig.get("imu.accel_g", 1.0) or 1.0)
            vertical = abs(g - 1.0) * GRAVITY * float(seat)
            lateral = abs(float(sig.get("imu.roll_deg", 0.0) or 0.0)) * DEG_TO_LATERAL_MS2
            self.wbv.observe(lateral, lateral, vertical, dt)
        return self.wbv.state(self.shift_length_h).as_dict()

    def _p2p(self, frame: RawFrame, state: dict[str, Any], sig: dict[str, Any]) -> dict[str, Any]:
        if self.p2p is None:
            return {"peers": 0, "tier": "normal", "blind_spot": False}
        envelope = float(self.derived.get("tail_swing_radius", self.specs.get("width_m", 3.0)))
        own = beacon_from_state(self.machine_id, self.manifest.class_, state, envelope, frame.ts.timestamp())
        self.p2p.publish(own)
        risks = self.p2p.assess(own, frame.ts.timestamp())
        top = risks[0] if risks else None
        return {
            "peers": len(risks),
            "tier": top.tier if top else "normal",
            "blind_spot": bool(top.blind_spot) if top else False,
            "nearest_id": top.machine_id if top else None,
            "nearest_gap_m": top.gap_m if top else None,
            "nearest_ttc_s": top.ttc_s if top else None,
            "tracks": [r.as_dict() for r in risks[:3]],
        }

    def _etc(self, now: datetime, task: dict[str, Any]) -> dict[str, Any] | None:
        qty = float(task.get("quantity") or 0.0)
        done = float(task.get("progress_qty") or 0.0)
        cycles = int(task.get("cycles") or 0)
        if self._etc_t0 is None:
            self._etc_t0, self._etc_q0, self._last_cycles = now, done, cycles
        if cycles > self._last_cycles:
            self._cycle_marks.append(now)
            self._last_cycles = cycles
        if qty <= 0:
            return None
        n = len(self._cycle_marks)
        elapsed_min = (now - self._etc_t0).total_seconds() / 60
        rate_obs = (done - self._etc_q0) / elapsed_min if elapsed_min > 0 else 0.0
        gaps = [(b - a).total_seconds() for a, b in zip(self._cycle_marks, self._cycle_marks[1:], strict=False)]
        cv = float(np.std(gaps) / np.mean(gaps)) if len(gaps) >= self.etc_min_cycles and np.mean(gaps) > 0 else 0.0
        e = live_etc(now, qty - done, n, rate_obs, self.task_prior, self.etc_k, cv, self.etc_z)
        return {
            "remaining_min_p50": round(e.remaining_min_p50, 1),
            "remaining_min_p10": round(e.remaining_min_p10, 1),
            "remaining_min_p90": round(e.remaining_min_p90, 1),
            "etc_p50": e.etc_p50.isoformat(),
            "etc_p10": e.etc_p10.isoformat(),
            "etc_p90": e.etc_p90.isoformat(),
            "weight_observed": round(e.weight_observed, 3),
            "prior": self.task_prior.source,
        }

    def _ground_risk(self) -> float:
        soil = self.cfg.datagen["ground"]["soils"].get(self.world.zone_soil)
        if not soil:
            return 0.0
        gr = self.cfg.datagen["ground"]["ground_risk"]
        return round(
            float(
                ground_properties(self.world.zone_moisture, soil, gr["weights"], gr["surface_class_risk"])["risk_score"]
            ),
            3,
        )

    def _proximity(self, frame: RawFrame, pose: dict[str, float], sig: dict[str, Any]) -> dict[str, Any]:
        t = frame.ts.timestamp()
        prox = self.raw["proximity"]
        working = float(sig.get("hydraulic.pump_pressure", 0.0) or 0.0) > float(
            self.raw["motion"]["hydraulic_active_pressure_bar"]
        ) or float(sig.get("motion.ground_speed_kph", 0.0) or 0.0) > float(self.raw["motion"]["moving_threshold_kph"])
        derived = self.specs["derived"]
        hazard = float(derived.get("max_reach_m", prox["swing_radius_m"])) if working else float(prox["swing_radius_m"])
        for d in frame.detections:
            rel = rotate2((float(d["x"]) - pose["x"], float(d["y"]) - pose["y"]), -math.radians(pose["heading_deg"]))
            tr = self.tracks.get(d["id"]) or Track(d["id"], d.get("kind", "person"), rel, ppe=dict(d.get("ppe") or {}))
            tr.update(rel, t, float(self.edge_cfg["track_velocity_alpha"]))
            self.tracks[d["id"]] = tr
            self.track_seen[d["id"]] = t
        for tid in [k for k, seen in self.track_seen.items() if t - seen > float(self.edge_cfg["person_drop_after_s"])]:
            self.tracks.pop(tid, None)
            self.track_seen.pop(tid, None)
        risks = [assess(tr, hazard, prox["zones_m"], float(prox["min_moving_speed_ms"])) for tr in self.tracks.values()]
        people = [r for r in risks if r.kind == "person" and not r.static]
        nearest = min((r.distance_m for r in people), default=None)
        ttcs = [r.ttc_s for r in people if r.ttc_s is not None]
        return {
            "nearest_person_m": nearest,
            "min_ttc_s": min(ttcs) if ttcs else None,
            "hazard_radius_m": round(hazard, 2),
            "ppe_missing": any(r.zone and not all(r.ppe.values()) for r in people if r.ppe),
            "tracks": [
                {
                    "id": r.track_id,
                    "kind": r.kind,
                    "x": round(r.pos[0], 2),
                    "y": round(r.pos[1], 2),
                    "vx": round(r.vel[0], 2),
                    "vy": round(r.vel[1], 2),
                    "distance_m": r.distance_m,
                    "ttc_s": r.ttc_s,
                    "cpa_m": r.cpa_m,
                    "zone": r.zone,
                    "static": r.static,
                    "ppe": r.ppe,
                }
                for r in risks
            ],
        }

    def _geofence(
        self, tip: tuple[float, float, float] | None, arm_top: tuple[float, float, float] | None
    ) -> dict[str, Any]:
        out: dict[str, Any] = {}
        if tip is None:
            return out
        best_u: tuple[float, Any] | None = None
        for g in self.world.geofences:
            if g.kind != "utility_buried":
                continue
            d = polyline_distance3(tip, g.points)[0] - g.depth_uncertainty_m
            if best_u is None or d < best_u[0]:
                best_u = (d, g)
        if best_u is not None:
            out.update(
                {
                    "utility_id": best_u[1].id,
                    "utility_distance_m": round(max(0.0, best_u[0]), 2),
                    "utility_clearance_m": best_u[1].clearance_m,
                }
            )
        boom_top = arm_top or tip
        best_o: tuple[float, Any] | None = None
        for g in self.world.geofences:
            if g.kind != "overhead_line":
                continue
            d = polyline_distance3(boom_top, g.points)[0]
            if best_o is None or d < best_o[0]:
                best_o = (d, g)
        if best_o is not None:
            out.update(
                {
                    "overhead_id": best_o[1].id,
                    "overhead_distance_m": round(best_o[0], 2),
                    "overhead_clearance_m": best_o[1].clearance_m,
                }
            )
        return out

    def _dig_line(self, geo: dict[str, Any], t: float) -> dict[str, Any]:
        """Report the closest bucket approach over the recent window, so a cutting cycle does not flicker the alert."""
        if "utility_distance_m" in geo:
            self._utility_hist.append((t, geo["utility_distance_m"], geo["utility_id"], geo["utility_clearance_m"]))
        window = float(self.edge_cfg["dig_line_window_s"])
        while self._utility_hist and t - self._utility_hist[0][0] > window:
            self._utility_hist.popleft()
        if self._utility_hist:
            _, d, uid, clr = min(self._utility_hist, key=lambda h: h[1])
            geo.update({"utility_id": uid, "utility_distance_m": d, "utility_clearance_m": clr})
        return geo

    def _energy(self, sig: dict[str, Any]) -> dict[str, Any]:
        if self.manifest.powertrain == "electric":
            soc = sig.get("battery.soc")
            return {"powertrain": "electric", "soc": soc, "projected_min_soc": soc}
        return {"powertrain": self.manifest.powertrain, "fuel_pct": sig.get("fuel.level_pct")}

    # ------------------------------------------------------------------ tick
    def process(self, frame: RawFrame) -> TickOutput:
        state = self.fuse(frame)
        now = frame.ts
        out = TickOutput(ts=now, state=state)
        out.alerts = self.rules.evaluate(state, now)
        out.behavior = self.episodes.update(state, now, self.world.operator_id, self.task_id)
        state["idle"] = idle_cost_so_far(self.episodes, now)
        state["alerts_open"] = len(self.rules.open_alerts())
        location = {"x": state["pose"]["x"], "y": state["pose"]["y"]}
        ctx = {
            "operator_id": self.world.operator_id,
            "site_id": self.world.machine.get("site_id"),
            "location": location,
        }
        for ev in out.alerts:
            actions = self.rules.actions_for(ev.alert.rule_id)
            wants = "blackbox_trigger" in actions or ("blackbox_mark" in actions and ev.alert.severity == "warning")
            if ev.phase in ("open", "escalate") and wants:
                self.blackbox.trigger(
                    ev.alert.rule_id, now, "near_miss", "medium", {**ctx, "description": ev.alert.rule_id}
                )
        g = float(state.get("imu", {}).get("accel_g", 1.0) or 1.0)
        threshold = float(self.cfg.app.blackbox["g_spike_threshold_g"])
        if g >= threshold and self._g_armed:
            self.blackbox.trigger("IMU_G_SPIKE", now, "incident", "high", {**ctx, "description": f"G spike {g:.1f} g"})
            self._g_armed = False
        elif g < threshold:
            self._g_armed = True
        out.clips = self.blackbox.push(_bb_frame(now, state))
        if self.advisor is not None:
            out.advisories = self.advisor(state, self.rules.open_alerts(), now)
        return out

    def mark(self, now: datetime, note: str = "manual_mark") -> str:
        return self.blackbox.trigger(
            "MANUAL_MARK",
            now,
            "hazard",
            "low",
            {"operator_id": self.world.operator_id, "site_id": self.world.machine.get("site_id"), "description": note},
        )

    def close(self, now: datetime) -> TickOutput:
        out = TickOutput(ts=now, state={})
        out.behavior = self.episodes.flush(now, self.world.operator_id, self.task_id)
        out.alerts = self.rules.clear_all(now)
        out.clips = self.blackbox.flush()
        return out


def _stab(st: StabilityResult) -> dict[str, Any]:
    return {
        "margin": st.margin,
        "limiting_axis": st.limiting_axis,
        "hint": st.hint,
        "sensitivity": st.sensitivity,
        "edge_m": st.edge_m,
    }


def _bb_frame(now: datetime, state: dict[str, Any]) -> dict[str, Any]:
    """Compact black-box frame: enough to replay pose, people and alerts in the twin (§10.4.8 playback)."""
    keep = (
        "pose",
        "boom",
        "stick",
        "bucket",
        "swing",
        "imu",
        "stability",
        "grade",
        "hydraulic",
        "motion",
        "seat",
        "payload",
        "bucket_tip",
        "reach_m",
        "alerts_open",
    )
    frame: dict[str, Any] = {"ts": now.isoformat()}
    frame.update({k: state[k] for k in keep if k in state})
    frame["tracks"] = state.get("proximity", {}).get("tracks", [])
    return frame
