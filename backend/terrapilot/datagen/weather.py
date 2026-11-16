"""Weather (§7.3): climate seasonal curve + AR(1) noise + Markov wet days + storms/dust/fog events.
Also the lead-time–dependent forecasts (weather, truck availability) the optimiser sees.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

import numpy as np
import pandas as pd

from terrapilot.datagen.context import GenContext

WX_VARS = ["temp_c", "rh", "rain_mm", "wind_ms", "gust_ms", "visibility_m", "lightning_km", "pm10", "heat_index"]


@dataclass
class HourlyWeather:
    """Truth weather for one site on the global hour grid starting at `t0` (UTC)."""

    t0: datetime
    data: dict[str, np.ndarray]

    def idx(self, ts: datetime) -> int:
        i = int((ts - self.t0).total_seconds() // 3600)
        return min(max(i, 0), len(self.data["temp_c"]) - 1)

    def idx_s(self, t: float) -> int:
        i = int((t - self.t0.timestamp()) // 3600)
        return min(max(i, 0), len(self.data["temp_c"]) - 1)

    def at(self, ts: datetime) -> dict[str, float]:
        i = self.idx(ts)
        return {k: float(v[i]) for k, v in self.data.items()}

    def window_mean(self, start: datetime, end: datetime, var: str) -> float:
        a, b = self.idx(start), max(self.idx(end), self.idx(start) + 1)
        return float(np.mean(self.data[var][a:b]))

    def window_sum(self, start: datetime, end: datetime, var: str) -> float:
        a, b = self.idx(start), max(self.idx(end), self.idx(start) + 1)
        return float(np.sum(self.data[var][a:b]))


def heat_index_c(temp_c: np.ndarray, rh: np.ndarray) -> np.ndarray:
    """NOAA Rothfusz regression (°F internally); equals the air temperature below ~27 °C."""
    t = temp_c * 9 / 5 + 32
    hi = (
        -42.379
        + 2.04901523 * t
        + 10.14333127 * rh
        - 0.22475541 * t * rh
        - 6.83783e-3 * t**2
        - 5.481717e-2 * rh**2
        + 1.22874e-3 * t**2 * rh
        + 8.5282e-4 * t * rh**2
        - 1.99e-6 * t**2 * rh**2
    )
    hi_c = (hi - 32) * 5 / 9
    return np.where(temp_c >= 26.7, hi_c, temp_c)


def _monthly_interp(values: list[float], months: np.ndarray, day_of_month: np.ndarray) -> np.ndarray:
    """Linear interpolation between mid-month values so seasons change smoothly."""
    arr = np.asarray(values, dtype=float)
    pos = (months - 1) + (day_of_month - 15) / 30.0
    lo = np.floor(pos).astype(int) % 12
    hi = (lo + 1) % 12
    frac = pos - np.floor(pos)
    out: np.ndarray = arr[lo] * (1 - frac) + arr[hi] * frac
    return out


def generate_weather(ctx: GenContext) -> None:
    climate = ctx.dg["climate"]
    hours = ctx.hours_index()
    local = hours.tz_convert(ctx.tz)
    n = len(hours)
    frames, truth = [], {}
    for s in ctx.world["sites"]:
        rng = ctx.rng(f"weather:{s['id']}")
        z = climate["zones"][s["climate"]]
        noise, storms, dust, vis_cfg, pm_cfg = (
            climate["noise"],
            climate["storms"],
            climate["dust_events"],
            climate["visibility"],
            climate["pm10"],
        )
        month = local.month.to_numpy()
        dom = local.day.to_numpy()
        hour = local.hour.to_numpy()
        day_key = (local.normalize().tz_localize(None) - local[0].normalize().tz_localize(None)).days.to_numpy()
        n_days = int(day_key.max()) + 1
        day_month = np.array([month[np.argmax(day_key == d)] for d in range(n_days)])

        # --- wet-day Markov chain, storms, dust events, fog
        wet = np.zeros(n_days, dtype=bool)
        daily_rain = np.zeros(n_days)
        storm = np.zeros(n_days, dtype=bool)
        dust_day = np.zeros(n_days, dtype=bool)
        fog_day = np.zeros(n_days, dtype=bool)
        for d in range(n_days):
            m = day_month[d] - 1
            p = z["p_wet_given_wet"][m] if d and wet[d - 1] else z["p_wet_given_dry"][m]
            wet[d] = rng.random() < p
            if wet[d]:
                daily_rain[d] = rng.exponential(z["wet_day_rain_mm_mean"][m])
                storm[d] = rng.random() < z["storm_prob_per_wet_day"]
            dust_day[d] = (not wet[d]) and rng.random() < z["dust_event_prob_per_day"][m]
            fog_day[d] = rng.random() < z["fog_prob_per_day"][m]

        profile = np.asarray(noise["rain_hour_profile"], dtype=float)
        profile = profile / profile.sum()
        rain = np.zeros(n)
        lightning = np.full(n, float(storms["no_lightning_km"]))
        gust_boost = np.zeros(n)
        dust_pm = np.zeros(n)
        dust_vis = np.full(n, np.inf)
        dust_wind = np.zeros(n)
        for d in map(int, np.flatnonzero(wet)):
            idx = np.flatnonzero(day_key == d)
            w = rng.gamma(0.6, 1.0, size=len(idx)) * profile[hour[idx]]
            rain[idx] = daily_rain[d] * w / w.sum()
            if storm[d]:
                start = int(rng.choice(len(idx), p=profile[hour[idx]] / profile[hour[idx]].sum()))
                dur = int(rng.integers(storms["duration_h"]["min"], storms["duration_h"]["max"] + 1))
                sidx = idx[start : start + dur]
                rain[sidx] *= storms["rain_boost_factor"]
                lightning[sidx] = rng.uniform(storms["lightning_km"]["min"], storms["lightning_km"]["max"], len(sidx))
                gust_boost[sidx] = rng.uniform(
                    storms["gust_boost_ms"]["min"], storms["gust_boost_ms"]["max"], len(sidx)
                )
        for d in map(int, np.flatnonzero(dust_day)):
            idx = np.flatnonzero(day_key == d)
            start = int(rng.integers(max(0, len(idx) // 2 - 3), max(1, len(idx) - 4)))
            dur = int(rng.integers(dust["duration_h"]["min"], dust["duration_h"]["max"] + 1))
            didx = idx[start : start + dur]
            dust_pm[didx] = rng.uniform(dust["pm10"]["min"], dust["pm10"]["max"])
            dust_vis[didx] = rng.uniform(dust["visibility_m"]["min"], dust["visibility_m"]["max"])
            dust_wind[didx] = rng.uniform(dust["wind_boost_ms"]["min"], dust["wind_boost_ms"]["max"])

        # --- temperature: seasonal + diurnal + AR(1), cooled by rain
        t_mean = _monthly_interp(z["temp_monthly_mean_c"], month, dom)
        amp = _monthly_interp(z["diurnal_amplitude_c"], month, dom)
        ar = np.zeros(n)
        eps = rng.normal(0, noise["temp_ar1_sd_c"], n)
        for i in range(1, n):
            ar[i] = noise["temp_ar1_phi"] * ar[i - 1] + eps[i]
        diurnal = np.cos(2 * np.pi * (hour - 15) / 24)
        temp = t_mean + amp * diurnal + ar - noise["rain_cooling_c"] * (rain > 0.2)

        rh = _monthly_interp(z["rh_monthly_mean"], month, dom) - 12 * diurnal + rng.normal(0, noise["rh_sd"], n)
        rh = np.where(rain > 0.2, rng.uniform(88, 98, n), rh)
        rh = np.clip(rh, 5, 100)

        wind_mean = _monthly_interp(z["wind_monthly_mean_ms"], month, dom) * (1 + 0.25 * np.clip(diurnal, 0, None))
        k = noise["wind_weibull_k"]
        wind = wind_mean / 0.886 * rng.weibull(k, n)
        wind = pd.Series(wind).rolling(3, min_periods=1, center=True).mean().to_numpy() + dust_wind
        gust = wind * z["gust_factor"] * rng.uniform(0.9, 1.15, n) + gust_boost

        dry_run = np.zeros(n)
        counter = 0
        for d in range(n_days):
            counter = 0 if wet[d] else counter + 1
            dry_run[day_key == d] = counter
        pm10 = z["pm10_base"] * (1 + pm_cfg["dry_day_buildup"] * np.minimum(dry_run, 10)) * (1 + 0.2 * diurnal)
        pm10 *= rng.lognormal(0, 0.15, n)
        pm10 = np.where(rain > 0.2, pm10 * (1 - pm_cfg["rain_washout"]), pm10)
        pm10 = np.maximum(pm10, dust_pm)

        vis = vis_cfg["clear_m"] * np.clip(1 - vis_cfg["per_rain_mm_h_reduction"] * rain, 0, 1)
        vis = np.maximum(vis, np.where(rain > 0, vis_cfg["min_rain_m"], 0))
        vis = np.minimum(vis, dust_vis)
        fog_hours = np.isin(hour, vis_cfg["fog_hours_local"]) & fog_day[day_key]
        vis = np.where(fog_hours, rng.uniform(vis_cfg["fog_m"]["min"], vis_cfg["fog_m"]["max"], n), vis)

        data = {
            "temp_c": temp,
            "rh": rh,
            "rain_mm": rain,
            "wind_ms": wind,
            "gust_ms": gust,
            "visibility_m": vis,
            "lightning_km": lightning,
            "pm10": pm10,
        }
        _apply_overrides(ctx, s["id"], local, data)
        data["heat_index"] = heat_index_c(data["temp_c"], data["rh"])
        data = {k: np.round(v.astype(float), 2) for k, v in data.items()}
        truth[s["id"]] = HourlyWeather(hours[0].to_pydatetime(), data)
        frames.append(pd.DataFrame({"ts": hours, "site_id": s["id"], **data}))

    full = pd.concat(frames, ignore_index=True)
    ctx.emit("truth_weather_hourly", full)
    ctx.emit("weather_hourly", full[full["ts"] < pd.Timestamp(ctx.now)].reset_index(drop=True))
    ctx.state["wx"] = truth


def _apply_overrides(ctx: GenContext, site_id: str, local: pd.DatetimeIndex, data: dict[str, np.ndarray]) -> None:
    for ov in (ctx.dg.get("demo_fixtures") or {}).get("weather_overrides", []):
        if ov["site"] != site_id:
            continue
        day = ctx.anchor + timedelta(days=int(ov["day_offset"]))
        mask = (local.date == day) & np.isin(local.hour, ov["hours_local"])
        for var, value in ov["set"].items():
            data[var] = np.where(mask, float(value), data[var])


# ------------------------------------------------------------------------------------------ forecasts
def generate_forecasts(ctx: GenContext) -> None:
    fc = ctx.dg["forecasts"]
    res = ctx.world["resolution"]["forecast"]
    horizon = int(res["horizon_h"])
    issue_days = [ctx.anchor - timedelta(days=i) for i in range(int(res["history_issues_days"]), -1, -1)]
    rows: dict[str, list[np.ndarray]] = {k: [] for k in ("issued_at", "site_id", "valid_at", "var", "value", "spread")}
    latest: dict[str, dict[str, np.ndarray]] = {}
    for s in ctx.world["sites"]:
        wx: HourlyWeather = ctx.state["wx"][s["id"]]
        rng = ctx.rng(f"forecast:{s['id']}")
        for day in issue_days:
            issued = ctx.local_dt(day, res["issue_local"])
            valid = pd.date_range(issued + timedelta(hours=1), periods=horizon, freq="h")
            lead = np.arange(1, horizon + 1, dtype=float)
            i0 = wx.idx(valid[0].to_pydatetime())
            for var, spec in fc["variables"].items():
                truth = wx.data[var][i0 : i0 + horizon]
                if len(truth) < horizon:
                    continue
                sd = spec["sd0"] + spec["sd_per_h"] * lead
                err = np.zeros(horizon)
                z = rng.normal(0, 1, horizon)
                for i in range(horizon):
                    err[i] = spec["ar_phi"] * (err[i - 1] if i else 0) + np.sqrt(1 - spec["ar_phi"] ** 2) * z[i]
                value = truth + err * sd
                if "multiplicative_sd" in spec:
                    value = truth * rng.lognormal(0, spec["multiplicative_sd"], horizon) + np.clip(
                        err * sd, 0, None
                    ) * (truth > 0)
                    missed = rng.random(horizon) < spec["miss_prob_per_h"] * lead
                    value = np.where(missed, 0.0, value)
                lo, hi = spec.get("clip") or [None, None]
                value = np.clip(value, lo if lo is not None else -np.inf, hi if hi is not None else np.inf)
                rows["issued_at"].append(np.full(horizon, pd.Timestamp(issued)))
                rows["site_id"].append(np.full(horizon, s["id"]))
                rows["valid_at"].append(valid.to_numpy())
                rows["var"].append(np.full(horizon, var))
                rows["value"].append(np.round(value, 2))
                rows["spread"].append(np.round(sd, 2))
                if day == ctx.anchor:
                    latest.setdefault(s["id"], {})[var] = value
                    latest[s["id"]]["_valid"] = valid.to_numpy()
    df = pd.DataFrame({k: np.concatenate(v) for k, v in rows.items()})
    df["issued_at"] = pd.to_datetime(df["issued_at"], utc=True)
    df["valid_at"] = pd.to_datetime(df["valid_at"], utc=True)
    ctx.emit("weather_forecast", df)
    ctx.state["latest_forecast"] = latest
    _truck_forecast(ctx)


def _truck_forecast(ctx: GenContext) -> None:
    spec = ctx.dg["forecasts"]["truck_availability"]
    issued = ctx.local_dt(ctx.anchor, ctx.world["resolution"]["forecast"]["issue_local"])
    valid = pd.date_range(issued + timedelta(hours=1), periods=int(spec["horizon_h"]), freq="h")
    lead = np.arange(1, len(valid) + 1)
    frames = []
    for s in ctx.world["sites"]:
        rng = ctx.rng(f"trucks_fc:{s['id']}")
        expected = s["truck_count"] * (1 - spec["breakdown_prob_per_day"])
        sd = spec["sd0"] + spec["sd_per_h"] * lead
        p50 = np.clip(expected + rng.normal(0, 1, len(valid)) * sd, 0, s["truck_count"])
        frames.append(
            pd.DataFrame(
                {
                    "issued_at": pd.Timestamp(issued),
                    "site_id": s["id"],
                    "valid_at": valid,
                    "trucks_p50": np.round(p50, 2),
                    "trucks_p10": np.round(np.clip(p50 - 1.28 * sd, 0, None), 2),
                }
            )
        )
    ctx.emit("truck_availability_forecast", pd.concat(frames, ignore_index=True))
