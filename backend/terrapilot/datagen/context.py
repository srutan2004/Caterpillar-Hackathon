"""Generation context: merged config (scale presets), seeded RNG streams, time anchor and table sink."""

from __future__ import annotations

import copy
import hashlib
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

from terrapilot.core.config import ConfigBundle
from terrapilot.core.timeutil import anchor_date, local_midnight, parse_hhmm


def deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    out = copy.deepcopy(base)
    for k, v in override.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = deep_merge(out[k], v)
        else:
            out[k] = copy.deepcopy(v)
    return out


def apply_scale(world: dict[str, Any], scale: str) -> dict[str, Any]:
    scales = world.get("scales", {})
    if scale not in scales:
        raise ValueError(f"unknown scale '{scale}' (known: {sorted(scales)})")
    over = scales[scale]
    merged = deep_merge(
        world,
        {
            k: v
            for k, v in over.items()
            if k not in ("fleet_counts", "fleet_sites", "operators", "instructors", "technicians")
        },
    )
    if "operators" in over:
        merged["operators"]["count"] = over["operators"]
    if "instructors" in over:
        merged["instructors"]["count"] = over["instructors"]
    if "technicians" in over:
        merged["technicians"]["count"] = over["technicians"]
    counts, sites = over.get("fleet_counts"), over.get("fleet_sites", {})
    if counts:
        fleet = []
        for entry in merged["fleet"]:
            mid = entry["manifest"]
            if mid not in counts or counts[mid] == 0:
                continue
            n = counts[mid]
            site_map = sites.get(mid) or _scale_sites(entry["sites"], n)
            fleet.append({"manifest": mid, "count": n, "sites": site_map})
        merged["fleet"] = fleet
    return merged


def _scale_sites(sites: dict[str, int], n: int) -> dict[str, int]:
    """Keep the first sites in declaration order until n machines are placed."""
    out: dict[str, int] = {}
    left = n
    for site, count in sites.items():
        take = min(count, left)
        if take:
            out[site] = take
        left -= take
    if left:
        first = next(iter(sites))
        out[first] = out.get(first, 0) + left
    return out


@dataclass
class GenContext:
    cfg: ConfigBundle
    scale: str
    seed: int
    anchor: date
    world: dict[str, Any]
    dg: dict[str, Any]
    tables: dict[str, pd.DataFrame] = field(default_factory=dict)
    state: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def create(cls, cfg: ConfigBundle, scale: str, seed: int | None, anchor: str | date | None) -> GenContext:
        dg = copy.deepcopy(cfg.datagen)
        world = apply_scale(dg["world"], scale)
        dg["world"] = world
        seed = int(seed if seed is not None else world["seed"])
        return cls(cfg=cfg, scale=scale, seed=seed, anchor=anchor_date(world["timezone"], anchor), world=world, dg=dg)

    # ---------------------------------------------------------------- randomness
    def rng(self, stream: str) -> np.random.Generator:
        """Independent, reproducible stream per generator module (adding a module never shifts others)."""
        digest = int(hashlib.sha256(stream.encode()).hexdigest()[:8], 16)
        return np.random.default_rng([self.seed, digest])

    # ---------------------------------------------------------------- time
    @property
    def tz(self) -> ZoneInfo:
        return ZoneInfo(self.world["timezone"])

    @property
    def history_days(self) -> int:
        return int(self.world["history_days"])

    @property
    def future_days(self) -> int:
        return int(self.world["future_days"])

    @property
    def first_day(self) -> date:
        return self.anchor - timedelta(days=self.history_days)

    def local_dt(self, d: date, hhmm: str | timedelta) -> datetime:
        offset = parse_hhmm(hhmm) if isinstance(hhmm, str) else hhmm
        return local_midnight(d, self.world["timezone"]) + offset

    @property
    def shift_start_offset(self) -> timedelta:
        return parse_hhmm(self.world["shift"]["start_local"])

    @property
    def shift_length(self) -> timedelta:
        return timedelta(hours=float(self.world["shift"]["length_h"]))

    def shift_start(self, d: date) -> datetime:
        return self.local_dt(d, self.shift_start_offset)

    def shift_end(self, d: date) -> datetime:
        return self.shift_start(d) + self.shift_length

    @property
    def now(self) -> datetime:
        """Generated history ends just before today's shift starts (tasks today are planned, not executed)."""
        return self.shift_start(self.anchor) - timedelta(minutes=30)

    @property
    def weather_start(self) -> datetime:
        return local_midnight(self.first_day - timedelta(days=2), self.world["timezone"])

    @property
    def weather_end(self) -> datetime:
        return local_midnight(self.anchor + timedelta(days=self.future_days + 1), self.world["timezone"])

    def history_dates(self) -> list[date]:
        return [self.first_day + timedelta(days=i) for i in range(self.history_days)]

    def is_workday(self, d: date) -> bool:
        return d.weekday() in self.world["shift"]["workdays"]

    def hours_index(self) -> pd.DatetimeIndex:
        start = pd.Timestamp(self.weather_start).tz_convert("UTC")
        end = pd.Timestamp(self.weather_end).tz_convert("UTC")
        return pd.date_range(start, end, freq="h", inclusive="left")

    # ---------------------------------------------------------------- output
    def emit(self, name: str, df: pd.DataFrame) -> None:
        if name in self.tables:
            self.tables[name] = pd.concat([self.tables[name], df], ignore_index=True)
        else:
            self.tables[name] = df.reset_index(drop=True)

    def site(self, site_id: str) -> dict[str, Any]:
        return next(s for s in self.world["sites"] if s["id"] == site_id)
