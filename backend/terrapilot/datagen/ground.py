"""Ground model (§7.3 Ground): hourly moisture per zone follows rain with soil-specific drainage.
Daily conditions (density, bearing capacity, slope FoS, risk) derive from moisture.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any

import numpy as np
import pandas as pd

from terrapilot.datagen.context import GenContext
from terrapilot.datagen.weather import HourlyWeather
from terrapilot.twin.ground import ground_properties

__all__ = ["ground_properties"]


def step_moisture(m: float, rain_mm: float, temp_c: float, soil: dict[str, Any]) -> float:
    m = m + soil["infiltration"] * rain_mm * (1 - m / soil["m_sat"])
    m = m - soil["drain_per_h"] * max(0.0, m - soil["m_field"])
    m = m - soil["evap_per_h_per_c"] * max(temp_c, 0.0) * (m > soil["m_min"])
    return float(min(max(m, soil["m_min"]), soil["m_sat"]))


def run_moisture(rain: np.ndarray, temp: np.ndarray, soil: dict[str, Any], m0: float | None = None) -> np.ndarray:
    out = np.empty(len(rain))
    m = soil["m_field"] if m0 is None else m0
    for i in range(len(rain)):
        m = step_moisture(m, float(rain[i]), float(temp[i]), soil)
        out[i] = m
    return out


def generate_ground(ctx: GenContext) -> None:
    gcfg = ctx.dg["ground"]
    soils = gcfg["soils"]
    hours = ctx.hours_index()
    local_dates = hours.tz_convert(ctx.tz).date
    moist: dict[str, np.ndarray] = {}
    truth_frames, daily_frames = [], []
    zones = ctx.tables["zones"]
    history = set(ctx.history_dates())
    for z in zones.itertuples():
        wx: HourlyWeather = ctx.state["wx"][z.site_id]
        soil = soils[z.soil]
        m = run_moisture(wx.data["rain_mm"], wx.data["temp_c"], soil)
        moist[z.id] = m
        truth_frames.append(pd.DataFrame({"ts": hours, "zone_id": z.id, "moisture": np.round(m, 4)}))
        df = pd.DataFrame({"date": local_dates, "m": m}).groupby("date", as_index=False)["m"].mean()
        df = df[df["date"].isin(history)]
        props = ground_properties(
            df["m"].to_numpy(), soil, gcfg["ground_risk"]["weights"], gcfg["ground_risk"]["surface_class_risk"]
        )
        daily_frames.append(
            pd.DataFrame(
                {
                    "date": df["date"].to_numpy(),
                    "zone_id": z.id,
                    "site_id": z.site_id,
                    "soil": z.soil,
                    "moisture": np.round(df["m"].to_numpy(), 4),
                    **{k: np.round(v, 3) for k, v in props.items()},
                }
            )
        )
    ctx.emit("truth_ground_hourly", pd.concat(truth_frames, ignore_index=True))
    ctx.emit("ground_conditions", pd.concat(daily_frames, ignore_index=True))
    ctx.state["moist"] = moist


def generate_moisture_forecast(ctx: GenContext) -> None:
    """Today's issue: run the ground model forward on the forecast rain/temperature."""
    soils = ctx.dg["ground"]["soils"]
    latest = ctx.state.get("latest_forecast", {})
    issued = ctx.local_dt(ctx.anchor, ctx.world["resolution"]["forecast"]["issue_local"])
    frames = []
    for z in ctx.tables["zones"].itertuples():
        fc = latest.get(z.site_id)
        if not fc:
            continue
        wx: HourlyWeather = ctx.state["wx"][z.site_id]
        m0 = float(ctx.state["moist"][z.id][wx.idx(issued)])
        path = run_moisture(fc["rain_mm"], fc["temp_c"], soils[z.soil], m0)
        lead = np.arange(1, len(path) + 1)
        frames.append(
            pd.DataFrame(
                {
                    "issued_at": pd.Timestamp(issued),
                    "zone_id": z.id,
                    "valid_at": pd.to_datetime(fc["_valid"], utc=True),
                    "moisture": np.round(path, 4),
                    "spread": np.round(0.005 + 0.0015 * lead, 4),
                }
            )
        )
    if frames:
        ctx.emit("ground_moisture_forecast", pd.concat(frames, ignore_index=True))


def moisture_at(ctx: GenContext, zone_id: str, site_id: str, ts: Any) -> float:
    wx: HourlyWeather = ctx.state["wx"][site_id]
    return float(ctx.state["moist"][zone_id][wx.idx(ts)])


def rain_last_hours(wx: HourlyWeather, ts: Any, hours: int) -> float:
    return wx.window_sum(ts - timedelta(hours=hours), ts, "rain_mm")
