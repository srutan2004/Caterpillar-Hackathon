"""Config loader: YAML → Pydantic schemas → ref resolution → cross-file validation (§6).

The app refuses to start on an invalid config; every issue points at the file and key.
"""

from __future__ import annotations

import ast
import copy
import json
import re
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ValidationError

from terrapilot.core import config_schema as cs
from terrapilot.core.manifest_derived import derive
from terrapilot.core.refs import RefError, get_path, has_path, is_file_ref, load_file_ref, resolve_inline_refs
from terrapilot.core.settings import get_settings

_REF_TOKEN = re.compile(r"\b(manifest|app)\.([A-Za-z_][\w]*(?:\.[A-Za-z_][\w]*)*)")


@dataclass(frozen=True)
class ConfigIssue:
    file: str
    key: str
    message: str
    level: str = "error"

    def __str__(self) -> str:
        where = f"{self.file}:{self.key}" if self.key else self.file
        return f"[{self.level}] {where} — {self.message}"


class ConfigError(Exception):
    def __init__(self, issues: list[ConfigIssue]):
        self.issues = issues
        errors = [i for i in issues if i.level == "error"]
        super().__init__(f"{len(errors)} config error(s):\n" + "\n".join(str(i) for i in errors))


@dataclass
class ConfigBundle:
    root: Path
    app: cs.AppConfig
    theme: cs.ThemeConfig
    units: cs.UnitsConfig
    i18n: dict[str, dict[str, Any]]
    llm: cs.LlmConfig
    planning: cs.PlanningConfig
    models: dict[str, Any]
    media: dict[str, Any]
    manifests: dict[str, cs.Manifest]
    manifests_raw: dict[str, dict[str, Any]]
    safety_rules: list[cs.SafetyRule]
    condition_rules: list[cs.SafetyRule]
    maintenance_rules: list[cs.MaintenanceRule]
    behavior_rules: cs.BehaviorRules
    layouts: list[cs.Layout]
    forms: dict[str, cs.FormConfig]
    nav: cs.NavConfig
    widgets: cs.WidgetsConfig
    scenarios: dict[str, cs.Scenario]
    sensor_limits: dict[str, Any]
    signatures: list[cs.Signature]
    service_intervals: dict[str, Any]
    lifecycle: cs.Lifecycle
    costs: dict[str, Any]
    fault_catalogue: list[cs.FaultCatalogueEntry]
    parts: list[cs.Part]
    datagen: dict[str, Any]
    adapters: dict[str, Any]
    sim: dict[str, Any] = field(default_factory=dict)
    copilot: dict[str, Any] = field(default_factory=dict)
    ask: dict[str, Any] = field(default_factory=dict)
    guardrails: dict[str, Any] = field(default_factory=dict)
    issues: list[ConfigIssue] = field(default_factory=list)

    # ---- helpers used by the API and generators
    def machine_classes(self) -> set[str]:
        return {m.class_ for m in self.manifests.values()}

    def manifests_for_class(self, machine_class: str) -> list[cs.Manifest]:
        return [m for m in self.manifests.values() if m.class_ == machine_class]

    def app_dict(self) -> dict[str, Any]:
        return self.app.model_dump(mode="json")

    def layout_for(self, screen: str, device: str, machine_class: str | None) -> cs.Layout | None:
        """Most specific match wins: (screen, device, class) > (screen, device) > (screen, any);
        then the devices in `app.ui.device_fallback[device]` are tried in order."""
        for candidate in [device, *self.app.ui.device_fallback.get(device, [])]:
            found = self._layout_exact(screen, candidate, machine_class)
            if found:
                return found
        return None

    def _layout_exact(self, screen: str, device: str, machine_class: str | None) -> cs.Layout | None:
        best: tuple[int, cs.Layout] | None = None
        for layout in self.layouts:
            if layout.screen != screen:
                continue
            if layout.device not in (device, "any"):
                continue
            if layout.machine_class and layout.machine_class != machine_class:
                continue
            score = (2 if layout.device == device else 0) + (1 if layout.machine_class else 0)
            if best is None or score > best[0]:
                best = (score, layout)
        return best[1] if best else None

    def fault(self, code: str) -> cs.FaultCatalogueEntry | None:
        return next((f for f in self.fault_catalogue if f.code == code), None)


# ------------------------------------------------------------------------------------------ helpers
def flatten_keys(d: dict[str, Any], prefix: str = "") -> dict[str, Any]:
    out: dict[str, Any] = {}
    for k, v in d.items():
        key = f"{prefix}.{k}" if prefix else str(k)
        if isinstance(v, dict):
            out.update(flatten_keys(v, key))
        else:
            out[key] = v
    return out


class _Loader:
    def __init__(self, root: Path):
        self.root = root
        self.issues: list[ConfigIssue] = []

    def rel(self, path: Path) -> str:
        try:
            return path.relative_to(self.root).as_posix()
        except ValueError:
            return str(path)

    def error(self, file: str, key: str, message: str) -> None:
        self.issues.append(ConfigIssue(file, key, message, "error"))

    def warn(self, file: str, key: str, message: str) -> None:
        self.issues.append(ConfigIssue(file, key, message, "warning"))

    def read(self, rel_path: str, required: bool = True) -> Any:
        path = self.root / rel_path
        if not path.is_file():
            if required:
                self.error(rel_path, "", "file is missing")
            return None
        try:
            text = path.read_text(encoding="utf-8")
            if path.suffix == ".json":
                return json.loads(text)
            return yaml.safe_load(text)
        except (yaml.YAMLError, json.JSONDecodeError) as exc:
            self.error(rel_path, "", f"parse error: {exc}")
            return None

    def read_dir(self, rel_dir: str) -> dict[str, Any]:
        base = self.root / rel_dir
        out: dict[str, Any] = {}
        if not base.is_dir():
            self.error(rel_dir, "", "directory is missing")
            return out
        for path in sorted(base.glob("*.y*ml")):
            out[self.rel(path)] = self.read(self.rel(path))
        return out

    def validate[M: BaseModel](self, model: type[M], data: Any, file: str, key_prefix: str = "") -> M | None:
        if data is None:
            return None
        try:
            return model.model_validate(data)
        except ValidationError as exc:
            for err in exc.errors():
                loc = ".".join(str(p) for p in err["loc"])
                key = f"{key_prefix}.{loc}" if key_prefix and loc else (key_prefix or loc)
                self.error(file, key, err["msg"])
            return None


# ------------------------------------------------------------------------------------------ loader
def load_config(root: Path | None = None, *, strict: bool = True) -> ConfigBundle:
    """Load and validate the whole config tree. Raises ConfigError on any error when strict."""
    root = (root or get_settings().config_dir).resolve()
    L = _Loader(root)

    app_raw = L.read("app.yaml")
    try:
        app_raw = resolve_inline_refs(app_raw, root) if app_raw is not None else None
    except RefError as exc:
        L.error("app.yaml", "", str(exc))
        app_raw = None
    app = L.validate(cs.AppConfig, app_raw, "app.yaml")
    theme = L.validate(cs.ThemeConfig, L.read("theme.yaml"), "theme.yaml")
    units = L.validate(cs.UnitsConfig, L.read("units.yaml"), "units.yaml")
    llm = L.validate(cs.LlmConfig, L.read("llm.yaml"), "llm.yaml")
    planning = L.validate(cs.PlanningConfig, L.read("planning.yaml"), "planning.yaml")
    models = L.read("models.yaml") or {}
    media = L.read("media.yaml") or {}

    i18n: dict[str, dict[str, Any]] = {}
    for rel, data in L.read_dir("i18n").items():
        i18n[Path(rel).stem] = data or {}

    # ---- maintenance
    sensor_limits = L.read("maintenance/sensor_limits.yaml") or {}
    for key, value in sensor_limits.items():
        if key != "fluid_limits":
            L.validate(cs.SensorLimit, value, "maintenance/sensor_limits.yaml", key)
    signatures = [
        s
        for i, raw in enumerate(L.read("maintenance/signatures.yaml") or [])
        if (s := L.validate(cs.Signature, raw, "maintenance/signatures.yaml", str(i)))
    ]
    service_intervals = L.read("maintenance/service_intervals.yaml") or {}
    for key, items in service_intervals.items():
        if key == "severity_factors":
            continue
        for i, item in enumerate(items or []):
            L.validate(cs.ServiceItem, item, "maintenance/service_intervals.yaml", f"{key}.{i}")
    lifecycle = L.validate(cs.Lifecycle, L.read("maintenance/lifecycle.yaml"), "maintenance/lifecycle.yaml")
    costs = L.read("maintenance/costs.yaml") or {}
    fault_catalogue = [
        f
        for i, raw in enumerate(L.read("maintenance/fault_catalogue.yaml") or [])
        if (f := L.validate(cs.FaultCatalogueEntry, raw, "maintenance/fault_catalogue.yaml", str(i)))
    ]
    parts = [
        p
        for i, raw in enumerate(L.read("maintenance/parts.yaml") or [])
        if (p := L.validate(cs.Part, raw, "maintenance/parts.yaml", str(i)))
    ]

    # ---- manifests: derive → resolve `ref:` values → validate
    manifests: dict[str, cs.Manifest] = {}
    manifests_raw: dict[str, dict[str, Any]] = {}
    for rel, raw in L.read_dir("manifests").items():
        if not isinstance(raw, dict):
            continue
        doc = copy.deepcopy(raw)
        try:
            doc.setdefault("specs", {})["derived"] = derive(doc.get("kinematics", ""), doc["specs"])
        except (KeyError, ValueError) as exc:
            L.error(rel, "specs", f"cannot derive values: {exc}")
            continue
        try:
            doc = resolve_inline_refs(doc, root)
        except RefError as exc:
            L.error(rel, "", str(exc))
            continue
        m = L.validate(cs.Manifest, doc, rel)
        if m is None:
            continue
        if Path(rel).stem != m.id:
            L.error(rel, "id", f"manifest id '{m.id}' must match the file name")
        manifests[m.id] = m
        manifests_raw[m.id] = doc

    # ---- rules
    safety_rules = [
        r
        for i, raw in enumerate(L.read("rules/safety.yaml") or [])
        if (r := L.validate(cs.SafetyRule, raw, "rules/safety.yaml", str(i)))
    ]
    condition_rules = [
        r
        for i, raw in enumerate(L.read("rules/conditions.yaml") or [])
        if (r := L.validate(cs.SafetyRule, raw, "rules/conditions.yaml", str(i)))
    ]
    maintenance_rules = [
        mr
        for i, raw in enumerate(L.read("rules/maintenance.yaml") or [])
        if (mr := L.validate(cs.MaintenanceRule, raw, "rules/maintenance.yaml", str(i)))
    ]
    behavior_rules = L.validate(cs.BehaviorRules, L.read("rules/behavior.yaml"), "rules/behavior.yaml")

    # ---- UI
    layouts = [lay for rel, raw in L.read_dir("ui/layouts").items() if (lay := L.validate(cs.Layout, raw, rel))]
    forms: dict[str, cs.FormConfig] = {}
    for rel, raw in L.read_dir("ui/forms").items():
        form = L.validate(cs.FormConfig, raw, rel)
        if form:
            forms[form.id] = form
    nav = L.validate(cs.NavConfig, L.read("ui/nav.yaml"), "ui/nav.yaml")
    widgets = L.validate(cs.WidgetsConfig, L.read("ui/widgets.yaml"), "ui/widgets.yaml")

    scenarios: dict[str, cs.Scenario] = {}
    for rel, raw in L.read_dir("scenarios").items():
        sc = L.validate(cs.Scenario, raw, rel)
        if sc:
            scenarios[sc.id] = sc

    datagen = {Path(rel).stem: data for rel, data in L.read_dir("datagen").items()}
    if "world" in datagen:
        L.validate(cs.DatagenWorld, datagen["world"], "datagen/world.yaml")
    adapters = {Path(rel).stem: data for rel, data in L.read_dir("adapters").items()}
    sim = {Path(rel).stem: data for rel, data in L.read_dir("sim").items()}
    copilot = L.read("copilot.yaml") or {}
    ask = L.read("ask.yaml") or {}
    guardrails = {Path(rel).stem: data for rel, data in L.read_dir("guardrails").items()}

    if any(x is None for x in (app, theme, units, llm, planning, lifecycle, behavior_rules, nav, widgets)):
        raise ConfigError(L.issues)

    assert app and theme and units and llm and planning and lifecycle and behavior_rules and nav and widgets
    bundle = ConfigBundle(
        root=root,
        app=app,
        theme=theme,
        units=units,
        i18n=i18n,
        llm=llm,
        planning=planning,
        models=models,
        media=media,
        manifests=manifests,
        manifests_raw=manifests_raw,
        safety_rules=safety_rules,
        condition_rules=condition_rules,
        maintenance_rules=maintenance_rules,
        behavior_rules=behavior_rules,
        layouts=layouts,
        forms=forms,
        nav=nav,
        widgets=widgets,
        scenarios=scenarios,
        sensor_limits=sensor_limits,
        signatures=signatures,
        service_intervals=service_intervals,
        lifecycle=lifecycle,
        costs=costs,
        fault_catalogue=fault_catalogue,
        parts=parts,
        datagen=datagen,
        adapters=adapters,
        sim=sim,
        copilot=copilot,
        ask=ask,
        guardrails=guardrails,
    )
    _cross_validate(bundle, L)
    bundle.issues = L.issues
    if strict and any(i.level == "error" for i in L.issues):
        raise ConfigError(L.issues)
    return bundle


# ------------------------------------------------------------------------------------------ cross checks
def _cross_validate(b: ConfigBundle, L: _Loader) -> None:
    default_locale = b.app.locales.default
    if default_locale not in b.i18n:
        L.error("i18n", "", f"default locale '{default_locale}' has no bundle")
        return
    keys = set(flatten_keys(b.i18n[default_locale]))
    app_doc = b.app_dict()

    def need_key(file: str, where: str, key: str) -> None:
        if key not in keys:
            L.error(file, where, f"i18n key '{key}' is missing from i18n/{default_locale}.yaml")

    # i18n parity across locales
    for loc, bundle in b.i18n.items():
        if loc == default_locale:
            continue
        missing = keys - set(flatten_keys(bundle))
        if missing:
            L.warn(
                f"i18n/{loc}.yaml", "", f"{len(missing)} keys missing vs {default_locale} (e.g. {sorted(missing)[:3]})"
            )
    for loc in b.app.locales.available:
        if loc not in b.i18n:
            L.error("app.yaml", "locales.available", f"locale '{loc}' has no i18n bundle")

    need_key("app.yaml", "product.tagline_key", b.app.product.tagline_key)
    for role, screen in b.app.ui.default_screen_by_role.items():
        if screen not in b.nav.screens:
            L.error("app.yaml", f"ui.default_screen_by_role.{role}", f"unknown screen '{screen}'")
        elif role in b.nav.roles and screen not in b.nav.roles[role]:
            L.error(
                "app.yaml", f"ui.default_screen_by_role.{role}", f"screen '{screen}' is not in nav for role '{role}'"
            )

    # manifests
    module_ids = {m["id"] for m in (b.datagen.get("training") or {}).get("modules", [])}
    degr = b.datagen.get("degradation") or {}
    for mid, m in b.manifests.items():
        f = f"manifests/{mid}.yaml"
        need_key(f, "name_key", m.name_key)
        need_key(f, "class", f"machine.class.{m.class_}")
        for i, ms in enumerate(m.maintenance_sensors):
            _check_file_ref(b.root, L, f, f"maintenance_sensors.{i}.limits_ref", ms.limits_ref)
        _check_file_ref(b.root, L, f, "service_intervals_ref", m.service_intervals_ref)
        for mod in m.training.required_modules:
            if module_ids and mod not in module_ids:
                L.error(f, "training.required_modules", f"unknown training module '{mod}'")
        for device, layout_path in (m.ui.get("layouts") or {}).items():
            if not (b.root / layout_path).is_file():
                L.error(f, f"ui.layouts.{device}", f"layout file '{layout_path}' does not exist")
        for comp in m.components:
            need_key(f, "components", f"maintenance.component.{comp}")
            if degr and comp not in degr.get("components", {}):
                L.error(f, "components", f"component '{comp}' has no degradation model in datagen/degradation.yaml")
        for item in (m.walkaround or {}).get("items", []):
            need_key(f, "walkaround", item["label_key"])
        soc_ref = m.energy.get("soc_floor_ref")
        if soc_ref:
            _check_expr_refs(b, L, f, "energy.soc_floor_ref", soc_ref, [m], app_doc)

    # rules
    def check_rule_common(file: str, rule: cs.SafetyRule | cs.MaintenanceRule, idx: int) -> list[cs.Manifest]:
        classes = b.machine_classes()
        unknown = set(rule.applies_to) - classes
        if unknown:
            L.error(file, f"{idx}.applies_to", f"unknown machine classes {sorted(unknown)}")
        need_key(file, f"{idx}.message_key", rule.message_key)
        applicable = [
            m
            for m in b.manifests.values()
            if m.class_ in rule.applies_to and (rule.powertrain is None or m.powertrain in rule.powertrain)
        ]
        if not applicable:
            L.error(file, f"{idx}", f"rule '{rule.id}' applies to no configured manifest")
        return applicable

    seen_ids: set[str] = set()
    for file, rules in (("rules/safety.yaml", b.safety_rules), ("rules/conditions.yaml", b.condition_rules)):
        for idx, rule in enumerate(rules):
            if rule.id in seen_ids:
                L.error(file, f"{idx}.id", f"duplicate rule id '{rule.id}'")
            seen_ids.add(rule.id)
            applicable = check_rule_common(file, rule, idx)
            exprs: dict[str, str] = {"when": rule.when}
            for k in ("for_s", "clear_after_s"):
                v = getattr(rule, k)
                if isinstance(v, str):
                    exprs[k] = v
            if rule.escalate:
                if isinstance(rule.escalate.after_s, str):
                    exprs["escalate.after_s"] = rule.escalate.after_s
                if rule.escalate.when:
                    exprs["escalate.when"] = rule.escalate.when
            for k, v in (rule.message_params or {}).items():
                exprs[f"message_params.{k}"] = v
            for key, expr in exprs.items():
                _check_expr_syntax(L, file, f"{idx}.{key}", expr)
                _check_expr_refs(b, L, file, f"{idx}.{key}", expr, applicable, app_doc)

    for idx, mrule in enumerate(b.maintenance_rules):
        applicable = check_rule_common("rules/maintenance.yaml", mrule, idx)
        _check_file_ref(b.root, L, "rules/maintenance.yaml", f"{idx}.limits_ref", mrule.limits_ref)
        for m in applicable:
            if not m.sensor(mrule.sensor):
                L.error("rules/maintenance.yaml", f"{idx}.sensor", f"manifest '{m.id}' has no sensor '{mrule.sensor}'")

    for name, ep in b.behavior_rules.episodes.items():
        applicable = [m for m in b.manifests.values() if ep.applies_to is None or m.class_ in ep.applies_to]
        need_key("rules/behavior.yaml", f"episodes.{name}", f"behavior.{name}")
        _check_expr_syntax(L, "rules/behavior.yaml", f"episodes.{name}.when", ep.when)
        for field_name, value in (("when", ep.when), ("min_s", ep.min_s), ("excessive_s", ep.excessive_s)):
            if isinstance(value, str):
                _check_expr_refs(
                    b, L, "rules/behavior.yaml", f"episodes.{name}.{field_name}", value, applicable, app_doc
                )
    for key, ref in b.behavior_rules.costs.items():
        _check_expr_refs(b, L, "rules/behavior.yaml", f"costs.{key}", ref, [], app_doc)

    # layouts
    widget_types = set(b.widgets.types)
    for layout in b.layouts:
        f = f"ui/layouts ({layout.screen}/{layout.device}/{layout.machine_class or 'any'})"
        if layout.screen not in b.nav.screens:
            L.error(f, "screen", f"unknown screen '{layout.screen}'")
        if layout.machine_class and layout.machine_class not in b.machine_classes():
            L.error(f, "machine_class", f"unknown machine class '{layout.machine_class}'")
        if layout.grid.gap_token.split(".", 1)[-1] not in b.theme.space:
            L.error(f, "grid.gap_token", f"unknown spacing token '{layout.grid.gap_token}'")
        scoped = b.manifests_for_class(layout.machine_class) if layout.machine_class else list(b.manifests.values())
        for w in layout.widgets:
            if w.type not in widget_types:
                L.error(f, f"widgets.{w.id}.type", f"unknown widget type '{w.type}' (see ui/widgets.yaml)")
            for key, ref in w.refs().items():
                _check_expr_refs(b, L, f, f"widgets.{w.id}.{key}", ref, scoped, app_doc, require_prefix=True)
            if w.sensor_ref:
                for m in scoped:
                    if not m.sensor(w.sensor_ref):
                        L.error(f, f"widgets.{w.id}.sensor_ref", f"manifest '{m.id}' has no sensor '{w.sensor_ref}'")
            for pk in ("title_key", "subtitle_key"):
                if pk in w.props:
                    need_key(f, f"widgets.{w.id}.props.{pk}", w.props[pk])
            if w.type == "FormView" and w.props.get("form_id") not in b.forms:
                L.error(f, f"widgets.{w.id}.props.form_id", f"unknown form '{w.props.get('form_id')}'")

    # nav / screens
    for sid, screen_cfg in b.nav.screens.items():
        need_key("ui/nav.yaml", f"screens.{sid}.label_key", screen_cfg.label_key)
        if not any(lay.screen == sid for lay in b.layouts):
            L.error("ui/nav.yaml", f"screens.{sid}", "no layout defines this screen")
    for role in b.app.auth.roles:
        if role not in b.nav.roles:
            L.error("ui/nav.yaml", "roles", f"role '{role}' has no navigation")
        need_key("ui/nav.yaml", f"roles.{role}", f"role.{role}")

    # forms: every title is an i18n key
    for fid, form in b.forms.items():
        f = f"ui/forms/{fid}.yaml"
        need_key(f, "title_key", form.title_key)
        need_key(f, "submit_key", form.submit_key)
        for code, key in form.errors.items():
            need_key(f, f"errors.{code}", key)
        for path, key in _schema_titles(form.schema_):
            need_key(f, f"schema.{path}", key)

    # llm tasks: prompt + schema files exist
    for name, task in b.llm.tasks.items():
        f = "llm.yaml"
        prompts = [task.prompt] if task.prompt else []
        prompts += [st["prompt"] for st in (task.subtasks or {}).values() if "prompt" in st]
        for p in prompts:
            if not (b.root / p).is_file():
                L.error(f, f"tasks.{name}.prompt", f"prompt file '{p}' does not exist")
        schema_ref = task.response_format.schema_ref if task.response_format else None
        if schema_ref and not (b.root / schema_ref).is_file():
            L.error(f, f"tasks.{name}.response_format.schema_ref", f"schema '{schema_ref}' missing")
        if task.provider == "groq" and task.model not in b.llm.limits:
            L.warn(f, f"tasks.{name}.model", f"no rate limit configured for '{task.model}'")
        if name not in b.llm.priority_lanes and task.provider == "groq":
            L.warn(f, f"tasks.{name}", "task has no priority lane (defaults to lowest)")

    # maintenance cross refs
    codes = {fc.code for fc in b.fault_catalogue}
    part_nos = {p.part_no for p in b.parts}
    for fc in b.fault_catalogue:
        need_key("maintenance/fault_catalogue.yaml", f"{fc.code}.title_key", fc.title_key)
        for pn in fc.part_numbers:
            if pn not in part_nos:
                L.error("maintenance/fault_catalogue.yaml", fc.code, f"unknown part number '{pn}'")
    for sig in b.signatures:
        if sig.fault_catalogue_ref not in codes:
            L.error("maintenance/signatures.yaml", sig.id, f"unknown fault code '{sig.fault_catalogue_ref}'")
    for mid, m in b.manifests.items():
        if m.id not in b.service_intervals:
            L.error(f"manifests/{mid}.yaml", "service_intervals_ref", "no service intervals for this manifest")

    # datagen cross refs
    _cross_validate_datagen(b, L, codes)

    # scenarios
    fixtures = b.datagen.get("demo_fixtures") or {}
    pinned_tasks = {t["id"] for t in fixtures.get("today_tasks", [])}
    pinned_ops = set(fixtures.get("operators", {}))
    site_ids = {s["id"] for s in (b.datagen.get("world") or {}).get("sites", [])}
    for sid, sc in b.scenarios.items():
        f = f"scenarios/{sid}.yaml"
        if sc.task not in pinned_tasks:
            L.error(f, "task", f"task '{sc.task}' is not pinned in datagen/demo_fixtures.yaml")
        if sc.operator not in pinned_ops:
            L.error(f, "operator", f"operator '{sc.operator}' is not pinned in datagen/demo_fixtures.yaml")
        if site_ids and sc.site not in site_ids:
            L.error(f, "site", f"unknown site '{sc.site}'")


def _cross_validate_datagen(b: ConfigBundle, L: _Loader, codes: set[str]) -> None:
    dg = b.datagen
    world, climate, ground = dg.get("world") or {}, dg.get("climate") or {}, dg.get("ground") or {}
    cycles, tasks, degr = dg.get("cycles") or {}, dg.get("tasks") or {}, dg.get("degradation") or {}
    soils = set((ground.get("soils") or {}).keys())
    for s in world.get("sites", []):
        if s.get("climate") not in (climate.get("zones") or {}):
            L.error("datagen/world.yaml", f"sites.{s['id']}.climate", f"unknown climate '{s.get('climate')}'")
        unknown = set(s.get("soil_mix", {})) - soils
        if unknown:
            L.error("datagen/world.yaml", f"sites.{s['id']}.soil_mix", f"unknown soils {sorted(unknown)}")
        if s.get("type") not in (tasks.get("task_types") or {}):
            L.error("datagen/world.yaml", f"sites.{s['id']}.type", f"no task types for site type '{s.get('type')}'")
    for entry in world.get("fleet", []):
        if entry["manifest"] not in b.manifests:
            L.error("datagen/world.yaml", "fleet", f"unknown manifest '{entry['manifest']}'")
    for scale, over in (world.get("scales") or {}).items():
        for mid in over.get("fleet_counts") or {}:
            if mid not in b.manifests:
                L.error("datagen/world.yaml", f"scales.{scale}.fleet_counts", f"unknown manifest '{mid}'")
    for site_type, by_class in (tasks.get("task_types") or {}).items():
        for cls, choices in by_class.items():
            for c in choices:
                if c["type"] not in (tasks.get("quantity") or {}):
                    L.error(
                        "datagen/tasks.yaml", f"task_types.{site_type}.{cls}", f"no quantity model for '{c['type']}'"
                    )
                if cls in ("excavator", "wheel_loader") and c["type"] not in cycles.get(cls, {}).get("t_cycle", {}).get(
                    "base_s", {}
                ):
                    L.error(
                        "datagen/cycles.yaml", f"{cls}.t_cycle.base_s", f"missing base cycle time for '{c['type']}'"
                    )
    for comp, spec in (degr.get("components") or {}).items():
        for fault in spec.get("faults", []):
            if fault["code"] not in codes:
                L.error("datagen/degradation.yaml", f"components.{comp}", f"unknown fault code '{fault['code']}'")
    sensors = degr.get("sensors") or {}
    for name, mode in (degr.get("fault_modes") or {}).items():
        if mode["sensor"] not in sensors:
            L.error("datagen/degradation.yaml", f"fault_modes.{name}.sensor", f"no sensor model for '{mode['sensor']}'")
        for code_key in ("failure_code", "detect_code"):
            if mode.get(code_key) not in codes:
                L.error(
                    "datagen/degradation.yaml",
                    f"fault_modes.{name}.{code_key}",
                    f"unknown fault code '{mode.get(code_key)}'",
                )
    for m in b.manifests.values():
        for ms in m.maintenance_sensors:
            if ms.id not in sensors:
                L.error(
                    "datagen/degradation.yaml", "sensors", f"no generator for maintenance sensor '{ms.id}' ({m.id})"
                )
    fixtures = dg.get("demo_fixtures") or {}
    for mode in fixtures.get("active_fault_modes", []):
        if mode["mode"] not in (degr.get("fault_modes") or {}):
            L.error("datagen/demo_fixtures.yaml", "active_fault_modes", f"unknown fault mode '{mode['mode']}'")
    training = dg.get("training") or {}
    for mod in training.get("modules", []):
        need = mod["title_key"]
        if need not in set(flatten_keys(b.i18n.get(b.app.locales.default, {}))):
            L.error("datagen/training.yaml", f"modules.{mod['id']}.title_key", f"i18n key '{need}' is missing")


def _schema_titles(schema: dict[str, Any], path: str = "") -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    if "title" in schema and path:
        out.append((path, schema["title"]))
    for name, sub in (schema.get("properties") or {}).items():
        out.extend(_schema_titles(sub, f"{path}.{name}" if path else name))
    for i, opt in enumerate(schema.get("oneOf") or []):
        if "title" in opt:
            out.append((f"{path}.oneOf.{i}", opt["title"]))
    return out


def _check_file_ref(root: Path, L: _Loader, file: str, key: str, target: str) -> None:
    if not is_file_ref(target):
        L.error(file, key, f"'{target}' is not a file reference")
        return
    try:
        load_file_ref(root, target)
    except RefError as exc:
        L.error(file, key, str(exc))


def _check_expr_syntax(L: _Loader, file: str, key: str, expr: str) -> None:
    try:
        ast.parse(expr.strip(), mode="eval")
    except SyntaxError as exc:
        L.error(file, key, f"expression syntax error: {exc.msg}")


def _check_expr_refs(
    b: ConfigBundle,
    L: _Loader,
    file: str,
    key: str,
    expr: str,
    manifests: list[cs.Manifest],
    app_doc: dict[str, Any],
    *,
    require_prefix: bool = False,
) -> None:
    """Every `manifest.<path>` must exist in each applicable manifest; every `app.<path>` in app.yaml."""
    tokens = list(_REF_TOKEN.finditer(expr))
    if require_prefix and not tokens:
        L.error(file, key, f"reference '{expr}' must start with 'manifest.' or 'app.'")
    for match in tokens:
        scope, path = match.group(1), match.group(2)
        if scope == "app":
            if not has_path(app_doc, path):
                L.error(file, key, f"'app.{path}' does not exist in app.yaml")
        else:
            for m in manifests:
                doc = b.manifests_raw.get(m.id, {})
                if not has_path(doc, path):
                    L.error(file, key, f"'manifest.{path}' does not exist in manifest '{m.id}'")


def resolve_ref_value(b: ConfigBundle, ref: str, manifest_id: str | None = None) -> Any:
    """Resolve a `manifest.<path>` / `app.<path>` pointer to its value (used by the API layer)."""
    scope, _, path = ref.partition(".")
    if scope == "app":
        return get_path(b.app_dict(), path)
    if scope == "manifest":
        if manifest_id is None:
            raise RefError(f"'{ref}' needs a manifest context")
        return get_path(b.manifests_raw[manifest_id], path)
    raise RefError(f"unsupported reference scope in '{ref}'")


@lru_cache(maxsize=1)
def get_config() -> ConfigBundle:
    return load_config()


def reload_config() -> ConfigBundle:
    get_config.cache_clear()
    return get_config()
