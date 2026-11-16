"""Live machine state, alerts, incidents + playback, and the admin scenario player (§9.2 Safety, Admin/demo)."""

from __future__ import annotations

import json
import threading
from typing import Any

from fastapi import APIRouter, Depends, status
from pydantic import BaseModel
from sqlalchemy import and_, select, update

from terrapilot.api.deps import ConfigDep, CurrentUser, DbDep, Principal, api_error, require_roles
from terrapilot.core.config import get_config
from terrapilot.core.expr import nest_dotted
from terrapilot.core.settings import get_settings
from terrapilot.core.timeutil import utcnow
from terrapilot.db.schema import alerts, blackbox_clips, incidents

router = APIRouter(tags=["live"])


def _redis() -> Any:
    import redis

    return redis.Redis.from_url(get_settings().redis_url, socket_timeout=0.5)


def live_snapshot(machine_id: str) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    try:
        r = _redis()
        state = json.loads(r.get(f"tp:state:{machine_id}") or "{}")
        open_alerts = json.loads(r.get(f"tp:alerts:{machine_id}") or "[]")
        return state, open_alerts
    except Exception:
        return {}, []


@router.get("/api/machines/{machine_id}/state")
def machine_state(machine_id: str, _: CurrentUser) -> dict[str, Any]:
    flat, open_alerts = live_snapshot(machine_id)
    return {"machine_id": machine_id, "live": bool(flat), "state": nest_dotted(flat), "alerts": open_alerts}


# ------------------------------------------------------------------ alerts
@router.get("/api/alerts")
def list_alerts(
    principal: CurrentUser, conn: DbDep, machine: str | None = None, state: str = "open", limit: int = 100
) -> list[dict[str, Any]]:
    q = select(alerts).order_by(alerts.c.opened_at.desc()).limit(min(limit, 500))
    conds = []
    if machine:
        conds.append(alerts.c.machine_id == machine)
    if state == "open":
        conds.append(alerts.c.cleared_at.is_(None))
    if conds:
        q = q.where(and_(*conds))
    return [dict(r) for r in conn.execute(q).mappings()]


@router.post("/api/alerts/{alert_id}/ack")
def ack_alert(alert_id: str, principal: CurrentUser, conn: DbDep) -> dict[str, Any]:
    res = conn.execute(update(alerts).where(alerts.c.id == alert_id).values(acked_by=principal.user_id))
    conn.commit()
    if res.rowcount == 0:
        raise api_error(status.HTTP_404_NOT_FOUND, "not_found")
    return {"id": alert_id, "acked_by": principal.user_id}


# ------------------------------------------------------------------ compliance & conditions (§9.2)
@router.get("/api/compliance/seatbelt")
def compliance_seatbelt(
    _: CurrentUser,
    conn: DbDep,
    scope: str = "site",
    site_id: str | None = None,
    operator_id: str | None = None,
    days: int = 7,
) -> dict[str, Any]:
    from terrapilot.db.schema import seatbelt_compliance_daily

    q = select(seatbelt_compliance_daily).order_by(seatbelt_compliance_daily.c.date.desc())
    conds = []
    if site_id:
        conds.append(seatbelt_compliance_daily.c.site_id == site_id)
    if operator_id:
        conds.append(seatbelt_compliance_daily.c.operator_id == operator_id)
    if conds:
        q = q.where(and_(*conds))
    rows = [dict(r) for r in conn.execute(q.limit(min(days * 20, 500))).mappings()]
    total_active = sum(float(r.get("active_seconds") or 0) for r in rows)
    total_unbelted = sum(float(r.get("unbelted_seconds") or 0) for r in rows)
    overall_pct = (1.0 - (total_unbelted / total_active)) if total_active > 0 else 1.0
    return {
        "scope": scope,
        "overall_compliance_pct": round(max(0.0, min(1.0, overall_pct)), 4),
        "total_active_seconds": total_active,
        "total_unbelted_seconds": total_unbelted,
        "records": rows[:days],
    }


@router.get("/api/compliance/ppe")
def compliance_ppe(
    _: CurrentUser,
    conn: DbDep,
    site_id: str | None = None,
    days: int = 7,
) -> dict[str, Any]:
    from terrapilot.db.schema import ppe_observations

    q = select(ppe_observations).order_by(ppe_observations.c.ts.desc())
    if site_id:
        q = q.where(ppe_observations.c.site_id == site_id)
    rows = [dict(r) for r in conn.execute(q.limit(min(days * 50, 500))).mappings()]
    compliant = sum(1 for r in rows if r.get("vest_ok") and r.get("hard_hat_ok"))
    pct = (compliant / len(rows)) if rows else 1.0
    return {
        "overall_compliance_pct": round(pct, 4),
        "total_observations": len(rows),
        "compliant_count": compliant,
        "observations": rows[:20],
    }


@router.get("/api/conditions/{site_id}")
def site_conditions(
    site_id: str,
    _: CurrentUser,
    cfg: ConfigDep,
) -> dict[str, Any]:
    from terrapilot.api.routers.day import planning_ctx
    from terrapilot.planning.start_time import _forecast_frame

    ctx = planning_ctx(cfg)
    fc = _forecast_frame(ctx, site_id)
    now_row = fc.iloc[0].to_dict() if not fc.empty else {}
    moisture = 0.15
    try:
        from terrapilot.planning.extras import _zone_moisture

        moisture = _zone_moisture(ctx, site_id)
    except Exception:
        pass
    ground_risk = min(1.0, max(0.0, moisture * 1.5 + float(now_row.get("rain_mm", 0) or 0) * 0.05))
    active_rules = []
    gust = float(now_row.get("gust_ms", 0) or 0)
    for rule in cfg.condition_rules:
        if "wind" in rule.id.lower() and gust > 15:
            active_rules.append({"id": rule.id, "severity": rule.severity, "message_key": rule.message_key})
    return {
        "site_id": site_id,
        "weather": {
            "temp_c": now_row.get("temp_c", 22),
            "rain_mm": now_row.get("rain_mm", 0),
            "gust_ms": gust,
            "visibility_m": now_row.get("visibility_m", 10000),
            "lightning_km": now_row.get("lightning_km", None),
        },
        "ground": {
            "moisture": round(moisture, 3),
            "ground_risk_score": round(ground_risk, 3),
        },
        "active_condition_rules": active_rules,
    }


# ------------------------------------------------------------------ incidents
class IncidentIn(BaseModel):
    kind: str
    severity: str
    description: str
    location: str | None = None
    machine_id: str | None = None


class IncidentPatch(BaseModel):
    status: str
    root_cause: str | None = None


@router.get("/api/incidents")
def list_incidents(
    principal: CurrentUser, conn: DbDep, machine: str | None = None, status_: str | None = None, limit: int = 50
) -> list[dict[str, Any]]:
    q = select(incidents).order_by(incidents.c.occurred_at.desc()).limit(min(limit, 200))
    if machine:
        q = q.where(incidents.c.machine_id == machine)
    if principal.role == "operator":
        q = q.where(incidents.c.operator_id == principal.user_id)
    if status_:
        q = q.where(incidents.c.status == status_)
    return [dict(r) for r in conn.execute(q).mappings()]


@router.post("/api/incidents", status_code=status.HTTP_201_CREATED)
def create_incident(body: IncidentIn, principal: CurrentUser, cfg: ConfigDep, conn: DbDep) -> dict[str, Any]:
    form = cfg.forms["incident_report"]
    allowed = {o["const"] for o in form.schema_["properties"]["kind"]["oneOf"]}
    if body.kind not in allowed:
        raise api_error(status.HTTP_422_UNPROCESSABLE_ENTITY, "not_found")
    workflow = form.workflow_states or ["new"]
    now = utcnow()
    row = {
        "id": f"IN-M-{principal.user_id}-{int(now.timestamp())}",
        "machine_id": body.machine_id,
        "operator_id": principal.user_id,
        "site_id": principal.site_id,
        "kind": body.kind,
        "severity": body.severity,
        "source": "manual",
        "occurred_at": now,
        "location": json.dumps({"text": body.location}),
        "description": body.description,
        "root_cause": None,
        "blackbox_clip_id": None,
        "status": workflow[0],
        "reviewer_id": None,
    }
    conn.execute(incidents.insert().values(**row))
    conn.commit()
    return row


@router.patch("/api/incidents/{incident_id}")
def update_incident(
    incident_id: str,
    body: IncidentPatch,
    cfg: ConfigDep,
    conn: DbDep,
    principal: Principal = Depends(require_roles("supervisor", "admin")),
) -> dict[str, Any]:
    workflow = cfg.forms["incident_report"].workflow_states or []
    row = conn.execute(select(incidents).where(incidents.c.id == incident_id)).mappings().first()
    if row is None:
        raise api_error(status.HTTP_404_NOT_FOUND, "not_found")
    current = workflow.index(row["status"]) if row["status"] in workflow else 0
    if body.status not in workflow or workflow.index(body.status) < current:  # workflow only moves forward
        raise api_error(status.HTTP_422_UNPROCESSABLE_ENTITY, "forbidden")
    values: dict[str, Any] = {"status": body.status, "reviewer_id": principal.user_id}
    if body.root_cause:
        values["root_cause"] = body.root_cause
    conn.execute(update(incidents).where(incidents.c.id == incident_id).values(**values))
    conn.commit()
    return {**dict(row), **values}


@router.get("/api/incidents/{incident_id}/playback")
def incident_playback(incident_id: str, principal: CurrentUser, conn: DbDep) -> dict[str, Any]:
    inc = conn.execute(select(incidents).where(incidents.c.id == incident_id)).mappings().first()
    if inc is None or not inc["blackbox_clip_id"]:
        raise api_error(status.HTTP_404_NOT_FOUND, "not_found")
    clip = conn.execute(select(blackbox_clips).where(blackbox_clips.c.id == inc["blackbox_clip_id"])).mappings().first()
    frames: list[dict[str, Any]] = []
    if clip and clip["frames_uri"]:
        path = get_settings().data_dir / clip["frames_uri"]
        if path.is_file():
            frames = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    window: list[dict[str, Any]] = []
    if clip:
        window = [
            dict(r)
            for r in conn.execute(
                select(alerts).where(
                    and_(
                        alerts.c.machine_id == inc["machine_id"],
                        alerts.c.opened_at >= clip["t0"] - _td(clip["pre_s"]),
                        alerts.c.opened_at <= clip["t0"] + _td(clip["post_s"]),
                    )
                )
            ).mappings()
        ]
    return {
        "incident": dict(inc),
        "clip": dict(clip) if clip else None,
        "frames": frames,
        "markers": [{"ts": a["opened_at"], "rule_id": a["rule_id"], "severity": a["severity"]} for a in window],
        "workflow": get_config().forms["incident_report"].workflow_states or [],
    }


def _td(seconds: float | None) -> Any:
    from datetime import timedelta

    return timedelta(seconds=float(seconds or 0))


# ------------------------------------------------------------------ admin: scenario player
class _ScenarioManager:
    def __init__(self) -> None:
        self.runs: dict[str, tuple[threading.Thread, threading.Event]] = {}
        self.lock = threading.Lock()

    def start(self, scenario_id: str, speed: float) -> None:
        from terrapilot.edge.runner import run_scenario
        from terrapilot.edge.sinks import RedisDbSink

        cfg = get_config()
        settings = get_settings()
        with self.lock:
            if scenario_id in self.runs and self.runs[scenario_id][0].is_alive():
                return
            stop = threading.Event()
            sink = RedisDbSink(settings.redis_url, settings.database_url)
            advisor = _advisor_factory(cfg, scenario_id)
            from terrapilot.edge.runner import scenario_spec
            from terrapilot.planning.scenario_hooks import attach_task_prior, copilot_context, maintenance_observer
            from terrapilot.sim.world import load_context

            spec = scenario_spec(cfg, scenario_id)
            world = load_context(spec["machine"], spec.get("task"), spec.get("operator"))
            attach_task_prior(cfg, world)
            copilot_context(cfg, world, advisor, sink)
            monitor = maintenance_observer(cfg, world, spec, sink, advisor)
            th = threading.Thread(
                target=run_scenario,
                name=f"scenario-{scenario_id}",
                daemon=True,
                kwargs={
                    "cfg": cfg,
                    "scenario_id": scenario_id,
                    "sink": sink,
                    "realtime": True,
                    "speed": speed,
                    "stop": stop,
                    "blackbox_dir": settings.data_dir / "blackbox",
                    "advisor": advisor,
                    "world": world,
                    "observers": [monitor],
                },
            )
            th.start()
            self.runs[scenario_id] = (th, stop)

    def stop(self, scenario_id: str) -> None:
        with self.lock:
            run = self.runs.get(scenario_id)
            if run:
                run[1].set()

    def status(self) -> dict[str, bool]:
        return {k: v[0].is_alive() for k, v in self.runs.items()}


def _advisor_factory(cfg: Any, scenario_id: str) -> Any:
    """Live copilot hook (Phase 3A). Returns None until the copilot package is present."""
    try:
        from terrapilot.copilot.live import make_advisor
    except ImportError:
        return None
    return make_advisor(cfg, cfg.scenarios[scenario_id].machine)


scenarios = _ScenarioManager()


@router.get("/api/admin/scenarios")
def list_scenarios(
    cfg: ConfigDep, _: Principal = Depends(require_roles("admin", "supervisor"))
) -> list[dict[str, Any]]:
    running = scenarios.status()
    return [
        {"id": sid, "machine": sc.machine, "duration_s": sc.duration_s, "running": running.get(sid, False)}
        for sid, sc in cfg.scenarios.items()
        if sc.duration_s
    ]


@router.post("/api/admin/scenarios/{scenario_id}/start")
def start_scenario(
    scenario_id: str, cfg: ConfigDep, speed: float = 1.0, _: Principal = Depends(require_roles("admin", "supervisor"))
) -> dict[str, Any]:
    if scenario_id not in cfg.scenarios:
        raise api_error(status.HTTP_404_NOT_FOUND, "not_found")
    scenarios.start(scenario_id, speed)
    return {"id": scenario_id, "running": True, "machine": cfg.scenarios[scenario_id].machine}


@router.post("/api/admin/scenarios/{scenario_id}/stop")
def stop_scenario(scenario_id: str, _: Principal = Depends(require_roles("admin", "supervisor"))) -> dict[str, Any]:
    scenarios.stop(scenario_id)
    return {"id": scenario_id, "running": False}


@router.post("/api/machines/{machine_id}/demo")
def auto_start_demo(machine_id: str, cfg: ConfigDep, _: Principal = Depends(require_roles("operator", "admin", "supervisor"))) -> dict[str, Any]:
    """Auto-start the first available scenario for the given machine (§18 demo convenience).

    Any authenticated user may start a demo for their machine so cockpit widgets receive live data.
    """
    running = scenarios.status()
    for sid, sc in cfg.scenarios.items():
        if sc.machine == machine_id and sc.duration_s:
            if running.get(sid, False):
                return {"id": sid, "running": True, "machine": machine_id, "action": "already_running"}
            scenarios.start(sid, speed=1.0)
            return {"id": sid, "running": True, "machine": machine_id, "action": "started"}
    return {"id": None, "running": False, "machine": machine_id, "action": "no_scenario"}
