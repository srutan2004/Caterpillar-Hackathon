"""SHAP → localisable factors (§11 `ml/explain.py`).

LightGBM's `pred_contrib` gives exact TreeSHAP values in the model's output space (log minutes per unit).
They are turned into minutes relative to the model's base value and mapped to i18n keys `factor.<feature>`.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

import numpy as np


@dataclass(frozen=True)
class Factor:
    feature: str
    key: str
    minutes: float
    value: Any

    def as_dict(self) -> dict[str, Any]:
        return {"feature": self.feature, "key": self.key, "minutes": round(self.minutes, 1), "value": self.value}


def contributions_to_minutes(contrib: np.ndarray, p50_min: float) -> np.ndarray:
    """Each log-space contribution c is expressed as the minutes it adds at the predicted p50:
    p50 · (1 − e^(−c)). Positive = makes the task longer."""
    return p50_min * (1 - np.exp(-contrib))


def top_factors(
    features: list[str],
    contrib_row: np.ndarray,
    p50_min: float,
    row: dict[str, Any],
    top_n: int,
    min_abs_min: float,
    exclude: frozenset[str] = frozenset(),
) -> list[Factor]:
    mins = contributions_to_minutes(np.asarray(contrib_row[: len(features)], dtype=float), p50_min)
    order = np.argsort(-np.abs(mins))
    out = []
    for i in order:
        if features[i] in exclude or abs(mins[i]) < min_abs_min or math.isnan(mins[i]):
            continue
        f = features[i]
        out.append(Factor(f, f"factor.{f}", float(mins[i]), _plain(row.get(f))))
        if len(out) >= top_n:
            break
    return out


def factor_deltas(
    features: list[str],
    a: np.ndarray,
    b: np.ndarray,
    p50_b_min: float,
    min_abs_min: float,
    top_n: int,
    exclude: frozenset[str] = frozenset(),
) -> list[Factor]:
    """Why is start B different from start A? Difference of SHAP rows, in minutes at B (§10.14 step 6)."""
    d = contributions_to_minutes(np.asarray(b[: len(features)]) - np.asarray(a[: len(features)]), p50_b_min)
    order = np.argsort(np.abs(d))[::-1]
    return [
        Factor(features[i], f"factor.{features[i]}", float(d[i]), None)
        for i in [j for j in order if features[j] not in exclude][:top_n]
        if abs(d[i]) >= min_abs_min
    ]


def _plain(v: Any) -> Any:
    if isinstance(v, float | np.floating):
        return None if math.isnan(float(v)) else round(float(v), 3)
    return v
