"""Fleet (§7.3): machines with signed QR tokens, components with latent health state."""

from __future__ import annotations

import hashlib
import hmac
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

import numpy as np
import pandas as pd

from terrapilot.core.config_schema import Manifest
from terrapilot.datagen.context import GenContext


@dataclass
class MachineRt:
    """Mutable runtime state while the history is simulated."""

    id: str
    manifest: Manifest
    site_id: str
    hour_meter: float
    eff_age_h: dict[str, float]  # Weibull effective age τ per component (h = 1 − λ(τ/η)^β)
    faults_open: set[str] = field(default_factory=set)
    down_until: datetime | None = None
    soc: float | None = None
    fuel_l: float | None = None
    service_last_h: dict[str, float] = field(default_factory=dict)
    activity: list[tuple[float, float, int]] = field(default_factory=list)  # (t_start_s, t_end_s, state)
    soc_points: list[tuple[float, float]] = field(default_factory=list)
    primary_operator: str | None = None

    @property
    def cls(self) -> str:
        return self.manifest.class_

    @property
    def powertrain(self) -> str:
        return self.manifest.powertrain


STATE_OFF, STATE_IDLE, STATE_WORK, STATE_CHARGE = 0, 1, 2, 3


def plan_fleet(ctx: GenContext) -> None:
    """Decide machine ids and sites first (people generation needs them)."""
    plan: list[tuple[str, str, str, str]] = []
    counters: dict[str, int] = {}
    for entry in ctx.world["fleet"]:
        manifest = ctx.cfg.manifests[entry["manifest"]]
        for site, count in entry["sites"].items():
            for _ in range(int(count)):
                counters[manifest.id_prefix] = counters.get(manifest.id_prefix, 0) + 1
                plan.append(
                    (f"{manifest.id_prefix}-{counters[manifest.id_prefix]:02d}", manifest.id, manifest.class_, site)
                )
    # demo pins: move a machine to its pinned site by swapping with a same-manifest machine there
    for mid, site in (ctx.dg.get("demo_fixtures") or {}).get("machine_sites", {}).items():
        idx = next((i for i, p in enumerate(plan) if p[0] == mid), None)
        if idx is None or plan[idx][3] == site:
            continue
        swap = next((i for i, p in enumerate(plan) if p[1] == plan[idx][1] and p[3] == site and p[0] != mid), None)
        if swap is not None:
            a, b = plan[idx], plan[swap]
            plan[idx], plan[swap] = (a[0], a[1], a[2], b[3]), (b[0], b[1], b[2], a[3])
        else:
            plan[idx] = (plan[idx][0], plan[idx][1], plan[idx][2], site)
    ctx.state["machine_plan"] = plan


def qr_token(machine_id: str, seed: int) -> str:
    sig = hmac.new(f"tp-qr-{seed}".encode(), machine_id.encode(), hashlib.sha256).hexdigest()[:16]
    return f"tp1.{machine_id}.{sig}"


def health(ctx: GenContext, comp: str, eff_age_h: float) -> float:
    c = ctx.dg["degradation"]["components"][comp]
    return float(np.clip(1 - c["lambda"] * (eff_age_h / c["eta_h"]) ** c["beta"], 0.0, 1.0))


def age_for_health(ctx: GenContext, comp: str, h: float) -> float:
    c = ctx.dg["degradation"]["components"][comp]
    return float(c["eta_h"] * (max(0.0, 1 - h) / c["lambda"]) ** (1 / c["beta"]))


def generate_fleet(ctx: GenContext) -> None:
    rng = ctx.rng("fleet")
    hours_cfg = ctx.world["machine_hours_initial"]
    age_cfg = ctx.dg["degradation"]["initial_age_fraction"]
    start = ctx.shift_start(ctx.first_day)
    machines, components = [], []
    runtime: dict[str, MachineRt] = {}
    intervals = ctx.cfg.service_intervals
    for mid, manifest_id, cls, site in ctx.state["machine_plan"]:
        manifest = ctx.cfg.manifests[manifest_id]
        hours = float(rng.uniform(hours_cfg["min"], hours_cfg["max"]))
        eff = {}
        for comp in manifest.components:
            eta = ctx.dg["degradation"]["components"][comp]["eta_h"]
            eff[comp] = float(rng.uniform(age_cfg["min"], age_cfg["max"]) * eta)
            components.append(
                {
                    "id": f"{mid}-{comp}",
                    "machine_id": mid,
                    "kind": comp,
                    "installed_at": start - timedelta(hours=eff[comp] * 2.8),
                    "hours": round(eff[comp], 1),
                }
            )
        service_last = {}
        for item in intervals.get(manifest_id, []):
            service_last[item["item"]] = hours - float(rng.uniform(0, item["every_h"]))
        ctx.state.setdefault("service_initial", {}).update({(mid, k): v for k, v in service_last.items()})
        rt = MachineRt(
            id=mid, manifest=manifest, site_id=site, hour_meter=hours, eff_age_h=eff, service_last_h=dict(service_last)
        )
        if manifest.powertrain == "electric":
            rt.soc = 0.9
        else:
            rt.fuel_l = float(manifest.energy.get("tank_l", 400)) * 0.8
        runtime[mid] = rt
        machines.append(
            {
                "id": mid,
                "site_id": site,
                "manifest_id": manifest_id,
                "machine_class": cls,
                "serial": f"{manifest.id_prefix}{int(rng.integers(10000, 99999))}",
                "qr_token": qr_token(mid, ctx.seed),
                "hour_meter": round(hours, 1),
                "powertrain": manifest.powertrain,
                "status": "available",
                "commissioned_at": start - timedelta(days=float(hours / 8)),
            }
        )
    ctx.state["machines"] = runtime
    ctx.state["machine_rows"] = machines
    ctx.emit("components", pd.DataFrame(components))


def finalize_machines(ctx: GenContext) -> None:
    """Hour meters and status reflect the end of the simulated history."""
    rows: list[dict[str, Any]] = []
    for row in ctx.state["machine_rows"]:
        rt: MachineRt = ctx.state["machines"][row["id"]]
        status = "maintenance" if rt.down_until and rt.down_until > ctx.now else "available"
        rows.append(row | {"hour_meter": round(rt.hour_meter, 1), "status": status})
    ctx.emit("machines", pd.DataFrame(rows))
