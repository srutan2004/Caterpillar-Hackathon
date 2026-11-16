"""Sensor limit semantics (§6.6): bands, boolean tiers, curve margins (e.g. oil pressure vs rpm)."""

from __future__ import annotations

import math
from typing import Any

import numpy as np

TIERS = ["normal", "monitor", "service_soon", "stop"]


def tier_rank(tier: str | None) -> int:
    return TIERS.index(tier) if tier in TIERS else 0


def worse(a: str | None, b: str | None) -> str:
    return (a or "normal") if tier_rank(a) >= tier_rank(b) else (b or "normal")


def band_tier(limit: dict[str, Any], value: float | bool | None, rpm: float | None = None) -> str:
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return "normal"
    if "boolean" in limit:
        return str(limit["boolean"]["true_tier"]) if bool(value) else "normal"
    if "curve" in limit:
        if rpm is None or math.isnan(rpm):
            return "normal"
        floor = float(np.interp(rpm, limit["curve"]["rpm"], limit["curve"]["min_kpa"]))
        margin = (float(value) - floor) / floor if floor else 0.0
        tier = "normal"
        for t, m in sorted(limit["bands_on_margin"].items(), key=lambda kv: -float(kv[1])):
            if margin < float(m):
                tier = t
        return tier
    v = float(value)
    for t, (lo, hi) in (limit.get("bands") or {}).items():
        if (lo is None or v >= lo) and (hi is None or v < hi):
            return str(t)
    return "normal"


def threshold(limit: dict[str, Any], tier: str) -> float | None:
    """Value at which `tier` starts, in the bad direction (None if the tier has no numeric band)."""
    bands = limit.get("bands") or {}
    if tier not in bands:
        return None
    lo, hi = bands[tier]
    edge = lo if limit["direction"] == "high" else hi
    return None if edge is None else float(edge)


def bad_sign(limit: dict[str, Any]) -> float:
    return 1.0 if limit["direction"] == "high" else -1.0


def catalogue_code(limit: dict[str, Any], tier: str) -> str | None:
    ref = limit.get("catalogue_ref")
    if isinstance(ref, dict):
        return ref.get(tier) or ref.get("default")
    return ref
