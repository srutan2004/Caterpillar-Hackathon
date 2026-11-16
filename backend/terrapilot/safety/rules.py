"""Rules engine (§6.2, §10.4). Conditions are simpleeval expressions over the fused state, `manifest.*` and
`app.*`. Each rule has a debounce (`for_s`), clear hysteresis (`clear_after_s`) and optional escalation
(`after_s` or a `when` expression). Stop-tier maintenance limits (layer A) run here too, so they work offline.
"""

from __future__ import annotations

import math
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from simpleeval import EvalWithCompoundTypes

from terrapilot.core.config_schema import MaintenanceRule, SafetyRule
from terrapilot.core.expr import SAFE_FUNCTIONS, to_namespace
from terrapilot.domain.models import Alert, AlertEvent, Severity

SEVERITY_RANK: dict[str, int] = {"advisory": 0, "caution": 1, "warning": 2}
PARAM_DECIMALS = 1


def _num(value: float | str, names: dict[str, Any]) -> float:
    if isinstance(value, int | float):
        return float(value)
    return float(EvalWithCompoundTypes(names=names, functions=SAFE_FUNCTIONS).eval(value.strip()))


@dataclass
class _RuleState:
    true_since: float | None = None
    false_since: float | None = None
    alert: Alert | None = None


@dataclass
class CompiledRule:
    id: str
    when: str
    for_s: float
    clear_after_s: float
    severity: Severity
    escalate_to: Severity | None
    escalate_after_s: float | None
    escalate_when: str | None
    message_key: str
    message_params: dict[str, str]
    actions: list[str]
    priority: int
    state: _RuleState = field(default_factory=_RuleState)


class RulesEngine:
    """One engine per machine. `evaluate` is called every tick with the fused state as nested dicts."""

    def __init__(
        self,
        machine_id: str,
        manifest: dict[str, Any],
        app: dict[str, Any],
        rules: list[SafetyRule],
        maintenance_rules: list[MaintenanceRule],
        sensor_limits: dict[str, Any],
        machine_class: str,
        powertrain: str,
    ):
        self.machine_id = machine_id
        self._static = {"manifest": to_namespace(manifest), "app": to_namespace(app)}
        self.rules: list[CompiledRule] = []
        for r in rules:
            if machine_class not in r.applies_to or (r.powertrain and powertrain not in r.powertrain):
                continue
            esc = r.escalate
            self.rules.append(
                CompiledRule(
                    id=r.id,
                    when=r.when,
                    for_s=_num(r.for_s, self._static),
                    clear_after_s=_num(r.clear_after_s, self._static),
                    severity=r.severity,
                    escalate_to=esc.to if esc else None,
                    escalate_after_s=_num(esc.after_s, self._static) if esc and esc.after_s is not None else None,
                    escalate_when=esc.when if esc else None,
                    message_key=r.message_key,
                    message_params=dict(r.message_params or {}),
                    actions=list(r.actions),
                    priority=r.copilot_priority,
                )
            )
        self.maint: list[tuple[MaintenanceRule, dict[str, Any], _RuleState]] = []
        for mr in maintenance_rules:
            if machine_class not in mr.applies_to or (mr.powertrain and powertrain not in mr.powertrain):
                continue
            key = mr.limits_ref.split("#", 1)[1]
            self.maint.append((mr, sensor_limits[key], _RuleState()))
        self._counter = 0
        self._run = format(int(time.time()), "x")

    # ------------------------------------------------------------------ evaluation helpers
    def _names(self, state: dict[str, Any]) -> dict[str, Any]:
        return {**{k: to_namespace(v) for k, v in state.items()}, **self._static}

    @staticmethod
    def _truthy(expr: str, names: dict[str, Any]) -> bool:
        try:
            return bool(EvalWithCompoundTypes(names=names, functions=SAFE_FUNCTIONS).eval(expr.strip()))
        except Exception:
            return False  # missing input (sensor absent / no person tracked) → condition not met

    def _params(self, rule: CompiledRule, names: dict[str, Any]) -> dict[str, Any]:
        out: dict[str, Any] = {}
        for k, expr in rule.message_params.items():
            try:
                v = EvalWithCompoundTypes(names=names, functions=SAFE_FUNCTIONS).eval(expr.strip())
            except Exception:
                continue
            out[k] = round(float(v), PARAM_DECIMALS) if isinstance(v, int | float) and not isinstance(v, bool) else v
        return out

    def _new_id(self) -> str:
        self._counter += 1
        return f"AL-{self.machine_id}-{self._run}-{self._counter:05d}"

    # ------------------------------------------------------------------ main
    def evaluate(self, state: dict[str, Any], now: datetime) -> list[AlertEvent]:
        t = now.timestamp()
        names = self._names(state)
        events: list[AlertEvent] = []
        for rule in self.rules:
            events.extend(self._step(rule, self._truthy(rule.when, names), names, t, now))
        for mr, limits, st in self.maint:
            value = _lookup(state, mr.sensor)
            active = value is not None and in_stop_band(float(value), limits, state)
            proxy = CompiledRule(
                id=mr.id,
                when="",
                for_s=float(limits.get("debounce_s", 0)),
                clear_after_s=float(limits.get("debounce_s", 0)),
                severity=mr.severity,
                escalate_to=None,
                escalate_after_s=None,
                escalate_when=None,
                message_key=mr.message_key,
                message_params={},
                actions=["log_event"],
                priority=mr.copilot_priority,
                state=st,
            )
            evs = self._step(proxy, active, names, t, now)
            for e in evs:
                e.alert.params = {
                    "component": mr.sensor,
                    "reason": mr.tier,
                    "value": None if value is None else round(float(value), 1),
                }
            events.extend(evs)
        return events

    def _step(
        self, rule: CompiledRule, active: bool, names: dict[str, Any], t: float, now: datetime
    ) -> list[AlertEvent]:
        st = rule.state
        out: list[AlertEvent] = []
        if active:
            st.false_since = None
            st.true_since = st.true_since if st.true_since is not None else t
            if st.alert is None and t - st.true_since >= rule.for_s:
                st.alert = Alert(
                    id=self._new_id(),
                    machine_id=self.machine_id,
                    rule_id=rule.id,
                    severity=rule.severity,
                    opened_at=now,
                    message_key=rule.message_key,
                    params=self._params(rule, names),
                    copilot_priority=rule.priority,
                )
                out.append(AlertEvent(phase="open", alert=st.alert.model_copy()))
            elif st.alert is not None:
                should_escalate = (
                    rule.escalate_to is not None
                    and st.alert.escalated_at is None
                    and (
                        (rule.escalate_after_s is not None and t - st.true_since >= rule.for_s + rule.escalate_after_s)
                        or (rule.escalate_when is not None and self._truthy(rule.escalate_when, names))
                    )
                )
                if should_escalate and rule.escalate_to is not None:
                    st.alert.severity = rule.escalate_to
                    st.alert.escalated_at = now
                    st.alert.params = self._params(rule, names)
                    out.append(AlertEvent(phase="escalate", alert=st.alert.model_copy()))
                else:
                    params = self._params(rule, names)
                    if params != st.alert.params:
                        st.alert.params = params
                        out.append(AlertEvent(phase="update", alert=st.alert.model_copy()))
        else:
            st.true_since = None
            if st.alert is not None:
                st.false_since = st.false_since if st.false_since is not None else t
                if t - st.false_since >= rule.clear_after_s:
                    st.alert.cleared_at = now
                    out.append(AlertEvent(phase="clear", alert=st.alert.model_copy()))
                    st.alert = None
                    st.false_since = None
        return out

    def clear_all(self, now: datetime) -> list[AlertEvent]:
        """End of session (scenario stop, machine off): close every open alert so no stale state lingers."""
        out: list[AlertEvent] = []
        states = [r.state for r in self.rules] + [st for _, _, st in self.maint]
        for st in states:
            if st.alert is not None:
                st.alert.cleared_at = now
                out.append(AlertEvent(phase="clear", alert=st.alert.model_copy()))
                st.alert = None
                st.true_since = st.false_since = None
        return out

    def open_alerts(self) -> list[Alert]:
        alerts = [r.state.alert for r in self.rules if r.state.alert is not None]
        alerts += [st.alert for _, _, st in self.maint if st.alert is not None]
        return sorted(alerts, key=lambda a: (-SEVERITY_RANK[a.severity], -a.copilot_priority))

    def actions_for(self, rule_id: str) -> list[str]:
        return next((r.actions for r in self.rules if r.id == rule_id), [])


def _lookup(state: dict[str, Any], dotted: str) -> Any:
    node: Any = state
    for part in dotted.split("."):
        if not isinstance(node, dict) or part not in node:
            return None
        node = node[part]
    return node


def in_stop_band(value: float, limits: dict[str, Any], state: dict[str, Any]) -> bool:
    """Layer A stop band: plain bands, curve margins (oil pressure vs rpm) or boolean channels."""
    if "boolean" in limits:
        return bool(value) and limits["boolean"].get("true_tier") == "stop"
    if "curve" in limits:
        rpm = _lookup(state, "engine.rpm")
        if rpm is None:
            return False
        curve = limits["curve"]
        xs, ys = [float(x) for x in curve["rpm"]], [float(y) for y in curve["min_kpa"]]
        min_allowed = _interp(float(rpm), xs, ys)
        margin = (value - min_allowed) / min_allowed if min_allowed else math.inf
        return margin <= float(limits["bands_on_margin"]["stop"])
    lo, hi = limits["bands"]["stop"]
    return (lo is None or value >= lo) and (hi is None or value < hi)


def _interp(x: float, xs: list[float], ys: list[float]) -> float:
    if x <= xs[0]:
        return ys[0]
    for (x0, y0), (x1, y1) in zip(zip(xs, ys, strict=True), zip(xs[1:], ys[1:], strict=True), strict=False):
        if x <= x1:
            return y0 + (y1 - y0) * (x - x0) / (x1 - x0)
    return ys[-1]
