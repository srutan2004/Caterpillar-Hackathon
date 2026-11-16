"""Sandboxed rule-expression evaluation (simpleeval), shared by the rules engine and the generator.

Rule conditions reference state paths (`seat.belt_fastened`, `site.gust_ms`) and config pointers
(`manifest.motion.moving_threshold_kph`, `app.energy.soc_floor`). Nested dicts are exposed as
attribute-access namespaces so expressions read exactly as written in YAML.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from simpleeval import EvalWithCompoundTypes

SAFE_FUNCTIONS = {"abs": abs, "min": min, "max": max, "round": round}


def to_namespace(value: Any) -> Any:
    if isinstance(value, dict):
        return SimpleNamespace(**{str(k): to_namespace(v) for k, v in value.items()})
    if isinstance(value, list):
        return [to_namespace(v) for v in value]
    return value


def nest_dotted(flat: dict[str, Any]) -> dict[str, Any]:
    """{'seat.belt_fastened': True} → {'seat': {'belt_fastened': True}}"""
    out: dict[str, Any] = {}
    for key, value in flat.items():
        node = out
        parts = key.split(".")
        for part in parts[:-1]:
            node = node.setdefault(part, {})
        node[parts[-1]] = value
    return out


class ExprEvaluator:
    def __init__(self, context: dict[str, Any]):
        self._names = {k: to_namespace(v) for k, v in context.items()}

    def eval(self, expr: str, extra: dict[str, Any] | None = None) -> Any:
        names = dict(self._names)
        if extra:
            names.update({k: to_namespace(v) for k, v in extra.items()})
        return EvalWithCompoundTypes(names=names, functions=SAFE_FUNCTIONS).eval(expr.strip())
