"""Cloud-side wiring for live scenarios: the model prior for live ETC and the streaming maintenance monitor.

The edge stays cloud-free: the prior is handed over as plain numbers in `world.extras`, and the monitor is an
observer callable the runner invokes after every tick.
"""

from __future__ import annotations

import contextlib
import math
from typing import Any

from terrapilot.core.config import ConfigBundle
from terrapilot.domain.ws import MaintenanceAlertMessage
from terrapilot.maintenance.monitor import LiveMaintenanceMonitor
from terrapilot.sim.world import WorldContext


def attach_task_prior(cfg: ConfigBundle, world: WorldContext) -> dict[str, Any] | None:
    """rate_per_min and the conformal log half-width from task_duration, for the edge's Bayesian ETC."""
    if not world.task:
        return None
    from terrapilot.planning.context import PlanningContext
    from terrapilot.planning.estimate import estimate_task

    try:
        ctx = PlanningContext(cfg, live_state=False)
        task = {**world.task, "status": "planned"}
        est = estimate_task(ctx, task, ctx.now)
    except Exception:  # no DB / untrained model → the edge falls back to the plan prior
        return None
    if est.source != "model" or est.estimate.p50 <= 0:
        return None
    e = est.estimate
    prior = {
        "rate_per_min": float(task["quantity"]) / e.p50,
        "log_half_width": (math.log(e.p90) - math.log(max(e.p10, 1e-6))) / 2,
    }
    world.extras["task_prior"] = prior
    return prior


def copilot_context(cfg: ConfigBundle, world: WorldContext, advisor: Any, sink: Any = None) -> None:
    """Cloud context for the live copilot's `energy` generator; guard events are persisted through the sink."""
    if advisor is None:
        return
    if sink is not None:
        advisor.on_guard = lambda row: sink.persist("guard_events", [row])
    if not world.task:
        return
    from terrapilot.planning.context import PlanningContext
    from terrapilot.planning.energy import energy_estimate

    try:
        ctx = PlanningContext(cfg, live_state=False)
        advisor.extras["energy"] = energy_estimate(ctx, dict(world.task), str(world.machine["id"]))
    except Exception:  # the copilot must start even when the planning stack is unavailable
        return


def maintenance_observer(
    cfg: ConfigBundle, world: WorldContext, spec: dict[str, Any], sink: Any, advisor: Any = None
) -> LiveMaintenanceMonitor:
    machine = world.machine
    machine_id = str(machine["id"])

    def on_change(row: dict[str, Any], change: str) -> None:
        if advisor is not None:  # service_soon alerts relevant now become copilot advisories (§12.1 rev 2)
            advisor.extras.setdefault("maintenance", {})[row["component"]] = row
        phase = "open" if change == "open" else "update"
        with contextlib.suppress(Exception):
            sink.publish(
                machine_id,
                [
                    MaintenanceAlertMessage(
                        ts=row["updated_at"],
                        machine_id=machine_id,
                        phase=phase,
                        alert_id=row["id"],
                        component=row["component"],
                        tier=row["tier"],
                    )
                ],
            )
        engine = getattr(sink, "engine", None)
        if engine is None:
            return
        from terrapilot.maintenance.service import upsert_alert

        try:
            with engine.connect() as conn:
                upsert_alert(conn, row)
                conn.commit()
        except Exception:
            return

    existing: dict[str, dict[str, Any]] = {}
    engine = getattr(sink, "engine", None)
    if engine is not None:
        from sqlalchemy import and_, select

        from terrapilot.db.schema import maintenance_alerts

        try:
            with engine.connect() as conn:
                rows = conn.execute(
                    select(maintenance_alerts)
                    .where(
                        and_(
                            maintenance_alerts.c.machine_id == machine_id,
                            maintenance_alerts.c.state.notin_(["false_alarm"]),
                        )
                    )
                    .order_by(maintenance_alerts.c.opened_at)
                ).mappings()
                existing = {r["component"]: dict(r) for r in rows}  # latest per component wins
        except Exception:
            existing = {}
    return LiveMaintenanceMonitor(
        cfg,
        machine_id,
        str(machine["manifest_id"]),
        str(machine.get("site_id")),
        str(machine.get("machine_class")),
        float(spec.get("time_scale") or 1.0),
        on_change=on_change,
        existing=existing,
    )
