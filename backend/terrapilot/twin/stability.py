"""Static stability margin (§10.4.5).

Masses are projected onto the load direction (swing azimuth). The tipping edge is where that direction
leaves the support rectangle (tracks). margin = M_restoring / M_overturning about the edge, with gravity
tilted by the ground slope component along the load direction. A finite-difference sensitivity tells the
copilot which action improves the margin most.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

from terrapilot.twin.geometry import rect_edge_distance
from terrapilot.twin.kinematics import ArmPose, excavator_points

G = 9.81
NO_OVERTURN = 99.0  # margin reported when nothing is beyond the edge
REACH_STEP_M = 0.5
LOAD_STEP_T = 0.5
SLEW_STEP_DEG = 10.0


@dataclass(frozen=True)
class Stability:
    margin: float
    limiting_axis: str
    edge_m: float
    sensitivity: dict[str, float]
    hint: str


def _margin(
    specs: dict[str, Any],
    pose: ArmPose,
    payload_t: float,
    pitch_deg: float,
    roll_deg: float,
    reach_extra_m: float = 0.0,
) -> tuple[float, str, float]:
    pts = excavator_points(specs, pose)
    swing = math.radians(pose.swing_deg)
    edge, axis = rect_edge_distance(swing, float(specs["track_length_m"]) / 2, float(specs["track_gauge_m"]) / 2)
    # slope component along the load direction tilts gravity: effective radial shift = z · tan(slope)
    slope = math.radians(pitch_deg * math.cos(swing) + roll_deg * math.sin(swing))

    def radial(p: tuple[float, float, float]) -> float:
        return p[0] * math.cos(swing) + p[1] * math.sin(swing)

    def eff(r: float, z: float) -> float:
        return r + z * math.tan(slope)

    bucket_mass = float(specs["bucket"]["mass_kg"]) + payload_t * 1000
    masses: list[tuple[float, float]] = [
        (float(specs["undercarriage_mass_kg"]), eff(0.0, 0.5)),
        (float(specs["upper_mass_kg"]), eff(float(specs["upper_cog_offset_m"]), 1.5)),
        (float(specs["counterweight_kg"]), eff(float(specs["counterweight_offset_m"]), 1.3)),
        (float(specs["boom"]["mass_kg"]), eff(radial(pts.boom_mid) + reach_extra_m / 2, pts.boom_mid[2])),
        (float(specs["stick"]["mass_kg"]), eff(radial(pts.stick_mid) + reach_extra_m, pts.stick_mid[2])),
        (bucket_mass, eff(radial(pts.bucket_mid) + reach_extra_m, pts.bucket_mid[2])),
    ]
    over = sum(m * (r - edge) for m, r in masses if r > edge)
    rest = sum(m * (edge - r) for m, r in masses if r <= edge)
    margin = NO_OVERTURN if over <= 0 else min(NO_OVERTURN, rest / over)
    return margin, axis, edge


def stability(specs: dict[str, Any], pose: ArmPose, payload_t: float, pitch_deg: float, roll_deg: float) -> Stability:
    m0, axis, edge = _margin(specs, pose, payload_t, pitch_deg, roll_deg)
    d_reach = _margin(specs, pose, payload_t, pitch_deg, roll_deg, reach_extra_m=-REACH_STEP_M)[0] - m0
    d_load = _margin(specs, pose, max(0.0, payload_t - LOAD_STEP_T), pitch_deg, roll_deg)[0] - m0
    # slewing toward the tracks' long axis is the "stop slew / reposition" lever
    toward = pose.swing_deg - math.copysign(SLEW_STEP_DEG, math.sin(math.radians(pose.swing_deg)) or 1.0)
    d_slew = (
        _margin(specs, ArmPose(pose.boom_deg, pose.stick_deg, pose.bucket_deg, toward), payload_t, pitch_deg, roll_deg)[
            0
        ]
        - m0
    )
    sens = {"reduce_reach": round(d_reach, 3), "lower_load": round(d_load, 3), "stop_slew": round(d_slew, 3)}
    best = max(sens.items(), key=lambda kv: kv[1])
    hint = best[0] if best[1] > 0 else "none"
    return Stability(margin=round(m0, 3), limiting_axis=axis, edge_m=round(edge, 3), sensitivity=sens, hint=hint)


def vehicle_stability(specs: dict[str, Any], roll_deg: float, pitch_deg: float, payload_ratio: float) -> Stability:
    """Wheeled machines: static rollover margin = (half track width) / (CoG height · tan(slope)), loaded CoG raised."""
    half_w = float(specs["track_width_m"]) / 2
    cog = float(specs["cog_height_m"]) * (1 + 0.15 * max(0.0, payload_ratio))
    slope = max(abs(roll_deg), 1e-3)
    margin = min(NO_OVERTURN, half_w / (cog * math.tan(math.radians(slope))))
    axis = "lateral" if abs(roll_deg) >= abs(pitch_deg) else "longitudinal"
    hint = "lower_load" if payload_ratio > 0 else "none"
    return Stability(margin=round(margin, 3), limiting_axis=axis, edge_m=round(half_w, 3), sensitivity={}, hint=hint)
