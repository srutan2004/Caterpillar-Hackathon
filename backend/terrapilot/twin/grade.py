"""Grade deviation vs. the design surface (§10.4, cockpit GradeProfile)."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class DesignSurface:
    origin: tuple[float, float]
    cell_m: float
    grid: list[list[float]]  # rows (y) × cols (x), elevation relative to machine ground level

    @classmethod
    def from_row(cls, row: dict[str, Any]) -> DesignSurface:
        import json

        origin = row["origin"] if isinstance(row["origin"], list) else json.loads(row["origin"])
        grid = row["grid"] if isinstance(row["grid"], list) else json.loads(row["grid"])
        return cls((float(origin[0]), float(origin[1])), float(row["cell_m"]), [[float(v) for v in r] for r in grid])

    def elevation(self, x: float, y: float) -> float | None:
        j = math.floor((x - self.origin[0]) / self.cell_m)
        i = math.floor((y - self.origin[1]) / self.cell_m)
        if 0 <= i < len(self.grid) and 0 <= j < len(self.grid[0]):
            return self.grid[i][j]
        return None


@dataclass(frozen=True)
class GradeState:
    deviation_m: float
    direction: str  # raise | lower | on_grade
    design_z: float
    tip_z: float


def grade_deviation(tip_z: float, design_z: float, tolerance_m: float) -> GradeState:
    dev = tip_z - design_z
    direction = "on_grade" if abs(dev) <= tolerance_m else ("raise" if dev < 0 else "lower")
    return GradeState(round(dev, 3), direction, round(design_z, 3), round(tip_z, 3))
