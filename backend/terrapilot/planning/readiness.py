"""Machine readiness score (§10.15.5): readiness = Σ wᵢ · componentᵢ, each component in [0, 1], × 100."""

from __future__ import annotations

from typing import Any

import numpy as np

from terrapilot.planning.context import PlanningContext


def readiness(
    ctx: PlanningContext, machine_id: str, operator_id: str | None = None, next_task: dict[str, Any] | None = None
) -> dict[str, Any]:
    rc = ctx.cfg.planning.readiness
    w = rc["weights"]
    comps: dict[str, dict[str, Any]] = {}

    h = ctx.health_index(machine_id)
    hs = rc["health_scale"]
    comps["health"] = {
        "score": float(np.clip((h - hs["poor"]) / (hs["good"] - hs["poor"]), 0, 1)),
        "value": round(h, 3),
    }

    alerts = ctx.open_maintenance_alerts(machine_id)
    pen = rc["maint_tier_penalty"]
    worst = max((float(pen.get(a["tier"], 0.0)) for a in alerts), default=0.0)
    comps["open_maint_alerts"] = {
        "score": 1 - worst,
        "value": [{"id": a["id"], "component": a["component"], "tier": a["tier"]} for a in alerts],
    }

    if next_task is not None:
        from terrapilot.planning.energy import energy_estimate

        e = energy_estimate(ctx, next_task, machine_id)
        if e.get("can_finish") is None or e["can_finish"]:
            es = 1.0
        else:
            es = float(np.clip(e["avail_frac"] / e["need_frac"], 0, 1)) if e.get("need_frac") else 0.0
        comps["energy"] = {"score": es, "value": {k: e.get(k) for k in ("can_finish", "margin", "unit", "p90")}}
    else:
        comps["energy"] = {"score": 1.0, "value": None}

    wk = ctx.latest_walkaround(machine_id)
    ws = rc["walkaround_score"]
    status = "missing" if wk is None else str(wk["result"])
    comps["walkaround"] = {"score": float(ws.get(status, 0.0)), "value": status}

    cert, detail = ctx.cert_status(operator_id, machine_id) if operator_id else ("valid", [])
    comps["cert"] = {"score": float(rc["cert_score"].get(cert, 0.0)), "value": cert, "detail": detail}

    score = 100 * sum(float(w[k]) * comps[k]["score"] for k in w)
    bands = rc["bands"]
    band = "go" if score >= float(bands["go"]) else "caution" if score >= float(bands["caution"]) else "hold"
    deductions = sorted(
        (
            {"component": k, "points": round(100 * float(w[k]) * (1 - c["score"]), 1), "key": f"readiness.{k}"}
            for k, c in comps.items()
            if c["score"] < 1
        ),
        key=lambda d: -d["points"],
    )
    return {
        "machine_id": machine_id,
        "score": round(score, 1),
        "band": band,
        "bands": bands,
        "components": {k: {**c, "score": round(c["score"], 3), "weight": w[k]} for k, c in comps.items()},
        "deductions": deductions,
        "blocks_start": bool(wk and wk.get("blocks_start")),
    }
