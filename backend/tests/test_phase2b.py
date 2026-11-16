"""Phase 2B: ETC model + CQR, live ETC, energy/readiness, backward scheduling, maintenance layers + fusion,
the streaming maintenance monitor, and the start-time optimiser — on the tiny generated dataset."""

from __future__ import annotations

import math
from datetime import UTC, datetime, timedelta
from pathlib import Path

import numpy as np
import pytest

from terrapilot.core.config import ConfigBundle
from terrapilot.edge.etc import TaskPrior, blend_rate, live_etc
from terrapilot.maintenance.fusion import can_transition, fuse, merge_with_existing
from terrapilot.maintenance.layers import EvidenceItem, Series, forecast_layer, limit_layer, rate_layer
from terrapilot.ml.calibration import cqr_offset, picp
from terrapilot.ml.data import Tables
from terrapilot.planning.energy import charge_minutes

T0 = datetime(2026, 9, 23, 6, 0, tzinfo=UTC)
HOUR = 3600.0


# ------------------------------------------------------------------ calibration + ETC maths
def test_cqr_offset_restores_coverage() -> None:
    rng = np.random.default_rng(0)
    y = rng.normal(0, 1, 4000)
    lo, hi = np.full_like(y, -0.5), np.full_like(y, 0.5)  # deliberately too narrow
    q = cqr_offset(y[:2000], lo[:2000], hi[:2000], alpha=0.2)
    assert picp(y[2000:], lo[2000:] - q, hi[2000:] + q) == pytest.approx(0.8, abs=0.03)


def test_live_etc_blend_moves_from_prior_to_observed() -> None:
    prior = TaskPrior(rate_per_min=2.0, log_half_width=0.3, source="model")
    assert blend_rate(0, 5.0, 2.0, 12) == 2.0
    assert blend_rate(1000, 3.0, 2.0, 12) == pytest.approx(3.0, abs=0.02)
    early = live_etc(T0, 100, 2, 3.0, prior, 12, 0.1, 1.28)
    late = live_etc(T0, 100, 200, 3.0, prior, 12, 0.1, 1.28)
    assert early.remaining_min_p50 > late.remaining_min_p50  # observed (faster) rate dominates later
    assert late.remaining_min_p90 - late.remaining_min_p10 < early.remaining_min_p90 - early.remaining_min_p10


def test_charge_minutes_taper(cfg: ConfigBundle) -> None:
    energy = cfg.manifests_raw["excavator_20t_electric"]["energy"]
    linear = charge_minutes(energy, 0.2, 0.8, 150)
    tapered = charge_minutes(energy, 0.8, 1.0, 150)
    cap = energy["battery_kwh"] * energy["usable_fraction"]
    assert linear == pytest.approx(0.6 * cap / (150 * energy["charge_efficiency"]) * 60, rel=0.01)
    assert tapered > 0.2 * cap / (150 * energy["charge_efficiency"]) * 60  # slower above the taper start


# ------------------------------------------------------------------ maintenance layers
def _series(values: list[float], step_h: float = 0.25) -> Series:
    t = T0.timestamp() + np.arange(len(values)) * step_h * HOUR
    return Series(t, np.array(values, dtype=float))


def test_limit_layer_needs_the_whole_debounce_window(cfg: ConfigBundle) -> None:
    lim = cfg.sensor_limits["coolant_temp"]
    assert limit_layer(_series([95, 95, 104], step_h=1 / 3600), lim, "M", "cooling", "engine.coolant_temp") is None
    ev = limit_layer(_series([104] * 40, step_h=1 / 3600), lim, "M", "cooling", "engine.coolant_temp")
    assert ev is not None and ev.tier == "service_soon"


def test_rate_and_forecast_layers_on_a_rising_filter(cfg: ConfigBundle) -> None:
    lim = cfg.sensor_limits["filter_dp"]
    rng = np.random.default_rng(1)
    vals = list(1.0 + 0.03 * np.arange(100) * 0.25 + rng.normal(0, 0.01, 100))  # +0.03 bar/h, ends ≈ 1.75 bar
    s = _series(vals)
    rate = rate_layer(s, lim, "M", "hydraulic_pump", "hydraulic.filter_dp", 6, 0.5)
    assert rate is not None and rate.detail["slope_per_h"] == pytest.approx(0.03, rel=0.2)
    fcfg = cfg.models["models"]["sensor_forecaster"]
    ev, curve = forecast_layer(s, lim, "M", "hydraulic_pump", "hydraulic.filter_dp", fcfg, lead_time_h=48)
    assert curve is not None and "service_soon" in curve["etas"]
    eta = curve["etas"]["service_soon"]
    level = curve["level"]
    assert eta["eta_h_p50"] == pytest.approx((2.2 - level) / 0.03, rel=0.25)
    assert eta["eta_h_p10"] <= eta["eta_h_p50"] <= (eta["eta_h_p90"] or math.inf)
    assert ev is not None and ev.tier in ("monitor", "service_soon")


def test_flat_series_raises_nothing(cfg: ConfigBundle) -> None:
    lim = cfg.sensor_limits["hyd_oil_temp"]
    s = _series(list(66 + np.random.default_rng(2).normal(0, 0.2, 200)))
    fcfg = cfg.models["models"]["sensor_forecaster"]
    assert rate_layer(s, lim, "M", "hydraulic_pump", "hydraulic.oil_temp", 6, 0.5) is None
    assert forecast_layer(s, lim, "M", "hydraulic_pump", "hydraulic.oil_temp", fcfg, 48)[0] is None


def test_fusion_merges_promotes_and_never_duplicates(cfg: ConfigBundle) -> None:
    ev = [
        EvidenceItem("rate", "M", "cooling", "monitor", T0, "engine.coolant_temp", 99.0),
        EvidenceItem(
            "forecast", "M", "cooling", "monitor", T0, "engine.coolant_temp", 99.0, {"eta_h_p50": 5, "eta_h_p10": 3}
        ),
        EvidenceItem("limit", "M", "hydraulic_pump", "monitor", T0, "hydraulic.oil_temp", 84.0),
    ]
    fused = {f.component: f for f in fuse(ev, cfg)}
    assert fused["cooling"].tier == "service_soon"  # two independent layers agree → promoted
    assert fused["hydraulic_pump"].tier == "monitor"
    row, change = merge_with_existing(fused["cooling"], None, T0, cfg, "site_metro", "excavator")
    assert change == "open" and row["kind"] in ("rate", "forecast")
    again, change2 = merge_with_existing(
        fused["cooling"], row, T0 + timedelta(minutes=5), cfg, "site_metro", "excavator"
    )
    assert again["id"] == row["id"] and change2 == "none"
    assert can_transition(cfg, "open", "acknowledged") and not can_transition(cfg, "false_alarm", "open")


def test_stop_needs_a_hard_limit(cfg: ConfigBundle) -> None:
    ev = [
        EvidenceItem("rate", "M", "cooling", "service_soon", T0, "engine.coolant_temp", 99.0),
        EvidenceItem(
            "forecast",
            "M",
            "cooling",
            "service_soon",
            T0,
            "engine.coolant_temp",
            99.0,
            {"eta_h_p50": 1, "eta_h_p10": 0.5},
        ),
    ]
    assert fuse(ev, cfg)[0].tier == "service_soon"  # promotion is capped below stop


# ------------------------------------------------------------------ live maintenance scenario
def test_maintenance_scenario_raises_one_merged_rising_alert(cfg: ConfigBundle, tiny_data: Path) -> None:
    from terrapilot.edge.runner import run_scenario
    from terrapilot.maintenance.monitor import LiveMaintenanceMonitor

    spec = cfg.scenarios["demo_maintenance_alert"].model_dump()
    mon = LiveMaintenanceMonitor(cfg, "EX-03", "excavator_20t", "site_metro", "excavator", float(spec["time_scale"]))
    run_scenario(cfg, "demo_maintenance_alert", data_dir=tiny_data, observers=[mon])
    cooling = [(row, ch) for _, row, ch in mon.changes if row["component"] == "cooling"]
    assert cooling, "no cooling alert"
    assert len({row["id"] for row, _ in cooling}) == 1  # merged into one alert
    final = cooling[-1][0]
    assert final["tier"] == spec["expect"]["maintenance_alert"]["tier_rises_to"]
    assert {"rate", "forecast"} <= set(final["evidence"]["layers"])
    assert final["eta"] is not None


# ------------------------------------------------------------------ models + planning on the tiny dataset
@pytest.fixture(scope="module")
def trained(tiny_data: Path) -> Path:
    from terrapilot.core.config import load_config
    from terrapilot.core.settings import REPO_ROOT
    from terrapilot.ml.task_duration import artefact_dir, train

    cfg = load_config(REPO_ROOT / "config")
    report = train(cfg, Tables(tiny_data), artefact_dir(cfg, tiny_data))
    assert report.rows["test"] > 0 and 0 < report.metrics["picp"] <= 1
    return tiny_data


def test_task_duration_model_serves_bands_and_factors(cfg: ConfigBundle, trained: Path) -> None:
    from terrapilot.planning.context import PlanningContext
    from terrapilot.planning.estimate import estimate_task, usual_duration

    ctx = PlanningContext(
        cfg, Tables(trained), now=datetime(2026, 9, 23, 1, 45, tzinfo=UTC), data_dir=trained, live_state=False
    )
    t = ctx.tasks
    task = ctx.task(str(t[t["status"] == "completed"].iloc[-1]["id"]))
    est = estimate_task(ctx, {**task, "status": "planned"}, ctx.now)
    e = est.estimate
    assert est.source == "model" and e.p10 <= e.p50 <= e.p90
    excluded = set(cfg.models["models"]["task_duration"]["factors"]["exclude"])
    assert all(f.feature not in excluded for f in e.factors)
    assert usual_duration(ctx, task) is not None


def test_backschedule_respects_dependencies(cfg: ConfigBundle, trained: Path) -> None:
    from terrapilot.planning.context import PlanningContext
    from terrapilot.planning.schedule import backschedule

    ctx = PlanningContext(
        cfg, Tables(trained), now=datetime(2026, 9, 23, 1, 0, tzinfo=UTC), data_dir=trained, live_state=False
    )
    t = ctx.tasks
    dep = t[t["depends_on"].map(lambda d: len(d) if d is not None else 0) > 0]
    if dep.empty:
        pytest.skip("no dependent tasks in the tiny dataset")
    tid = str(dep.iloc[0]["id"])
    deadline = datetime(2026, 9, 30, 12, 0, tzinfo=UTC)
    out = {r["task_id"]: r for r in backschedule(ctx, [tid], deadline)["tasks"]}
    pred = next(iter(dep.iloc[0]["depends_on"]))
    if pred in out:
        assert out[pred]["latest_finish"] <= out[tid]["latest_start"]


def test_start_time_recommendation_is_feasible_and_explained(cfg: ConfigBundle, trained: Path) -> None:
    from terrapilot.planning.context import PlanningContext
    from terrapilot.planning.start_time import recommend

    tz_now = datetime.fromisoformat("2026-09-23T07:15:00+05:30").astimezone(UTC)
    ctx = PlanningContext(cfg, Tables(trained), now=tz_now, data_dir=trained, live_state=False)
    rec = recommend(ctx, "T-2045")
    assert (rec["feasible"] and not rec["binding"]) or rec["binding"]
    assert rec["curve"] and all("violations" in p for p in rec["curve"])
    best = datetime.fromisoformat(rec["recommended_start"])
    assert best >= ctx.now - timedelta(minutes=1)
    if rec["recommend_change"]:
        assert rec["duration_saving_vs_now_min"] >= cfg.planning.start_time["min_saving_to_recommend_min"]
    kinds = {p["kind"] for p in rec["preconditions"]}
    assert kinds <= {"charge", "mid_task_charge", "refuel", "maintenance_check"}
    assert rec["energy"]["unit"] == "kWh"
