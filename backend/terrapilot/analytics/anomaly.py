"""`cycle_anomaly` (§10.5 layers 2 + 3): per-operator robust z-scores and an Isolation Forest per machine class.

Per-cycle features are normalised within (machine class, task type) so that a long trench cycle is not
"unusual" just because trenching is slow. Scored cycles land in `<artefact_dir>/anomalies.parquet`, which the
anomaly board and scorecards read.
"""

from __future__ import annotations

import json
import pickle
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from sklearn.ensemble import IsolationForest

from terrapilot.core.config import ConfigBundle
from terrapilot.core.settings import get_settings
from terrapilot.core.timeutil import utcnow
from terrapilot.ml.data import Tables

FEATURES = ["log_cycle_rel", "payload_rel", "fill_factor", "energy_rel"]
MAD_TO_SD = 1.4826


def _cfg(cfg: ConfigBundle) -> dict[str, Any]:
    return dict(cfg.models["models"]["cycle_anomaly"])


def artefact_dir(cfg: ConfigBundle) -> Path:
    return get_settings().data_dir / str(_cfg(cfg).get("artefact_dir", "models/cycle_anomaly"))


def cycle_features(cycles: pd.DataFrame, tasks: pd.DataFrame, machines: pd.DataFrame) -> pd.DataFrame:
    df = cycles.merge(tasks[["id", "type"]], left_on="task_id", right_on="id", how="left").drop(columns=["id"])
    df = df.merge(machines[["id", "machine_class"]], left_on="machine_id", right_on="id", how="left").drop(
        columns=["id"]
    )
    df["energy"] = df["fuel_l"].fillna(df["kwh"])
    grp = df.groupby(["machine_class", "type"])
    log_c = np.log(df["cycle_s"].clip(lower=1e-3))
    df["log_cycle_rel"] = log_c - log_c.groupby([df["machine_class"], df["type"]]).transform("median")
    df["payload_rel"] = df["payload_t"] / grp["payload_t"].transform("median")
    df["energy_rel"] = df["energy"] / grp["energy"].transform("median")
    return df


def robust_z(df: pd.DataFrame, window: int) -> pd.Series:
    """Cycle time vs the operator's own rolling median/MAD for the task type (prior cycles only)."""
    df = df.sort_values("ts")
    keys = [df["operator_id"], df["type"]]
    x = df["log_cycle_rel"]
    med = x.groupby(keys).transform(lambda s: s.shift(1).rolling(window, min_periods=20).median())
    mad = (x - med).abs().groupby(keys).transform(lambda s: s.shift(1).rolling(window, min_periods=20).median())
    return ((x - med) / (MAD_TO_SD * mad.replace(0, np.nan))).reindex(df.index)


def train(cfg: ConfigBundle, tables: Tables, out_dir: Path | None = None) -> dict[str, Any]:
    beh = cfg.behavior_rules.model_dump()
    iso_cfg = beh["ml"]["isolation_forest"]
    z_thr = float(beh["statistical"]["robust_z_threshold"])
    window = int(beh["statistical"]["baseline_window_cycles"])
    mc = _cfg(cfg)
    df = cycle_features(tables.get("cycles"), tables.get("tasks"), tables.get("machines"))
    df = df.dropna(subset=["log_cycle_rel", "payload_rel", "fill_factor"]).copy()
    df["energy_rel"] = df["energy_rel"].fillna(1.0)
    df["robust_z"] = robust_z(df, window)
    df["iforest_score"] = np.nan
    df["iforest_flag"] = False
    models = {}
    for cls, g in df.groupby("machine_class"):
        m = IsolationForest(
            n_estimators=int(iso_cfg["n_estimators"]),
            contamination=float(iso_cfg["contamination"]),
            random_state=int(mc.get("seed", 0)),
        )
        m.fit(g[FEATURES].to_numpy())
        df.loc[g.index, "iforest_score"] = -m.score_samples(g[FEATURES].to_numpy())
        df.loc[g.index, "iforest_flag"] = m.predict(g[FEATURES].to_numpy()) == -1
        models[str(cls)] = m
    df["z_flag"] = df["robust_z"].abs() > z_thr
    flagged = df[df["iforest_flag"].astype("boolean").fillna(False).astype(bool) | df["z_flag"]]
    # Evaluation vs truth: an unusual cycle should coincide with a labelled behaviour episode or an active
    # fault mode on that machine (the generator's causes of abnormal cycles).
    k = int(mc.get("eval_top_k", 500))
    top = df.nlargest(k, "iforest_score")
    hit = _truth_overlap(top, tables)
    base_rate = _truth_overlap(df.sample(min(k, len(df)), random_state=0), tables)
    precision = float(hit.mean()) if len(hit) else float("nan")
    metrics = {
        "cycles": float(len(df)),
        "flagged": float(len(flagged)),
        "precision_at_k": precision,
        "base_rate_at_k": float(base_rate.mean()) if len(base_rate) else float("nan"),
        "lift": precision / max(float(base_rate.mean()), 1e-9) if len(base_rate) else float("nan"),
    }
    out = out_dir or artefact_dir(cfg)
    out.mkdir(parents=True, exist_ok=True)
    (out / "models.pkl").write_bytes(pickle.dumps(models))
    cols = [
        "ts",
        "machine_id",
        "operator_id",
        "task_id",
        "machine_class",
        "type",
        "cycle_s",
        *FEATURES,
        "robust_z",
        "iforest_score",
        "z_flag",
        "iforest_flag",
    ]
    flagged[cols].to_parquet(out / "anomalies.parquet", index=False)
    target = float(mc.get("targets", {}).get("precision_at_k_min", 0.0))
    meta = {"metrics": metrics, "trained_at": utcnow().isoformat(), "k": k, "features": FEATURES}
    (out / "meta.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
    return {"rows": {"cycles": len(df)}, "metrics": metrics, "passed": precision >= target, "artefact_dir": str(out)}


def _ns(s: pd.Series) -> np.ndarray:
    out: np.ndarray = pd.to_datetime(s, utc=True).dt.tz_convert(None).to_numpy(dtype="datetime64[ns]")
    return out


def _truth_overlap(cyc: pd.DataFrame, tables: Tables) -> np.ndarray:
    labels = tables.get("truth_behavior_labels")
    faults = tables.get("truth_fault_modes")
    t1s = _ns(cyc["ts"])
    t0s = t1s - (cyc["cycle_s"].to_numpy() * 1e9).astype("timedelta64[ns]")
    lab = {m: (_ns(g["start_ts"]), _ns(g["end_ts"])) for m, g in labels.groupby("machine_id")}
    flt = {
        m: (_ns(g["onset"]), _ns(g["resolved_at"].fillna(g["failure_time"]))) for m, g in faults.groupby("machine_id")
    }
    out = np.zeros(len(cyc), dtype=bool)
    for i, (m, t0, t1) in enumerate(zip(cyc["machine_id"].to_numpy(), t0s, t1s, strict=True)):
        for spans in (lab.get(m), flt.get(m)):
            if spans is not None and ((spans[0] <= t1) & (spans[1] >= t0)).any():
                out[i] = True
                break
    return out


def load_anomalies(cfg: ConfigBundle) -> pd.DataFrame:
    path = artefact_dir(cfg) / "anomalies.parquet"
    return pd.read_parquet(path) if path.is_file() else pd.DataFrame()
