"""Maintenance alert service (§10.13): history scan, persistence, lifecycle actions, work orders, forecast views."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

import numpy as np
import pandas as pd
from sqlalchemy import Connection, and_, insert, select, update

from terrapilot.core.config import ConfigBundle
from terrapilot.db.schema import fault_events, maintenance_alerts, sensor_forecasts, service_requests
from terrapilot.maintenance.engine import evaluate_machine, watched_sensors
from terrapilot.maintenance.fusion import FusedAlert, can_transition, fuse, merge_with_existing
from terrapilot.maintenance.layers import EvidenceItem, fault_layer, interval_layer
from terrapilot.maintenance.limits import threshold
from terrapilot.planning.context import PlanningContext
from terrapilot.planning.service_due import service_due

SECONDS_PER_HOUR = 3600.0
PEER_TAIL = 30  # samples used for the current residual level


def _series_frame(ctx: PlanningContext, machine_id: str, since: datetime, until: datetime) -> pd.DataFrame:
    if ctx.t.source == "db":
        return ctx.t.get(
            "sensor_1min",
            "SELECT ts, sensor_id, value FROM sensor_1min WHERE machine_id = :m AND ts > :a AND ts <= :b ORDER BY ts",
            {"m": machine_id, "a": since, "b": until},
        )
    df = ctx.t.get("sensor_1min")
    return df[(df["machine_id"] == machine_id) & (df["ts"] > pd.Timestamp(since)) & (df["ts"] <= pd.Timestamp(until))]


def series_for(
    ctx: PlanningContext, machine_id: str, since: datetime, until: datetime
) -> dict[str, tuple[np.ndarray, np.ndarray]]:
    df = _series_frame(ctx, machine_id, since, until)
    out = {}
    for sid, grp in df.groupby("sensor_id"):
        g = grp.sort_values("ts")
        t = pd.to_datetime(g["ts"], utc=True).astype("int64").to_numpy() / 1e9
        out[str(sid)] = (t, g["value"].to_numpy(dtype=float))
    return out


def site_series(
    ctx: PlanningContext, machine_id: str, since: datetime, until: datetime
) -> dict[str, tuple[np.ndarray, np.ndarray]]:
    """Weather covariates as pseudo-sensors (`site.<var>`) for baseline normalisation."""
    site = str(ctx.machines.loc[machine_id, "site_id"])
    wx = ctx.t.get("weather_hourly")
    wx = wx[
        (wx["site_id"] == site)
        & (wx["ts"] > pd.Timestamp(since) - pd.Timedelta(hours=1))
        & (wx["ts"] <= pd.Timestamp(until))
    ].sort_values("ts")
    t = pd.to_datetime(wx["ts"], utc=True).astype("int64").to_numpy() / 1e9
    return {f"site.{c}": (t, wx[c].to_numpy(dtype=float)) for c in ("temp_c", "pm10") if c in wx}


def machine_series(
    ctx: PlanningContext, machine_id: str, since: datetime, until: datetime
) -> dict[str, tuple[np.ndarray, np.ndarray]]:
    return {**series_for(ctx, machine_id, since, until), **site_series(ctx, machine_id, since, until)}


def machine_evidence(ctx: PlanningContext, machine_id: str) -> tuple[list[EvidenceItem], dict[str, Any]]:
    cfg = ctx.cfg
    fc = cfg.models["models"]["maint_alert_fusion"]
    since = ctx.now - timedelta(hours=float(fc["scan_lookback_h"]))
    manifest_id = ctx.manifest_id(machine_id)
    series = machine_series(ctx, machine_id, since, ctx.now)
    ev = evaluate_machine(cfg, machine_id, manifest_id, series, ctx.now)
    items = list(ev.evidence)
    items += _advanced_layers(ctx, machine_id, manifest_id, series, ev)
    items += interval_layer(service_due(ctx, machine_id), machine_id, ctx.now, fc["service_interval_tier"])
    fe = ctx.t.get("fault_events")
    fe = fe[fe["machine_id"] == machine_id] if not fe.empty else fe
    events = [
        {
            "code": r["code"],
            "ts": pd.Timestamp(r["ts"]).to_pydatetime(),
            "cleared_ts": None if pd.isna(r["cleared_ts"]) else pd.Timestamp(r["cleared_ts"]).to_pydatetime(),
            "occurrences": r.get("occurrences"),
        }
        for r in fe.to_dict("records")
        if pd.Timestamp(r["ts"]) <= pd.Timestamp(ctx.now)
    ]
    catalogue = {f.code: f for f in cfg.fault_catalogue}
    items += fault_layer(events, machine_id, ctx.now, catalogue, float(fc["fault_code_active_h"]))
    return items, ev.curves


def _advanced_layers(
    ctx: PlanningContext, machine_id: str, manifest_id: str, series: dict[str, tuple[np.ndarray, np.ndarray]], ev: Any
) -> list[EvidenceItem]:
    """Layers D (signature), E (peer drift) and G (fluid samples) — §10.13 rev 2."""
    from terrapilot.maintenance.advanced import fluid_layer, peer_layer, signature_layer

    cfg = ctx.cfg
    fc = cfg.models["models"]["maint_alert_fusion"]
    machine_class = str(ctx.machines.loc[machine_id, "machine_class"])
    items = signature_layer(cfg, machine_id, machine_class, series, ev.normalised, ctx.now)
    items += peer_layer(
        cfg, machine_id, _residual_now(ev), _peer_residuals(ctx, machine_id, manifest_id), ev.component_of, ctx.now
    )
    fs = ctx.t.get("fluid_samples")
    fs = fs[(fs["machine_id"] == machine_id) & (fs["ts"] <= pd.Timestamp(ctx.now))] if not fs.empty else fs
    items += fluid_layer(cfg, machine_id, fs, ctx.now, float(fc["fluid"]["max_sample_age_days"]))
    return items


def _residual_now(ev: Any) -> dict[str, float]:
    return {sid: float(np.median(v[-PEER_TAIL:])) for sid, v in ev.normalised.items() if len(v)}


def _peer_residuals(ctx: PlanningContext, machine_id: str, manifest_id: str) -> dict[str, list[float]]:
    """The same duty-normalised sensors on sibling machines of the same manifest (layer E baseline)."""
    fc = ctx.cfg.models["models"]["maint_alert_fusion"]
    since = ctx.now - timedelta(hours=float(fc["peer"]["window_h"]))
    peers = [m for m in ctx.machines.index if m != machine_id and ctx.machines.loc[m, "manifest_id"] == manifest_id]
    out: dict[str, list[float]] = {}
    for peer in peers:
        series = machine_series(ctx, str(peer), since, ctx.now)
        ev = evaluate_machine(ctx.cfg, str(peer), manifest_id, series, ctx.now)
        for sid, value in _residual_now(ev).items():
            out.setdefault(sid, []).append(value)
    return out


def existing_open(
    conn: Connection | None, ctx: PlanningContext, machine_id: str, component: str
) -> dict[str, Any] | None:
    if conn is None:
        return None
    row = (
        conn.execute(
            select(maintenance_alerts)
            .where(and_(maintenance_alerts.c.machine_id == machine_id, maintenance_alerts.c.component == component))
            .where(maintenance_alerts.c.state != "false_alarm")
            .order_by(maintenance_alerts.c.opened_at.desc())
            .limit(1)
        )
        .mappings()
        .first()
    )
    return dict(row) if row else None


def upsert_alert(conn: Connection, row: dict[str, Any]) -> None:
    exists = conn.execute(select(maintenance_alerts.c.id).where(maintenance_alerts.c.id == row["id"])).first()
    if exists:
        conn.execute(update(maintenance_alerts).where(maintenance_alerts.c.id == row["id"]).values(**row))
    else:
        conn.execute(insert(maintenance_alerts).values(**row))


def apply_fused(
    ctx: PlanningContext, conn: Connection | None, fused: list[FusedAlert], persist: bool = True
) -> list[tuple[dict[str, Any], str]]:
    out = []
    for fa in fused:
        m = ctx.machines.loc[fa.machine_id]
        existing = existing_open(conn, ctx, fa.machine_id, fa.component)
        row, change = merge_with_existing(fa, existing, ctx.now, ctx.cfg, str(m["site_id"]), str(m["machine_class"]))
        if persist and conn is not None and change != "none":
            upsert_alert(conn, row)
        out.append((row, change))
    return out


def scan(
    ctx: PlanningContext, conn: Connection | None, machine_ids: list[str] | None = None, persist: bool = True
) -> dict[str, Any]:
    """Evaluate every watched sensor of each machine at `ctx.now`, fuse and merge with stored alerts."""
    ids = machine_ids or ctx.machines.index.tolist()
    results: list[tuple[dict[str, Any], str]] = []
    forecasts = 0
    for mid in ids:
        items, curves = machine_evidence(ctx, mid)
        results += apply_fused(ctx, conn, fuse(items, ctx.cfg), persist)
        if persist and conn is not None:
            forecasts += _store_forecasts(conn, ctx, mid, curves)
    if persist and conn is not None:
        conn.commit()
    return {
        "now": ctx.now.isoformat(),
        "machines": len(ids),
        "alerts": [
            {
                "id": r["id"],
                "machine_id": r["machine_id"],
                "component": r["component"],
                "tier": r["tier"],
                "kind": "+".join(r["evidence"]["layers"]),
                "change": c,
            }
            for r, c in results
        ],
        "forecasts_stored": forecasts,
    }


def _store_forecasts(conn: Connection, ctx: PlanningContext, machine_id: str, curves: dict[str, dict[str, Any]]) -> int:
    n = 0
    for sid, c in curves.items():
        for tier, e in c["etas"].items():

            def at(h: float | None) -> datetime | None:
                return None if h is None else ctx.now + timedelta(hours=float(h))

            conn.execute(
                insert(sensor_forecasts).values(
                    id=f"SF-{machine_id}-{sid}-{tier}-{int(ctx.now.timestamp())}",
                    machine_id=machine_id,
                    sensor_id=sid,
                    issued_at=ctx.now,
                    horizon_h=c["horizon_h"],
                    threshold_tier=tier,
                    eta_p10=at(e["eta_h_p10"]),
                    eta_p50=at(e["eta_h_p50"]),
                    eta_p90=at(e["eta_h_p90"]),
                    p_cross_h=e["p_cross_within_horizon"],
                    model="holt",
                )
            )
            n += 1
    return n


# ------------------------------------------------------------------ views
def sensor_forecast_view(ctx: PlanningContext, machine_id: str, sensor_id: str) -> dict[str, Any]:
    """History (operating samples), fitted trend + cone to the horizon, and every tier threshold."""
    ws = next((w for w in watched_sensors(ctx.cfg, ctx.manifest_id(machine_id)) if w.sensor_id == sensor_id), None)
    if ws is None:
        raise KeyError(sensor_id)
    fc = ctx.cfg.models["models"]["maint_alert_fusion"]
    since = ctx.now - timedelta(hours=float(fc["scan_lookback_h"]))
    series = machine_series(ctx, machine_id, since, ctx.now)
    ev = evaluate_machine(ctx.cfg, machine_id, ctx.manifest_id(machine_id), series, ctx.now)
    t, v = series.get(sensor_id, (np.array([]), np.array([])))
    curve = ev.curves.get(sensor_id)
    cone = []
    if curve:
        steps = np.linspace(0, float(curve["horizon_h"]), 25)
        z = float(curve["z"])
        for h in steps:
            mid = curve["level"] + curve["trend_per_h"] * h
            spread = z * (curve["resid_sd"] + curve["trend_se"] * h)
            cone.append(
                {
                    "ts": (
                        datetime.fromtimestamp(curve["t_last"], ctx.now.tzinfo) + timedelta(hours=float(h))
                    ).isoformat(),
                    "p50": round(mid, 4),
                    "p10": round(mid - spread, 4),
                    "p90": round(mid + spread, 4),
                }
            )
    return {
        "machine_id": machine_id,
        "sensor_id": sensor_id,
        "component": ws.component,
        "unit": ws.limit.get("unit"),
        "direction": ws.limit.get("direction"),
        "thresholds": {tier: threshold(ws.limit, tier) for tier in ("monitor", "service_soon", "stop")},
        "history": [
            {"ts": datetime.fromtimestamp(float(a), ctx.now.tzinfo).isoformat(), "value": round(float(b), 4)}
            for a, b in zip(t[-400:], v[-400:], strict=True)
        ],
        "forecast": cone,
        "etas": (curve or {}).get("etas", {}),
        "trend_per_h": (curve or {}).get("trend_per_h"),
    }


def transition(
    conn: Connection, cfg: ConfigBundle, alert_id: str, target: str, actor: str, now: datetime
) -> dict[str, Any]:
    row = conn.execute(select(maintenance_alerts).where(maintenance_alerts.c.id == alert_id)).mappings().first()
    if row is None:
        raise KeyError(alert_id)
    if not can_transition(cfg, row["state"], target):
        raise ValueError(f"{row['state']} → {target} is not allowed")
    ev = dict(row["evidence"] or {})
    ev["history"] = [*ev.get("history", []), {"ts": now.isoformat(), "state": target, "by": actor}]
    values: dict[str, Any] = {"state": target, "updated_at": now, "evidence": ev}
    if target == "false_alarm":
        values["feedback"] = "false_alarm"
    elif target == "resolved":
        values["feedback"] = row.get("feedback") or "confirmed"
    conn.execute(update(maintenance_alerts).where(maintenance_alerts.c.id == alert_id).values(**values))
    conn.commit()
    return {**dict(row), **values}


def create_work_order(conn: Connection, alert_id: str, actor: str, now: datetime) -> dict[str, Any]:
    """One tap from the alert: a service request pre-filled with the fault code and parts (§10.13)."""
    row = conn.execute(select(maintenance_alerts).where(maintenance_alerts.c.id == alert_id)).mappings().first()
    if row is None:
        raise KeyError(alert_id)
    if row["work_order_id"]:
        existing = (
            conn.execute(select(service_requests).where(service_requests.c.id == row["work_order_id"]))
            .mappings()
            .first()
        )
        if existing:
            return dict(existing)
    wo = {
        "id": f"SR-{alert_id}",
        "machine_id": row["machine_id"],
        "requested_by": actor,
        "kind": "maintenance_alert",
        "fault_code": row["recommended_action_ref"],
        "part_nos": list(row["parts"] or []),
        "diagnosis_ref": alert_id,
        "status": "open",
        "eta": None,
    }
    conn.execute(insert(service_requests).values(**wo))
    conn.execute(
        update(maintenance_alerts)
        .where(maintenance_alerts.c.id == alert_id)
        .values(work_order_id=wo["id"], updated_at=now)
    )
    conn.commit()
    return wo


def active_fault_events(conn: Connection, machine_id: str) -> list[dict[str, Any]]:
    return [
        dict(r) for r in conn.execute(select(fault_events).where(fault_events.c.machine_id == machine_id)).mappings()
    ]
