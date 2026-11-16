"""`/api/me/shift` (§10.3): today's assignment, tasks with ETC + factors + best start + energy + maintenance,
pacing, readiness and walkaround state — everything the Today screen renders comes from here."""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from typing import Any

import pandas as pd
from sqlalchemy import Connection, insert, select

from terrapilot.analytics.pacing import pacing
from terrapilot.db.schema import start_recommendations
from terrapilot.planning.context import PlanningContext, _clean
from terrapilot.planning.energy import energy_estimate
from terrapilot.planning.estimate import estimate_task
from terrapilot.planning.readiness import readiness
from terrapilot.planning.start_time import recommend

WEATHER_STRIP_VARS = ("temp_c", "rain_mm", "gust_ms", "visibility_m")


def cached_recommendation(
    ctx: PlanningContext, conn: Connection | None, task_id: str, force: bool = False
) -> dict[str, Any]:
    ttl = timedelta(minutes=float(ctx.cfg.planning.refresh_min))
    if conn is not None and not force:
        row = (
            conn.execute(
                select(start_recommendations)
                .where(start_recommendations.c.task_id == task_id)
                .order_by(start_recommendations.c.computed_at.desc())
                .limit(1)
            )
            .mappings()
            .first()
        )
        if row and row["explanation"] and abs(row["computed_at"] - ctx.now) <= ttl:
            payload = (row["explanation"] or {}).get("payload")
            if payload:
                return {
                    **payload,
                    "id": row["id"],
                    "accepted_at": row["accepted_at"],
                    "accepted_by": row["accepted_by"],
                }
    rec = recommend(ctx, task_id)
    rec["explanation"] = _explain(ctx, rec)
    rec_id = f"SR-{task_id}-{int(ctx.now.timestamp())}"
    if conn is not None:
        conn.execute(
            insert(start_recommendations).values(
                id=rec_id,
                task_id=task_id,
                computed_at=ctx.now,
                recommended_start=datetime.fromisoformat(rec["recommended_start"]),
                alt_starts=[p["start"] for p in rec["curve"] if p["feasible"]][:10],
                duration=rec["duration"],
                usual_duration=rec["usual_duration"],
                saving_vs_now_min=rec["duration_saving_vs_now_min"],
                saving_vs_usual_min=rec["saving_vs_usual_min"],
                preconditions=rec["preconditions"],
                factors=rec["factors"],
                constraints={"binding": rec["binding"], "deadline": rec["deadline"]},
                feasible=rec["feasible"],
                explanation={**rec["explanation"], "payload": json.loads(json.dumps(rec, default=str))},
            )
        )
        conn.commit()
    return {**rec, "id": rec_id, "accepted_at": None, "accepted_by": None}


def _explain(ctx: PlanningContext, rec: dict[str, Any]) -> dict[str, Any]:
    from terrapilot.copilot.explainers import explain_start_time

    try:
        from terrapilot.llm.gateway import get_gateway

        gateway = get_gateway()
    except Exception:
        gateway = None
    out = explain_start_time(ctx.cfg, rec, gateway=gateway)
    out.pop("guard_events", None)
    return out


def todays_tasks(ctx: PlanningContext, operator_id: str) -> list[dict[str, Any]]:
    start, end = ctx.shift_bounds()
    t = ctx.tasks
    open_states = ctx.cfg.planning.shift_view["statuses_open"]
    mine = t[t["assigned_operator_id"] == operator_id]
    s0, s1 = pd.Timestamp(start), pd.Timestamp(end)
    carry = pd.Timedelta(days=float(ctx.cfg.planning.shift_view["carryover_days"]))
    is_open = mine["status"].isin(open_states) & (mine["planned_start"] >= s0 - carry)
    overlaps = (mine["planned_start"] < s1) & (mine["planned_end"] >= s0)
    done_today = (mine["status"] == "completed") & (mine["actual_end"] >= s0)
    today = mine[(mine["planned_start"] < s1) & (is_open | (overlaps & done_today))]
    return [_clean(r) for r in today.sort_values("planned_start").to_dict("records")]


def weather_strip(ctx: PlanningContext, site_id: str, hours: int) -> list[dict[str, Any]]:
    fc = ctx.t.get("weather_forecast")
    fc = fc[(fc["site_id"] == site_id) & (fc["issued_at"] <= pd.Timestamp(ctx.now))]
    fc = fc[
        (fc["valid_at"] >= pd.Timestamp(ctx.now).floor("h"))
        & (fc["valid_at"] <= pd.Timestamp(ctx.now) + pd.Timedelta(hours=hours))
    ]
    if fc.empty:
        return []
    latest = fc.sort_values("issued_at").groupby(["valid_at", "var"]).tail(1)
    wide = latest.pivot_table(index="valid_at", columns="var", values="value", aggfunc="last").sort_index()
    return [
        {
            "ts": pd.Timestamp(ts).isoformat(),
            **{v: (round(float(r[v]), 1) if v in r and pd.notna(r[v]) else None) for v in WEATHER_STRIP_VARS},
        }
        for ts, r in wide.iterrows()
    ]


def build_shift(
    ctx: PlanningContext, conn: Connection | None, operator_id: str, with_recommendations: bool = True
) -> dict[str, Any]:
    tasks = todays_tasks(ctx, operator_id)
    start, end = ctx.shift_bounds()
    assignments = ctx.t.get("shift_assignments")
    day = pd.Timestamp(ctx.now).tz_convert(ctx.tz).date()
    a = assignments[(assignments["operator_id"] == operator_id) & (pd.to_datetime(assignments["date"]).dt.date == day)]
    machine_id = (
        str(a.iloc[0]["machine_id"])
        if not a.empty
        else next((t["assigned_machine_id"] for t in tasks if t.get("assigned_machine_id")), None)
    )
    site_id = str(a.iloc[0]["site_id"]) if not a.empty else (tasks[0]["site_id"] if tasks else None)
    live = ctx._live(machine_id) if machine_id else {}
    live_task = live.get("task.task_id")
    cards = []
    open_tasks = [x for x in tasks if x.get("status") != "completed"]
    for tk in tasks:
        card: dict[str, Any] = {
            k: tk.get(k)
            for k in (
                "id",
                "type",
                "quantity",
                "unit",
                "progress_qty",
                "status",
                "planned_start",
                "planned_end",
                "deadline",
                "depends_on",
                "priority",
                "zone_id",
                "assigned_machine_id",
                "design_ref",
            )
        }
        if tk.get("status") == "completed":
            card["actual"] = {
                "start": tk.get("actual_start"),
                "end": tk.get("actual_end"),
                "duration_min": tk.get("duration_min"),
            }
            cards.append(card)
            continue
        est = estimate_task(ctx, tk)
        card["estimate"] = est.as_dict()
        if live_task == tk["id"]:
            card["live"] = {k.removeprefix("task.etc."): v for k, v in live.items() if k.startswith("task.etc.")}
            card["progress_qty"] = live.get("task.progress_qty", card.get("progress_qty"))
        mid = tk.get("assigned_machine_id")
        if mid:
            e = energy_estimate(ctx, tk, mid, est.estimate.as_dict())
            card["energy"] = {
                k: e.get(k)
                for k in (
                    "unit",
                    "p10",
                    "p50",
                    "p90",
                    "can_finish",
                    "margin",
                    "recharge_min",
                    "refuel_min",
                    "soc_now",
                    "fuel_pct_now",
                )
            }
            alerts = ctx.open_maintenance_alerts(mid)
            card["maintenance"] = [
                {"id": x["id"], "component": x["component"], "tier": x["tier"], "eta": x.get("eta")}
                for x in alerts
                if x["tier"] in ("service_soon", "stop")
            ]
            if with_recommendations:
                rec = cached_recommendation(ctx, conn, tk["id"])
                card["best_start"] = {
                    k: rec.get(k)
                    for k in (
                        "id",
                        "recommended_start",
                        "recommend_change",
                        "feasible",
                        "saving_vs_usual_min",
                        "duration_saving_vs_now_min",
                        "finish_delta_vs_now_min",
                        "binding",
                        "accepted_at",
                    )
                }
                card["best_start"]["preconditions"] = [p["kind"] for p in rec.get("preconditions", [])]
                card["best_start"]["usual_p50_min"] = (rec.get("usual_duration") or {}).get("p50_min")
        cards.append(card)
    rd = readiness(ctx, machine_id, operator_id, open_tasks[0] if open_tasks else None) if machine_id else None
    live_progress = {live_task: float(live.get("task.progress_qty") or 0.0)} if live_task else {}
    wk = ctx.latest_walkaround(machine_id) if machine_id else None
    return {
        "now": ctx.now.isoformat(),
        "operator_id": operator_id,
        "date": day.isoformat(),
        "site_id": site_id,
        "machine_id": machine_id,
        "machine_live": bool(live),
        "shift": {
            "start": start.isoformat(),
            "end": end.isoformat(),
            "breaks": [{"start": b0.isoformat(), "end": b1.isoformat()} for b0, b1 in ctx.breaks()],
        },
        "weather": weather_strip(ctx, site_id, int((end - ctx.now).total_seconds() // 3600) + 1) if site_id else [],
        "readiness": rd,
        "walkaround": None
        if wk is None
        else {"result": wk["result"], "ts": wk["ts"], "blocks_start": wk["blocks_start"]},
        "tasks": cards,
        "pacing": pacing(ctx, tasks, live_progress),
    }
