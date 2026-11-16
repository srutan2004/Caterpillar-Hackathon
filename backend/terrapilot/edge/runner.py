"""Scenario runner (§7.6): simulator → edge pipeline → sinks, in real time (demo) or as fast as possible (tests)."""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from terrapilot.core.config import ConfigBundle
from terrapilot.core.timeutil import utcnow
from terrapilot.domain.models import AlertEvent, BehaviorEvent, RawFrame
from terrapilot.edge.pipeline import EdgePipeline, TickOutput
from terrapilot.edge.sinks import MemorySink, Publisher, RedisDbSink, Sink
from terrapilot.safety.blackbox import FinishedClip
from terrapilot.sim.machine import MachineSim
from terrapilot.sim.world import WorldContext, load_context


@dataclass
class RunSummary:
    scenario_id: str
    ticks: int = 0
    alerts: list[AlertEvent] = field(default_factory=list)
    behavior: list[BehaviorEvent] = field(default_factory=list)
    clips: list[FinishedClip] = field(default_factory=list)
    advisories: list[dict[str, Any]] = field(default_factory=list)
    last_state: dict[str, Any] = field(default_factory=dict)

    def first_open_order(self) -> list[str]:
        seen: list[str] = []
        for e in self.alerts:
            if e.phase == "open" and e.alert.rule_id not in seen:
                seen.append(e.alert.rule_id)
        return seen


def scenario_spec(cfg: ConfigBundle, scenario_id: str) -> dict[str, Any]:
    sc = cfg.scenarios.get(scenario_id)
    if sc is None:
        raise KeyError(f"unknown scenario '{scenario_id}'")
    return sc.model_dump()


def build(
    cfg: ConfigBundle,
    scenario_id: str,
    world: WorldContext | None = None,
    data_dir: Path | None = None,
    advisor: Any = None,
    start: datetime | None = None,
    blackbox_dir: Path | None = None,
    p2p: bool = False,
) -> tuple[MachineSim, EdgePipeline, dict[str, Any]]:
    spec = scenario_spec(cfg, scenario_id)
    world = world or load_context(spec["machine"], spec.get("task"), spec.get("operator"), data_dir)
    tick_hz = float(spec.get("tick_hz") or 10)
    sim = MachineSim(cfg, world, spec, seed=0, start=start or utcnow())
    link = None
    if p2p:
        from terrapilot.core.settings import get_settings
        from terrapilot.safety.p2p import P2PLink

        link = P2PLink(cfg.app.p2p, str(world.machine.get("site_id")), get_settings().redis_url)
    pipe = EdgePipeline(
        cfg, world, tick_hz, blackbox_dir=blackbox_dir, advisor=advisor, p2p_link=link, start_of_run=start or utcnow()
    )
    return sim, pipe, spec


def run_scenario(
    cfg: ConfigBundle,
    scenario_id: str,
    *,
    sink: Sink | None = None,
    realtime: bool = False,
    speed: float = 1.0,
    world: WorldContext | None = None,
    data_dir: Path | None = None,
    advisor: Any = None,
    stop: threading.Event | None = None,
    blackbox_dir: Path | None = None,
    until_s: float | None = None,
    p2p: bool = False,
    observers: list[Callable[[RawFrame, TickOutput], None]] | None = None,
) -> RunSummary:
    """`observers` are called after every tick; the cloud wires its consumers (e.g. the maintenance monitor)
    through them so the edge never imports cloud code."""
    sim, pipe, spec = build(cfg, scenario_id, world, data_dir, advisor, blackbox_dir=blackbox_dir, p2p=p2p)
    sink = sink or MemorySink()
    publisher = Publisher(pipe.machine_id, sink, float(cfg.app.ui.state_diff_throttle_ms))
    hz = float(spec.get("tick_hz") or 10)
    dt = 1.0 / hz
    duration = float(until_s if until_s is not None else spec.get("duration_s") or 60)
    summary = RunSummary(scenario_id)
    wall0 = time.monotonic()
    n = int(duration * hz)
    for i in range(n + 1):
        if stop is not None and stop.is_set():
            break
        t = i * dt
        frame = sim.step(t, dt)
        if isinstance(sink, RedisDbSink):
            sink.raw(pipe.machine_id, frame.model_dump_json(), maxlen=int(hz * 600))
        out = pipe.process(frame)
        _collect(summary, out)
        publisher.handle(out)
        for obs in observers or []:
            obs(frame, out)
        summary.ticks += 1
        if realtime:
            ahead = wall0 + t / speed - time.monotonic()
            if ahead > 0:
                time.sleep(ahead)
    closing = pipe.close(sim.start + timedelta(seconds=summary.ticks * dt))
    _collect(summary, closing)
    publisher.handle(closing)
    return summary


def _collect(summary: RunSummary, out: TickOutput) -> None:
    summary.alerts.extend(out.alerts)
    summary.behavior.extend(out.behavior)
    summary.clips.extend(out.clips)
    summary.advisories.extend(out.advisories)
    if out.state:
        summary.last_state = out.state


def run_pair(
    cfg: ConfigBundle,
    scenario_id: str,
    data_dir: Path | None = None,
    redis_url: str | None = None,
) -> dict[str, RunSummary]:
    """Two machines in lockstep over one P2P link (§10.4.3). The link is in-memory unless `redis_url` is given,
    so the pair demo runs without any broker."""
    from terrapilot.safety.p2p import P2PLink

    spec = scenario_spec(cfg, scenario_id)
    peer_spec = dict(spec.get("peer") or {})
    if not peer_spec:
        raise ValueError(f"scenario '{scenario_id}' has no peer machine")
    start = utcnow()
    link = P2PLink(cfg.app.p2p, str(spec["site"]), redis_url)
    runs = {}
    for name, sp in (("own", spec), ("peer", {**spec, **peer_spec, "expect": {}})):
        world = load_context(str(sp["machine"]), sp.get("task"), sp.get("operator"), data_dir)
        tick_hz = float(sp.get("tick_hz") or spec.get("tick_hz") or 10)
        sim = MachineSim(cfg, world, sp, seed=0, start=start)
        pipe = EdgePipeline(cfg, world, tick_hz, advisor=None, p2p_link=link, start_of_run=start)
        runs[name] = (sim, pipe, RunSummary(scenario_id), tick_hz)
    duration = float(spec.get("duration_s") or 60)
    hz = max(r[3] for r in runs.values())
    dt = 1.0 / hz
    for i in range(int(duration * hz) + 1):
        t = i * dt
        for _, (sim, pipe, summary, _hz) in runs.items():
            out = pipe.process(sim.step(t, dt))
            _collect(summary, out)
    return {name: summary for name, (_sim, _pipe, summary, _hz) in runs.items()}


def is_subsequence(expected: list[str], actual: list[str]) -> bool:
    it = iter(actual)
    return all(any(x == y for y in it) for x in expected)
