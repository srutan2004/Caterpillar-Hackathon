"""`sensor_baseline` (§11): per (manifest, sensor) Huber regression of the value on its duty covariates.

residual = value − f(covariates); the normalised series used for trends/forecasts is residual + f(reference
covariates), i.e. "what the sensor would read under typical conditions" — so ambient swings and load changes
do not look like degradation.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from sklearn.linear_model import HuberRegressor

from terrapilot.core.config import ConfigBundle
from terrapilot.core.settings import get_settings
from terrapilot.core.timeutil import utcnow
from terrapilot.ml.data import Tables


def _cfg(cfg: ConfigBundle) -> dict[str, Any]:
    return dict(cfg.models["models"]["sensor_baseline"])


def artefact_path(cfg: ConfigBundle, data_dir: Path | None = None) -> Path:
    return (data_dir or get_settings().data_dir) / str(_cfg(cfg)["artefact_dir"]) / "baselines.json"


def normalised_sensors(cfg: ConfigBundle, manifest_id: str) -> dict[str, list[str]]:
    out = {}
    for ms in cfg.manifests_raw[manifest_id].get("maintenance_sensors", []):
        key = str(ms["limits_ref"]).split("#", 1)[1]
        by = ((cfg.sensor_limits.get(key) or {}).get("normalise") or {}).get("by")
        if by:
            out[str(ms["id"])] = list(by)
    return out


def train(cfg: ConfigBundle, tables: Tables, out: Path | None = None) -> dict[str, Any]:
    bc = _cfg(cfg)
    signals = bc["covariate_signals"]
    sensors = tables.get("sensor_1min")
    machines = tables.get("machines").set_index("id")
    wx = tables.get("weather_hourly")[["ts", "site_id", "temp_c", "pm10"]].rename(
        columns={"temp_c": "site.temp_c", "pm10": "site.pm10"}
    )
    result: dict[str, dict[str, Any]] = {}
    ratios = []
    for manifest_id in cfg.manifests_raw:
        targets = normalised_sensors(cfg, manifest_id)
        mids = machines[machines["manifest_id"] == manifest_id].index.tolist()
        if not targets or not mids:
            continue
        df = sensors[sensors["machine_id"].isin(mids)]
        wide = df.pivot_table(
            index=["ts", "machine_id"], columns="sensor_id", values="value", aggfunc="last"
        ).reset_index()
        wide["site_id"] = wide["machine_id"].map(machines["site_id"])
        wide = pd.merge_asof(wide.sort_values("ts"), wx.sort_values("ts"), on="ts", by="site_id", direction="backward")
        for sensor, by in targets.items():
            cols = [signals[c] for c in by]
            if sensor not in wide or any(c not in wide for c in cols):
                continue
            d = wide[[sensor, *cols]].dropna()
            if len(d) < 50:
                continue
            d = d.sample(min(len(d), int(bc["max_rows_per_sensor"])), random_state=0)
            X, y = d[cols].to_numpy(dtype=float), d[sensor].to_numpy(dtype=float)
            mu, sd = X.mean(axis=0), X.std(axis=0)
            sd[sd == 0] = 1.0
            model = HuberRegressor(max_iter=500).fit((X - mu) / sd, y)
            resid = y - model.predict((X - mu) / sd)
            ratio = float(np.std(resid) / max(np.std(y), 1e-9))
            ratios.append(ratio)
            result.setdefault(manifest_id, {})[sensor] = {
                "covariates": cols,
                "mean": mu.tolist(),
                "scale": sd.tolist(),
                "coef": model.coef_.tolist(),
                "intercept": float(model.intercept_),
                "reference": np.median(X, axis=0).tolist(),
                "rmse": float(np.sqrt(np.mean(resid**2))),
                "rmse_ratio": ratio,
                "rows": len(d),
            }
    path = out / "baselines.json" if out else artefact_path(cfg)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"trained_at": utcnow().isoformat(), "models": result}, indent=2), encoding="utf-8")
    load_baselines.cache_clear()
    worst = max(ratios, default=0.0)
    return {
        "rows": {"models": len(ratios)},
        "metrics": {"median_rmse_ratio": float(np.median(ratios)) if ratios else float("nan"), "max_rmse_ratio": worst},
        "passed": bool(ratios) and worst <= float(bc["targets"]["residual_rmse_ratio_max"]),
        "artefact_dir": str(path.parent),
    }


@lru_cache(maxsize=2)
def load_baselines(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    return dict(json.loads(path.read_text(encoding="utf-8")).get("models", {}))


def normalise(
    cfg: ConfigBundle,
    manifest_id: str,
    sensor: str,
    t: np.ndarray,
    v: np.ndarray,
    covariates: dict[str, tuple[np.ndarray, np.ndarray]],
) -> np.ndarray:
    """Values under reference conditions; unchanged when no baseline exists or a covariate is missing."""
    b = load_baselines(artefact_path(cfg)).get(manifest_id, {}).get(sensor)
    if not b:
        return v
    cols = []
    for sig in b["covariates"]:
        series = covariates.get(sig)
        if series is None or not len(series[0]):
            return v
        idx = np.clip(np.searchsorted(series[0], t, side="right") - 1, 0, len(series[0]) - 1)
        cols.append(series[1][idx])
    X = np.vstack(cols).T
    mu, sd, coef = np.array(b["mean"]), np.array(b["scale"]), np.array(b["coef"])
    pred = (X - mu) / sd @ coef + b["intercept"]
    ref = (np.array(b["reference"]) - mu) / sd @ coef + b["intercept"]
    out: np.ndarray = v - pred + ref
    return out
