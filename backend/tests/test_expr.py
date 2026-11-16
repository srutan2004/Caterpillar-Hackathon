from __future__ import annotations

from terrapilot.core.config import ConfigBundle
from terrapilot.core.expr import ExprEvaluator, nest_dotted


def test_seatbelt_rule_expression(cfg: ConfigBundle) -> None:
    rule = next(r for r in cfg.safety_rules if r.id == "SEATBELT_UNFASTENED_ACTIVE")
    manifest = cfg.manifests_raw["excavator_20t"]
    state = nest_dotted(
        {
            "seat.occupied": True,
            "seat.belt_fastened": False,
            "motion.ground_speed_kph": 0.0,
            "hydraulic.pump_pressure": 120.0,
        }
    )
    ev = ExprEvaluator({**state, "manifest": manifest})
    assert ev.eval(rule.when) is True
    assert ev.eval(str(rule.for_s)) == 5
    state["seat"]["belt_fastened"] = True
    assert ExprEvaluator({**state, "manifest": manifest}).eval(rule.when) is False


def test_condition_rules_use_abs_and_config(cfg: ConfigBundle) -> None:
    slope = next(r for r in cfg.safety_rules if r.id == "SIDE_SLOPE")
    ev = ExprEvaluator({"imu": {"roll_deg": -12.0}, "manifest": cfg.manifests_raw["excavator_20t"]})
    assert ev.eval(slope.when) is True


def test_expression_sandbox_blocks_imports() -> None:
    import pytest
    from simpleeval import FeatureNotAvailable, FunctionNotDefined, NameNotDefined

    with pytest.raises((FeatureNotAvailable, FunctionNotDefined, NameNotDefined)):
        ExprEvaluator({}).eval("__import__('os').system('echo hi')")
