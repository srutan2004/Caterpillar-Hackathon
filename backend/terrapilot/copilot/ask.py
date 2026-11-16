"""Ask mode (§12.2) as a LangGraph state graph.

    input_guard → router → tools → synthesizer → output_guard → response

Every stage is deterministic except the router and the synthesizer, and both are bounded: the router may only
choose from the enabled tool list (keyword fallback if the model is unavailable), and the synthesizer may only
use tool outputs — the output guard drops any sentence without a citation, then falls back to
"not in the manual for this machine" when nothing grounded remains.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any, TypedDict

from terrapilot.copilot.guard_log import guard_row
from terrapilot.copilot.guards import GuardDecision, InputGuard, RuntimeRules, ground
from terrapilot.copilot.tools import TOOLS, AskContext, ToolResult
from terrapilot.core.config import ConfigBundle
from terrapilot.core.logging import get_logger

log = get_logger("copilot.ask")

KEYWORD_ROUTES: list[tuple[str, str, str]] = [
    # (regex, intent, tool) — the fallback router, also used to seed extra tools alongside the model's plan
    (r"\b(when should i start|best (time|start)|start time|should i start)\b", "planning", "plan"),
    (r"\b(can i finish|enough (charge|fuel|battery)|recharge|refuel)\b", "planning", "plan"),
    (
        r"\b(next service|service due|maintenance alert|why is the .* alert|coolant alert|filter alert)\b",
        "maintenance",
        "maint",
    ),
    (r"\b(how long|how much longer|etc|finish (time|by)|estimate)\b", "prediction", "predict"),
    (r"\b(how many|average|total|count|yesterday|last (week|month)|compare)\b", "telemetry_question", "sql"),
    (r"\b(right now|current(ly)?|at the moment|what is my)\b", "telemetry_question", "twin"),
    (r"\b[A-Z]{2,4}-[A-Z]{2,5}-\d{2}\b", "maintenance", "fault"),
    (r"\b(how do i|procedure|steps|replace|check|manual|torque|interval|capacity)\b", "manual_question", "rag"),
]
OVERRIDE = re.compile(
    r"\b(disable|turn off|silence|mute|bypass|suppress|ignore)\b.{0,30}\b(alarm|alert|warning|interlock|geofence|seat ?belt|safety)\b",
    re.I,
)


class AskState(TypedDict, total=False):
    ctx: Any
    question: str
    intent: str
    plan: list[dict[str, Any]]
    results: list[ToolResult]
    answer: str
    citations: list[str]
    confidence: str
    confidence_score: float
    decision: GuardDecision
    trace: list[dict[str, Any]]
    guard_events: list[dict[str, Any]]
    suggested_actions: list[dict[str, Any]]


@dataclass
class AskResponse:
    text: str
    message_key: str | None = None
    citations: list[dict[str, Any]] = field(default_factory=list)
    confidence: str = "low"
    confidence_score: float = 0.0
    intent: str = "unknown"
    trace: list[dict[str, Any]] = field(default_factory=list)
    guard_events: list[dict[str, Any]] = field(default_factory=list)
    suggested_actions: list[dict[str, Any]] = field(default_factory=list)
    blocked: bool = False

    def as_dict(self) -> dict[str, Any]:
        return {
            "text": self.text,
            "message_key": self.message_key,
            "citations": self.citations,
            "confidence": self.confidence,
            "confidence_score": round(self.confidence_score, 3),
            "intent": self.intent,
            "trace": self.trace,
            "guard_events": [{k: v for k, v in g.items() if k != "id"} for g in self.guard_events],
            "suggested_actions": self.suggested_actions,
            "blocked": self.blocked,
        }


class AskGraph:
    """Compiled once per process; `run` is per question."""

    def __init__(self, cfg: ConfigBundle, gateway: Any = None):
        self.cfg = cfg
        self.gateway = gateway
        self.input_guard = InputGuard(cfg, gateway)
        self.rules = RuntimeRules(cfg)
        self.enabled = list(cfg.ask["tools"]["enabled"])
        self.graph = self._compile()

    # ------------------------------------------------------------------ nodes
    def _node_input(self, state: AskState) -> AskState:
        d = self.input_guard.check(state["question"])
        if OVERRIDE.search(state["question"]):  # architectural: never routed to a tool (§13.1)
            d = GuardDecision("refuse", "REFUSE_OVERRIDE", "ask.refuse.override")
        if d.action != "allow":
            state["guard_events"] = [
                *state.get("guard_events", []),
                guard_row("input", d.rule_id or "input", d.action, d.detail, state["question"]),
            ]
        state["decision"] = d
        state["trace"] = [*state.get("trace", []), {"node": "input_guard", "action": d.action, "rule": d.rule_id}]
        return state

    def _route_keywords(self, question: str) -> tuple[str, list[dict[str, Any]]]:
        q = question.lower()
        hits = [(intent, tool) for pat, intent, tool in KEYWORD_ROUTES if re.search(pat, q, re.I)]
        if not hits:
            return "manual_question", [{"name": "rag", "args": {}}]
        intent = hits[0][0]
        tools, seen = [], set()
        for _, tool in hits:
            if tool not in seen and tool in self.enabled:
                seen.add(tool)
                tools.append({"name": tool, "args": {}})
        return intent, tools[: int(self.cfg.ask["tools"]["max_tool_calls"])]

    def _node_router(self, state: AskState) -> AskState:
        ctx: AskContext = state["ctx"]
        intent, plan = self._route_keywords(state["question"])
        source = "keyword"
        if self.gateway is not None:
            try:
                res = self.gateway.run(
                    "ask_router",
                    {"question": state["question"], "tools": self.enabled, "machine_class": ctx.machine_class},
                )
                out = res.output or {}
                if res.provider not in ("template", "sentinel") and out.get("tools"):
                    model_plan = [t for t in out["tools"] if isinstance(t, dict) and t.get("name") in self.enabled]
                    if model_plan:
                        intent, plan, source = str(out.get("intent", intent)), model_plan, res.provider
                        merged = {t["name"] for t in plan}
                        for extra in self._route_keywords(state["question"])[1]:  # keyword hits the model missed
                            if extra["name"] not in merged:
                                plan.append(extra)
            except Exception as exc:
                log.info("router fallback", error=str(exc)[:160])
        plan = plan[: int(self.cfg.ask["tools"]["max_tool_calls"])]
        d = self.rules.evaluate("route", {"intent": intent})
        if d.action != "allow":
            state["guard_events"] = [
                *state.get("guard_events", []),
                guard_row("runtime", d.rule_id or "route", d.action, {"intent": intent}, state["question"]),
            ]
            state["decision"] = d
        state["intent"], state["plan"] = intent, plan
        state["trace"] = [
            *state.get("trace", []),
            {"node": "router", "intent": intent, "tools": [t["name"] for t in plan], "source": source},
        ]
        return state

    def _node_tools(self, state: AskState) -> AskState:
        ctx: AskContext = state["ctx"]
        results: list[ToolResult] = []
        for call in state.get("plan", []):
            name = str(call.get("name"))
            fn = TOOLS.get(name)
            if fn is None or name not in self.enabled:
                continue
            args = call.get("args") or {}
            try:
                if name == "sql":
                    res = fn(ctx, args, self.input_guard, self.gateway, self.rules)
                elif name == "action":
                    res = fn(ctx, args, self.input_guard, self.rules)
                else:
                    res = fn(ctx, args, self.input_guard)
            except Exception as exc:
                log.warning("tool failed", tool=name, error=str(exc)[:200])
                res = ToolResult(name, False, {"error": str(exc)[:200]})
            results.append(res)
            if res.decision is not None and res.decision.action != "allow":
                state["guard_events"] = [
                    *state.get("guard_events", []),
                    guard_row(
                        "runtime", res.decision.rule_id or name, res.decision.action, res.trace, state["question"]
                    ),
                ]
        state["results"] = results
        state["trace"] = [
            *state.get("trace", []),
            {"node": "tools", "calls": [{"tool": r.name, "ok": r.ok, **r.trace} for r in results]},
        ]
        return state

    def _node_synth(self, state: AskState) -> AskState:
        ctx: AskContext = state["ctx"]
        results = state.get("results", [])
        sources = {k: v for r in results for k, v in r.sources.items()}
        if not sources:
            state["answer"], state["citations"] = "", []
            return state
        profile = self.cfg.ask["synthesis"]["profiles"].get(ctx.device, self.cfg.ask["synthesis"]["profiles"]["mobile"])
        not_in_manual = self._t("ask.not_in_manual")
        payload = [{"id": k, "text": v[:1500]} for k, v in sources.items()]
        answer, cites = "", []
        if self.gateway is not None:
            try:
                res = self.gateway.run(
                    "ask_answer",
                    {
                        "question": state["question"],
                        "tool_outputs": payload,
                        "device": f"{ctx.device} (at most {profile['max_words']} words)",
                        "not_in_manual": not_in_manual,
                    },
                    locale=ctx.locale,
                )
                out = res.output or {}
                if not out.get("not_in_manual"):
                    answer, cites = str(out.get("answer", "")), [str(c) for c in out.get("citations", [])]
                state["trace"] = [
                    *state.get("trace", []),
                    {
                        "node": "synthesizer",
                        "provider": res.provider,
                        "model": res.model,
                        "prompt_version": res.prompt_version,
                    },
                ]
            except Exception as exc:
                log.warning("synthesis failed", error=str(exc)[:200])
        if answer and not re.search(self.cfg.guardrails["output"]["grounding"]["citation_pattern"], answer):
            answer = (
                " ".join(f"{s.strip()} [{cites[0]}]" for s in re.split(r"(?<=[.!?])\s+", answer.strip()) if s.strip())
                if cites
                else answer
            )
        state["answer"], state["citations"] = answer, cites
        return state

    def _node_output(self, state: AskState) -> AskState:
        results = state.get("results", [])
        sources = {k: v for r in results for k, v in r.sources.items()}
        g = ground(state.get("answer", ""), sources, self.cfg)
        d = self.rules.evaluate(
            "output", {"uncited_sentences": g.uncited_sentences, "cited_sentences": g.cited_sentences}
        )
        if g.dropped or g.numeric_violations:
            state["guard_events"] = [
                *state.get("guard_events", []),
                guard_row(
                    "output",
                    "grounding",
                    "drop_sentences" if g.text else "bounded_fallback",
                    {"dropped": g.dropped[:3], "numeric": g.numeric_violations[:5]},
                    state["question"],
                ),
            ]
        if not g.text.strip():
            d = GuardDecision("bounded_fallback", d.rule_id or "UNGROUNDED_ANSWER", "ask.not_in_manual")
        state["answer"], state["citations"] = g.text, g.citations
        state["decision"] = d if d.action != "allow" else state.get("decision", GuardDecision())
        state["trace"] = [
            *state.get("trace", []),
            {"node": "output_guard", "cited": g.cited_sentences, "dropped": len(g.dropped), "action": d.action},
        ]
        return state

    # ------------------------------------------------------------------ graph
    def _compile(self) -> Any:
        try:
            from langgraph.graph import END, START, StateGraph
        except ImportError:  # the linear fallback keeps Ask working without langgraph
            return None
        g = StateGraph(AskState)
        g.add_node("input_guard", self._node_input)
        g.add_node("router", self._node_router)
        g.add_node("tools", self._node_tools)
        g.add_node("synthesizer", self._node_synth)
        g.add_node("output_guard", self._node_output)
        g.add_edge(START, "input_guard")
        g.add_conditional_edges(
            "input_guard", lambda s: END if s["decision"].stops else "router", {END: END, "router": "router"}
        )
        g.add_conditional_edges(
            "router",
            lambda s: END if s.get("decision", GuardDecision()).stops else "tools",
            {END: END, "tools": "tools"},
        )
        g.add_edge("tools", "synthesizer")
        g.add_edge("synthesizer", "output_guard")
        g.add_edge("output_guard", END)
        return g.compile()

    def _t(self, key: str) -> str:
        from terrapilot.core.refs import RefError, get_path

        try:
            return str(get_path(self.cfg.i18n[self.cfg.app.locales.default], key))
        except (RefError, KeyError):
            return key

    # ------------------------------------------------------------------ confidence
    def confidence(self, state: AskState) -> tuple[str, float]:
        c = self.cfg.ask["confidence"]
        results = state.get("results", [])
        rag = next((r for r in results if r.name == "rag"), None)
        retrieval = (
            min(max((rag.score or 0.0) / max(float(self.cfg.ask["retrieval"]["min_dense_score"]), 1e-6), 0.0), 1.0)
            if rag
            else (1.0 if results else 0.0)
        )
        tools = sum(1 for r in results if r.ok) / len(results) if results else 0.0
        trace = next((t for t in state.get("trace", []) if t.get("node") == "output_guard"), {})
        cited, dropped = float(trace.get("cited", 0)), float(trace.get("dropped", 0))
        grounding = cited / (cited + dropped) if cited + dropped else 0.0
        w = c["weights"]
        score = float(w["retrieval"]) * retrieval + float(w["tools"]) * tools + float(w["grounding"]) * grounding
        band = (
            "high"
            if score >= float(c["bands"]["high"])
            else "medium"
            if score >= float(c["bands"]["medium"])
            else "low"
        )
        return band, score

    # ------------------------------------------------------------------ run
    def run(self, ctx: AskContext) -> AskResponse:
        state: AskState = {"question": ctx.question, "trace": [], "guard_events": [], "decision": GuardDecision()}
        state["ctx"] = ctx
        if self.graph is not None:
            state = self.graph.invoke(state)
        else:
            state = self._node_input(state)
            if not state["decision"].stops:
                state = self._node_router(state)
            if not state.get("decision", GuardDecision()).stops:
                state = self._node_output(self._node_synth(self._node_tools(state)))
        d: GuardDecision = state.get("decision", GuardDecision())
        results = state.get("results", [])
        sources = {k: v for r in results for k, v in r.sources.items()}
        cites = [self._citation(c, results) for c in state.get("citations", []) if c in sources]
        actions = [
            {"kind": r.output.get("kind"), "draft": r.output, "requires_confirmation": True}
            for r in results
            if r.name == "action" and isinstance(r.output, dict)
        ]
        if d.action == "redirect" and d.detail.get("suggested_action") not in (None, "none"):
            actions.append({"kind": d.detail["suggested_action"], "requires_confirmation": True})
        band, score = self.confidence(state)
        if d.stops:
            return AskResponse(
                self._t(d.message_key or "ask.refuse.policy"),
                d.message_key,
                [],
                "low",
                0.0,
                state.get("intent", "unknown"),
                state.get("trace", []),
                state.get("guard_events", []),
                actions,
                blocked=d.action in ("block", "refuse"),
            )
        return AskResponse(
            state.get("answer", ""),
            None,
            cites[: int(self.cfg.ask["synthesis"]["max_citations"])],
            band,
            score,
            state.get("intent", "unknown"),
            state.get("trace", []),
            state.get("guard_events", []),
            actions,
        )

    def _citation(self, cid: str, results: list[ToolResult]) -> dict[str, Any]:
        for r in results:
            if r.name == "rag":
                for c in r.trace.get("chunks", []):
                    if c["chunk_id"] == cid:
                        return {"id": cid, "kind": "manual", **c}
        kind = cid.split(":", 1)[0] if ":" in cid else "tool"
        return {"id": cid, "kind": kind}


_GRAPH: dict[str, AskGraph] = {}


def get_graph(cfg: ConfigBundle, gateway: Any = None) -> AskGraph:
    if "g" not in _GRAPH:
        _GRAPH["g"] = AskGraph(cfg, gateway)
    return _GRAPH["g"]


def ask(cfg: ConfigBundle, ctx: AskContext, gateway: Any = None) -> AskResponse:
    return get_graph(cfg, gateway).run(ctx)


def to_json(resp: AskResponse) -> str:
    return json.dumps(resp.as_dict(), default=str, ensure_ascii=False)
