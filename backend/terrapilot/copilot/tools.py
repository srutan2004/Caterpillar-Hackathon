"""Ask-mode tools (§12.2). Each returns a `ToolResult` whose `sources` are what the answer may cite.

No tool can change or silence a safety alert: there is no such tool (§13.1 architectural layer).
`action` only drafts; the UI must confirm.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from terrapilot.core.config import ConfigBundle
from terrapilot.core.logging import get_logger

log = get_logger("copilot.tools")
TASK_ID = re.compile(r"\bT-\d{3,6}\b")
MACHINE_ID = re.compile(r"\b(?:EX|EXE|WL|AT)-\d{2}\b")


@dataclass
class AskContext:
    cfg: ConfigBundle
    user_id: str
    role: str
    site_id: str | None
    machine_id: str | None
    manifest: dict[str, Any] | None
    question: str
    device: str = "mobile"
    locale: str = "en"
    kb: Any = None
    planning: Any = None

    @property
    def scope(self) -> list[str] | None:
        return list((self.manifest or {}).get("knowledge_scope") or []) or None

    @property
    def machine_class(self) -> str:
        return str((self.manifest or {}).get("class", "any"))


@dataclass
class ToolResult:
    name: str
    ok: bool
    output: Any
    sources: dict[str, str] = field(default_factory=dict)  # citation id → text the answer may use
    trace: dict[str, Any] = field(default_factory=dict)
    score: float | None = None  # retrieval strength (rag)
    decision: Any = None  # runtime guard decision, if any


def _src(obj: Any) -> str:
    return json.dumps(obj, default=str, ensure_ascii=False)


def _local(ctx: AskContext, iso: str | None) -> str | None:
    """Site-local "HH:MM" for a timestamp, so the answer may state the time the operator will read."""
    if not iso:
        return None
    import pandas as pd

    return pd.Timestamp(iso).tz_convert(ctx.planning.tz).strftime("%H:%M")


# ------------------------------------------------------------------ rag / fault
def rag_tool(ctx: AskContext, args: dict[str, Any], guard: Any) -> ToolResult:
    query = str(args.get("query") or ctx.question)
    hits = ctx.kb.search(query, ctx.scope)
    sources = {h.chunk.id: guard.sanitize_context(h.chunk.text) for h in hits}
    best = max((h.dense for h in hits), default=0.0)
    return ToolResult(
        "rag",
        bool(hits),
        [{"id": h.chunk.id, "heading": h.chunk.heading, "text": sources[h.chunk.id]} for h in hits],
        sources,
        {"query": query, "chunks": [h.cite() for h in hits], "dense_source": getattr(ctx.kb, "dense_source", "local")},
        best,
    )


def fault_tool(ctx: AskContext, args: dict[str, Any], guard: Any) -> ToolResult:
    pattern = re.compile(ctx.cfg.ask["knowledge"]["fault_code_pattern"])
    codes = [str(args["code"])] if args.get("code") else pattern.findall(ctx.question.upper())
    out, sources = [], {}
    for code in codes:
        f = ctx.cfg.fault(code)
        if f is None:
            continue
        entry = f.model_dump()
        sid = f"fault:{code}"
        sources[sid] = _src(entry)
        linked = ctx.kb.by_procedure(f.manual_ref.get("procedure_id", "")) if ctx.kb else []
        for c in linked:
            sources[c.id] = guard.sanitize_context(c.text)
        out.append({**entry, "manual_chunks": [c.id for c in linked]})
    return ToolResult("fault", bool(out), out, sources, {"codes": codes})


# ------------------------------------------------------------------ sql
def validate_sql(sql: str, views: set[str], max_rows: int, machine_id: str | None, role: str) -> dict[str, Any]:
    import sqlglot
    from sqlglot import exp

    try:
        tree = sqlglot.parse_one(sql, read="postgres")
    except Exception as exc:
        return {"ok": False, "reason": f"parse: {exc}"[:200]}
    select_only = isinstance(tree, exp.Select | exp.Union) and not any(
        isinstance(n, exp.Insert | exp.Update | exp.Delete | exp.Drop | exp.Create | exp.Alter | exp.Command)
        for n in tree.walk()
    )
    ctes = {c.alias for c in tree.find_all(exp.CTE)}
    tables = {t.name for t in tree.find_all(exp.Table)} - ctes
    truth = any(t.startswith("truth_") for t in tables)
    unknown = tables - views
    limit = tree.args.get("limit") if select_only else None
    if select_only and (limit is None or int(limit.expression.name or max_rows + 1) > max_rows):
        tree = sqlglot.parse_one(f"SELECT * FROM ({tree.sql(dialect='postgres')}) q LIMIT {max_rows}", read="postgres")
    scoped = True
    if role == "operator" and machine_id:
        text = tree.sql(dialect="postgres")
        scoped = f"'{machine_id}'" in text
    return {
        "ok": select_only and not unknown and not truth,
        "sql": tree.sql(dialect="postgres"),
        "tables": sorted(tables),
        "select_only": select_only,
        "any_truth_table": truth,
        "unknown": sorted(unknown),
        "scoped": scoped,
    }


def sql_tool(ctx: AskContext, args: dict[str, Any], guard: Any, gateway: Any, rules: Any) -> ToolResult:
    from terrapilot.db.views import VIEWS

    sc = ctx.cfg.ask["tools"]["sql"]
    views_txt = "\n".join(
        f"- {v.name}: {v.comment} Columns: {', '.join(f'{k} ({d})' for k, d in v.columns.items())}" for v in VIEWS
    )
    res = gateway.run(
        "text_to_sql",
        {
            "question": str(args.get("question") or ctx.question),
            "views": views_txt,
            "row_limit": int(sc["max_rows"]),
            "machine_id": ctx.machine_id or "",
            "site_id": ctx.site_id or "",
        },
    )
    sql = str((res.output or {}).get("sql", ""))
    if not sql:
        return ToolResult("sql", False, {"error": "no_sql"}, trace={"fallback": (res.output or {}).get("fallback")})
    v = validate_sql(sql, {x.name for x in VIEWS}, int(sc["max_rows"]), ctx.machine_id, ctx.role)
    decision = rules.evaluate(
        "tool",
        {
            "tool": "sql",
            "any_truth_table": v.get("any_truth_table", False),
            "sql_select_only": v.get("select_only", False),
            "sql_scoped": v.get("scoped", True),
            "role": ctx.role,
        },
    )
    trace = {"sql": v.get("sql", sql), "tables": v.get("tables"), "rationale": (res.output or {}).get("rationale")}
    if decision.stops or not v["ok"]:
        return ToolResult(
            "sql", False, {"error": "rejected", "unknown_views": v.get("unknown")}, trace=trace, decision=decision
        )
    rows = _run_readonly(v["sql"], int(sc["timeout_ms"]))
    return ToolResult("sql", rows is not None, rows or [], {"sql:1": _src({"sql": v["sql"], "rows": rows})}, trace)


def _run_readonly(sql: str, timeout_ms: int) -> list[dict[str, Any]] | None:
    """Execute as tp_ro (read-only role with SELECT on the curated views only)."""
    from sqlalchemy import create_engine, text
    from sqlalchemy.engine import make_url

    from terrapilot.core.settings import get_settings

    s = get_settings()
    url = make_url(s.database_url).set(username="tp_ro", password=s.tp_ro_password.get_secret_value())
    try:
        eng = create_engine(url, pool_pre_ping=True, poolclass=None)
        with eng.connect() as conn:
            conn.execute(text(f"SET statement_timeout = {int(timeout_ms)}"))
            rows = [dict(r) for r in conn.execute(text(sql)).mappings()]
        eng.dispose()
        out: list[dict[str, Any]] = json.loads(json.dumps(rows, default=str))
        return out
    except Exception as exc:
        log.info("readonly sql failed", error=str(exc)[:200])
        return None


# ------------------------------------------------------------------ twin / predict / maint / plan
def twin_tool(ctx: AskContext, args: dict[str, Any], guard: Any) -> ToolResult:
    from terrapilot.api.routers.live import live_snapshot
    from terrapilot.core.expr import nest_dotted

    if not ctx.machine_id:
        return ToolResult("twin", False, {"error": "no_machine"})
    flat, alerts = live_snapshot(ctx.machine_id)
    keep = ("stability", "grade", "proximity", "geofence", "energy", "task", "site", "hydraulic", "engine", "idle")
    state = {k: v for k, v in nest_dotted(flat).items() if k in keep}
    out = {
        "live": bool(flat),
        "state": state,
        "open_alerts": [{"rule_id": a.get("rule_id"), "severity": a.get("severity")} for a in alerts],
    }
    return ToolResult("twin", bool(flat), out, {"twin": _src(out)} if flat else {})


def _task_from(ctx: AskContext, args: dict[str, Any]) -> dict[str, Any] | None:
    tid = args.get("task_id") or next(iter(TASK_ID.findall(ctx.question)), None)
    p = ctx.planning
    if tid:
        try:
            return dict(p.task(str(tid)))
        except KeyError:
            return None
    from terrapilot.planning.shift import todays_tasks

    open_ = [t for t in todays_tasks(p, ctx.user_id) if t.get("status") != "completed"]
    return open_[0] if open_ else None


def predict_tool(ctx: AskContext, args: dict[str, Any], guard: Any) -> ToolResult:
    from terrapilot.planning.estimate import estimate_task, usual_duration

    task = _task_from(ctx, args)
    if task is None:
        return ToolResult("predict", False, {"error": "no_task"})
    est = estimate_task(ctx.planning, task)
    out = {
        "task_id": task["id"],
        "type": task["type"],
        **est.as_dict(),
        "usual": usual_duration(ctx.planning, task),
        "model": "task_duration",
    }
    return ToolResult("predict", True, out, {f"predict:{task['id']}": _src(out)})


def maint_tool(ctx: AskContext, args: dict[str, Any], guard: Any) -> ToolResult:
    from terrapilot.planning.service_due import service_due

    mid = args.get("machine_id") or next(iter(MACHINE_ID.findall(ctx.question)), None) or ctx.machine_id
    if not mid:
        return ToolResult("maint", False, {"error": "no_machine"})
    alerts = ctx.planning.open_maintenance_alerts(str(mid))
    slim = [
        {
            "id": a["id"],
            "component": a["component"],
            "tier": a["tier"],
            "state": a["state"],
            "eta": a.get("eta"),
            "layers": (a.get("evidence") or {}).get("layers"),
            "safe_to_continue": a.get("safe_to_continue"),
            "fault_code": a.get("recommended_action_ref"),
        }
        for a in alerts
    ]
    due = [
        {
            "item": d["item"],
            "remaining_hours": round(float(d["remaining_h"])),
            "due_soon": d["due_soon"],
            "overdue": d["overdue"],
            "work": d["work"],
        }
        for d in service_due(ctx.planning, str(mid))[:4]
    ]
    out = {"machine_id": mid, "alerts": slim, "service_due": due}
    return ToolResult("maint", True, out, {f"maint:{mid}": _src(out)})


def plan_tool(ctx: AskContext, args: dict[str, Any], guard: Any) -> ToolResult:
    from terrapilot.planning.energy import energy_estimate
    from terrapilot.planning.readiness import readiness
    from terrapilot.planning.start_time import recommend

    task = _task_from(ctx, args)
    if task is None or not task.get("assigned_machine_id"):
        return ToolResult("plan", False, {"error": "no_task"})
    mid = str(task["assigned_machine_id"])
    rec = recommend(ctx.planning, task["id"])
    energy = energy_estimate(ctx.planning, task, mid)
    ready = readiness(ctx.planning, mid, task.get("assigned_operator_id"), task)
    out = {
        "task_id": task["id"],
        "recommended_start": rec["recommended_start"],
        "recommended_start_local": _local(ctx, rec["recommended_start"]),
        "now_start_local": _local(ctx, rec["now"]["start"]),
        "recommend_change": rec["recommend_change"],
        "duration_p50_min": rec["duration"]["p50_min"],
        "duration_p50_h": round(float(rec["duration"]["p50_min"]) / 60, 1),
        "finish_p50_local": _local(ctx, rec["duration"]["finish_p50"]),
        "saving_vs_usual_min": rec["saving_vs_usual_min"],
        "preconditions": [p["kind"] for p in rec["preconditions"]],
        "energy": {
            k: energy.get(k) for k in ("unit", "p50", "p90", "can_finish", "margin", "recharge_min", "refuel_min")
        },
        "readiness": {"score": ready["score"], "band": ready["band"]},
    }
    return ToolResult("plan", True, out, {f"plan:{task['id']}": _src(out)})


def action_tool(ctx: AskContext, args: dict[str, Any], guard: Any, rules: Any) -> ToolResult:
    kind = str(args.get("kind") or "service_request")
    draft = {"kind": kind, "machine_id": ctx.machine_id, "note": ctx.question[:300], "requires_confirmation": True}
    decision = rules.evaluate("tool", {"tool": "action", "confirmed": False})
    return ToolResult("action", True, draft, {"action": _src(draft)}, decision=decision)


TOOLS: dict[str, Callable[..., ToolResult]] = {
    "rag": rag_tool,
    "fault": fault_tool,
    "sql": sql_tool,
    "twin": twin_tool,
    "predict": predict_tool,
    "maint": maint_tool,
    "plan": plan_tool,
    "action": action_tool,
}
