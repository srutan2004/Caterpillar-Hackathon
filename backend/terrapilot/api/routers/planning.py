"""Planning & estimation (§9.2 rev 2): start-time recommendation + accept, readiness, energy, service due."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from fastapi import APIRouter, status
from sqlalchemy import insert, select, update

from terrapilot.api.deps import ConfigDep, CurrentUser, DbDep, api_error
from terrapilot.api.routers.day import planning_ctx
from terrapilot.db.schema import charger_reservations, maintenance_alerts, start_recommendations, tasks
from terrapilot.planning.context import invalidate_shared
from terrapilot.planning.energy import energy_estimate
from terrapilot.planning.estimate import estimate_task
from terrapilot.planning.readiness import readiness
from terrapilot.planning.service_due import service_due
from terrapilot.planning.shift import cached_recommendation

router = APIRouter(tags=["planning"])


@router.get("/api/tasks/{task_id}/start-recommendation")
def start_recommendation(
    task_id: str, _: CurrentUser, cfg: ConfigDep, conn: DbDep, at: str | None = None, refresh: bool = False
) -> dict[str, Any]:
    ctx = planning_ctx(cfg, at)
    try:
        return cached_recommendation(ctx, conn, task_id, force=refresh)
    except KeyError as exc:
        raise api_error(status.HTTP_404_NOT_FOUND, "not_found") from exc
    except ValueError as exc:
        raise api_error(status.HTTP_422_UNPROCESSABLE_ENTITY, "task_unassigned") from exc


@router.post("/api/tasks/{task_id}/start-recommendation/accept")
def accept_recommendation(
    task_id: str, principal: CurrentUser, cfg: ConfigDep, conn: DbDep, at: str | None = None
) -> dict[str, Any]:
    """Moves the task's planned start, reserves the charger for a charge precondition and schedules the
    maintenance checks the recommendation asked for."""
    ctx = planning_ctx(cfg, at)
    try:
        rec = cached_recommendation(ctx, conn, task_id)
    except KeyError as exc:
        raise api_error(status.HTTP_404_NOT_FOUND, "not_found") from exc
    start = datetime.fromisoformat(rec["recommended_start"])
    task = ctx.task(task_id)
    duration = datetime.fromisoformat(rec["duration"]["finish_p50"]) - start
    conn.execute(update(tasks).where(tasks.c.id == task_id).values(planned_start=start, planned_end=start + duration))
    reserved, scheduled = [], []
    for p in rec["preconditions"]:
        if p["kind"] == "charge":
            rid = f"CR-{task_id}-{int(ctx.now.timestamp())}"
            exists = conn.execute(select(charger_reservations.c.id).where(charger_reservations.c.id == rid)).first()
            if not exists:
                conn.execute(
                    insert(charger_reservations).values(
                        id=rid,
                        station_id=p["station_id"],
                        machine_id=task["assigned_machine_id"],
                        task_id=task_id,
                        start=datetime.fromisoformat(p["start"]),
                        end=datetime.fromisoformat(p["end"]),
                        target_soc=p["target_soc"],
                        source="start_recommendation",
                        status="reserved",
                    )
                )
            reserved.append(
                {
                    "id": rid,
                    "station_id": p["station_id"],
                    "start": p["start"],
                    "end": p["end"],
                    "target_soc": p["target_soc"],
                }
            )
        elif p["kind"] == "maintenance_check":
            row = conn.execute(
                select(maintenance_alerts.c.state).where(maintenance_alerts.c.id == p["alert_id"])
            ).first()
            if row and row[0] in ("open", "acknowledged"):
                conn.execute(
                    update(maintenance_alerts)
                    .where(maintenance_alerts.c.id == p["alert_id"])
                    .values(state="scheduled", updated_at=ctx.now)
                )
            scheduled.append({"alert_id": p["alert_id"], "technician_slot": p.get("technician_slot")})
    conn.execute(
        update(start_recommendations)
        .where(start_recommendations.c.id == rec["id"])
        .values(accepted_by=principal.user_id, accepted_at=ctx.now)
    )
    conn.commit()
    invalidate_shared()
    return {
        "task_id": task_id,
        "planned_start": start.isoformat(),
        "charger_reservations": reserved,
        "maintenance_scheduled": scheduled,
    }


@router.get("/api/machines/{machine_id}/readiness")
def machine_readiness(
    machine_id: str,
    _: CurrentUser,
    cfg: ConfigDep,
    operator: str | None = None,
    task: str | None = None,
    at: str | None = None,
) -> dict[str, Any]:
    ctx = planning_ctx(cfg, at)
    if machine_id not in ctx.machines.index:
        raise api_error(status.HTTP_404_NOT_FOUND, "not_found")
    next_task = ctx.task(task) if task else None
    return readiness(ctx, machine_id, operator, next_task)


@router.get("/api/tasks/{task_id}/energy-estimate")
def task_energy(task_id: str, _: CurrentUser, cfg: ConfigDep, at: str | None = None) -> dict[str, Any]:
    ctx = planning_ctx(cfg, at)
    try:
        task = ctx.task(task_id)
    except KeyError as exc:
        raise api_error(status.HTTP_404_NOT_FOUND, "not_found") from exc
    if not task.get("assigned_machine_id"):
        raise api_error(status.HTTP_422_UNPROCESSABLE_ENTITY, "task_unassigned")
    est = estimate_task(ctx, task).estimate.as_dict()
    return energy_estimate(ctx, task, task["assigned_machine_id"], est)


@router.get("/api/machines/{machine_id}/service-due")
def machine_service_due(machine_id: str, _: CurrentUser, cfg: ConfigDep, at: str | None = None) -> list[dict[str, Any]]:
    ctx = planning_ctx(cfg, at)
    if machine_id not in ctx.machines.index:
        raise api_error(status.HTTP_404_NOT_FOUND, "not_found")
    return service_due(ctx, machine_id)
