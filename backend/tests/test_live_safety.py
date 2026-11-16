"""Phase 2A: twin maths, rules engine fixtures, scenario integration, black box, edge/cloud boundary."""

from __future__ import annotations

import ast
import math
from pathlib import Path

import pytest

from terrapilot.core.config import ConfigBundle
from terrapilot.core.settings import REPO_ROOT
from terrapilot.edge.runner import is_subsequence, run_scenario
from terrapilot.safety.fixtures import run_all
from terrapilot.sim.machine import excavator_ik
from terrapilot.twin.geometry import point_segment_distance3, rect_edge_distance
from terrapilot.twin.grade import grade_deviation
from terrapilot.twin.kinematics import ArmPose, excavator_points
from terrapilot.twin.proximity import Track, assess, time_to_radius
from terrapilot.twin.stability import stability


# ------------------------------------------------------------------ twin maths (hand-computed cases)
def test_forward_kinematics_straight_arm(cfg: ConfigBundle) -> None:
    specs = cfg.manifests_raw["excavator_20t"]["specs"]
    pts = excavator_points(specs, ArmPose(0, 0, 0, 0))
    total = (
        specs["boom"]["pivot"][0] + specs["boom"]["length_m"] + specs["stick"]["length_m"] + specs["bucket"]["length_m"]
    )
    assert pts.tip == pytest.approx((total, 0.0, specs["boom"]["pivot"][1]))
    swung = excavator_points(specs, ArmPose(0, 0, 0, 90))
    assert swung.tip[0] == pytest.approx(0, abs=1e-9) and swung.tip[1] == pytest.approx(total)


def test_ik_round_trip(cfg: ConfigBundle) -> None:
    specs = cfg.manifests_raw["excavator_20t"]["specs"]
    for r, z, b in [(6.0, -2.5, -110), (4.2, -2.5, -30), (5.0, 1.8, -150)]:
        boom, stick, bucket = excavator_ik(specs, r, z, b)
        tip = excavator_points(specs, ArmPose(boom, stick, bucket)).tip
        assert tip[0] == pytest.approx(r, abs=1e-6) and tip[2] == pytest.approx(z, abs=1e-6)


def test_stability_by_hand(cfg: ConfigBundle) -> None:
    """Over the side at full reach, the moment balance computed by hand is ~1.3; slope makes it worse."""
    specs = cfg.manifests_raw["excavator_20t"]["specs"]
    pose = ArmPose(5, -45, -30, 90)
    flat = stability(specs, pose, 2.0, 0, 0)
    sloped = stability(specs, pose, 2.0, 0, 12)
    front = stability(specs, ArmPose(5, -45, -30, 0), 2.0, 0, 0)
    assert 1.2 < flat.margin < 1.4 and flat.limiting_axis == "lateral"
    assert sloped.margin < flat.margin < front.margin
    assert front.limiting_axis == "longitudinal"
    assert flat.sensitivity["lower_load"] > 0 and flat.sensitivity["reduce_reach"] > 0


def test_stability_monotonic_in_reach(cfg: ConfigBundle) -> None:
    specs = cfg.manifests_raw["excavator_20t"]["specs"]
    margins = [
        stability(specs, ArmPose(*excavator_ik(specs, r, -0.5, -60), 90), 2.0, 0, 0).margin for r in (5, 6, 7, 8)
    ]
    assert margins == sorted(margins, reverse=True)


def test_geometry_helpers() -> None:
    d, c = point_segment_distance3((0, 1, 0), (-1, 0, 0), (1, 0, 0))
    assert d == pytest.approx(1) and c == pytest.approx((0, 0, 0))
    assert rect_edge_distance(0, 1.8, 1.2) == (pytest.approx(1.8), "longitudinal")
    assert rect_edge_distance(math.pi / 2, 1.8, 1.2)[1] == "lateral"


def test_ttc_and_static_suppression(cfg: ConfigBundle) -> None:
    assert time_to_radius((20, 0), (-2, 0), 10) == pytest.approx(5)
    assert time_to_radius((20, 0), (2, 0), 10) is None
    zones = cfg.manifests_raw["excavator_20t"]["proximity"]["zones_m"]
    parked = assess(Track("p", "person", (12, 3), (0.0, 0.0)), 10.2, zones, 0.3)
    walking = assess(Track("w", "person", (20, 0), (-2.0, 0.0)), 10.2, zones, 0.3)
    assert parked.static and parked.ttc_s is None
    assert not walking.static and walking.ttc_s == pytest.approx(4.9, abs=0.01)


def test_grade_direction() -> None:
    assert grade_deviation(-2.54, -2.5, 0.03).direction == "raise"
    assert grade_deviation(-2.51, -2.5, 0.03).direction == "on_grade"
    assert grade_deviation(-2.4, -2.5, 0.03).direction == "lower"


# ------------------------------------------------------------------ rules engine
def test_rule_fixtures(cfg: ConfigBundle) -> None:
    results = run_all(cfg)
    assert results, "no rule fixtures found"
    failed = [(r.id, r.expected, r.actual) for r in results if not r.passed]
    assert not failed, failed


# ------------------------------------------------------------------ scenarios end to end (fast-forward)
@pytest.mark.parametrize(
    "scenario_id",
    [
        "demo_trench_pedestrian",
        "demo_seatbelt",
        "demo_slope",
        "demo_wind",
        "demo_utility",
        "demo_electric_charging",
        "demo_idle",
    ],
)
def test_scenario_alert_order(cfg: ConfigBundle, tiny_data: Path, scenario_id: str) -> None:
    from terrapilot.sim.world import load_context

    spec = cfg.scenarios[scenario_id]
    world = load_context(spec.machine, spec.task, spec.operator, tiny_data) if _no_db() else None
    s = run_scenario(cfg, scenario_id, world=world, data_dir=tiny_data)
    expected = spec.expect.get("alerts_in_order", [])
    assert is_subsequence(expected, s.first_open_order()), (expected, s.first_open_order())
    for kind in spec.expect.get("behavior_events", []) or []:
        assert kind in {b.kind for b in s.behavior}, kind
    for esc in spec.expect.get("escalations", []) or []:
        evs = [e for e in s.alerts if e.alert.rule_id == esc["rule"] and e.phase == "escalate"]
        assert evs and evs[0].alert.severity == esc["to"]


def test_trench_scenario_details(cfg: ConfigBundle, tiny_data: Path) -> None:
    s = run_scenario(cfg, "demo_trench_pedestrian", data_dir=tiny_data)
    ttc = next(e for e in s.alerts if e.alert.rule_id == "PERSON_TTC" and e.phase == "open")
    zone = next(e for e in s.alerts if e.alert.rule_id == "PERSON_IN_ZONE_WARNING" and e.phase == "open")
    assert ttc.alert.opened_at < zone.alert.opened_at  # TTC warns before the person is in the warning radius
    utility = next(e for e in s.alerts if e.alert.rule_id == "UTILITY_APPROACH" and e.phase == "open")
    assert utility.alert.params["utility_id"] == "U-07" and utility.alert.severity == "advisory"
    assert any(
        e.alert.rule_id == "UTILITY_APPROACH" and e.phase == "escalate" and e.alert.severity == "caution"
        for e in s.alerts
    )
    assert s.clips and all(c.incident["source"] == "auto" for c in s.clips)
    assert any(c.frames and "tracks" in c.frames[-1] for c in s.clips)  # playback has person tracks
    cav = next(b for b in s.behavior if b.kind == "cavitation")
    assert cav.metrics["duration_s"] >= 2


def test_g_spike_opens_incident(cfg: ConfigBundle, tiny_data: Path) -> None:
    sc = cfg.scenarios["demo_seatbelt"].model_copy(deep=True)
    sc.timeline = [*sc.timeline, type(sc.timeline[0]).model_validate({"t": 40, "inject": "g_spike"})]
    cfg2 = cfg
    cfg2.scenarios = {**cfg.scenarios, "_g": sc.model_copy(update={"id": "_g"})}
    s = run_scenario(cfg2, "_g", data_dir=tiny_data)
    assert any(c.clip["trigger_rule_id"] == "IMU_G_SPIKE" and c.incident["kind"] == "incident" for c in s.clips)
    cfg2.scenarios.pop("_g")


def test_tick_latency_budget(cfg: ConfigBundle, tiny_data: Path) -> None:
    import time

    t0 = time.perf_counter()
    s = run_scenario(cfg, "demo_wind", data_dir=tiny_data)
    per_tick_ms = (time.perf_counter() - t0) / s.ticks * 1000
    assert per_tick_ms < cfg.app.latency_budgets_ms["tick_processing"]


# ------------------------------------------------------------------ architecture boundary
EDGE_PACKAGES = ["twin", "safety", "behavior", "edge", "sim"]
CLOUD_PACKAGES = {"analytics", "ml", "planning", "maintenance", "training", "datagen", "api"}


def test_edge_does_not_import_cloud() -> None:
    offenders = []
    for pkg in EDGE_PACKAGES:
        for path in (REPO_ROOT / "backend" / "terrapilot" / pkg).rglob("*.py"):
            for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
                mods = (
                    [node.module]
                    if isinstance(node, ast.ImportFrom) and node.module
                    else [a.name for a in node.names]
                    if isinstance(node, ast.Import)
                    else []
                )
                for m in mods:
                    parts = m.split(".")
                    if parts[0] == "terrapilot" and len(parts) > 1 and parts[1] in CLOUD_PACKAGES:
                        offenders.append(f"{path.name}: {m}")
    assert not offenders, offenders


def _no_db() -> bool:
    try:
        from sqlalchemy import text

        from terrapilot.db.engine import get_engine

        with get_engine().connect() as c:
            c.execute(text("SELECT 1 FROM machines LIMIT 1"))
        return False
    except Exception:
        return True
