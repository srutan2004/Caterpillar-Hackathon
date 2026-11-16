"""Advanced maintenance, energy and planning endpoints (§9.2 rev 2 Maintenance / Planning / Energy)."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, status
from pydantic import BaseModel

from terrapilot.api.deps import ConfigDep, CurrentUser, DbDep, api_error
from terrapilot.api.routers.day import planning_ctx
from terrapilot.db.schema import fault_codes, fluid_samples, service_requests
from terrapilot.maintenance.advanced import health_index, risk_index, rul_estimate
from terrapilot.maintenance.repair import estimate as repair_estimate
from terrapilot.maintenance.windows import availability_forecast, plan_windows
from terrapilot.planning.extras import machine_options, task_cost_estimate, weather_windows
from terrapilot.planning.milp import charge_plan, day_plan, power_mode

router = APIRouter(tags=["fleet"])


# ------------------------------------------------------------------ machine health (§10.7.1)
@router.get("/api/machines/{machine_id}/health")
def machine_health(machine_id: str, _: CurrentUser, cfg: ConfigDep, at: str | None = None) -> dict[str, Any]:
    from terrapilot.maintenance.service import machine_evidence

    ctx = planning_ctx(cfg, at)
    if machine_id not in ctx.machines.index:
        raise api_error(status.HTTP_404_NOT_FOUND, "not_found")
    items, curves = machine_evidence(ctx, machine_id)
    component_of = {i.sensor_id: i.component for i in items if i.sensor_id}
    components = sorted(
        {i.component for i in items}
        | {str(k) for k in ctx.t.get("components").query("machine_id == @machine_id")["kind"]}
    )
    out: list[dict[str, Any]] = []
    for c in components:
        out.append(
            {
                "component": c,
                "health_index": health_index(cfg, items, c),
                "risk": risk_index(cfg, machine_id, c, ctx.t, ctx.now),
                "rul": rul_estimate(curves, component_of, c),
                "evidence": [
                    {"layer": i.layer, "tier": i.tier, "sensor_id": i.sensor_id} for i in items if i.component == c
                ],
            }
        )
    out.sort(key=lambda r: (float(r["health_index"]), -float(r["risk"]["p_fail"])))
    return {"machine_id": machine_id, "components": out}


@router.get("/api/faults/{code}")
def fault_lookup(code: str, _: CurrentUser, cfg: ConfigDep, conn: DbDep) -> dict[str, Any]:
    """Structured lookup (§10.7.2): catalogue row → manual chunks → safe-to-continue → parts."""
    entry = cfg.fault(code)
    if entry is None:
        raise api_error(status.HTTP_404_NOT_FOUND, "not_found")
    chunks: list[dict[str, Any]] = []
    try:
        from terrapilot.copilot.knowledge import KnowledgeBase

        kb = KnowledgeBase.load(cfg)
        found = kb.by_procedure(entry.manual_ref.get("procedure_id", "")) or [
            h.chunk for h in kb.search(entry.description, None, 2)
        ]
        chunks = [{"chunk_id": c.id, "heading": c.heading, "section": c.section, "text": c.text[:1500]} for c in found]
    except (FileNotFoundError, RuntimeError):
        chunks = []
    row = conn.execute(fault_codes.select().where(fault_codes.c.code == code)).mappings().first()
    parts = [
        {
            "part_no": p.part_no,
            "description": p.description,
            "price": p.price,
            "stock": p.stock,
            "lead_time_days": p.lead_time_days,
        }
        for p in cfg.parts
        if p.part_no in entry.part_numbers
    ]
    return {**entry.model_dump(), "manual_chunks": chunks, "parts": parts, "catalogue_row": dict(row) if row else None}


@router.get("/api/fluid-samples")
def list_fluid_samples(
    _: CurrentUser, conn: DbDep, machine: str | None = None, limit: int = 50
) -> list[dict[str, Any]]:
    q = fluid_samples.select().order_by(fluid_samples.c.ts.desc()).limit(min(limit, 200))
    if machine:
        q = q.where(fluid_samples.c.machine_id == machine)
    return [dict(r) for r in conn.execute(q).mappings()]


class ServiceRequestIn(BaseModel):
    machine_id: str
    kind: str = "service"
    fault_code: str | None = None
    part_nos: list[str] = []
    note: str | None = None


@router.post("/api/service-requests", status_code=status.HTTP_201_CREATED)
def create_service_request(body: ServiceRequestIn, principal: CurrentUser, conn: DbDep) -> dict[str, Any]:
    import uuid

    row = {
        "id": f"SR-{uuid.uuid4().hex[:12]}",
        "machine_id": body.machine_id,
        "requested_by": principal.user_id,
        "kind": body.kind,
        "fault_code": body.fault_code,
        "part_nos": body.part_nos,
        "diagnosis_ref": body.note,
        "status": "open",
        "eta": None,
    }
    conn.execute(service_requests.insert().values(**row))
    conn.commit()
    return row


@router.get("/api/maintenance/estimate")
def maintenance_estimate(
    _: CurrentUser, cfg: ConfigDep, component: str, machine: str, work_type: str = "minor", parts: str | None = None
) -> dict[str, Any]:
    ctx = planning_ctx(cfg)
    return repair_estimate(cfg, ctx.t, component, work_type, machine, (parts or "").split(",") if parts else [])


@router.get("/api/maintenance/windows")
def maintenance_windows(
    _: CurrentUser, cfg: ConfigDep, machine: str | None = None, at: str | None = None
) -> list[dict[str, Any]]:
    ctx = planning_ctx(cfg, at)
    return plan_windows(ctx, [machine] if machine else None)


@router.get("/api/fleet/availability")
def fleet_availability(
    _: CurrentUser, cfg: ConfigDep, site: str | None = None, days: int = 7, at: str | None = None
) -> list[dict[str, Any]]:
    return availability_forecast(planning_ctx(cfg, at), site, min(days, 14))


# ------------------------------------------------------------------ planning extras
@router.get("/api/planning/weather-windows")
def planning_weather_windows(
    _: CurrentUser, cfg: ConfigDep, site: str, task_type: str, hours: int = 36, at: str | None = None
) -> dict[str, Any]:
    return weather_windows(planning_ctx(cfg, at), site, task_type, hours)


@router.get("/api/tasks/{task_id}/cost-estimate")
def task_cost(
    task_id: str, _: CurrentUser, cfg: ConfigDep, machine: str | None = None, at: str | None = None
) -> dict[str, Any]:
    ctx = planning_ctx(cfg, at)
    try:
        task = ctx.task(task_id)
    except KeyError as exc:
        raise api_error(status.HTTP_404_NOT_FOUND, "not_found") from exc
    mid = machine or task.get("assigned_machine_id")
    if not mid:
        raise api_error(status.HTTP_422_UNPROCESSABLE_ENTITY, "task_unassigned")
    return task_cost_estimate(ctx, task, str(mid))


@router.get("/api/tasks/{task_id}/machine-options")
def task_machine_options(task_id: str, _: CurrentUser, cfg: ConfigDep, at: str | None = None) -> dict[str, Any]:
    ctx = planning_ctx(cfg, at)
    try:
        return machine_options(ctx, task_id)
    except KeyError as exc:
        raise api_error(status.HTTP_404_NOT_FOUND, "not_found") from exc


class DayPlanIn(BaseModel):
    site_id: str
    date: str | None = None


@router.post("/api/planning/day-plan")
def planning_day_plan(body: DayPlanIn, _: CurrentUser, cfg: ConfigDep, at: str | None = None) -> dict[str, Any]:
    return day_plan(planning_ctx(cfg, at), body.site_id, body.date)


# ------------------------------------------------------------------ energy
@router.get("/api/machines/{machine_id}/energy")
def machine_energy(machine_id: str, _: CurrentUser, cfg: ConfigDep, at: str | None = None) -> dict[str, Any]:
    ctx = planning_ctx(cfg, at)
    if machine_id not in ctx.machines.index:
        raise api_error(status.HTTP_404_NOT_FOUND, "not_found")
    return {"machine_id": machine_id, **ctx.energy_state(machine_id), "power_mode": power_mode(ctx, machine_id)}


class ChargePlanIn(BaseModel):
    site_id: str
    horizon_h: float | None = None


@router.post("/api/energy/charge-plan")
def energy_charge_plan(body: ChargePlanIn, _: CurrentUser, cfg: ConfigDep, at: str | None = None) -> dict[str, Any]:
    return charge_plan(planning_ctx(cfg, at), body.site_id, body.horizon_h)


@router.get("/api/energy/power-mode/{machine_id}")
def energy_power_mode(machine_id: str, _: CurrentUser, cfg: ConfigDep) -> dict[str, Any]:
    return power_mode(planning_ctx(cfg), machine_id)
