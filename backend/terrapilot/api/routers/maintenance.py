"""Maintenance alerts (§9.2 Maintenance, rev 2): list/detail, lifecycle actions, work orders, sensor forecasts."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, status
from pydantic import BaseModel
from sqlalchemy import and_, select, update

from terrapilot.api.deps import ConfigDep, CurrentUser, DbDep, Principal, api_error, require_roles
from terrapilot.api.routers.day import planning_ctx
from terrapilot.core import clock
from terrapilot.db.schema import machines, maintenance_alerts
from terrapilot.maintenance.fusion import enrich_row
from terrapilot.maintenance.service import create_work_order, scan, sensor_forecast_view, transition
from terrapilot.planning.context import invalidate_shared

router = APIRouter(tags=["maintenance"])
ACTIONS = {
    "ack": "acknowledged",
    "schedule": "scheduled",
    "start": "in_service",
    "resolve": "resolved",
    "false_alarm": "false_alarm",
}


@router.get("/api/maintenance/alerts")
def list_alerts(
    _: CurrentUser,
    cfg: ConfigDep,
    conn: DbDep,
    machine: str | None = None,
    site: str | None = None,
    tier: str | None = None,
    state: str = "active",
    limit: int = 200,
) -> list[dict[str, Any]]:
    q = select(maintenance_alerts, machines.c.site_id).join(machines, machines.c.id == maintenance_alerts.c.machine_id)
    conds = []
    if machine:
        conds.append(maintenance_alerts.c.machine_id == machine)
    if site:
        conds.append(machines.c.site_id == site)
    if tier:
        conds.append(maintenance_alerts.c.tier == tier)
    if state == "active":
        conds.append(maintenance_alerts.c.state.notin_(["resolved", "false_alarm"]))
    elif state != "all":
        conds.append(maintenance_alerts.c.state == state)
    if conds:
        q = q.where(and_(*conds))
    tiers = cfg.lifecycle.tiers
    rows = [dict(r) for r in conn.execute(q.limit(min(limit, 500))).mappings()]
    rows.sort(key=lambda r: (-tiers.index(r["tier"]) if r["tier"] in tiers else 0, str(r["opened_at"])))
    return [enrich_row(cfg, r) for r in rows]


@router.get("/api/maintenance/alerts/{alert_id}")
def get_alert(alert_id: str, _: CurrentUser, cfg: ConfigDep, conn: DbDep, at: str | None = None) -> dict[str, Any]:
    row = conn.execute(select(maintenance_alerts).where(maintenance_alerts.c.id == alert_id)).mappings().first()
    if row is None:
        raise api_error(status.HTTP_404_NOT_FOUND, "not_found")
    out = enrich_row(cfg, dict(row))
    ctx = planning_ctx(cfg, at)
    out["forecasts"] = []
    for sid in row["sensor_ids"] or []:
        try:
            out["forecasts"].append(sensor_forecast_view(ctx, row["machine_id"], sid))
        except KeyError:
            continue
    out["explanation"] = _explanation(cfg, conn, dict(row))
    return out


def _explanation(cfg: ConfigDep, conn: DbDep, row: dict[str, Any]) -> dict[str, Any]:
    """Cached plain-language explanation (§10.13): Groq when available, i18n template otherwise."""
    if row.get("explanation"):
        return dict(row["explanation"])
    from terrapilot.copilot.explainers import explain_maintenance_alert
    from terrapilot.copilot.guard_log import persist_guard

    excerpt = ""
    code = row.get("recommended_action_ref")
    entry = cfg.fault(code) if code else None
    if entry is not None:
        try:
            from terrapilot.copilot.knowledge import KnowledgeBase

            kb = KnowledgeBase.load(cfg)
            chunks = kb.by_procedure(entry.manual_ref.get("procedure_id", "")) or [
                h.chunk for h in kb.search(entry.description, None, 1)
            ]
            excerpt = chunks[0].text if chunks else ""
        except (FileNotFoundError, RuntimeError):
            excerpt = entry.description
    out = explain_maintenance_alert(cfg, row, excerpt, gateway=_gateway())
    for g in out.pop("guard_events", []):
        persist_guard(conn, g)
    conn.execute(update(maintenance_alerts).where(maintenance_alerts.c.id == row["id"]).values(explanation=out))
    conn.commit()
    return out


def _gateway() -> Any:
    from terrapilot.llm.gateway import get_gateway

    try:
        return get_gateway()
    except Exception:
        return None


class FeedbackIn(BaseModel):
    verdict: str  # false_alarm | confirmed


@router.post("/api/maintenance/alerts/{alert_id}/work-order", status_code=status.HTTP_201_CREATED)
def alert_work_order(alert_id: str, principal: CurrentUser, conn: DbDep) -> dict[str, Any]:
    """One tap: a service request pre-filled with the fault code and parts (§10.13)."""
    try:
        wo = create_work_order(conn, alert_id, principal.user_id, clock.now())
    except KeyError as exc:
        raise api_error(status.HTTP_404_NOT_FOUND, "not_found") from exc
    invalidate_shared()
    return wo


@router.post("/api/maintenance/alerts/{alert_id}/{action}")
def alert_action(alert_id: str, action: str, principal: CurrentUser, cfg: ConfigDep, conn: DbDep) -> dict[str, Any]:
    if action not in ACTIONS:
        raise api_error(status.HTTP_404_NOT_FOUND, "not_found")
    try:
        row = transition(conn, cfg, alert_id, ACTIONS[action], principal.user_id, clock.now())
    except KeyError as exc:
        raise api_error(status.HTTP_404_NOT_FOUND, "not_found") from exc
    except ValueError as exc:
        raise api_error(status.HTTP_409_CONFLICT, "invalid_transition") from exc
    invalidate_shared()
    return enrich_row(cfg, row)


@router.get("/api/machines/{machine_id}/sensors/{sensor_id}/forecast")
def sensor_forecast(
    machine_id: str, sensor_id: str, _: CurrentUser, cfg: ConfigDep, at: str | None = None
) -> dict[str, Any]:
    ctx = planning_ctx(cfg, at)
    if machine_id not in ctx.machines.index:
        raise api_error(status.HTTP_404_NOT_FOUND, "not_found")
    try:
        return sensor_forecast_view(ctx, machine_id, sensor_id)
    except KeyError as exc:
        raise api_error(status.HTTP_404_NOT_FOUND, "not_found") from exc


@router.post("/api/admin/maintenance/scan")
def maintenance_scan(
    cfg: ConfigDep,
    conn: DbDep,
    _: Principal = Depends(require_roles("admin", "supervisor", "technician")),
    at: str | None = None,
) -> dict[str, Any]:
    ctx = planning_ctx(cfg, at)
    ctx.live_state = False
    res = scan(ctx, conn)
    invalidate_shared()
    return res
