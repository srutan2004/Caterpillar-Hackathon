"""Proximity tracks (§10.4.2): constant-velocity tracks, closest point of approach and time-to-collision
against the machine's dynamic hazard radius, with static-object suppression."""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from terrapilot.twin.geometry import Vec2


@dataclass
class Track:
    track_id: str
    kind: str
    pos: Vec2
    vel: Vec2 = (0.0, 0.0)
    ppe: dict[str, bool] = field(default_factory=dict)
    last_t: float | None = None

    def update(self, pos: Vec2, t: float, alpha: float) -> None:
        """Exponentially smoothed velocity estimate (a 1-state α filter standing in for a CV Kalman)."""
        if self.last_t is not None and t > self.last_t:
            dt = t - self.last_t
            raw = ((pos[0] - self.pos[0]) / dt, (pos[1] - self.pos[1]) / dt)
            self.vel = (alpha * raw[0] + (1 - alpha) * self.vel[0], alpha * raw[1] + (1 - alpha) * self.vel[1])
        self.pos = pos
        self.last_t = t


@dataclass(frozen=True)
class TrackRisk:
    track_id: str
    kind: str
    distance_m: float
    ttc_s: float | None
    cpa_m: float
    static: bool
    zone: str | None
    ppe: dict[str, bool]
    pos: Vec2
    vel: Vec2


def time_to_radius(p: Vec2, v: Vec2, radius: float) -> float | None:
    """Earliest t ≥ 0 with |p + v t| = radius (None if never entered); 0 if already inside."""
    if math.hypot(*p) <= radius:
        return 0.0
    a = v[0] ** 2 + v[1] ** 2
    if a < 1e-12:
        return None
    b = 2 * (p[0] * v[0] + p[1] * v[1])
    c = p[0] ** 2 + p[1] ** 2 - radius**2
    disc = b * b - 4 * a * c
    if disc < 0:
        return None
    t = (-b - math.sqrt(disc)) / (2 * a)
    return t if t >= 0 else None


def assess(track: Track, hazard_radius_m: float, zones_m: dict[str, float], min_moving_speed_ms: float) -> TrackRisk:
    p, v = track.pos, track.vel
    dist = math.hypot(*p)
    speed = math.hypot(*v)
    a = v[0] ** 2 + v[1] ** 2
    t_cpa = max(0.0, -(p[0] * v[0] + p[1] * v[1]) / a) if a > 1e-12 else 0.0
    cpa = math.hypot(p[0] + v[0] * t_cpa, p[1] + v[1] * t_cpa)
    static = speed < min_moving_speed_ms and dist > hazard_radius_m
    ttc = None if static else time_to_radius(p, v, hazard_radius_m)
    zone = next((tier for tier in ("warning", "caution", "advisory") if dist < zones_m[tier]), None)
    return TrackRisk(
        track.track_id,
        track.kind,
        round(dist, 2),
        None if ttc is None else round(ttc, 2),
        round(cpa, 2),
        static,
        zone,
        dict(track.ppe),
        p,
        v,
    )
