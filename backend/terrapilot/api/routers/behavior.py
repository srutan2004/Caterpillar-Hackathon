"""Behaviour (§9.2 Behaviour): events, operator scorecard, idle summary, unusual cycles."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

import pandas as pd
from fastapi import APIRouter, status
from sqlalchemy import and_, select

from terrapilot.analytics.anomaly import load_anomalies
from terrapilot.analytics.behavior import idle_summary, scorecard
from terrapilot.api.deps import ConfigDep, CurrentUser, DbDep, api_error
from terrapilot.api.routers.day import planning_ctx
from terrapilot.db.schema import behavior_events

router = APIRouter(tags=["behavior"])


@router.get("/api/behavior/events")
def events(
    principal: CurrentUser,
    cfg: ConfigDep,
    conn: DbDep,
    operator: str | None = None,
    kind: str | None = None,
    days: int = 7,
    limit: int = 200,
    at: str | None = None,
) -> list[dict[str, Any]]:
    if principal.role == "operator" and operator not in (None, principal.user_id):
        raise api_error(status.HTTP_403_FORBIDDEN, "forbidden")
    op = operator or (principal.user_id if principal.role == "operator" else None)
    ctx = planning_ctx(cfg, at)
    conds = [behavior_events.c.start_ts >= ctx.now - timedelta(days=days)]
    if op:
        conds.append(behavior_events.c.operator_id == op)
    if kind:
        conds.append(behavior_events.c.kind == kind)
    q = select(behavior_events).where(and_(*conds)).order_by(behavior_events.c.start_ts.desc()).limit(min(limit, 1000))
    return [dict(r) for r in conn.execute(q).mappings()]


@router.get("/api/behavior/scorecard/{operator_id}")
def operator_scorecard(
    operator_id: str, principal: CurrentUser, cfg: ConfigDep, days: int = 30, at: str | None = None
) -> dict[str, Any]:
    if principal.role == "operator" and operator_id != principal.user_id:
        raise api_error(status.HTTP_403_FORBIDDEN, "forbidden")
    ctx = planning_ctx(cfg, at)
    return scorecard(cfg, ctx.t, operator_id, ctx.now, days)


@router.get("/api/behavior/idle-summary")
def behavior_idle_summary(
    _: CurrentUser, cfg: ConfigDep, site: str | None = None, days: int = 7, at: str | None = None
) -> dict[str, Any]:
    ctx = planning_ctx(cfg, at)
    return idle_summary(cfg, ctx.t, ctx.now, days, site)


@router.get("/api/behavior/anomalies")
def anomalies(
    _: CurrentUser, cfg: ConfigDep, operator: str | None = None, machine: str | None = None, limit: int = 100
) -> list[dict[str, Any]]:
    df = load_anomalies(cfg)
    if df.empty:
        return []
    if operator:
        df = df[df["operator_id"] == operator]
    if machine:
        df = df[df["machine_id"] == machine]
    df = df.sort_values("iforest_score", ascending=False).head(min(limit, 500))
    return [
        {k: (v.isoformat() if isinstance(v, pd.Timestamp) else v) for k, v in r.items()} for r in df.to_dict("records")
    ]
