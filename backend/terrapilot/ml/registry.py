"""Trainable models (§11). `tp train <name>` / `tp train --all` dispatch through this registry."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

from terrapilot.core.config import ConfigBundle
from terrapilot.ml.data import Tables


def _task_duration(cfg: ConfigBundle, tables: Tables, out: Path | None) -> dict[str, Any]:
    from terrapilot.ml.task_duration import train

    return train(cfg, tables, out).as_dict()


def _cycle_anomaly(cfg: ConfigBundle, tables: Tables, out: Path | None) -> dict[str, Any]:
    from terrapilot.analytics.anomaly import train

    return train(cfg, tables, out)


def _sensor_baseline(cfg: ConfigBundle, tables: Tables, out: Path | None) -> dict[str, Any]:
    from terrapilot.maintenance.baselines import train

    return train(cfg, tables, out)


TRAINERS: dict[str, Callable[[ConfigBundle, Tables, Path | None], dict[str, Any]]] = {
    "task_duration": _task_duration,
    "cycle_anomaly": _cycle_anomaly,
    "sensor_baseline": _sensor_baseline,
}


def trainable(cfg: ConfigBundle) -> list[str]:
    return [n for n in cfg.models["models"] if n in TRAINERS]
