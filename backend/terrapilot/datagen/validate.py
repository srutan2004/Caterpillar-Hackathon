"""`tp validate-data`: integrity/distribution checks + the learnability gate (§7.8).

The gate catches generator bugs before the demo: every target must be learnable (a trivial model beats a
naive baseline on a time-ordered hold-out) and recovered effects must have the configured sign.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from rich.console import Console
from rich.table import Table
from sklearn.linear_model import LinearRegression, LogisticRegression
from sklearn.metrics import mean_absolute_error, roc_auc_score
from sklearn.preprocessing import StandardScaler

from terrapilot.core.config import ConfigBundle, get_config
from terrapilot.core.settings import get_settings


@dataclass
class CheckResult:
    name: str
    passed: bool
    detail: str
    skipped: bool = False
    metrics: dict[str, Any] = field(default_factory=dict)


@dataclass
class ValidationReport:
    checks: list[CheckResult]

    @property
    def passed(self) -> bool:
        return all(c.passed or c.skipped for c in self.checks)


def _read(data_dir: Path, name: str) -> pd.DataFrame:
    path = data_dir / f"{name}.parquet"
    return pd.read_parquet(path) if path.is_file() else pd.DataFrame()


# ------------------------------------------------------------------------------------------ integrity
def integrity_checks(d: Path, cfg: ConfigBundle, manifest: dict[str, Any]) -> list[CheckResult]:
    out: list[CheckResult] = []
    required = [
        "sites",
        "machines",
        "users",
        "tasks",
        "cycles",
        "weather_hourly",
        "ground_conditions",
        "sensor_1min",
        "behavior_events",
        "truth_behavior_labels",
        "truth_component_health",
        "truth_fault_modes",
        "certifications",
        "weather_forecast",
        "task_start_context",
        "fault_codes",
        "parts",
    ]
    empty = [t for t in required if manifest["row_counts"].get(t, 0) == 0]
    out.append(
        CheckResult("required tables populated", not empty, f"empty: {empty}" if empty else f"{len(required)} tables")
    )

    machines, tasks, users = _read(d, "machines"), _read(d, "tasks"), _read(d, "users")
    bad_m = set(tasks["assigned_machine_id"].dropna()) - set(machines["id"])
    bad_o = set(tasks["assigned_operator_id"].dropna()) - set(users["id"])
    out.append(
        CheckResult(
            "task foreign keys",
            not bad_m and not bad_o,
            f"unknown machines {sorted(bad_m)[:3]}, operators {sorted(bad_o)[:3]}"
            if bad_m or bad_o
            else "all tasks reference known machines/operators",
        )
    )

    wx = _read(d, "weather_hourly")
    ranges = {
        "temp_c": (-15, 55),
        "rh": (0, 100),
        "rain_mm": (0, 150),
        "wind_ms": (0, 60),
        "visibility_m": (0, 10001),
        "pm10": (0, 3000),
    }
    bad = {
        k: (float(wx[k].min()), float(wx[k].max()))
        for k, (lo, hi) in ranges.items()
        if wx[k].min() < lo or wx[k].max() > hi
    }
    out.append(
        CheckResult(
            "weather ranges", not bad, f"out of range: {bad}" if bad else "all variables within physical ranges"
        )
    )

    done = tasks[tasks["status"] == "completed"]
    ok = bool((done["duration_min"] > 0).all()) and bool((done["actual_end"] >= done["actual_start"]).all())
    out.append(
        CheckResult(
            "task durations", ok, f"{len(done)} completed tasks, median {done['duration_min'].median():.0f} min"
        )
    )

    cyc = _read(d, "cycles")
    ok = bool((cyc["cycle_s"] > 0).all()) and bool((cyc["payload_t"] > 0).all())
    out.append(CheckResult("cycle sanity", ok, f"{len(cyc):,} cycles, median {cyc['cycle_s'].median():.1f} s"))

    # demo fixtures line up (§18)
    fx = cfg.datagen.get("demo_fixtures") or {}
    problems = []
    for t in fx.get("today_tasks", []):
        row = tasks[tasks["id"] == t["id"]]
        if row.empty:
            problems.append(f"missing task {t['id']}")
        elif t.get("machine") and row.iloc[0]["assigned_machine_id"] != t["machine"]:
            problems.append(f"{t['id']} not on {t['machine']}")
    for mid, site in fx.get("machine_sites", {}).items():
        row = machines[machines["id"] == mid]
        if not row.empty and row.iloc[0]["site_id"] != site:
            problems.append(f"{mid} not at {site}")
    certs = _read(d, "certifications")
    now = pd.Timestamp(manifest["now"])
    for oid, spec in fx.get("operators", {}).items():
        exp = spec.get("cert_expiring")
        if exp:
            row = certs[(certs["user_id"] == oid) & (certs["module_id"] == exp["module"])]
            days = (row["expires_at"].iloc[0] - now).total_seconds() / 86400 if len(row) else None
            if days is None or abs(days - exp["days"]) > 1:
                problems.append(f"{oid} {exp['module']} expires in {days} days (expected {exp['days']})")
    counters = _read(d, "service_counters")
    for mid, due in fx.get("service_due", {}).items():
        row = counters[(counters["machine_id"] == mid) & (counters["item"] == due["item"])]
        mrow = machines[machines["id"] == mid]
        if len(row) and len(mrow):
            left = float(row.iloc[0]["due_hours"] - mrow.iloc[0]["hour_meter"])
            if abs(left - due["due_in_h"]) > 1:
                problems.append(f"{mid} {due['item']} due in {left:.1f} h (expected {due['due_in_h']})")
    fms = _read(d, "truth_fault_modes")
    for fm in fx.get("active_fault_modes", []):
        if fms[(fms["machine_id"] == fm["machine"]) & (fms["mode"] == fm["mode"]) & (fms["outcome"] == "active")].empty:
            problems.append(f"{fm['machine']} {fm['mode']} not active")
    out.append(
        CheckResult(
            "demo fixtures",
            not problems,
            "; ".join(problems) if problems else "tasks, sites, certs, service due, fault modes",
        )
    )
    return out


# ------------------------------------------------------------------------------------------ feature builders
def task_features(d: Path, cfg: ConfigBundle) -> pd.DataFrame:
    """One row per completed task, features from observable tables only.

    `y_duration` = log(wall-clock minutes per unit); `y_cycle` = mean log(cycle seconds) — the latter isolates
    the multiplicative causal factors from breaks, waits and weather stoppages.
    """
    tasks = _read(d, "tasks")
    done = tasks[(tasks["status"] == "completed") & tasks["duration_min"].notna()].copy()
    wx = _read(d, "weather_hourly").sort_values("ts")
    ctx = _read(d, "task_start_context").set_index("task_id")
    profiles = _read(d, "operator_profiles").set_index("user_id")
    zones = _read(d, "zones").set_index("id")
    cyc = _read(d, "cycles")
    cycle_mean = np.log(cyc["cycle_s"]).groupby(cyc["task_id"]).mean()
    soils = cfg.datagen["ground"]["soils"]  # field capacity is a known soil property, not hidden truth
    world = cfg.datagen["world"]
    stop = cfg.datagen["cycles"]["stoppages"]["hard_stop"]
    tz = world["timezone"]
    shift_h, shift_m = (int(x) for x in world["shift"]["start_local"].split(":"))
    rows = []
    wx_by_site = {s: g.set_index("ts") for s, g in wx.groupby("site_id")}
    for t in done.itertuples():
        planned_end = t.actual_start + (t.planned_end - t.planned_start)
        w = wx_by_site[t.site_id].loc[t.actual_start.floor("h") : planned_end]
        if w.empty or t.id not in cycle_mean.index:
            continue
        local_start = t.actual_start.tz_convert(tz)
        shift0 = local_start.normalize() + pd.Timedelta(hours=shift_h, minutes=shift_m)
        overlap = 0.0
        for b in world["shift"]["breaks"]:
            b0 = shift0 + pd.Timedelta(hours=float(b["at_h"]))
            b1 = b0 + pd.Timedelta(minutes=float(b["minutes"]))
            overlap += max(0.0, (min(b1, planned_end) - max(b0, local_start)).total_seconds() / 60)
        soil = zones.loc[t.zone_id, "soil"]
        c = ctx.loc[t.id] if t.id in ctx.index else None
        rows.append(
            {
                "id": t.id,
                "type": t.type,
                "start": t.actual_start,
                "y_duration": float(np.log(t.duration_min / t.quantity)),
                "y_cycle": float(cycle_mean[t.id]),
                "start_hour": local_start.hour + local_start.minute / 60,
                "break_overlap_min": overlap,
                "stop_weather_hours": float(
                    (
                        (w["lightning_km"] < stop["lightning_km_lt"])
                        | (w["gust_ms"] > stop["gust_ms_gt"])
                        | (w["rain_mm"] > stop["rain_mm_h_gt"])
                    ).sum()
                ),
                "rain_mm_h_work": float(w["rain_mm"].mean()),
                "temp_excess_c": float(np.clip(w["temp_c"].mean() - 30, 0, None)),
                "visibility_low": float((w["visibility_m"] < 250).mean()),
                "moisture_excess": max(0.0, float(c["ground_moisture"]) - soils[soil]["m_field"])
                if c is not None
                else np.nan,
                "health_index": float(c["health_index"]) if c is not None else np.nan,
                "experience_years": float(profiles.loc[t.assigned_operator_id, "experience_years"]),
                "soil_clay": float(soil == "clay"),
                "soil_rock": float(soil == "rock"),
                "depth_m": float(t.depth_m) if pd.notna(t.depth_m) else 0.0,
                "haul_km": float(t.haul_distance_m) / 1000 if pd.notna(t.haul_distance_m) else 0.0,
            }
        )
    return pd.DataFrame(rows).dropna()


def failure_features(d: Path, horizon_days: int) -> pd.DataFrame:
    h = _read(d, "truth_component_health").sort_values(["machine_id", "component", "date"])
    wx = _read(d, "weather_hourly")
    machines = _read(d, "machines").set_index("id")
    wx["date"] = wx["ts"].dt.date
    daily = (
        wx.groupby(["site_id", "date"]).agg(dust_pm10_mean=("pm10", "mean"), temp_mean=("temp_c", "mean")).reset_index()
    )
    h["site_id"] = h["machine_id"].map(machines["site_id"])
    h = h.merge(daily, on=["site_id", "date"], how="left")
    h["date"] = pd.to_datetime(h["date"])
    fails = h[h["failed"]].groupby(["machine_id", "component"])["date"].apply(list).to_dict()

    def label(r: Any) -> int:
        return int(any(0 <= (f - r.date).days <= horizon_days for f in fails.get((r.machine_id, r.component), [])))

    h["y"] = [label(r) for r in h.itertuples()]
    h["start"] = h["date"]
    return h.dropna(subset=["dust_pm10_mean", "temp_mean"])


def idle_features(d: Path, tz: str, min_waits: int) -> pd.DataFrame:
    """Share of wait windows in which the operator kept idling, per operator-day."""
    be = _read(d, "behavior_events")
    waits = _read(d, "idle_windows")
    shifts = _read(d, "shift_assignments")
    traits = _read(d, "truth_operator_traits").set_index("operator_id")
    waits = waits[waits["kind"].isin(["truck_wait", "radio"])].copy()
    waits["date"] = waits["start"].dt.tz_convert(tz).dt.date
    n_waits = waits.groupby(["machine_id", "date"]).size().rename("waits").reset_index()
    idle = be[be["kind"].isin(["idle", "high_rpm_idle"])].copy()
    idle["date"] = idle["start_ts"].dt.tz_convert(tz).dt.date
    n_idle = idle.groupby(["machine_id", "date"]).size().rename("idles").reset_index()
    df = (
        shifts[["machine_id", "date", "operator_id"]]
        .merge(n_waits, on=["machine_id", "date"])
        .merge(n_idle, on=["machine_id", "date"], how="left")
        .fillna({"idles": 0})
    )
    df = df[df["waits"] >= min_waits]
    df["y"] = np.clip(df["idles"] / df["waits"], 0, 1)
    df["idle_propensity"] = df["operator_id"].map(traits["idle_propensity"])
    df["start"] = pd.to_datetime(df["date"])
    return df


def seatbelt_features(d: Path) -> pd.DataFrame:
    sc = _read(d, "seatbelt_compliance")
    traits = _read(d, "truth_operator_traits").set_index("operator_id")
    df = sc[sc["active_s"] > 1800].copy()
    df["y"] = 1 - df["unbelted_active_s"] / df["active_s"]
    df["belt_compliance_p"] = df["operator_id"].map(traits["belt_compliance_p"])
    df["start"] = pd.to_datetime(df["date"])
    return df


def drift_features(d: Path, sensor: str, cfg: ConfigBundle) -> pd.DataFrame:
    s = _read(d, "sensor_1min")
    s = s[s["sensor_id"] == sensor].copy()
    comp = cfg.datagen["degradation"]["sensors"][sensor]["component"]
    tz = cfg.datagen["world"]["timezone"]
    h = _read(d, "truth_component_health")
    h = h[h["component"] == comp][["date", "machine_id", "health"]]
    s["date"] = s["ts"].dt.tz_convert(tz).dt.date
    daily = s.groupby(["machine_id", "date"])["resid"].mean().rename("y").reset_index()
    df = daily.merge(h, on=["machine_id", "date"], how="inner")
    df["wear"] = 1 - df["health"]
    df["start"] = pd.to_datetime(df["date"])
    return df


# ------------------------------------------------------------------------------------------ evaluation
def _split(df: pd.DataFrame, frac: float) -> tuple[pd.DataFrame, pd.DataFrame]:
    df = df.sort_values("start")
    cut = int(len(df) * (1 - frac))
    return df.iloc[:cut], df.iloc[cut:]


def _signs(
    df: pd.DataFrame,
    features: list[str],
    expected: dict[str, str],
    extra: pd.DataFrame | None = None,
    t_min: float = 2.0,
) -> tuple[dict[str, float], list[str], list[str]]:
    """OLS on standardised features. Returns (coefficients, wrong-sign features, inconclusive features).

    A sign is only judged when |t| ≥ t_min; otherwise the effect is reported as inconclusive.
    """
    x = StandardScaler().fit_transform(df[features].to_numpy(dtype=float))
    # type dummies absorb the intercept; otherwise add one
    x = np.hstack([x, extra.to_numpy(dtype=float) if extra is not None else np.ones((len(x), 1))])
    y = df["y"].to_numpy(dtype=float)
    beta, *_ = np.linalg.lstsq(x, y, rcond=None)
    resid = y - x @ beta
    dof = max(len(y) - x.shape[1], 1)
    cov = np.linalg.pinv(x.T @ x) * float(resid @ resid) / dof
    se = np.sqrt(np.clip(np.diag(cov), 1e-18, None))
    coefs = {f: round(float(beta[i]), 4) for i, f in enumerate(features)}
    tvals = {f: float(beta[i] / se[i]) for i, f in enumerate(features)}
    wrong = [f for f, s in expected.items() if abs(tvals[f]) >= t_min and (coefs[f] > 0) != (s == "+")]
    inconclusive = [f for f in expected if abs(tvals[f]) < t_min]
    return coefs, wrong, inconclusive


def evaluate_regression(name: str, df: pd.DataFrame, spec: dict[str, Any], frac: float, min_rows: int) -> CheckResult:
    if len(df) < min_rows:
        return CheckResult(name, False, f"only {len(df)} rows (< {min_rows})", skipped=True)
    feats = spec["features"]
    train, test = _split(df, frac)
    groups = spec.get("group_by")
    if spec["baseline"] == "group_median" and groups:
        med = train.groupby(groups)["y"].median()
        base_pred = test[groups[0]].map(med).fillna(train["y"].median())
        dummies_train = pd.get_dummies(train[groups[0]], dtype=float)
        dummies_test = pd.get_dummies(test[groups[0]], dtype=float).reindex(
            columns=dummies_train.columns, fill_value=0.0
        )
    else:
        base_pred = np.full(len(test), train["y"].mean())
        dummies_train = dummies_test = None
    scaler = StandardScaler().fit(train[feats].to_numpy(dtype=float))
    xtr = scaler.transform(train[feats].to_numpy(dtype=float))
    xte = scaler.transform(test[feats].to_numpy(dtype=float))
    if dummies_train is not None:
        xtr, xte = np.hstack([xtr, dummies_train.to_numpy()]), np.hstack([xte, dummies_test.to_numpy()])
    model = LinearRegression().fit(xtr, train["y"])
    mae_base = mean_absolute_error(test["y"], base_pred)
    mae_model = mean_absolute_error(test["y"], model.predict(xte))
    improvement = 1 - mae_model / mae_base if mae_base > 0 else 0.0
    extra = pd.get_dummies(df[groups[0]], dtype=float) if groups else None
    coefs, wrong, unsure = _signs(df, feats, spec.get("expected_signs", {}), extra)
    strict = len(df) >= int(spec.get("conclusive_from_rows", 10**9))
    passed = improvement >= spec["min_improvement"] and not wrong and not (strict and unsure)
    detail = f"MAE {mae_model:.4f} vs baseline {mae_base:.4f} (improvement {improvement:+.1%}, need {spec['min_improvement']:.0%})"
    if wrong:
        detail += f"; wrong sign: {wrong}"
    if unsure:
        detail += f"; inconclusive (|t|<2{', enforced' if strict else ''}): {unsure}"
    return CheckResult(
        name, passed, detail, metrics={"improvement": improvement, "coefficients": coefs, "rows": len(df)}
    )


def evaluate_classification(
    name: str, df: pd.DataFrame, spec: dict[str, Any], frac: float, min_rows: int
) -> CheckResult:
    pos = int(df["y"].sum()) if len(df) else 0
    if len(df) < min_rows or pos < spec.get("min_positives", 1) or pos == len(df):
        return CheckResult(name, False, f"{len(df)} rows, {pos} positives — too few events at this scale", skipped=True)
    feats = spec["features"]
    x = StandardScaler().fit_transform(df[feats].to_numpy(dtype=float))
    # stratified-by-time is too sparse for rare failures: evaluate in-sample AUROC + coefficient sign
    clf = LogisticRegression(max_iter=1000).fit(x, df["y"])
    auc = roc_auc_score(df["y"], clf.predict_proba(x)[:, 1])
    coefs = {f: round(float(c), 4) for f, c in zip(feats, clf.coef_[0], strict=True)}
    wrong = [f for f, s in spec.get("expected_signs", {}).items() if (coefs[f] > 0) != (s == "+")]
    passed = auc >= 0.5 + spec["min_improvement"] and not wrong
    detail = f"AUROC {auc:.3f} (need ≥ {0.5 + spec['min_improvement']:.2f}), {pos} positives"
    if wrong:
        detail += f"; wrong sign: {wrong}"
    return CheckResult(name, passed, detail, metrics={"auroc": auc, "coefficients": coefs})


def run_validation(data_dir: Path | None = None, console: Console | None = None) -> ValidationReport:
    console = console or Console()
    cfg = get_config()
    d = data_dir or get_settings().data_dir / "generated"
    manifest = json.loads((d / "manifest.json").read_text(encoding="utf-8"))
    learn = cfg.models["learnability"]
    frac, min_rows = float(learn["holdout_fraction"]), int(learn["min_rows"])
    t = learn["targets"]
    checks = integrity_checks(d, cfg, manifest)
    tf = task_features(d, cfg)
    checks.append(
        evaluate_regression(
            "learnable: task_duration", tf.assign(y=tf["y_duration"]), t["task_duration"], frac, min_rows
        )
    )
    checks.append(
        evaluate_regression("effects: cycle_time", tf.assign(y=tf["y_cycle"]), t["cycle_time_effects"], frac, min_rows)
    )
    checks.append(
        evaluate_classification(
            "learnable: component_failure",
            failure_features(d, t["component_failure"]["horizon_days"]),
            t["component_failure"],
            frac,
            min_rows,
        )
    )
    tz = cfg.datagen["world"]["timezone"]
    checks.append(
        evaluate_regression(
            "learnable: idle_ratio",
            idle_features(d, tz, int(t["idle_ratio"]["min_waits"])),
            t["idle_ratio"],
            frac,
            min_rows,
        )
    )
    checks.append(evaluate_regression("learnable: seatbelt", seatbelt_features(d), t["seatbelt"], frac, min_rows))
    checks.append(
        evaluate_regression(
            "learnable: sensor_drift",
            drift_features(d, t["sensor_drift"]["sensor"], cfg),
            t["sensor_drift"],
            frac,
            min_rows,
        )
    )

    table = Table(title=f"validate-data — {d} (scale={manifest['scale']}, anchor={manifest['anchor']})")
    table.add_column("check")
    table.add_column("result")
    table.add_column("detail", overflow="fold")
    for c in checks:
        status = "[yellow]skipped[/yellow]" if c.skipped else "[green]pass[/green]" if c.passed else "[red]FAIL[/red]"
        table.add_row(c.name, status, c.detail)
    console.print(table)
    effects = next((c.metrics.get("coefficients") for c in checks if c.name == "effects: cycle_time"), None)
    if effects:
        console.print(
            "cycle-time effects (standardised coefficients on mean log cycle seconds): "
            + ", ".join(f"{k} {v:+.3f}" for k, v in effects.items())
        )
    report = ValidationReport(checks)
    (d / "validation_report.json").write_text(
        json.dumps({"passed": report.passed, "checks": [c.__dict__ for c in checks]}, indent=2, default=str),
        encoding="utf-8",
    )
    return report
