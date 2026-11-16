"""Alert fusion, enrichment and lifecycle (§10.13).

Evidence is merged per (machine, component) into one alert: tier = max of the items, promoted one tier when
≥ N independent layers agree (never beyond `promote_max_tier`, so only hard limits/fault codes stop a machine).
Enrichment (action, parts, safe_to_continue, repair estimate, routing) always comes from config/catalogue.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

from terrapilot.core.config import ConfigBundle
from terrapilot.maintenance.layers import EvidenceItem
from terrapilot.maintenance.limits import TIERS, tier_rank

WORK_TYPE_BY_TIER = {"monitor": "inspect", "service_soon": "minor", "stop": "major"}
HOURS_PER_DAY = 24.0


@dataclass
class FusedAlert:
    machine_id: str
    component: str
    tier: str
    evidence: list[EvidenceItem] = field(default_factory=list)

    @property
    def layers(self) -> list[str]:
        return sorted({e.layer for e in self.evidence})

    @property
    def primary_layer(self) -> str:
        """The layer that set the tier (first by tier, then by the configured layer order)."""
        return max(self.evidence, key=lambda e: tier_rank(e.tier)).layer

    @property
    def sensor_ids(self) -> list[str]:
        return sorted({e.sensor_id for e in self.evidence if e.sensor_id})


def fuse(evidence: list[EvidenceItem], cfg: ConfigBundle) -> list[FusedAlert]:
    lc = cfg.lifecycle.model_dump()
    fusion = lc["fusion"]
    need = int(fusion["promote_when_independent_layers"])
    independent = set(fusion["layers_independent"])
    cap = str(fusion.get("promote_max_tier", "service_soon"))
    groups: dict[tuple[str, str], FusedAlert] = {}
    for ev in evidence:
        key = (ev.machine_id, ev.component)
        fa = groups.setdefault(key, FusedAlert(ev.machine_id, ev.component, "normal"))
        fa.evidence.append(ev)
        if tier_rank(ev.tier) > tier_rank(fa.tier):
            fa.tier = ev.tier
    for fa in groups.values():
        agreeing = {
            e.layer for e in fa.evidence if e.layer in independent and tier_rank(e.tier) >= tier_rank("monitor")
        }
        if len(agreeing) >= need and tier_rank(fa.tier) < tier_rank(cap):
            fa.tier = TIERS[tier_rank(fa.tier) + 1]
    return [fa for fa in groups.values() if fa.tier != "normal"]


def parts_lead_time_h(cfg: ConfigBundle, code: str | None, component: str) -> float:
    """Hours until parts are on hand: 0 when every part is in stock, else the longest lead time."""
    entry = cfg.fault(code) if code else None
    part_nos = entry.part_numbers if entry else [p.part_no for p in cfg.parts if p.component_kind == component]
    parts = [p for p in cfg.parts if p.part_no in part_nos]
    missing = [p.lead_time_days for p in parts if p.stock <= 0]
    return float(max(missing, default=0)) * HOURS_PER_DAY


def enrich(fa: FusedAlert, cfg: ConfigBundle, site_id: str | None, machine_class: str) -> dict[str, Any]:
    codes = [e.catalogue_code for e in fa.evidence if e.catalogue_code]
    by_tier = sorted(fa.evidence, key=lambda e: -tier_rank(e.tier))
    code = next((e.catalogue_code for e in by_tier if e.layer == "fault_code"), None) or (codes[0] if codes else None)
    entry = cfg.fault(code) if code else None
    parts = [p for p in cfg.parts if entry and p.part_no in entry.part_numbers]
    costs = cfg.costs
    work = WORK_TYPE_BY_TIER.get(fa.tier, "inspect")
    base_h = float((costs.get("repair_durations", {}).get(fa.component) or {}).get(work, 0.0))
    travel = float((costs.get("site_remoteness_travel_h") or {}).get(site_id or "", 0.0))
    labour = float((costs.get("labour_rate_per_h") or {}).get("technician", 0.0))
    parts_cost = sum(p.price for p in parts) if work != "inspect" else 0.0
    est = {
        "work_type": work,
        "hours": round(base_h + travel, 1),
        "labour_cost": round((base_h + travel) * labour, 0),
        "parts_cost": round(parts_cost, 0),
        "total_cost": round((base_h + travel) * labour + parts_cost, 0),
        "downtime_cost_per_h": (costs.get("downtime_cost_per_h_by_class") or {}).get(machine_class),
        "currency": cfg.app.costs["currency"],
        "method": "catalogue_base",  # the LightGBM repair_estimate model is P1 (§10.15.2)
    }
    forecasts = [e for e in fa.evidence if e.layer == "forecast"]
    eta = None
    if forecasts:
        f = min(forecasts, key=lambda e: e.detail["eta_h_p50"])
        eta = {k: f.detail.get(k) for k in ("target_tier", "threshold", "eta_h_p10", "eta_h_p50", "eta_h_p90")}
        eta["sensor_id"] = f.sensor_id
        eta["from"] = f.ts.isoformat()
    routing = cfg.lifecycle.model_dump()["routing"].get(fa.tier, {})
    return {
        "fault_code": code,
        "title_key": entry.title_key if entry else None,
        "recommended_action_ref": code,
        "checks": entry.checks if entry else [],
        "safe_to_continue": entry.safe_to_continue if entry else None,
        "parts": [
            {
                "part_no": p.part_no,
                "description": p.description,
                "price": p.price,
                "stock": p.stock,
                "lead_time_days": p.lead_time_days,
            }
            for p in parts
        ],
        "est_repair": est,
        "eta": eta,
        "routing": routing,
    }


def merge_with_existing(
    fused: FusedAlert,
    existing: dict[str, Any] | None,
    now: datetime,
    cfg: ConfigBundle,
    site_id: str | None,
    machine_class: str,
) -> tuple[dict[str, Any], str]:
    """Return the alert row to persist and the change kind: open | escalate | update | reopen | suppressed."""
    lc = cfg.lifecycle.model_dump()
    info = enrich(fused, cfg, site_id, machine_class)
    evidence = [e.as_dict() for e in fused.evidence]
    if existing is not None and existing["state"] in ("resolved",):
        resolved_at = existing.get("updated_at") or existing["opened_at"]
        if now - resolved_at > timedelta(hours=float(lc["reopen_within_h"])):
            existing = None  # old fix; this is a new problem
    if existing is None or existing["state"] == "false_alarm":
        row = {
            "id": f"MA-{fused.machine_id}-{fused.component}-{int(now.timestamp())}",
            "machine_id": fused.machine_id,
            "component": fused.component,
            "sensor_ids": fused.sensor_ids,
            "kind": fused.primary_layer,
            "tier": fused.tier,
            "opened_at": now,
            "updated_at": now,
            "state": lc["initial"],
            "evidence": {
                "items": evidence,
                "layers": fused.layers,
                "history": [{"ts": now.isoformat(), "tier": fused.tier, "layers": fused.layers}],
            },
            "eta": info["eta"],
            "recommended_action_ref": info["recommended_action_ref"],
            "safe_to_continue": info["safe_to_continue"],
            "parts": [p["part_no"] for p in info["parts"]],
            "est_repair": info["est_repair"],
            "window_id": None,
            "work_order_id": None,
            "explanation": None,
            "feedback": None,
        }
        return row, "open"
    row = dict(existing)
    prev_tier = row["tier"]
    prev_layers = set((row.get("evidence") or {}).get("layers", []))
    old_items = (row.get("evidence") or {}).get("items", [])
    keyed = {(i["layer"], i.get("sensor_id")): i for i in old_items}
    for e in evidence:
        keyed[(e["layer"], e.get("sensor_id"))] = e
    layers = sorted({k[0] for k in keyed})
    tier = prev_tier if tier_rank(prev_tier) >= tier_rank(fused.tier) else fused.tier  # tiers only rise until fixed
    history = list((row.get("evidence") or {}).get("history", []))
    change = "update"
    if row["state"] == "resolved":
        row["state"] = "open"
        change = "reopen"
    elif tier_rank(tier) > tier_rank(prev_tier):
        change = "escalate"
    elif set(layers) - prev_layers:
        change = "update"
    else:
        change = "none"
    if change != "none":
        history.append({"ts": now.isoformat(), "tier": tier, "layers": layers})
    row.update(
        {
            "tier": tier,
            "sensor_ids": sorted({*(row.get("sensor_ids") or []), *fused.sensor_ids}),
            "updated_at": now,
            "evidence": {"items": list(keyed.values()), "layers": layers, "history": history},
            "eta": info["eta"] or row.get("eta"),
            "recommended_action_ref": row.get("recommended_action_ref") or info["recommended_action_ref"],
            "safe_to_continue": info["safe_to_continue"] or row.get("safe_to_continue"),
            "parts": row.get("parts") or [p["part_no"] for p in info["parts"]],
            "est_repair": info["est_repair"],
        }
    )
    if lc.get("suppress_while_work_order_open") and row.get("work_order_id") and change not in ("reopen",):
        change = "suppressed" if change != "none" else "none"
    return row, change


def can_transition(cfg: ConfigBundle, current: str, target: str) -> bool:
    return target in cfg.lifecycle.model_dump()["transitions"].get(current, [])


def enrich_row(cfg: ConfigBundle, row: dict[str, Any]) -> dict[str, Any]:
    """A stored alert plus everything the alert card needs: catalogue action/checks, parts, routing, the
    lifecycle actions allowed from its state, and localisable "why" bullets built from the evidence."""
    code = row.get("recommended_action_ref")
    entry = cfg.fault(code) if code else None
    lc = cfg.lifecycle.model_dump()
    parts = [p for p in cfg.parts if p.part_no in (row.get("parts") or [])]
    why = []
    for item in (row.get("evidence") or {}).get("items", []):
        d = item.get("detail") or {}
        why.append(
            {
                "key": f"maint.why.{item['layer']}",
                "layer": item["layer"],
                "tier": item["tier"],
                "sensor_id": item.get("sensor_id"),
                "value": item.get("value"),
                "params": {
                    k: d.get(k)
                    for k in (
                        "threshold",
                        "slope_per_h",
                        "limit_per_h",
                        "window_h",
                        "eta_h_p10",
                        "eta_h_p50",
                        "eta_h_p90",
                        "target_tier",
                        "item",
                        "remaining_h",
                        "code",
                    )
                    if d.get(k) is not None
                },
            }
        )
    return {
        **row,
        "title_key": entry.title_key if entry else None,
        "checks": entry.checks if entry else [],
        "probable_causes": entry.probable_causes if entry else [],
        "parts_detail": [
            {
                "part_no": p.part_no,
                "description": p.description,
                "price": p.price,
                "stock": p.stock,
                "lead_time_days": p.lead_time_days,
            }
            for p in parts
        ],
        "routing": lc["routing"].get(row["tier"], {}),
        "actions": lc["transitions"].get(row["state"], []),
        "layers": (row.get("evidence") or {}).get("layers", []),
        "why": why,
    }
