"""Forward kinematics (§3.2 step 2). Machine frame: x forward along the upper structure, y left, z up.

Excavator angles (degrees): boom from horizontal, stick relative to boom, bucket relative to stick.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

from terrapilot.twin.geometry import Vec3, rotate2


@dataclass(frozen=True)
class ArmPose:
    boom_deg: float
    stick_deg: float
    bucket_deg: float
    swing_deg: float = 0.0


@dataclass(frozen=True)
class ArmPoints:
    """Joint and link-centre positions in the machine (undercarriage) frame, swing applied."""

    boom_pivot: Vec3
    stick_pivot: Vec3
    bucket_pivot: Vec3
    tip: Vec3
    boom_mid: Vec3
    stick_mid: Vec3
    bucket_mid: Vec3
    reach_m: float


def _planar(specs: dict[str, Any], pose: ArmPose) -> list[tuple[float, float]]:
    """Points in the arm plane (r forward, z up) before swing: pivot, stick pivot, bucket pivot, tip."""
    pivot_x, pivot_z = (float(v) for v in specs["boom"]["pivot"])
    lb, ls, lk = float(specs["boom"]["length_m"]), float(specs["stick"]["length_m"]), float(specs["bucket"]["length_m"])
    a1 = math.radians(pose.boom_deg)
    a2 = a1 + math.radians(pose.stick_deg)
    a3 = a2 + math.radians(pose.bucket_deg)
    p0 = (pivot_x, pivot_z)
    p1 = (p0[0] + lb * math.cos(a1), p0[1] + lb * math.sin(a1))
    p2 = (p1[0] + ls * math.cos(a2), p1[1] + ls * math.sin(a2))
    p3 = (p2[0] + lk * math.cos(a3), p2[1] + lk * math.sin(a3))
    return [p0, p1, p2, p3]


def excavator_points(specs: dict[str, Any], pose: ArmPose) -> ArmPoints:
    planar = _planar(specs, pose)
    swing = math.radians(pose.swing_deg)

    def lift(p: tuple[float, float]) -> Vec3:
        x, y = rotate2((p[0], 0.0), swing)
        return (x, y, p[1])

    def mid(a: tuple[float, float], b: tuple[float, float]) -> tuple[float, float]:
        return ((a[0] + b[0]) / 2, (a[1] + b[1]) / 2)

    p0, p1, p2, p3 = planar
    return ArmPoints(
        boom_pivot=lift(p0),
        stick_pivot=lift(p1),
        bucket_pivot=lift(p2),
        tip=lift(p3),
        boom_mid=lift(mid(p0, p1)),
        stick_mid=lift(mid(p1, p2)),
        bucket_mid=lift(mid(p2, p3)),
        reach_m=p3[0],
    )


def to_site(p: Vec3, machine_xy: tuple[float, float], heading_deg: float) -> Vec3:
    """Machine frame → site frame (local metres) given machine position and heading."""
    x, y = rotate2((p[0], p[1]), math.radians(heading_deg))
    return (x + machine_xy[0], y + machine_xy[1], p[2])
