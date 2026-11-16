"""Fatigue and whole-body vibration (§10.4.7). Pure maths — no camera frames ever leave the machine.

Fatigue: PERCLOS and microsleeps from eye-aspect-ratio samples (MediaPipe on the edge, or simulated signals),
combined with hours on shift, circadian phase and heat in a logistic score.
WBV: frequency-weighted A(8) per ISO 2631-1, compared with the exposure action/limit values in config.
"""

from __future__ import annotations

import math
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

import numpy as np

SECONDS_PER_HOUR = 3600.0
T0_HOURS = 8.0  # A(8) reference period


@dataclass
class FatigueState:
    score: float
    tier: str
    perclos: float
    microsleeps: int
    blink_rate_per_min: float
    hours_on_shift: float
    break_min: int

    def as_dict(self) -> dict[str, Any]:
        return {
            "score": round(self.score, 3),
            "tier": self.tier,
            "perclos": round(self.perclos, 3),
            "microsleeps": self.microsleeps,
            "blink_rate_per_min": round(self.blink_rate_per_min, 1),
            "hours_on_shift": round(self.hours_on_shift, 2),
            "break_min": self.break_min,
        }


class FatigueMonitor:
    """Rolling PERCLOS over `window_s`; `observe` takes one eye-aspect-ratio sample per frame."""

    def __init__(self, cfg: dict[str, Any], shift_start: datetime):
        self.c = cfg
        self.shift_start = shift_start
        self.samples: deque[tuple[float, float]] = deque()  # (t, ear)
        self.microsleeps = 0
        self._closed_since: float | None = None
        self._blinks = 0

    def observe(self, t: float, ear: float) -> None:
        closed = ear < float(self.c["ear_closed_threshold"])
        self.samples.append((t, 1.0 if closed else 0.0))
        window = float(self.c["window_s"])
        while self.samples and t - self.samples[0][0] > window:
            self.samples.popleft()
        if closed and self._closed_since is None:
            self._closed_since = t
        elif not closed and self._closed_since is not None:
            duration = t - self._closed_since
            if duration >= float(self.c["microsleep_s"]):
                self.microsleeps += 1
            else:
                self._blinks += 1
            self._closed_since = None

    def score(self, now: datetime, heat_index_c: float | None = None) -> FatigueState:
        perclos = float(np.mean([v for _, v in self.samples])) if self.samples else 0.0
        hours = max((now - self.shift_start).total_seconds() / SECONDS_PER_HOUR, 0.0)
        span_min = ((self.samples[-1][0] - self.samples[0][0]) / 60) if len(self.samples) > 1 else 0.0
        blink_rate = self._blinks / span_min if span_min > 0 else 0.0
        w = self.c["weights"]
        circadian = math.cos(2 * math.pi * (now.hour + now.minute / 60 - float(self.c["circadian_peak_hour"])) / 24)
        heat = max(0.0, (heat_index_c or 0.0) - float(self.c["heat_ref_c"])) if heat_index_c is not None else 0.0
        z = (
            float(w["intercept"])
            + float(w["perclos"]) * perclos
            + float(w["microsleeps"]) * self.microsleeps
            + float(w["hours"]) * hours
            + float(w["circadian"]) * max(0.0, -circadian)
            + float(w["heat"]) * heat
        )
        score = 1 / (1 + math.exp(-z))
        tiers = self.c["tiers"]
        tier = (
            "warning"
            if score >= float(tiers["warning"])
            else "caution"
            if score >= float(tiers["caution"])
            else "advisory"
            if score >= float(tiers["advisory"])
            else "normal"
        )
        return FatigueState(score, tier, perclos, self.microsleeps, blink_rate, hours, int(self.c["break_min"]))


# ------------------------------------------------------------------ WBV (ISO 2631-1)
@dataclass
class WbvState:
    a8: float
    exposure_ratio: float
    tier: str
    hours: float
    projected_a8: float
    samples: int = field(default=0)

    def as_dict(self) -> dict[str, Any]:
        return {
            "a8_ms2": round(self.a8, 3),
            "projected_a8_ms2": round(self.projected_a8, 3),
            "exposure_ratio": round(self.exposure_ratio, 3),
            "tier": self.tier,
            "hours": round(self.hours, 2),
            "samples": self.samples,
        }


class WbvMonitor:
    """A(8) = sqrt( (1/T0) Σ a_w,i² · t_i ) with the ISO axis weighting (1.4× on x/y, 1.0 on z)."""

    def __init__(self, cfg: dict[str, Any]):
        self.c = cfg
        self.energy = 0.0  # Σ a_w² · t, in m²/s⁴ · s
        self.seconds = 0.0
        self.samples = 0

    def observe(self, ax: float, ay: float, az: float, dt: float) -> None:
        kx, ky, kz = (float(self.c["axis_weights"][k]) for k in ("x", "y", "z"))
        aw = math.sqrt((kx * ax) ** 2 + (ky * ay) ** 2 + (kz * az) ** 2)
        self.energy += aw**2 * dt
        self.seconds += dt
        self.samples += 1

    def state(self, shift_length_h: float | None = None) -> WbvState:
        hours = self.seconds / SECONDS_PER_HOUR
        a8 = math.sqrt(self.energy / (T0_HOURS * SECONDS_PER_HOUR)) if self.seconds > 0 else 0.0
        remaining = max((shift_length_h or hours) - hours, 0.0)
        rate = self.energy / self.seconds if self.seconds > 0 else 0.0
        projected = (
            math.sqrt((self.energy + rate * remaining * SECONDS_PER_HOUR) / (T0_HOURS * SECONDS_PER_HOUR))
            if self.seconds
            else 0.0
        )
        action, limit = float(self.c["action_value_ms2"]), float(self.c["limit_value_ms2"])
        tier = (
            "warning" if a8 >= limit else "caution" if a8 >= action else "advisory" if projected >= action else "normal"
        )
        return WbvState(a8, a8 / limit if limit else 0.0, tier, hours, projected, self.samples)
