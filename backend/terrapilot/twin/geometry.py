"""Small vector helpers (tuples keep the edge code dependency-free and fast)."""

from __future__ import annotations

import itertools
import math

Vec2 = tuple[float, float]
Vec3 = tuple[float, float, float]


def rotate2(p: Vec2, angle_rad: float) -> Vec2:
    c, s = math.cos(angle_rad), math.sin(angle_rad)
    return (p[0] * c - p[1] * s, p[0] * s + p[1] * c)


def norm2(p: Vec2) -> float:
    return math.hypot(p[0], p[1])


def point_segment_distance3(p: Vec3, a: Vec3, b: Vec3) -> tuple[float, Vec3]:
    """Distance from p to segment ab and the closest point on the segment."""
    ab = (b[0] - a[0], b[1] - a[1], b[2] - a[2])
    ap = (p[0] - a[0], p[1] - a[1], p[2] - a[2])
    denom = ab[0] ** 2 + ab[1] ** 2 + ab[2] ** 2
    t = 0.0 if denom == 0 else max(0.0, min(1.0, (ap[0] * ab[0] + ap[1] * ab[1] + ap[2] * ab[2]) / denom))
    c = (a[0] + t * ab[0], a[1] + t * ab[1], a[2] + t * ab[2])
    return math.dist(p, c), c


def polyline_distance3(p: Vec3, pts: list[Vec3]) -> tuple[float, Vec3]:
    best: tuple[float, Vec3] = (math.inf, p)
    for a, b in itertools.pairwise(pts):
        d = point_segment_distance3(p, a, b)
        if d[0] < best[0]:
            best = d
    return best


def rect_edge_distance(direction_rad: float, half_length: float, half_width: float) -> tuple[float, str]:
    """Distance from the centre to a rectangle's edge along a direction (machine frame: x forward).

    Returns the distance and the limiting axis ("longitudinal" over front/rear, "lateral" over the side).
    """
    c, s = abs(math.cos(direction_rad)), abs(math.sin(direction_rad))
    dx = half_length / c if c > 1e-9 else math.inf
    dy = half_width / s if s > 1e-9 else math.inf
    return (dx, "longitudinal") if dx <= dy else (dy, "lateral")
