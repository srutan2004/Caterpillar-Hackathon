"""`task_duration` (§10.6): LightGBM quantile regression on log(minutes per unit) + CQR + TreeSHAP factors.

Train with `tp train task_duration`. Artefacts (three boosters + meta.json) live under
`<data_dir>/<artefact_dir>` and are served in-process by `TaskDurationModel`.
"""

from __future__ import annotations

import json
import math
from dataclasses import asdict, dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any

import lightgbm as lgb
import numpy as np
import pandas as pd

from terrapilot.core.config import ConfigBundle
from terrapilot.core.refs import load_ref_cached
from terrapilot.core.settings import get_settings
from terrapilot.core.timeutil import utcnow
from terrapilot.ml.calibration import cqr_offset, mape, picp, pinball
from terrapilot.ml.data import Tables
from terrapilot.ml.explain import Factor, top_factors
from terrapilot.ml.features import TaskFeatureBuilder, model_cfg

SECONDS_PER_MINUTE = 60.0
SECONDS_PER_HOUR = 3600.0


@dataclass
class Estimate:
    p10: float
    p50: float
    p90: float
    factors: list[Factor] = field(default_factory=list)
    baseline_min: float | None = None
    contrib: np.ndarray | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "p10_min": round(self.p10, 1),
            "p50_min": round(self.p50, 1),
            "p90_min": round(self.p90, 1),
            "factors": [f.as_dict() for f in self.factors],
            "baseline_min": None if self.baseline_min is None else round(self.baseline_min, 1),
        }


@dataclass
class TrainReport:
    rows: dict[str, int]
    metrics: dict[str, float]
    by_condition: dict[str, dict[str, float]]
    targets: dict[str, float]
    passed: bool
    artefact_dir: str

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


# ------------------------------------------------------------------ physics baseline
def physics_baseline_min(cfg: ConfigBundle, task: dict[str, Any], capacity_m3: float) -> float | None:
    """quantity / (capacity × fill × cycles per hour × efficiency) — shown for comparison only."""
    b = model_cfg(cfg, "task_duration")["baseline"]
    cycles = load_ref_cached(cfg.root, b["cycle_s_ref"])
    cls, ttype, qty = str(task["machine_class"]), str(task["type"]), float(task["quantity"])
    c = cycles.get(cls) or {}
    eff, fill = float(b["efficiency"]), float(b["fill_factor"])
    if "t_cycle" in c:
        base = (c["t_cycle"].get("base_s") or {}).get(ttype)
        if not base or capacity_m3 <= 0:
            return None
        per_h = SECONDS_PER_HOUR / float(base) * capacity_m3 * fill * eff
        return qty / per_h * SECONDS_PER_MINUTE
    if "load_time_s" in c:  # haul: loads × (load + dump + round trip)
        haul_m = float(task.get("haul_distance_m") or 0.0)
        v_e, v_l = (float(c["speed_kph"][k]) / 3.6 for k in ("empty", "loaded"))
        per_load_s = float(c["load_time_s"]["mean"]) + float(c["dump_time_s"]) + haul_m / v_l + haul_m / v_e
        return qty * per_load_s / eff / SECONDS_PER_MINUTE
    return None


# ------------------------------------------------------------------ frames
def _frame(rows: pd.DataFrame, features: list[str], categories: dict[str, list[str]]) -> pd.DataFrame:
    X = rows.reindex(columns=features).copy()
    for col, cats in categories.items():
        X[col] = pd.Categorical(X[col].astype("string"), categories=cats)
    for col in features:
        if col not in categories:
            X[col] = pd.to_numeric(X[col], errors="coerce").astype(float)
    return X


def _target(rows: pd.DataFrame) -> np.ndarray:
    out: np.ndarray = np.log(rows["duration_min"].to_numpy() / rows["quantity"].to_numpy())
    return out


# ------------------------------------------------------------------ training
def train(cfg: ConfigBundle, tables: Tables, out_dir: Path | None = None) -> TrainReport:
    mc = model_cfg(cfg, "task_duration")
    features: list[str] = list(mc["features"])
    cat_cols = [c for c in mc["categorical"] if c in features]
    fb = TaskFeatureBuilder(cfg, tables)
    hist = fb.history().sort_values("start").reset_index(drop=True)
    n = len(hist)
    n_test = int(n * float(mc["split"]["test_fraction"]))
    n_cal = int(n * float(mc["split"]["calibration_fraction"]))
    train_df, cal_df, test_df = (
        hist.iloc[: n - n_cal - n_test],
        hist.iloc[n - n_cal - n_test : n - n_test],
        hist.iloc[n - n_test :],
    )
    categories = {c: sorted(hist[c].astype(str).unique().tolist()) for c in cat_cols}
    X_tr, y_tr = _frame(train_df, features, categories), _target(train_df)
    qs = [float(q) for q in mc["quantiles"]]
    boosters: dict[float, lgb.LGBMRegressor] = {}
    for q in qs:
        m = lgb.LGBMRegressor(objective="quantile", alpha=q, **mc["params"])
        m.fit(X_tr, y_tr, categorical_feature=cat_cols)
        boosters[q] = m
    lo_q, mid_q, hi_q = min(qs), sorted(qs)[len(qs) // 2], max(qs)
    alpha = float(mc["interval_alpha"])

    def raw(df: pd.DataFrame) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        X = _frame(df, features, categories)
        preds = np.vstack([boosters[q].predict(X) for q in (lo_q, mid_q, hi_q)])
        preds.sort(axis=0)  # guard against quantile crossing
        return preds[0], preds[1], preds[2]

    lo_c, _, hi_c = raw(cal_df)
    offset = cqr_offset(_target(cal_df), lo_c, hi_c, alpha)
    lo_t, mid_t, hi_t = raw(test_df)
    y_t = _target(test_df)
    lo_t, hi_t = lo_t - offset, hi_t + offset
    qty = test_df["quantity"].to_numpy()
    dur = test_df["duration_min"].to_numpy()
    p50_min = np.exp(mid_t) * qty
    base = np.array(
        [
            physics_baseline_min(
                cfg, {**r, "machine_class": r["machine_class"], "type": r["task_type"]}, r["bucket_capacity_m3"]
            )
            or np.nan
            for r in _baseline_rows(test_df, tables)
        ]
    )
    ok = ~np.isnan(base)
    metrics = {
        "mape_p50": mape(dur, p50_min),
        "mae_p50_min": float(np.mean(np.abs(p50_min - dur))),
        "picp": picp(y_t, lo_t, hi_t),
        "mean_width_min": float(np.mean((np.exp(hi_t) - np.exp(lo_t)) * qty)),
        "pinball_p50": pinball(y_t, mid_t, mid_q),
        "cqr_offset": offset,
        "baseline_mape": mape(dur[ok], base[ok]) if ok.any() else math.nan,
    }
    rain = test_df["rain_mm_h"].to_numpy() > 0.1
    by_condition = {}
    for name, mask in (("rain", rain), ("dry", ~rain)):
        if mask.sum() >= 3:
            by_condition[name] = {
                "rows": int(mask.sum()),
                "mape_p50": mape(dur[mask], p50_min[mask]),
                "picp": picp(y_t[mask], lo_t[mask], hi_t[mask]),
            }
    t = mc["targets"]
    passed = metrics["mape_p50"] <= float(t["mape_max"]) and abs(metrics["picp"] - float(t["picp_target"])) <= float(
        t["picp_tolerance"]
    )
    out = out_dir or artefact_dir(cfg)
    out.mkdir(parents=True, exist_ok=True)
    for q, m in boosters.items():
        m.booster_.save_model(str(out / f"q{round(q * 100):02d}.txt"))
    meta = {
        "features": features,
        "categories": categories,
        "quantiles": qs,
        "cqr_offset": offset,
        "metrics": metrics,
        "by_condition": by_condition,
        "rows": {"train": len(train_df), "calibration": len(cal_df), "test": len(test_df)},
        "trained_at": utcnow().isoformat(),
        "source": tables.source,
    }
    (out / "meta.json").write_text(json.dumps(meta, indent=2, default=float), encoding="utf-8")
    _log_mlflow("task_duration", mc, metrics)
    TaskDurationModel.load.cache_clear()
    rows = {"train": len(train_df), "calibration": len(cal_df), "test": len(test_df)}
    return TrainReport(rows, metrics, by_condition, {k: float(v) for k, v in t.items()}, passed, str(out))


def _baseline_rows(df: pd.DataFrame, tables: Tables) -> list[dict[str, Any]]:
    tasks = tables.get("tasks").set_index("id")
    out = []
    for r in df.to_dict("records"):
        t = tasks.loc[r["task_id"]]
        out.append({**r, "quantity": float(t["quantity"]), "haul_distance_m": t.get("haul_distance_m")})
    return out


def _log_mlflow(name: str, params: dict[str, Any], metrics: dict[str, float]) -> None:
    import os

    if not os.environ.get("MLFLOW_TRACKING_URI"):
        return
    try:
        import mlflow

        with mlflow.start_run(run_name=name):
            mlflow.log_params({k: str(v) for k, v in params.items() if not isinstance(v, dict | list)})
            mlflow.log_metrics({k: float(v) for k, v in metrics.items() if not math.isnan(float(v))})
    except Exception:  # tracking is optional; training never fails because of it
        return


def artefact_dir(cfg: ConfigBundle, data_dir: Path | None = None) -> Path:
    return (data_dir or get_settings().data_dir) / str(model_cfg(cfg, "task_duration")["artefact_dir"])


# ------------------------------------------------------------------ serving
class ModelNotTrainedError(RuntimeError):
    pass


class TaskDurationModel:
    def __init__(self, path: Path, meta: dict[str, Any], boosters: dict[float, lgb.Booster]):
        self.path = path
        self.meta = meta
        self.features: list[str] = meta["features"]
        self.categories: dict[str, list[str]] = meta["categories"]
        self.boosters = boosters
        self.offset = float(meta["cqr_offset"])
        qs = sorted(boosters)
        self.lo_q, self.mid_q, self.hi_q = qs[0], qs[len(qs) // 2], qs[-1]

    @classmethod
    @lru_cache(maxsize=4)
    def load(cls, path: Path) -> TaskDurationModel:
        meta_path = path / "meta.json"
        if not meta_path.is_file():
            raise ModelNotTrainedError(f"task_duration is not trained (run `uv run tp train task_duration`): {path}")
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        boosters = {
            float(q): lgb.Booster(model_file=str(path / f"q{round(q * 100):02d}.txt")) for q in meta["quantiles"]
        }
        return cls(path, meta, boosters)

    def predict(
        self,
        rows: list[dict[str, Any]],
        quantities: list[float],
        *,
        explain: bool = True,
        top_n: int = 2,
        min_abs_min: float = 1.0,
        exclude: frozenset[str] = frozenset(),
    ) -> list[Estimate]:
        if not rows:
            return []
        X = _frame(pd.DataFrame(rows), self.features, self.categories)
        preds = np.vstack([self.boosters[q].predict(X) for q in (self.lo_q, self.mid_q, self.hi_q)])
        preds.sort(axis=0)
        contrib = self.boosters[self.mid_q].predict(X, pred_contrib=True) if explain else None
        out = []
        for i, qty in enumerate(quantities):
            lo, mid, hi = preds[0][i] - self.offset, preds[1][i], preds[2][i] + self.offset
            p50 = math.exp(mid) * qty
            est = Estimate(math.exp(lo) * qty, p50, math.exp(hi) * qty)
            if contrib is not None:
                est.contrib = np.asarray(contrib[i])
                est.factors = top_factors(self.features, est.contrib, p50, rows[i], top_n, min_abs_min, exclude)
            out.append(est)
        return out


def load_model(cfg: ConfigBundle, data_dir: Path | None = None) -> TaskDurationModel:
    return TaskDurationModel.load(artefact_dir(cfg, data_dir))
