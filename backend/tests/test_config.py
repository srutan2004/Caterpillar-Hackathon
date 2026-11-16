from __future__ import annotations

import shutil
from pathlib import Path

import pytest
import yaml

from terrapilot.core.config import ConfigBundle, ConfigError, load_config, resolve_ref_value


def test_repo_config_is_valid(cfg: ConfigBundle) -> None:
    assert not [i for i in cfg.issues if i.level == "error"]
    assert {"excavator_20t", "excavator_20t_electric", "wheel_loader_m", "adt_30t"} <= set(cfg.manifests)


def test_inline_refs_and_derived_values(cfg: ConfigBundle) -> None:
    ex = cfg.manifests_raw["excavator_20t"]
    assert ex["proximity"]["swing_radius_m"] == ex["specs"]["derived"]["tail_swing_radius"] == pytest.approx(2.9)
    assert ex["walkaround"]["items"][0]["id"] == "tracks"  # ref:walkaround/excavator.yaml inlined
    assert cfg.manifests_raw["wheel_loader_m"]["proximity"]["swing_radius_m"] > 0


def test_pointer_refs_resolve(cfg: ConfigBundle) -> None:
    assert resolve_ref_value(cfg, "app.ui.alert_stack_max") == cfg.app.ui.alert_stack_max
    assert resolve_ref_value(cfg, "manifest.proximity.zones_m.caution", "excavator_20t") == 8


def test_layout_specificity(cfg: ConfigBundle) -> None:
    cab = cfg.layout_for("cockpit", "cab", "wheel_loader")
    assert cab and cab.machine_class == "wheel_loader"
    mobile = cfg.layout_for("cockpit", "mobile", "excavator")
    assert mobile and mobile.device == "mobile"
    assert cfg.layout_for("login", "desk", None).screen == "login"  # type: ignore[union-attr]
    desk = cfg.layout_for("cockpit", "desk", "excavator")  # no desk cockpit → falls back to cab
    assert desk and desk.device == "cab"


def test_overlapping_widgets_rejected(config_copy: Path) -> None:
    _edit(config_copy / "ui" / "layouts" / "today.yaml", lambda d: d["widgets"][1].__setitem__("area", [1, 1, 2, 2]))
    with pytest.raises(ConfigError, match="overlaps"):
        load_config(config_copy)


def _edit(path: Path, fn) -> None:  # type: ignore[no-untyped-def]
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    fn(data)
    path.write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=True), encoding="utf-8")


def test_error_points_to_file_and_key(config_copy: Path) -> None:
    _edit(config_copy / "manifests" / "excavator_20t.yaml", lambda d: d["seatbelt"].pop("grace_s"))
    with pytest.raises(ConfigError) as exc:
        load_config(config_copy)
    text = str(exc.value)
    assert "rules/safety.yaml" in text and "manifest.seatbelt.grace_s" in text and "excavator_20t" in text


def test_typo_in_key_is_rejected(config_copy: Path) -> None:
    _edit(config_copy / "app.yaml", lambda d: d["ui"].__setitem__("alert_stak_max", 3))
    with pytest.raises(ConfigError) as exc:
        load_config(config_copy)
    assert "app.yaml:ui.alert_stak_max" in str(exc.value)


def test_unknown_widget_type_rejected(config_copy: Path) -> None:
    _edit(config_copy / "ui" / "layouts" / "today.yaml", lambda d: d["widgets"][0].__setitem__("type", "FancyWidget"))
    with pytest.raises(ConfigError, match="unknown widget type 'FancyWidget'"):
        load_config(config_copy)


def test_missing_i18n_key_rejected(config_copy: Path) -> None:
    _edit(config_copy / "rules" / "safety.yaml", lambda d: d[0].__setitem__("message_key", "alert.nope"))
    with pytest.raises(ConfigError, match=r"alert\.nope"):
        load_config(config_copy)


def test_new_machine_model_is_one_yaml(config_copy: Path) -> None:
    """§10.2 acceptance: adding a model = one YAML (+ layout reuse). Zero code changes."""
    src = config_copy / "manifests" / "excavator_20t.yaml"
    dst = config_copy / "manifests" / "excavator_30t.yaml"
    shutil.copy(src, dst)

    def bigger(d: dict) -> None:  # type: ignore[type-arg]
        d["id"] = "excavator_30t"
        d["id_prefix"] = "EXL"
        d["specs"]["counterweight_offset_m"] = -3.1
        d["specs"]["bucket"]["capacity_m3"] = 1.8
        d["service_intervals_ref"] = "maintenance/service_intervals.yaml#excavator_20t"

    _edit(dst, bigger)
    _edit(
        config_copy / "maintenance" / "service_intervals.yaml",
        lambda d: d.__setitem__("excavator_30t", d["excavator_20t"]),
    )
    bundle = load_config(config_copy)
    m = bundle.manifests_raw["excavator_30t"]
    assert m["specs"]["derived"]["tail_swing_radius"] == pytest.approx(3.4)
    assert bundle.layout_for("cockpit", "cab", "excavator") is not None
    assert resolve_ref_value(bundle, "manifest.envelopes.stability_margin.caution", "excavator_30t") == 1.5
