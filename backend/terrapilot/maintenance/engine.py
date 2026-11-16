"""Run the detection layers for one machine over its sensor series (§10.13). Shared by the history scan and
the live monitor so both produce identical evidence."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

import numpy as np

from terrapilot.core.config import ConfigBundle
from terrapilot.maintenance.baselines import normalise
from terrapilot.maintenance.fusion import parts_lead_time_h
from terrapilot.maintenance.layers import EvidenceItem, Series, forecast_layer, limit_layer, rate_layer
from terrapilot.maintenance.limits import catalogue_code

SECONDS_PER_HOUR = 3600.0


@dataclass(frozen=True)
class WatchedSensor:
    sensor_id: str
    component: str
    limit_key: str
    limit: dict[str, Any]
    forecast: bool


@dataclass
class MachineEvaluation:
    evidence: list[EvidenceItem] = field(default_factory=list)
    curves: dict[str, dict[str, Any]] = field(default_factory=dict)
    # duty-normalised values per sensor (layers D/E read these), aligned with `series[sensor][0]`
    normalised: dict[str, np.ndarray] = field(default_factory=dict)
    component_of: dict[str, str] = field(default_factory=dict)


def watched_sensors(cfg: ConfigBundle, manifest_id: str) -> list[WatchedSensor]:
    out = []
    for ms in cfg.manifests_raw[manifest_id].get("maintenance_sensors", []):
        key = str(ms["limits_ref"]).split("#", 1)[1]
        limit = cfg.sensor_limits.get(key)
        if limit is None:
            continue
        out.append(WatchedSensor(ms["id"], ms["component"], key, limit, bool(ms.get("forecast"))))
    return out


def operating_mask(t: np.ndarray, rpm_t: np.ndarray | None, rpm_v: np.ndarray | None, min_rpm: float) -> np.ndarray:
    if rpm_t is None or rpm_v is None or not len(rpm_t):
        return np.ones(len(t), dtype=bool)
    idx = np.clip(np.searchsorted(rpm_t, t, side="right") - 1, 0, len(rpm_t) - 1)
    return rpm_v[idx] >= min_rpm


def evaluate_machine(
    cfg: ConfigBundle,
    machine_id: str,
    manifest_id: str,
    series: dict[str, tuple[np.ndarray, np.ndarray]],
    now: datetime,
) -> MachineEvaluation:
    """`series` maps sensor id → (POSIX seconds, values), sorted by time and ending at or before `now`."""
    models = cfg.models["models"]
    fusion_cfg = models["maint_alert_fusion"]
    fcfg = models["sensor_forecaster"]
    buffer_h = float(cfg.lifecycle.model_dump()["lead_time"]["scheduling_buffer_h"])
    op = fusion_cfg["operating_filter"]
    coverage = float(fusion_cfg["min_window_coverage"])
    rpm = series.get(op["sensor"])
    rpm_t, rpm_v = (rpm[0], rpm[1]) if rpm is not None else (None, None)
    out = MachineEvaluation()
    for ws in watched_sensors(cfg, manifest_id):
        raw = series.get(ws.sensor_id)
        if raw is None or not len(raw[0]):
            continue
        t, v = raw
        engine_sensor = ws.sensor_id.startswith(("engine.", "hydraulic.", "transmission.", "dpf."))
        mask = operating_mask(t, rpm_t, rpm_v, float(op["min"])) if engine_sensor else np.ones(len(t), dtype=bool)
        t, v = t[mask], v[mask]
        if not len(t):
            continue
        rpm_at = None
        if "curve" in ws.limit and rpm_t is not None and rpm_v is not None:
            idx = np.clip(np.searchsorted(rpm_t, t, side="right") - 1, 0, len(rpm_t) - 1)
            rpm_at = rpm_v[idx]
        s = Series(t, v.astype(float), rpm_at)
        # trends and forecasts run on duty-normalised values (sensor_baseline); limits on the raw reading
        sn = Series(t, normalise(cfg, manifest_id, ws.sensor_id, t, v.astype(float), series), rpm_at)
        out.normalised[ws.sensor_id] = sn.v
        out.component_of[ws.sensor_id] = ws.component
        items = [
            limit_layer(s, ws.limit, machine_id, ws.component, ws.sensor_id),
            rate_layer(
                sn, ws.limit, machine_id, ws.component, ws.sensor_id, int(fusion_cfg["min_points_trend"]), coverage
            ),
        ]
        if ws.forecast:
            code = catalogue_code(ws.limit, "service_soon")
            lead = parts_lead_time_h(cfg, code, ws.component) + buffer_h
            ev, curve = forecast_layer(sn, ws.limit, machine_id, ws.component, ws.sensor_id, fcfg, lead, coverage)
            items.append(ev)
            if curve is not None:
                out.curves[ws.sensor_id] = curve
        for ev in items:
            if ev is not None:
                ev.catalogue_code = ev.catalogue_code or catalogue_code(ws.limit, ev.tier)
                out.evidence.append(ev)
    return out
