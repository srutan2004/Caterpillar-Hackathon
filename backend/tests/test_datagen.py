from __future__ import annotations

import hashlib
import json
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd
from rich.console import Console

from terrapilot.core.config import ConfigBundle
from terrapilot.datagen.oracle import WorldState, simulate_task
from terrapilot.datagen.pipeline import run_generation
from terrapilot.datagen.validate import run_validation
from terrapilot.db.schema import metadata

from .conftest import ANCHOR


def _digest(path: Path) -> str:
    df = pd.read_parquet(path)
    return hashlib.sha256(pd.util.hash_pandas_object(df.astype(str), index=False).values.tobytes()).hexdigest()


def test_every_table_matches_schema(tiny_data: Path) -> None:
    for p in tiny_data.glob("*.parquet"):
        table = metadata.tables[p.stem]
        cols = list(pd.read_parquet(p).columns)
        assert cols == [c.name for c in table.columns if c.name in cols], p.stem


def test_generation_is_deterministic(tiny_data: Path, tmp_path: Path) -> None:
    run_generation(scale="tiny", seed=42, out_dir=tmp_path, anchor=ANCHOR, console=Console(quiet=True))
    for name in ("tasks", "cycles", "weather_hourly", "sensor_1min", "truth_fault_modes", "users"):
        assert _digest(tiny_data / f"{name}.parquet") == _digest(tmp_path / f"{name}.parquet"), name


def test_history_is_anchored_to_run_date(tiny_data: Path) -> None:
    manifest = json.loads((tiny_data / "manifest.json").read_text())
    now = pd.Timestamp(manifest["now"])
    wx = pd.read_parquet(tiny_data / "weather_hourly.parquet")
    assert wx["ts"].max() < now and (now - wx["ts"].max()) < pd.Timedelta(hours=2)
    cyc = pd.read_parquet(tiny_data / "cycles.parquet")
    assert cyc["ts"].max() < now


def test_truth_is_separate(tiny_data: Path) -> None:
    be = pd.read_parquet(tiny_data / "behavior_events.parquet")
    labels = pd.read_parquet(tiny_data / "truth_behavior_labels.parquet")
    assert len(labels) >= len(be[be["detector"] == "rule"]) * 0.8
    assert set(labels["detected_event_id"].dropna()) <= set(be["id"])


def test_learnability_gate_passes_or_skips(tiny_data: Path) -> None:
    report = run_validation(tiny_data, Console(quiet=True))
    failed = [c for c in report.checks if not c.passed and not c.skipped]
    integrity = [c for c in report.checks if not c.name.startswith(("learnable", "effects"))]
    assert all(c.passed for c in integrity), [c.detail for c in integrity if not c.passed]
    # tiny scale has few events; the full gate runs in CI on `small` — but nothing may fail with a wrong sign
    assert not [c for c in failed if "wrong sign" in c.detail]


def test_oracle_reuses_causal_model(tiny_data: Path, cfg: ConfigBundle) -> None:
    world = WorldState(tiny_data, cfg)
    tz = ZoneInfo(cfg.datagen["world"]["timezone"])
    y, m, d = (int(x) for x in ANCHOR.split("-"))
    a = simulate_task("T-2031", datetime(y, m, d, 7, 30, tzinfo=tz), world, seed=3)
    b = simulate_task("T-2031", datetime(y, m, d, 7, 30, tzinfo=tz), world, seed=3)
    assert a == b and a.completed and a.duration_min > 30
    electric = simulate_task("T-2045", datetime(y, m, d, 7, 15, tzinfo=tz), world, seed=1, soc=0.38)
    full = simulate_task("T-2045", datetime(y, m, d, 7, 15, tzinfo=tz), world, seed=1, soc=0.95)
    assert electric.charge_stop_min > 0 and full.charge_stop_min == 0
