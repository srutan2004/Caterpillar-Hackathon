"""`tp gen`: run every generator in dependency order and write parquet aligned to the DB schema (§7.8)."""

from __future__ import annotations

import hashlib
import json
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

import pandas as pd
from rich.console import Console
from sqlalchemy import Boolean, Date, DateTime, Float, Integer

from terrapilot.core.config import get_config, load_config
from terrapilot.core.settings import get_settings
from terrapilot.core.timeutil import utcnow
from terrapilot.datagen.context import GenContext
from terrapilot.datagen.fleet import finalize_machines, generate_fleet, plan_fleet
from terrapilot.datagen.ground import generate_ground, generate_moisture_forecast
from terrapilot.datagen.history import simulate_history
from terrapilot.datagen.knowledge import generate_knowledge
from terrapilot.datagen.notes import generate_notes
from terrapilot.datagen.people import generate_people
from terrapilot.datagen.safety import generate_operator_state, generate_safety
from terrapilot.datagen.sensors import (
    generate_battery_log,
    generate_maintenance_tables,
    generate_sensors,
    generate_telemetry,
)
from terrapilot.datagen.training import generate_training
from terrapilot.datagen.weather import generate_forecasts, generate_weather
from terrapilot.datagen.world import generate_world
from terrapilot.db.schema import metadata

STEPS: list[tuple[str, Callable[[GenContext], None]]] = [
    ("world", generate_world),
    ("weather", generate_weather),
    ("ground", generate_ground),
    ("forecasts", generate_forecasts),
    ("moisture forecast", generate_moisture_forecast),
    ("fleet plan", plan_fleet),
    ("people", generate_people),
    ("fleet", generate_fleet),
    ("history (execution, degradation, maintenance)", simulate_history),
    ("machines", finalize_machines),
    ("safety", generate_safety),
    ("operator state", generate_operator_state),
    ("maintenance sensors", generate_sensors),
    ("telemetry", generate_telemetry),
    ("battery", generate_battery_log),
    ("maintenance tables", generate_maintenance_tables),
    ("training", generate_training),
    ("cab notes", generate_notes),
    ("knowledge", generate_knowledge),
]


@dataclass
class GenerationResult:
    out_dir: Path
    row_counts: dict[str, int]
    anchor: date


def conform(name: str, df: pd.DataFrame) -> pd.DataFrame:
    """Align a generated frame to its DB table: column order, dtypes, missing nullable columns."""
    table = metadata.tables[name]
    out = pd.DataFrame(index=df.index)
    for col in table.columns:
        if col.name == "created_at" and col.name not in df:
            continue
        series = df[col.name] if col.name in df else pd.Series([None] * len(df), index=df.index, dtype=object)
        if isinstance(col.type, DateTime):
            series = pd.to_datetime(series, utc=True)
        elif isinstance(col.type, Date):
            series = pd.to_datetime(series).dt.date if len(series) else series
        elif isinstance(col.type, Float):
            series = pd.to_numeric(series, errors="coerce").astype(float)
        elif isinstance(col.type, Integer) and not col.primary_key:
            series = pd.to_numeric(series, errors="coerce").astype("Int64")
        elif isinstance(col.type, Boolean):
            series = series.astype("boolean")
        out[col.name] = series
    return out.reset_index(drop=True)


def config_hash(root: Path) -> str:
    h = hashlib.sha256()
    for path in sorted((root / "datagen").glob("*.yaml")) + sorted((root / "manifests").glob("*.yaml")):
        h.update(path.read_bytes())
    return h.hexdigest()[:16]


def run_generation(
    scale: str = "full",
    seed: int | None = None,
    out_dir: Path | None = None,
    anchor: str | None = None,
    datagen_dir: Path | None = None,
    console: Console | None = None,
) -> GenerationResult:
    console = console or Console()
    cfg = get_config() if datagen_dir is None else load_config(datagen_dir.parent)
    ctx = GenContext.create(cfg, scale, seed, anchor)
    out = out_dir or get_settings().data_dir / "generated"
    out.mkdir(parents=True, exist_ok=True)
    console.print(
        f"generating scale=[bold]{scale}[/bold] seed={ctx.seed} anchor={ctx.anchor} ({ctx.history_days} days) → {out}"
    )
    for label, fn in STEPS:
        t0 = time.perf_counter()
        fn(ctx)
        console.print(f"  • {label:<48} {time.perf_counter() - t0:6.1f}s")

    counts: dict[str, int] = {}
    unknown = sorted(set(ctx.tables) - set(metadata.tables))
    if unknown:
        raise RuntimeError(f"generated tables with no schema: {unknown}")
    for old in out.glob("*.parquet"):
        old.unlink()
    for name, df in sorted(ctx.tables.items()):
        conformed = conform(name, df)
        conformed.to_parquet(out / f"{name}.parquet", index=False)
        counts[name] = len(conformed)
    knowledge_dir = out / "knowledge"
    knowledge_dir.mkdir(exist_ok=True)
    fc = ctx.tables["fault_codes"].copy()
    for col in ("classes", "probable_causes", "checks", "part_numbers"):
        fc[col] = fc[col].map("|".join)
    fc.to_csv(knowledge_dir / "fault_codes.csv", index=False)

    manifest: dict[str, Any] = {
        "scale": scale,
        "seed": ctx.seed,
        "anchor": ctx.anchor.isoformat(),
        "now": ctx.now.isoformat(),
        "history_days": ctx.history_days,
        "generated_at": utcnow().isoformat(),
        "config_hash": config_hash(cfg.root),
        "row_counts": counts,
    }
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return GenerationResult(out_dir=out, row_counts=counts, anchor=ctx.anchor)
