"""Maintenance and plan explanations (§10.13, §10.14 step 6).

Both are built ONLY from the evidence the deterministic modules produced, validated like the live narrator
(every number must be in the evidence), and fall back to the i18n template on any failure. An explanation can
never change a tier, an ETA, a safe-to-continue flag or a recommended start (§13.1 decision authority).
"""

from __future__ import annotations

from typing import Any

from terrapilot.copilot.guard_log import guard_row
from terrapilot.copilot.validator import validate
from terrapilot.core.config import ConfigBundle
from terrapilot.core.logging import get_logger

log = get_logger("copilot.explainers")


def _validator_cfg(cfg: ConfigBundle) -> dict[str, Any]:
    return dict(cfg.copilot.get("validator", {}))


def _template(cfg: ConfigBundle, task: str, facts: dict[str, Any], locale: str) -> dict[str, Any]:
    from terrapilot.llm.providers.template_provider import TemplateProvider

    tp = TemplateProvider(cfg.i18n, "llm_template", cfg.app.locales.default)
    return tp.render(task, facts, locale, None)


def explain_maintenance_alert(
    cfg: ConfigBundle,
    alert: dict[str, Any],
    manual_excerpt: str = "",
    audience: str = "operator",
    locale: str | None = None,
    gateway: Any = None,
) -> dict[str, Any]:
    """Plain-language explanation of one maintenance alert, from its evidence + one manual chunk."""
    locale = locale or cfg.app.locales.default
    labels = cfg.i18n.get(cfg.app.locales.default, {}).get("maintenance", {})
    evidence = {
        "component": labels.get("component", {}).get(alert["component"], alert["component"]),
        "tier": labels.get("tier", {}).get(alert["tier"], alert["tier"]),
        "layers": (alert.get("evidence") or {}).get("layers", []),
        "items": [
            {
                "layer": i["layer"],
                "sensor_id": i.get("sensor_id"),
                "value": i.get("value"),
                **{
                    k: v
                    for k, v in (i.get("detail") or {}).items()
                    if k
                    in (
                        "threshold",
                        "slope_per_h",
                        "limit_per_h",
                        "eta_h_p10",
                        "eta_h_p50",
                        "target_tier",
                        "item",
                        "remaining_h",
                        "code",
                    )
                },
            }
            for i in (alert.get("evidence") or {}).get("items", [])
        ],
        "eta": alert.get("eta"),
        "fault_code": alert.get("recommended_action_ref"),
        "safe_to_continue": alert.get("safe_to_continue"),
    }
    facts = {
        "component": evidence["component"],
        "tier": evidence["tier"],
        "reason": (evidence["items"][0]["layer"] if evidence["items"] else ""),
        "code": evidence["fault_code"] or "",
    }
    out = _template(cfg, "maint_explainer", facts, locale)
    source, events = "template", []
    if gateway is not None:
        try:
            res = gateway.run(
                "maint_explainer",
                {"evidence": evidence, "manual_excerpt": manual_excerpt[:2000], "audience": audience},
                locale=locale,
                template_facts=facts,
            )
            if res.provider not in ("template", "sentinel"):
                text = " ".join(str(v) for v in (res.output or {}).values())
                verdict = validate(text, evidence, _validator_cfg(cfg))
                if verdict.ok:
                    out, source = dict(res.output), "llm"
                else:
                    events.append(
                        guard_row(
                            "output", "maint_explainer_validator", "keep_template", {"reasons": verdict.reasons}, text
                        )
                    )
        except Exception as exc:
            log.warning("maint explainer failed", error=str(exc)[:200])
    # the deterministic fields are re-stamped so the explanation can never contradict them
    return {
        **out,
        "source": source,
        "tier": alert["tier"],
        "safe_to_continue": alert.get("safe_to_continue"),
        "guard_events": events,
    }


def explain_start_time(
    cfg: ConfigBundle, rec: dict[str, Any], locale: str | None = None, gateway: Any = None
) -> dict[str, Any]:
    """One sentence on why the recommended start is better, from the SHAP factor deltas only."""
    locale = locale or cfg.app.locales.default
    from zoneinfo import ZoneInfo

    from terrapilot.core import clock

    tz = ZoneInfo(str(cfg.app.site_calendar["timezone"]))
    start_local = clock.now(tz, rec["recommended_start"]).astimezone(tz).strftime("%H:%M")
    facts = {
        "recommended_start": start_local,
        "saving_min": abs(round(float(rec.get("duration_saving_vs_now_min") or 0))),
        "factors": [{"key": f["key"], "minutes": f["minutes"]} for f in rec.get("factors", [])],
    }
    out = _template(cfg, "plan_explainer", facts, locale)
    source, events = "template", []
    if gateway is not None and rec.get("recommend_change"):
        try:
            res = gateway.run("plan_explainer", {"facts": facts}, locale=locale, template_facts=facts)
            if res.provider not in ("template", "sentinel"):
                text = str((res.output or {}).get("text", ""))
                verdict = validate(text, facts, _validator_cfg(cfg))
                if verdict.ok:
                    out, source = {"text": text}, "llm"
                else:
                    events.append(
                        guard_row(
                            "output", "plan_explainer_validator", "keep_template", {"reasons": verdict.reasons}, text
                        )
                    )
        except Exception as exc:
            log.warning("plan explainer failed", error=str(exc)[:200])
    return {**out, "source": source, "guard_events": events}
