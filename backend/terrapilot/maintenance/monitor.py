"""Streaming maintenance monitor for the live loop (§10.13): the same layers as the history scan, fed from
frames. Machine time = scenario time × `time_scale`, so compressed scenarios produce real-hour ETAs.

History rows are aggregates over whole work cycles, so every live sample is the mean of the signal over
`aggregate_window_sim_s` of scenario time — otherwise phase-dependent signals alias into fake trends when the
scenario clock is compressed.
"""

from __future__ import annotations

from collections import deque
from collections.abc import Callable
from datetime import datetime, timedelta
from typing import Any

import numpy as np

from terrapilot.core.config import ConfigBundle
from terrapilot.domain.models import RawFrame
from terrapilot.maintenance.engine import evaluate_machine, watched_sensors
from terrapilot.maintenance.fusion import fuse, merge_with_existing

ChangeHandler = Callable[[dict[str, Any], str], None]
MAX_SAMPLES = 5000


class LiveMaintenanceMonitor:
    def __init__(
        self,
        cfg: ConfigBundle,
        machine_id: str,
        manifest_id: str,
        site_id: str | None,
        machine_class: str,
        time_scale: float,
        on_change: ChangeHandler | None = None,
        existing: dict[str, dict[str, Any]] | None = None,
    ):
        self.cfg = cfg
        self.machine_id, self.manifest_id = machine_id, manifest_id
        self.site_id, self.machine_class = site_id, machine_class
        self.time_scale = max(time_scale, 1e-6)
        fusion = cfg.models["models"]["maint_alert_fusion"]
        live = fusion["live"]
        self.sample_every = float(live["sample_every_machine_s"])
        self.eval_every = float(live["evaluate_every_machine_s"])
        self.agg_window = float(live["aggregate_window_sim_s"])
        covs = set(cfg.models["models"]["sensor_baseline"]["covariate_signals"].values())
        self.signals = (
            {w.sensor_id for w in watched_sensors(cfg, manifest_id)} | {fusion["operating_filter"]["sensor"]} | covs
        )
        self.buffers: dict[str, deque[tuple[float, float]]] = {s: deque(maxlen=MAX_SAMPLES) for s in self.signals}
        self._raw: dict[str, deque[tuple[float, float]]] = {s: deque() for s in self.signals}
        self.on_change = on_change
        self.alerts: dict[str, dict[str, Any]] = dict(existing or {})
        self.changes: list[tuple[datetime, dict[str, Any], str]] = []
        self._t0: datetime | None = None
        self._last_sample = -np.inf
        self._last_eval = -np.inf

    def machine_time(self, ts: datetime) -> datetime:
        if self._t0 is None:
            self._t0 = ts
        return self._t0 + timedelta(seconds=(ts - self._t0).total_seconds() * self.time_scale)

    def __call__(self, frame: RawFrame, _out: Any = None) -> None:
        self.observe(frame)

    def observe(self, frame: RawFrame) -> None:
        sim_t = frame.ts.timestamp()
        values = {**frame.signals, **{f"site.{k}": v for k, v in frame.env.items()}}
        for sid in self.signals:
            v = values.get(sid)
            if isinstance(v, bool):
                v = float(v)
            if isinstance(v, int | float):
                raw = self._raw[sid]
                raw.append((sim_t, float(v)))
                while raw and sim_t - raw[0][0] > self.agg_window:
                    raw.popleft()
        mt = self.machine_time(frame.ts)
        t = mt.timestamp()
        if t - self._last_sample >= self.sample_every:
            self._last_sample = t
            for sid, raw in self._raw.items():
                if raw:
                    self.buffers[sid].append((t, float(np.mean([p[1] for p in raw]))))
        if t - self._last_eval >= self.eval_every:
            self._last_eval = t
            self.evaluate(mt, frame.ts)

    def evaluate(self, now: datetime, wall: datetime | None = None) -> list[tuple[dict[str, Any], str]]:
        """Layers run in machine time (`now`); stored rows are stamped with wall-clock time (`wall`)."""
        stamp = wall or now
        series = {
            sid: (np.array([p[0] for p in buf]), np.array([p[1] for p in buf]))
            for sid, buf in self.buffers.items()
            if buf
        }
        ev = evaluate_machine(self.cfg, self.machine_id, self.manifest_id, series, now)
        out = []
        for fa in fuse(ev.evidence, self.cfg):
            row, change = merge_with_existing(
                fa, self.alerts.get(fa.component), stamp, self.cfg, self.site_id, self.machine_class
            )
            if change == "none":
                continue
            if row.get("eta"):
                row["eta"] = {**row["eta"], "from": stamp.isoformat()}
            self.alerts[fa.component] = row
            self.changes.append((now, row, change))
            out.append((row, change))
            if self.on_change:
                self.on_change(row, change)
        return out
