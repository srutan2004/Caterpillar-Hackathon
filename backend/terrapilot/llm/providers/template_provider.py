"""TemplateProvider: deterministic i18n templates, the final fallback for every narrating task (§2.2, §12.1).

Template shapes under `llm_template.<task>` in the i18n bundle:
* a string                        → {"text": rendered}
* a map with a `default` key      → per-category templates; picks `<category>` or `default` → {"text": ...}
* any other map                   → per-output-field templates (e.g. maint_explainer) → {field: rendered}
"""

from __future__ import annotations

import re
from typing import Any

from terrapilot.core.refs import RefError, get_path

_PLACEHOLDER = re.compile(r"\{\{\s*([\w.]+)\s*\}\}")


def render_placeholders(template: str, facts: dict[str, Any]) -> str:
    def sub(match: re.Match[str]) -> str:
        try:
            value = get_path(facts, match.group(1))
        except RefError:
            return match.group(0)
        return f"{value:g}" if isinstance(value, float) else str(value)

    return _PLACEHOLDER.sub(sub, template)


class TemplateProvider:
    name = "template"

    def __init__(self, i18n: dict[str, dict[str, Any]], namespace: str, default_locale: str):
        self.i18n = i18n
        self.namespace = namespace
        self.default_locale = default_locale

    def has_template(self, task: str) -> bool:
        return self._node(task, None) is not None

    def _node(self, task: str, locale: str | None) -> Any:
        for loc in (locale, self.default_locale):
            if loc and loc in self.i18n:
                try:
                    return get_path(self.i18n[loc], f"{self.namespace}.{task}")
                except RefError:
                    continue
        return None

    def render(
        self, task: str, facts: dict[str, Any], locale: str | None = None, category: str | None = None
    ) -> dict[str, Any]:
        node = self._node(task, locale)
        if node is None:
            raise KeyError(f"no template for task '{task}'")
        values = {"category": category, **facts} if category else facts
        if isinstance(node, str):
            return {"text": render_placeholders(node, values)}
        if isinstance(node, dict) and "default" in node:
            chosen = node.get(category or "default") or node["default"]
            return {"text": render_placeholders(str(chosen), values)}
        if isinstance(node, dict):
            return {k: render_placeholders(str(v), values) for k, v in node.items()}
        raise KeyError(f"template for task '{task}' has an unsupported shape")

    def list_models(self) -> list[str]:
        return ["template"]
