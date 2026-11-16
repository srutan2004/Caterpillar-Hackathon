"""Rule fixture runner (config/rules/tests/*.yaml): frames → exact alert event sequence (§6.2, §13.2 `rules`)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import yaml

from terrapilot.core.config import ConfigBundle
from terrapilot.core.expr import nest_dotted
from terrapilot.safety.rules import RulesEngine

EPOCH = datetime(2026, 1, 1, tzinfo=UTC)


_EPS = 1e-9  # float tolerance when matching frame times


@dataclass
class FixtureResult:
    id: str
    passed: bool
    expected: list[tuple[float, str, str, str]]
    actual: list[tuple[float, str, str, str]]


def engine_for(cfg: ConfigBundle, manifest_id: str, machine_id: str = "FIXTURE") -> RulesEngine:
    m = cfg.manifests[manifest_id]
    return RulesEngine(
        machine_id,
        cfg.manifests_raw[manifest_id],
        cfg.app_dict(),
        cfg.safety_rules + cfg.condition_rules,
        cfg.maintenance_rules,
        cfg.sensor_limits,
        m.class_,
        m.powertrain,
    )


def run_fixture(cfg: ConfigBundle, spec: dict[str, Any]) -> FixtureResult:
    engine = engine_for(cfg, spec["manifest"])
    tick = float(spec.get("tick_s", 1))
    frames = sorted(spec["frames"], key=lambda f: f["t"])
    flat: dict[str, Any] = {}
    actual: list[tuple[float, str, str, str]] = []
    t = 0.0
    while t <= float(spec["until_s"]) + _EPS:
        for f in frames:
            if abs(f["t"] - t) < _EPS:
                flat.update(f["set"])
        for ev in engine.evaluate(nest_dotted(flat), EPOCH + timedelta(seconds=t)):
            if ev.phase != "update":
                actual.append((round(t, 3), ev.alert.rule_id, ev.phase, ev.alert.severity))
        t += tick
    expected = [(float(e["t"]), e["rule"], e["phase"], e["severity"]) for e in spec.get("expect", [])]
    return FixtureResult(spec["id"], sorted(actual) == sorted(expected), expected, actual)


def run_all(cfg: ConfigBundle, directory: Path | None = None) -> list[FixtureResult]:
    base = directory or cfg.root / "rules" / "tests"
    return [run_fixture(cfg, yaml.safe_load(p.read_text(encoding="utf-8"))) for p in sorted(base.glob("*.yaml"))]
