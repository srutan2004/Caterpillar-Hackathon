"""Derived manifest values (§10.2): tail swing radius, reach envelope, tipping lines.

Derivations are registered per `kinematics` type, so machine differences stay data-driven: a new
machine model with an existing kinematics type needs only a YAML file.
"""

from __future__ import annotations

import math
from collections.abc import Callable
from typing import Any

Derivation = Callable[[dict[str, Any]], dict[str, Any]]
_REGISTRY: dict[str, Derivation] = {}


def register(kinematics: str) -> Callable[[Derivation], Derivation]:
    def deco(fn: Derivation) -> Derivation:
        _REGISTRY[kinematics] = fn
        return fn

    return deco


def known_kinematics() -> list[str]:
    return sorted(_REGISTRY)


def derive(kinematics: str, specs: dict[str, Any]) -> dict[str, Any]:
    if kinematics not in _REGISTRY:
        raise ValueError(f"unknown kinematics '{kinematics}' (known: {known_kinematics()})")
    return _REGISTRY[kinematics](specs)


def _rect_tipping_lines(half_width: float, half_length: float) -> list[dict[str, Any]]:
    return [
        {"axis": "lateral_left", "p0": [-half_length, half_width], "p1": [half_length, half_width]},
        {"axis": "lateral_right", "p0": [-half_length, -half_width], "p1": [half_length, -half_width]},
        {"axis": "front", "p0": [half_length, -half_width], "p1": [half_length, half_width]},
        {"axis": "rear", "p0": [-half_length, -half_width], "p1": [-half_length, half_width]},
    ]


@register("excavator_boom_stick")
def _excavator(specs: dict[str, Any]) -> dict[str, Any]:
    boom, stick, bucket = specs["boom"], specs["stick"], specs["bucket"]
    pivot_x, pivot_z = boom["pivot"]
    max_reach = pivot_x + boom["length_m"] + stick["length_m"] + bucket["length_m"]
    tail = abs(specs["counterweight_offset_m"]) + specs.get("counterweight_depth_m", 0.0) / 2
    n = 24
    envelope = [
        [round(max_reach * math.cos(2 * math.pi * i / n), 3), round(max_reach * math.sin(2 * math.pi * i / n), 3)]
        for i in range(n)
    ]
    return {
        "tail_swing_radius": round(tail, 3),
        "max_reach_m": round(max_reach, 3),
        "boom_pivot_height_m": pivot_z,
        "reach_envelope": envelope,
        "tipping_lines": _rect_tipping_lines(specs["track_gauge_m"] / 2, specs["track_length_m"] / 2),
    }


@register("loader_lift_arm")
def _loader(specs: dict[str, Any]) -> dict[str, Any]:
    arm, bucket = specs["lift_arm"], specs["bucket"]
    reach = arm["pivot"][0] + arm["length_m"] + bucket["length_m"]
    rear = math.hypot(specs["rear_overhang_m"] + specs["wheelbase_m"] / 2, specs["rear_body_width_m"] / 2)
    return {
        "rear_swing_radius": round(rear, 3),
        "max_reach_m": round(reach, 3),
        "tipping_lines": _rect_tipping_lines(specs["track_width_m"] / 2, specs["wheelbase_m"] / 2),
    }


@register("adt_articulated")
def _adt(specs: dict[str, Any]) -> dict[str, Any]:
    wheelbase = specs["wheelbase_front_m"] + specs["wheelbase_rear_m"]
    rear = math.hypot(specs["rear_overhang_m"] + wheelbase / 2, specs["rear_body_width_m"] / 2)
    return {
        "rear_swing_radius": round(rear, 3),
        "wheelbase_total_m": round(wheelbase, 3),
        "tipping_lines": _rect_tipping_lines(specs["track_width_m"] / 2, wheelbase / 2),
    }
