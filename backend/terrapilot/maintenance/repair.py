"""Repair duration and cost estimation (§10.15.2): LightGBM quantile + CQR on `maintenance_records`.

Falls back to the catalogue base hours in config/maintenance/costs.yaml when history is thin, so an estimate
is always available. Cost = (hours + travel) × labour rate + parts.
"""

from __future__ import annotations

import json
import math
from functools import lru_cache
from pathlib import Path
from typing import Any

import lightgbm as lgb
import numpy as np
import pandas as pd

from terrapilot.core.config import ConfigBundle
from terrapilot.core.settings import get_settings
from terrapilot.core.timeutil import utcnow
from terrapilot.maintenance.fusion import WORK_TYPE_BY_TIER
from terrapilot.ml.calibration import cqr_offset, mape, picp
from terrapilot.ml.data import Tables

SECONDS_PER_HOUR = 3600.0


def _cfg(cfg: ConfigBundle) -> dict[str, Any]:
    return dict(cfg.models["models"]["repair_estimate"])


def artefact_dir(cfg: ConfigBundle, data_dir: Path | None = None) -> Path:
    return (data_dir or get_settings().data_dir) / str(_cfg(cfg)["artefact_dir"])


def features(cfg: ConfigBundle, tables: Tables) -> pd.DataFrame:
    recs = tables.get("maintenance_records")
    if recs.empty:
        return pd.DataFrame()
    machines = tables.get("machines").set_index("id")
    parts = {p.part_no: p for p in cfg.parts}
    travel = cfg.costs.get("site_remoteness_travel_h", {})
    jobs = recs.groupby("technician_id").size().to_dict() if "technician_id" in recs else {}
    rows = []
    for r in recs.to_dict("records"):
        mid = r.get("machine_id")
        if mid not in machines.index or not r.get("duration_h"):
            continue
        used = [parts[p] for p in (r.get("parts") or []) if p in parts]
        rows.append(
            {
                "component": str(r.get("component")),
                "work_type": str(r.get("work_type")),
                "machine_class": str(machines.loc[mid, "machine_class"]),
                "machine_hours": float(machines.loc[mid, "hour_meter"]),
                "parts_in_stock": float(np.mean([1.0 if p.stock > 0 else 0.0 for p in used])) if used else 1.0,
                "site_remoteness_h": float(travel.get(str(machines.loc[mid, "site_id"]), 0.0)),
                "technician_jobs": float(jobs.get(r.get("technician_id"), 0)),
                "duration_h": float(r["duration_h"]),
                "ts": r.get("ts"),
            }
        )
    return pd.DataFrame(rows)


def _frame(df: pd.DataFrame, feats: list[str], cats: dict[str, list[str]]) -> pd.DataFrame:
    X = df.reindex(columns=feats).copy()
    for c, values in cats.items():
        X[c] = pd.Categorical(X[c].astype("string"), categories=values)
    for c in feats:
        if c not in cats:
            X[c] = pd.to_numeric(X[c], errors="coerce").astype(float)
    return X


def train(cfg: ConfigBundle, tables: Tables, out_dir: Path | None = None) -> dict[str, Any]:
    mc = _cfg(cfg)
    df = features(cfg, tables).sort_values("ts").reset_index(drop=True)
    feats, cat_cols = list(mc["features"]), list(mc["categorical"])
    if len(df) < int(mc["min_rows"]):
        return {
            "rows": {"records": len(df)},
            "metrics": {},
            "passed": False,
            "artefact_dir": str(out_dir or artefact_dir(cfg)),
            "note": "not enough history; catalogue base hours are used",
        }
    n = len(df)
    n_test, n_cal = int(n * 0.2), int(n * 0.2)
    tr, cal, te = df.iloc[: n - n_cal - n_test], df.iloc[n - n_cal - n_test : n - n_test], df.iloc[n - n_test :]
    cats = {c: sorted(df[c].astype(str).unique().tolist()) for c in cat_cols}
    y = np.log(tr["duration_h"].to_numpy())
    boosters = {}
    for q in [float(x) for x in mc["quantiles"]]:
        m = lgb.LGBMRegressor(objective="quantile", alpha=q, **mc["params"])
        m.fit(_frame(tr, feats, cats), y, categorical_feature=cat_cols)
        boosters[q] = m
    qs = sorted(boosters)
    lo_q, mid_q, hi_q = qs[0], qs[len(qs) // 2], qs[-1]

    def raw(d: pd.DataFrame) -> np.ndarray:
        p = np.vstack([boosters[q].predict(_frame(d, feats, cats)) for q in (lo_q, mid_q, hi_q)])
        p.sort(axis=0)
        return p

    pc = raw(cal)
    offset = cqr_offset(np.log(cal["duration_h"].to_numpy()), pc[0], pc[2], float(mc["interval_alpha"]))
    pt = raw(te)
    y_te = np.log(te["duration_h"].to_numpy())
    metrics = {
        "mape_p50": mape(te["duration_h"].to_numpy(), np.exp(pt[1])),
        "picp": picp(y_te, pt[0] - offset, pt[2] + offset),
        "cqr_offset": offset,
    }
    out = out_dir or artefact_dir(cfg)
    out.mkdir(parents=True, exist_ok=True)
    for q, m in boosters.items():
        m.booster_.save_model(str(out / f"q{round(q * 100):02d}.txt"))
    (out / "meta.json").write_text(
        json.dumps(
            {
                "features": feats,
                "categories": cats,
                "quantiles": qs,
                "cqr_offset": offset,
                "metrics": metrics,
                "rows": {"train": len(tr), "test": len(te)},
                "trained_at": utcnow().isoformat(),
            },
            indent=2,
            default=float,
        ),
        encoding="utf-8",
    )
    _load.cache_clear()
    t = mc["targets"]
    passed = metrics["mape_p50"] <= float(t["mape_max"]) and abs(metrics["picp"] - float(t["picp_target"])) <= 0.1
    return {"rows": {"train": len(tr), "test": len(te)}, "metrics": metrics, "passed": passed, "artefact_dir": str(out)}


@lru_cache(maxsize=2)
def _load(path: Path) -> tuple[dict[str, Any], dict[float, lgb.Booster]] | None:
    meta_path = path / "meta.json"
    if not meta_path.is_file():
        return None
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    return meta, {
        float(q): lgb.Booster(model_file=str(path / f"q{round(float(q) * 100):02d}.txt")) for q in meta["quantiles"]
    }


def estimate(
    cfg: ConfigBundle,
    tables: Tables,
    component: str,
    tier_or_work: str,
    machine_id: str,
    parts: list[str] | None = None,
) -> dict[str, Any]:
    """p10/p50/p90 repair hours + labour and parts cost for one job."""
    work = WORK_TYPE_BY_TIER.get(tier_or_work, tier_or_work)
    machines = tables.get("machines").set_index("id")
    known = machine_id in machines.index
    site = str(machines.loc[machine_id, "site_id"]) if known else ""
    machine_class = str(machines.loc[machine_id, "machine_class"]) if known else "excavator"
    travel = float(cfg.costs.get("site_remoteness_travel_h", {}).get(site, 0.0))
    catalogue = float((cfg.costs.get("repair_durations", {}).get(component) or {}).get(work, 0.0))
    part_rows = [p for p in cfg.parts if p.part_no in (parts or [])]
    parts_cost = float(sum(p.price for p in part_rows)) if work != "inspect" else 0.0
    lead_h = max((p.lead_time_days * 24.0 for p in part_rows if p.stock <= 0), default=0.0)
    hours = {"p10": catalogue * 0.8, "p50": catalogue, "p90": catalogue * 1.5}
    method = "catalogue_base"
    loaded = _load(artefact_dir(cfg))
    if loaded is not None:
        meta, boosters = loaded
        row = pd.DataFrame(
            [
                {
                    "component": component,
                    "work_type": work,
                    "machine_class": machine_class,
                    "machine_hours": float(machines.loc[machine_id, "hour_meter"]) if known else 0.0,
                    "parts_in_stock": float(np.mean([1.0 if p.stock > 0 else 0.0 for p in part_rows]))
                    if part_rows
                    else 1.0,
                    "site_remoteness_h": travel,
                    "technician_jobs": 0.0,
                }
            ]
        )
        X = _frame(row, meta["features"], meta["categories"])
        qs = sorted(boosters)
        preds = np.sort(np.array([boosters[q].predict(X)[0] for q in qs]))
        off = float(meta["cqr_offset"])
        hours = {
            "p10": math.exp(preds[0] - off),
            "p50": math.exp(preds[len(preds) // 2]),
            "p90": math.exp(preds[-1] + off),
        }
        method = "lightgbm_cqr"
    rate = float(cfg.costs.get("labour_rate_per_h", {}).get("technician", 0.0))
    downtime = float(cfg.costs.get("downtime_cost_per_h_by_class", {}).get(machine_class, 0.0))
    return {
        "component": component,
        "work_type": work,
        "hours_p10": round(hours["p10"], 1),
        "hours_p50": round(hours["p50"], 1),
        "hours_p90": round(hours["p90"], 1),
        "travel_h": travel,
        "labour_cost": round((hours["p50"] + travel) * rate, 0),
        "parts_cost": round(parts_cost, 0),
        "total_cost": round((hours["p50"] + travel) * rate + parts_cost, 0),
        "downtime_cost_per_h": downtime,
        "parts_lead_time_h": lead_h,
        "currency": cfg.app.costs["currency"],
        "method": method,
    }
