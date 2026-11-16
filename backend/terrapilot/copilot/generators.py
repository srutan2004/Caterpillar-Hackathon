"""Advisory generators (§12.1 step 1): deterministic pure functions of the fused MachineState (+ cloud context).

Each returns zero or more `Candidate`s. Facts are the ONLY numbers the narrator may use, so they are rounded
here to the precision an operator should hear.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from terrapilot.core.config import ConfigBundle
from terrapilot.core.refs import get_path, load_ref_cached
from terrapilot.maintenance.limits import band_tier

SECONDS_PER_MINUTE = 60.0
CM_PER_M = 100.0


@dataclass
class Candidate:
    key: str
    category: str
    severity: str
    facts: dict[str, Any]
    template: str
    urgency: float = 1.0


@dataclass
class GenContext:
    cfg: ConfigBundle
    manifest: dict[str, Any]
    now: datetime
    extras: dict[str, Any] = field(default_factory=dict)  # cloud context: maintenance, plan, energy, pacing, fatigue

    def ref(self, value: Any) -> Any:
        if isinstance(value, str) and value.startswith("manifest."):
            return get_path(self.manifest, value[len("manifest.") :])
        return value


def _g(state: dict[str, Any], path: str, default: Any = None) -> Any:
    node: Any = state
    for part in path.split("."):
        if not isinstance(node, dict) or part not in node:
            return default
        node = node[part]
    return node


def grade(state: dict[str, Any], ctx: GenContext, p: dict[str, Any]) -> list[Candidate]:
    g = state.get("grade") or {}
    if not g.get("active") or g.get("direction") in (None, "on_grade"):
        return []
    raw = g.get("deviation_cm")
    cm = abs(float(raw) if raw is not None else float(g.get("deviation_m") or 0.0) * CM_PER_M)
    if cm < float(p["min_deviation_cm"]):
        return []
    return [
        Candidate(
            "grade", "grade", "advisory", {"deviation_cm": round(cm), "direction": g["direction"]}, "grade", 1 + cm / 10
        )
    ]


def proximity(state: dict[str, Any], ctx: GenContext, p: dict[str, Any]) -> list[Candidate]:
    prox = state.get("proximity") or {}
    zone = float(ctx.ref(p["zone_ref"]))
    out = []
    for tr in prox.get("tracks") or []:
        d, ttc = tr.get("distance_m"), tr.get("ttc_s")
        near = d is not None and d < zone
        closing = ttc is not None and ttc < float(p["max_ttc_s"])
        if not (near or closing):
            continue
        facts: dict[str, Any] = {"distance_m": round(float(d))}
        if closing:
            facts["ttc_s"] = round(float(ttc))
        if prox.get("ppe_missing"):
            facts["ppe_missing"] = True
        urgency = 1 + (float(p["max_ttc_s"]) / max(float(ttc), 1.0) if closing else zone / max(float(d), 1.0))
        out.append(
            Candidate(
                f"proximity:{tr.get('id')}",
                "proximity",
                "advisory",
                facts,
                "proximity_ttc" if closing else "proximity",
                urgency,
            )
        )
    return sorted(out, key=lambda c: -c.urgency)[:1]


def utility(state: dict[str, Any], ctx: GenContext, p: dict[str, Any]) -> list[Candidate]:
    geo = state.get("geofence") or {}
    d, clr = geo.get("utility_distance_m"), geo.get("utility_clearance_m")
    if d is None or clr is None or d > float(p["clearance_multiple"]) * float(clr):
        return []
    return [
        Candidate(
            f"utility:{geo.get('utility_id')}",
            "utility",
            "advisory",
            {"utility_id": geo.get("utility_id"), "distance_m": round(float(d), 1)},
            "utility",
            1 + clr / max(d, 0.1),
        )
    ]


def stability(state: dict[str, Any], ctx: GenContext, p: dict[str, Any]) -> list[Candidate]:
    st = state.get("stability") or {}
    m = st.get("margin")
    if m is None or m >= float(ctx.ref(p["margin_ref"])):
        return []
    hint = st.get("hint") or "reduce_reach"
    return [
        Candidate(
            "stability",
            "stability",
            "advisory",
            {"margin": round(float(m), 2), "hint": hint},
            f"stability_{hint}",
            1 + 1 / max(m, 0.1),
        )
    ]


def weather(state: dict[str, Any], ctx: GenContext, p: dict[str, Any]) -> list[Candidate]:
    gust = _g(state, "site.gust_ms")
    if gust is None or gust < float(p["gust_advisory_ms"]):
        return []
    return [Candidate("weather:gust", "weather", "advisory", {"gust_ms": round(float(gust))}, "weather")]


def cavitation(state: dict[str, Any], ctx: GenContext, p: dict[str, Any]) -> list[Candidate]:
    ripple, load = _g(state, "hydraulic.pressure_ripple"), _g(state, "engine.load_pct")
    if ripple is None or ripple < float(p["ripple_bar"]) or (load is not None and load < float(p["min_load_pct"])):
        return []
    return [Candidate("cavitation", "cavitation", "advisory", {"ripple_bar": round(float(ripple))}, "cavitation")]


def hydraulic_temp(state: dict[str, Any], ctx: GenContext, p: dict[str, Any]) -> list[Candidate]:
    t = _g(state, "hydraulic.oil_temp")
    if t is None:
        return []
    limit = load_ref_cached(ctx.cfg.root, p["limits_ref"])
    tier = band_tier(limit, float(t))
    if tier == "normal":
        return []
    return [
        Candidate("hydraulic_temp", "hydraulic_temp", "advisory", {"oil_temp_c": round(float(t))}, "hydraulic_temp")
    ]


def payload(state: dict[str, Any], ctx: GenContext, p: dict[str, Any]) -> list[Candidate]:
    w = _g(state, "payload.weight_t")
    if w is None or _g(state, "task.phase") != p["phase"]:
        return []
    rated = float(ctx.ref(p["rated_ref"]))
    if w >= float(p["under_fraction"]) * rated or w <= 0:
        return []
    return [
        Candidate(
            "payload", "payload", "advisory", {"payload_t": round(float(w), 1), "rated_t": round(rated, 1)}, "payload"
        )
    ]


def idle(state: dict[str, Any], ctx: GenContext, p: dict[str, Any]) -> list[Candidate]:
    s = _g(state, "idle.idle_s") or 0.0
    if s < float(p["min_idle_s"]):
        return []
    facts: dict[str, Any] = {"idle_min": round(s / SECONDS_PER_MINUTE)}
    cost = _g(state, "idle.cost")
    if cost:
        facts["cost"] = round(float(cost))
    return [Candidate("idle", "idle", "advisory", facts, "idle_cost" if cost else "idle", 1 + s / 600)]


def pacing(state: dict[str, Any], ctx: GenContext, p: dict[str, Any]) -> list[Candidate]:
    pc = ctx.extras.get("pacing") or {}
    gap = pc.get("gap_pct")
    if gap is None or -gap < float(p["behind_pct"]):
        return []
    return [Candidate("pacing", "pacing", "advisory", {"behind_pct": round(-float(gap))}, "pacing")]


def fatigue(state: dict[str, Any], ctx: GenContext, p: dict[str, Any]) -> list[Candidate]:
    f = state.get("fatigue") or ctx.extras.get("fatigue") or {}
    score = f.get("score")
    if score is None or score < float(p["score_advisory"]):
        return []
    return [
        Candidate(
            "fatigue",
            "fatigue",
            "caution" if f.get("tier") == "caution" else "advisory",
            {"break_min": int(f.get("break_min", 10))},
            "fatigue",
        )
    ]


def maintenance(state: dict[str, Any], ctx: GenContext, p: dict[str, Any]) -> list[Candidate]:
    out = []
    for a in (ctx.extras.get("maintenance") or {}).values():
        routing = (ctx.cfg.lifecycle.model_dump().get("routing") or {}).get(a.get("tier")) or {}
        if routing.get("cab") != "copilot_advisory":
            continue
        eta = (a.get("eta") or {}).get("eta_h_p50")
        labels = ctx.cfg.i18n.get(ctx.cfg.app.locales.default, {}).get("maintenance", {})
        facts: dict[str, Any] = {
            "component": labels.get("component", {}).get(a["component"], a["component"]),
            "tier": labels.get("tier", {}).get(a["tier"], a["tier"]).lower(),
        }
        if eta is not None:
            facts["eta_h"] = round(float(eta))
        template = "maintenance_eta" if eta is not None else "maintenance"
        out.append(Candidate(f"maintenance:{a['component']}", "maintenance", "advisory", facts, template))
    return out[:1]


def energy(state: dict[str, Any], ctx: GenContext, p: dict[str, Any]) -> list[Candidate]:
    e = ctx.extras.get("energy") or {}
    if e.get("can_finish") is None:
        return []
    if e["can_finish"]:
        return [
            Candidate(
                "energy",
                "energy",
                "advisory",
                {"margin_pct": round(100 * float(e.get("margin") or 0))},
                "energy_ok",
                0.5,
            )
        ]
    minutes = e.get("recharge_min") or e.get("refuel_min") or 0
    return [Candidate("energy", "energy", "advisory", {"charge_min": round(float(minutes))}, "energy_short", 1.5)]


def plan(state: dict[str, Any], ctx: GenContext, p: dict[str, Any]) -> list[Candidate]:
    r = ctx.extras.get("plan") or {}
    if not r.get("recommend_change") or r.get("started"):
        return []
    return [
        Candidate(
            "plan", "plan", "advisory", {"start": r["start_local"], "saving_min": round(float(r["saving_min"]))}, "plan"
        )
    ]


def power_mode(state: dict[str, Any], ctx: GenContext, p: dict[str, Any]) -> list[Candidate]:
    load = _g(state, "engine.load_pct")
    if load is None or not _g(state, "engine.running", True):
        return []
    band = next((m for m, (lo, hi) in p["load_bands"].items() if lo <= load < hi), None)
    current = ctx.extras.get("power_mode_current")
    if band is None or current is None or band == current:
        return []
    return [Candidate("power_mode", "power_mode", "advisory", {"mode": band}, f"power_mode_{band}")]


GENERATORS: dict[str, Callable[[dict[str, Any], GenContext, dict[str, Any]], list[Candidate]]] = {
    "grade": grade,
    "proximity": proximity,
    "utility": utility,
    "stability": stability,
    "weather": weather,
    "cavitation": cavitation,
    "hydraulic_temp": hydraulic_temp,
    "payload": payload,
    "idle": idle,
    "pacing": pacing,
    "fatigue": fatigue,
    "maintenance": maintenance,
    "energy": energy,
    "plan": plan,
    "power_mode": power_mode,
}


def generate(state: dict[str, Any], ctx: GenContext) -> list[Candidate]:
    gens = ctx.cfg.copilot.get("generators", {})
    out: list[Candidate] = []
    for name, fn in GENERATORS.items():
        if name not in ctx.cfg.copilot.get("categories", {}):
            continue
        try:
            out += fn(state, ctx, gens.get(name, {}))
        except (KeyError, TypeError, ValueError):
            continue  # a missing signal never breaks the copilot
    return out
