"""Ground properties from moisture (§7.3 Ground, §10.4.6 ground risk). Shared by the generator and the edge."""

from __future__ import annotations

from typing import Any

import numpy as np


def ground_properties(
    m: np.ndarray | float, soil: dict[str, Any], weights: dict[str, float], surface_risk: dict[str, float]
) -> dict[str, Any]:
    m = np.asarray(m, dtype=float)
    excess = m - soil["m_field"]
    density = soil["density_t_m3"] * (1 + 0.1 * excess)
    bearing = soil["bearing_kpa_dry"] * np.clip(1 - soil["bearing_moisture_k"] * (m - soil["m_min"]), 0.2, 1.0)
    fos = soil["fos_base"] * np.clip(1 - soil["fos_moisture_k"] * np.clip(excess, 0, None), 0.5, 1.0)
    wet = excess > 0.05
    surface = np.where(
        wet,
        surface_risk["wet"],
        np.where(
            soil["abrasiveness"] > 2,
            surface_risk["rocky"],
            np.where(soil["m_sat"] < 0.4, surface_risk["loose"], surface_risk["firm"]),
        ),
    )
    moist_norm = np.clip((m - soil["m_min"]) / (soil["m_sat"] - soil["m_min"]), 0, 1)
    slip = 0.1 + 0.4 * moist_norm
    risk = (
        weights["w1_surface"] * surface
        + weights["w2_slip"] * slip
        + weights["w3_inv_fos"] * np.clip(1 / fos, 0, 1)
        + weights["w4_moisture"] * moist_norm
    )
    return {"density": density, "bearing_kpa": bearing, "slope_fos": fos, "risk_score": np.clip(risk, 0, 1)}
