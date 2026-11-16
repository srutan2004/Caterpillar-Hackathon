"""World context for the live loop: machine, site geofences, task and current weather.

Read from Postgres when it is reachable, else from a `tp gen` output directory, so the edge runs offline too.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pandas as pd

from terrapilot.core.settings import get_settings


@dataclass
class Geofence:
    id: str
    kind: str
    points: list[tuple[float, float, float]]
    clearance_m: float
    depth_uncertainty_m: float = 0.0


@dataclass
class WorldContext:
    machine: dict[str, Any]
    task: dict[str, Any] | None
    geofences: list[Geofence]
    weather: dict[str, float]
    operator_id: str
    zone_moisture: float = 0.25
    zone_soil: str = "clay"
    extras: dict[str, Any] = field(default_factory=dict)


def _geofences(rows: pd.DataFrame) -> list[Geofence]:
    out: list[Geofence] = []
    for r in rows.itertuples():
        geom = json.loads(r.geom3d) if isinstance(r.geom3d, str) else (r.geom3d or {})
        pts = [tuple(float(v) for v in p) for p in geom.get("polyline", [])]
        if not pts:
            continue
        out.append(Geofence(r.id, r.kind, pts, float(r.clearance_m or 0.0), float(r.depth_uncertainty_m or 0.0)))  # type: ignore[arg-type]
    return out


def _read_sql(sql: str, params: dict[str, Any]) -> pd.DataFrame | None:
    try:
        from sqlalchemy import text

        from terrapilot.db.engine import get_engine

        with get_engine().connect() as conn:
            return pd.read_sql(text(sql), conn, params=params)
    except Exception:
        return None


def load_context(
    machine_id: str, task_id: str | None, operator_id: str | None, data_dir: Path | None = None
) -> WorldContext:
    machines = _read_sql("SELECT * FROM machines WHERE id = :m", {"m": machine_id})
    source = "db"
    if machines is None or machines.empty:
        source = "parquet"
        d = data_dir or get_settings().data_dir / "generated"
        all_m = pd.read_parquet(d / "machines.parquet")
        machines = all_m[all_m["id"] == machine_id]
        if machines.empty:
            raise KeyError(f"unknown machine '{machine_id}'")
    machine = machines.iloc[0].to_dict()
    site = machine["site_id"]
    if source == "db":
        fences = _read_sql("SELECT * FROM geofences WHERE site_id = :s", {"s": site})
        tasks = _read_sql("SELECT * FROM tasks WHERE id = :t", {"t": task_id or ""})
        wx = _read_sql("SELECT * FROM weather_hourly WHERE site_id = :s ORDER BY ts DESC LIMIT 1", {"s": site})
        zones = _read_sql(
            "SELECT z.id, z.soil, g.moisture FROM zones z LEFT JOIN LATERAL (SELECT moisture FROM ground_conditions gc "
            "WHERE gc.zone_id = z.id ORDER BY date DESC LIMIT 1) g ON TRUE WHERE z.site_id = :s",
            {"s": site},
        )
    else:
        d = data_dir or get_settings().data_dir / "generated"
        fences = pd.read_parquet(d / "geofences.parquet").query("site_id == @site")
        t = pd.read_parquet(d / "tasks.parquet")
        tasks = t[t["id"] == (task_id or "")]
        w = pd.read_parquet(d / "weather_hourly.parquet")
        wx = w[w["site_id"] == site].sort_values("ts").tail(1)
        z = pd.read_parquet(d / "zones.parquet").query("site_id == @site")
        gc = pd.read_parquet(d / "ground_conditions.parquet").sort_values("date").groupby("zone_id").tail(1)
        zones = z.merge(gc[["zone_id", "moisture"]], left_on="id", right_on="zone_id", how="left")
    task = tasks.iloc[0].to_dict() if tasks is not None and not tasks.empty else None
    weather = {}
    if wx is not None and not wx.empty:
        weather = {
            k: float(v) for k, v in wx.iloc[0].items() if k not in ("ts", "site_id") and v is not None and pd.notna(v)
        }
    soil, moisture = "clay", 0.25
    if zones is not None and not zones.empty:
        zrow = zones[zones["id"] == (task or {}).get("zone_id")] if task else zones.head(1)
        zrow = zrow if not zrow.empty else zones.head(1)
        soil = str(zrow.iloc[0]["soil"])
        moisture = float(zrow.iloc[0]["moisture"]) if pd.notna(zrow.iloc[0]["moisture"]) else moisture
    op = operator_id or (task or {}).get("assigned_operator_id") or "unknown"
    return WorldContext(
        machine=machine,
        task=task,
        geofences=_geofences(fences) if fences is not None else [],
        weather=weather,
        operator_id=str(op),
        zone_moisture=moisture,
        zone_soil=soil,
    )
