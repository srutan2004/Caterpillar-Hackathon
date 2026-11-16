"""Feature registry (§11 shared utilities): one definition used by training and serving, so they never skew.

`TaskFeatureBuilder.history()` builds one row per completed task from observed tables. `for_task()` builds the
same columns for a task at a candidate start time, reading forecasts for hours that have not happened yet.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

from terrapilot.core.config import ConfigBundle
from terrapilot.core.refs import load_ref_cached
from terrapilot.ml.data import Tables

WEATHER_VARS = ("temp_c", "rain_mm", "wind_ms", "gust_ms", "visibility_m", "lightning_km", "pm10")
MINUTES_PER_HOUR = 60.0


@dataclass(frozen=True)
class Window:
    """Aggregated covariates over the expected work window."""

    temp_c: float
    rain_mm_h: float
    gust_ms: float
    visibility_low: float
    stop_weather_hours: float
    hours: int


def model_cfg(cfg: ConfigBundle, name: str) -> dict[str, Any]:
    return dict(cfg.models["models"][name])


class TaskFeatureBuilder:
    def __init__(self, cfg: ConfigBundle, tables: Tables):
        self.cfg = cfg
        self.t = tables
        self.mcfg = model_cfg(cfg, "task_duration")
        cov = self.mcfg["covariates"]
        self.soils: dict[str, dict[str, float]] = load_ref_cached(cfg.root, cov["soil_properties_ref"])
        self.hard_stop: dict[str, float] = load_ref_cached(cfg.root, cov["hard_stop_ref"])
        self.vis_low_m = float(cov["visibility_low_m"])
        self.heat_c = float(cov["heat_comfort_c"])
        cal = cfg.app.site_calendar
        self.tz = ZoneInfo(str(cal["timezone"]))
        self.shift = cal["shift"]
        self.zones = tables.get("zones").set_index("id")
        self.profiles = tables.get("operator_profiles").set_index("user_id")
        self.machines = tables.get("machines").set_index("id")
        wx = tables.get("weather_hourly")
        self._obs = {s: g.set_index("ts").sort_index() for s, g in wx.groupby("site_id")} if not wx.empty else {}
        self._fc: dict[str, pd.DataFrame] | None = None
        self._ground = tables.get("ground_conditions")
        self._gm_fc = tables.get("ground_moisture_forecast")
        self._ctx = tables.get("task_start_context")

    # ------------------------------------------------------------------ helpers
    def capacity_m3(self, machine_class: str, manifest_id: str | None = None) -> float:
        manifests = [self.cfg.manifests_raw[manifest_id]] if manifest_id in self.cfg.manifests_raw else []
        manifests = manifests or [self.cfg.manifests_raw[m.id] for m in self.cfg.manifests_for_class(machine_class)]
        specs = manifests[0]["specs"] if manifests else {}
        return float((specs.get("bucket") or {}).get("capacity_m3") or specs.get("body_capacity_m3") or 0.0)

    def breaks_overlap_min(self, start: datetime | pd.Timestamp, end: datetime | pd.Timestamp) -> float:
        local = pd.Timestamp(start).tz_convert(self.tz)
        h, m = (int(x) for x in str(self.shift["start_local"]).split(":"))
        shift0 = local.normalize() + pd.Timedelta(hours=h, minutes=m)
        total = 0.0
        for b in self.shift["breaks"]:
            b0 = shift0 + pd.Timedelta(hours=float(b["at_h"]))
            b1 = b0 + pd.Timedelta(minutes=float(b["minutes"]))
            total += max(0.0, (min(b1, pd.Timestamp(end)) - max(b0, local)).total_seconds() / 60)
        return total

    def _forecasts(self, issued_before: datetime | None) -> dict[str, pd.DataFrame]:
        fc = self.t.get("weather_forecast")
        if fc.empty:
            return {}
        if issued_before is not None:
            fc = fc[fc["issued_at"] <= pd.Timestamp(issued_before)]
        if fc.empty:
            return {}
        latest = fc.sort_values("issued_at").groupby(["site_id", "valid_at", "var"]).tail(1)
        out = {}
        for site, g in latest.groupby("site_id"):
            wide = g.pivot_table(index="valid_at", columns="var", values="value", aggfunc="last").sort_index()
            out[str(site)] = wide
        return out

    def weather_window(
        self, site: str, start: datetime, end: datetime, now: datetime | None = None
    ) -> tuple[Window, pd.DataFrame]:
        """Observed hours before `now`, forecast hours after it (history: `now=None` → all observed)."""
        t0, t1 = pd.Timestamp(start).floor("h"), pd.Timestamp(end)
        obs = self._obs.get(site, pd.DataFrame())
        frames = []
        if not obs.empty:
            cut = t1 if now is None else min(t1, pd.Timestamp(now))
            frames.append(obs.loc[t0:cut, [c for c in WEATHER_VARS if c in obs.columns]])
        if now is not None and t1 > pd.Timestamp(now):
            if self._fc is None:
                self._fc = self._forecasts(now)
            fc = self._fc.get(site)
            if fc is not None:
                frames.append(fc.loc[max(t0, pd.Timestamp(now)) : t1, [c for c in WEATHER_VARS if c in fc.columns]])
        w = pd.concat(frames) if frames else pd.DataFrame(columns=list(WEATHER_VARS))
        if w.empty and not obs.empty:
            w = obs.loc[:t0].tail(1)  # nothing in the window: persist the latest observation
        hs = self.hard_stop
        stop = (
            (w.get("lightning_km", pd.Series(dtype=float)) < hs["lightning_km_lt"])
            | (w.get("gust_ms", pd.Series(dtype=float)) > hs["gust_ms_gt"])
            | (w.get("rain_mm", pd.Series(dtype=float)) > hs["rain_mm_h_gt"])
        )
        win = Window(
            temp_c=float(w["temp_c"].mean()) if "temp_c" in w and len(w) else math.nan,
            rain_mm_h=float(w["rain_mm"].mean()) if "rain_mm" in w and len(w) else 0.0,
            gust_ms=float(w["gust_ms"].mean()) if "gust_ms" in w and len(w) else math.nan,
            visibility_low=float((w["visibility_m"] < self.vis_low_m).mean())
            if "visibility_m" in w and len(w)
            else 0.0,
            stop_weather_hours=float(stop.sum()),
            hours=len(w),
        )
        return win, w

    def ground_at(self, zone_id: str, at: datetime, now: datetime | None = None) -> dict[str, float]:
        """Moisture/FoS for the zone: forecast moisture after `now`, latest observed ground condition otherwise."""
        g = self._ground[self._ground["zone_id"] == zone_id]
        row: dict[str, float] = {}
        if not g.empty:
            day = pd.Timestamp(at).tz_convert(self.tz).date()
            dates = pd.to_datetime(g["date"]).dt.date
            past = g[dates <= day]
            last = (past if not past.empty else g).sort_values("date").iloc[-1]
            row = {"moisture": float(last["moisture"]), "slope_fos": float(last["slope_fos"])}
        if now is not None and pd.Timestamp(at) > pd.Timestamp(now) and not self._gm_fc.empty:
            f = self._gm_fc[(self._gm_fc["zone_id"] == zone_id)]
            f = f[f["valid_at"] <= pd.Timestamp(at)].sort_values("valid_at")
            if not f.empty:
                row["moisture"] = float(f.iloc[-1]["moisture"])
        return row

    def soil_of(self, zone_id: str | None) -> str:
        if zone_id and zone_id in self.zones.index:
            return str(self.zones.loc[zone_id, "soil"])
        return next(iter(self.soils))

    # ------------------------------------------------------------------ row builder
    def row(
        self,
        task: dict[str, Any],
        start: datetime,
        duration_min: float,
        *,
        now: datetime | None,
        health_index: float,
        moisture: float | None,
        operator_prior: float,
        slope_fos: float | None = None,
        machine_id: str | None = None,
    ) -> dict[str, Any]:
        end = pd.Timestamp(start) + pd.Timedelta(minutes=max(duration_min, 1.0))
        site = str(task["site_id"])
        win, _ = self.weather_window(site, start, end, now)
        soil = self.soil_of(task.get("zone_id"))
        ground = self.ground_at(str(task.get("zone_id")), start, now) if task.get("zone_id") else {}
        m = moisture if moisture is not None and not pd.isna(moisture) else ground.get("moisture", math.nan)
        m_field = float(self.soils.get(soil, {}).get("m_field", 0.0))
        mid = machine_id or task.get("assigned_machine_id")
        manifest_id = str(self.machines.loc[mid, "manifest_id"]) if mid in self.machines.index else None
        powertrain = str(self.machines.loc[mid, "powertrain"]) if mid in self.machines.index else "diesel"
        op = task.get("assigned_operator_id")
        exp = float(self.profiles.loc[op, "experience_years"]) if op in self.profiles.index else math.nan
        local = pd.Timestamp(start).tz_convert(self.tz)
        qty = float(task["quantity"])
        return {
            "task_type": str(task["type"]),
            "log_quantity": math.log(max(qty, 1e-6)),
            "depth_m": _num(task.get("depth_m")),
            "haul_km": _num(task.get("haul_distance_m")) / 1000.0,
            "grade_pct": _num(task.get("grade_pct")),
            "machine_class": str(task["machine_class"]),
            "bucket_capacity_m3": self.capacity_m3(str(task["machine_class"]), manifest_id),
            "powertrain": powertrain,
            "health_index": health_index,
            "experience_years": exp,
            "operator_prior": operator_prior,
            "temp_c": win.temp_c,
            "temp_excess_c": max(0.0, win.temp_c - self.heat_c) if not math.isnan(win.temp_c) else 0.0,
            "rain_mm_h": win.rain_mm_h,
            "gust_ms": win.gust_ms,
            "visibility_low": win.visibility_low,
            "soil": soil,
            "moisture": m,
            "moisture_excess": max(0.0, m - m_field) if not math.isnan(m) else math.nan,
            "slope_fos": slope_fos if slope_fos is not None else ground.get("slope_fos", math.nan),
            "start_hour": local.hour + local.minute / MINUTES_PER_HOUR,
            "day_of_week": float(local.dayofweek),
            "break_overlap_min": self.breaks_overlap_min(start, end),
            "stop_weather_hours": win.stop_weather_hours,
            "site_id": site,
        }

    # ------------------------------------------------------------------ training set
    def history(self) -> pd.DataFrame:
        tasks = self.t.get("tasks")
        done = tasks[(tasks["status"] == "completed") & tasks["duration_min"].notna() & (tasks["quantity"] > 0)]
        done = done.sort_values("actual_start")
        ctx = self._ctx.set_index("task_id") if not self._ctx.empty else pd.DataFrame()
        y = np.log(done["duration_min"] / done["quantity"])
        type_med = y.groupby(done["type"]).transform("median")
        dev = (y - type_med).to_numpy()
        k = float(self.mcfg["operator_prior"]["shrinkage_k"])
        sums: dict[str, float] = {}
        counts: dict[str, int] = {}
        rows = []
        for i, t in enumerate(done.to_dict("records")):
            op = str(t.get("assigned_operator_id"))
            prior = sums.get(op, 0.0) / (counts.get(op, 0) + k)  # only earlier tasks → no leakage
            c = ctx.loc[t["id"]] if not ctx.empty and t["id"] in ctx.index else None
            planned = (t["planned_end"] - t["planned_start"]).total_seconds() / 60
            r = self.row(
                t,
                t["actual_start"].to_pydatetime(),
                planned,
                now=None,
                health_index=float(c["health_index"]) if c is not None else math.nan,
                moisture=float(c["ground_moisture"]) if c is not None else None,
                operator_prior=prior,
                machine_id=t.get("assigned_machine_id"),
            )
            r.update(
                {
                    "task_id": t["id"],
                    "start": t["actual_start"],
                    "quantity": float(t["quantity"]),
                    "duration_min": float(t["duration_min"]),
                }
            )
            rows.append(r)
            sums[op] = sums.get(op, 0.0) + float(dev[i])
            counts[op] = counts.get(op, 0) + 1
        self._op_prior = {op: sums[op] / (counts[op] + k) for op in sums}
        return pd.DataFrame(rows)

    # ------------------------------------------------------------------ serving
    def operator_prior(self, operator_id: str | None) -> float:
        if not hasattr(self, "_op_prior"):
            tasks = self.t.get("tasks")
            done = tasks[(tasks["status"] == "completed") & tasks["duration_min"].notna() & (tasks["quantity"] > 0)]
            y = np.log(done["duration_min"] / done["quantity"])
            dev = y - y.groupby(done["type"]).transform("median")
            k = float(self.mcfg["operator_prior"]["shrinkage_k"])
            g = dev.groupby(done["assigned_operator_id"])
            self._op_prior = (g.sum() / (g.count() + k)).to_dict()
        return float(self._op_prior.get(operator_id, 0.0)) if operator_id else 0.0

    def machine_health(self, machine_id: str | None) -> float:
        """Latest observed health index for the machine (from the most recent task start context)."""
        if not machine_id or self._ctx.empty:
            return math.nan
        tasks = self.t.get("tasks")[["id", "assigned_machine_id", "planned_start"]]
        joined = self._ctx.merge(tasks, left_on="task_id", right_on="id")
        joined = joined[joined["assigned_machine_id"] == machine_id]
        if joined.empty:
            return math.nan
        return float(joined.sort_values("planned_start").iloc[-1]["health_index"])

    def for_task(
        self,
        task: dict[str, Any],
        start: datetime,
        duration_min: float,
        now: datetime,
        overrides: dict[str, Any] | None = None,
        machine_id: str | None = None,
    ) -> dict[str, Any]:
        o = overrides or {}
        mid = machine_id or task.get("assigned_machine_id")
        r = self.row(
            task,
            start,
            duration_min,
            now=now,
            health_index=float(o.get("health_index", self.machine_health(mid))),
            moisture=o.get("moisture"),
            operator_prior=self.operator_prior(task.get("assigned_operator_id")),
            machine_id=mid,
        )
        r.update({k: v for k, v in o.items() if k in r})
        return r


def _num(v: Any) -> float:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return 0.0
    return 0.0 if math.isnan(f) else f


def planned_minutes(task: dict[str, Any]) -> float:
    ps, pe = task.get("planned_start"), task.get("planned_end")
    if ps is None or pe is None or pd.isna(ps) or pd.isna(pe):
        return MINUTES_PER_HOUR
    return float((pd.Timestamp(pe) - pd.Timestamp(ps)) / timedelta(minutes=1))
