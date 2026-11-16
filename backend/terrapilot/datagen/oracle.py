"""Start-time oracle (§7.4b): run the generator's causal task model under TRUE weather, ground and machine
state for any hypothetical start time. The optimiser (§10.14) is scored by counterfactual regret against it.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from terrapilot.core.config import ConfigBundle, get_config
from terrapilot.core.timeutil import local_midnight, parse_hhmm
from terrapilot.datagen.context import apply_scale
from terrapilot.datagen.execution import MachineView, OperatorView, TaskSpec, WorldView, execute_task
from terrapilot.datagen.weather import HourlyWeather


@dataclass
class OracleOutcome:
    start: datetime
    end: datetime
    duration_min: float
    completed: bool
    stoppage_min: float
    charge_stop_min: float
    wait_min: float


def _read(data_dir: Path, name: str) -> pd.DataFrame:
    return pd.read_parquet(data_dir / f"{name}.parquet")


class WorldState:
    """Truth needed by the oracle, loaded from a `tp gen` output directory."""

    def __init__(self, data_dir: Path, cfg: ConfigBundle | None = None):
        self.cfg = cfg or get_config()
        self.dir = data_dir
        self.manifest = json.loads((data_dir / "manifest.json").read_text(encoding="utf-8"))
        self.dg = dict(self.cfg.datagen)
        self.dg["world"] = apply_scale(self.dg["world"], self.manifest["scale"])
        self.dg["_soc_floor"] = float(self.cfg.app.energy["soc_floor"])
        wx = _read(data_dir, "truth_weather_hourly").sort_values("ts")
        self.weather = {
            s: HourlyWeather(
                g["ts"].iloc[0].to_pydatetime(),
                {c: g[c].to_numpy(dtype=float) for c in g.columns if c not in ("ts", "site_id")},
            )
            for s, g in wx.groupby("site_id")
        }
        gh = _read(data_dir, "truth_ground_hourly").sort_values("ts")
        self.moisture = {z: g["moisture"].to_numpy(dtype=float) for z, g in gh.groupby("zone_id")}
        self.zones = _read(data_dir, "zones").set_index("id")
        self.machines = _read(data_dir, "machines").set_index("id")
        self.tasks = _read(data_dir, "tasks").set_index("id")
        health = _read(data_dir, "truth_component_health")
        latest = health[health["date"] == health["date"].max()]
        self.health = {m: g.set_index("component")["health"].to_dict() for m, g in latest.groupby("machine_id")}
        self.traits = _read(data_dir, "truth_operator_traits").set_index("operator_id")
        self.chargers = _read(data_dir, "charging_stations")
        self.soc_now = {
            mid: float(s["soc"])
            for mid, s in (self.dg.get("demo_fixtures") or {}).get("machine_states_now", {}).items()
            if "soc" in s
        }

    def world_view(self, site_id: str, zone_id: str, machine_manifest: Any, start: datetime) -> WorldView:
        world = self.dg["world"]
        tz = world["timezone"]
        day = start.astimezone(local_midnight(start.date(), tz).tzinfo).date()
        shift_start = local_midnight(day, tz) + parse_hhmm(world["shift"]["start_local"])
        shift_end = shift_start + timedelta(hours=float(world["shift"]["length_h"]))
        breaks = [(shift_start + timedelta(hours=float(b["at_h"]))).timestamp() for b in world["shift"]["breaks"]]
        breaks_iv = [
            (b0, b0 + float(b["minutes"]) * 60) for b0, b in zip(breaks, world["shift"]["breaks"], strict=True)
        ]
        kinds = machine_manifest.energy.get("charge_power_kw_by_station", {})
        site_chargers = self.chargers[self.chargers["site_id"] == site_id]
        charger_kw = max((float(kinds.get(k, 0.0)) for k in site_chargers["kind"]), default=0.0)
        wx = self.weather[site_id]
        return WorldView(
            wx=wx,
            moisture=self.moisture[zone_id],
            trucks_missing=0,
            shift_start_s=shift_start.timestamp(),
            shift_end_s=shift_end.timestamp(),
            overtime_max_s=float(world["shift"]["overtime_max_h"]) * 3600,
            breaks=breaks_iv,
            charger_kw=charger_kw,
            t0_s=wx.t0.timestamp(),
        )


def simulate_task(
    task_id: str,
    start: datetime,
    world: WorldState,
    seed: int = 0,
    soc: float | None = None,
    operator_id: str | None = None,
) -> OracleOutcome:
    t = world.tasks.loc[task_id]
    machine_id = t["assigned_machine_id"]
    if machine_id is None or (isinstance(machine_id, float) and np.isnan(machine_id)):
        raise ValueError(f"task {task_id} has no assigned machine")
    mrow = world.machines.loc[machine_id]
    manifest = world.cfg.manifests[mrow["manifest_id"]]
    op_id = operator_id or t["assigned_operator_id"]
    tr = world.traits.loc[op_id]
    soil = world.zones.loc[t["zone_id"], "soil"]
    spec = TaskSpec(
        id=task_id,
        type=t["type"],
        machine_class=t["machine_class"],
        quantity=float(t["quantity"]),
        unit=t["unit"],
        soil=soil,
        depth_m=float(t["depth_m"]) if pd.notna(t["depth_m"]) else 0.0,
        haul_distance_m=float(t["haul_distance_m"]) if pd.notna(t["haul_distance_m"]) else 0.0,
        grade_pct=float(t["grade_pct"]) if pd.notna(t["grade_pct"]) else 0.0,
        planned_duration_s=(t["planned_end"] - t["planned_start"]).total_seconds(),
    )
    if manifest.powertrain == "electric":
        soc = (
            soc
            if soc is not None
            else world.soc_now.get(machine_id, float(world.dg["cycles"]["electric"]["overnight_target_soc"]))
        )
    mv = MachineView(manifest=manifest, health=world.health.get(machine_id, {}), soc=soc)
    opv = OperatorView(
        skill=float(tr["skill"]),
        idle_propensity=float(tr["idle_propensity"]),
        aggression=float(tr["aggression"]),
        fatigue_susceptibility=float(tr["fatigue_susceptibility"]),
    )
    wv = world.world_view(t["site_id"], t["zone_id"], manifest, start)
    rng = np.random.default_rng([seed, abs(hash(task_id)) % (2**31)])
    res = execute_task(spec, start.timestamp(), mv, opv, wv, world.dg, rng)
    return OracleOutcome(
        start=start,
        end=datetime.fromtimestamp(res.end_s, start.tzinfo),
        duration_min=round(res.duration_min, 2),
        completed=res.completed,
        stoppage_min=round(res.stoppage_s / 60, 2),
        charge_stop_min=round(res.charge_stop_s / 60, 2),
        wait_min=round(res.wait_s / 60, 2),
    )


def expected_duration(task_id: str, start: datetime, world: WorldState, samples: int = 20, **kw: Any) -> float:
    """Mean true duration over noise draws — the quantity regret is computed on."""
    return float(np.mean([simulate_task(task_id, start, world, seed=s, **kw).duration_min for s in range(samples)]))
