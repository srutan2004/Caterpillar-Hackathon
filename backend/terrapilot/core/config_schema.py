"""Pydantic schemas for every YAML file under config/ (§6).

Schemas use `extra="forbid"` wherever the shape is stable so a typo in a key fails validation with a
file/key pointer instead of being silently ignored. Deeply nested generator coefficient blocks are
validated structurally in `config.py` cross-checks rather than typed field-by-field.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

Tier = Literal["advisory", "caution", "warning"]
MaintTier = Literal["monitor", "service_soon", "stop"]
Role = Literal["anonymous", "operator", "supervisor", "instructor", "technician", "admin"]
Device = Literal["cab", "mobile", "desk", "any"]


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)


class Loose(BaseModel):
    model_config = ConfigDict(extra="allow", populate_by_name=True)


# ---------------------------------------------------------------- app.yaml
class ProductCfg(Strict):
    name: str
    tagline_key: str
    version: str


class LocalesCfg(Strict):
    default: str
    available: list[str]


class AuthCfg(Strict):
    jwt_algorithm: str
    token_ttl_min: int = Field(gt=0)
    roles: list[str]
    pin_hash: dict[str, Any]


class WsCfg(Strict):
    machine_path: str
    fleet_path: str
    heartbeat_s: float = Field(gt=0)


class ApiCfg(Strict):
    prefix: str
    ws: WsCfg


class UiCfg(Strict):
    default_device: Literal["cab", "mobile", "desk"]
    devices: list[Literal["cab", "mobile", "desk"]]
    device_fallback: dict[str, list[str]] = {}
    default_screen_by_role: dict[str, str]
    alert_stack_max: int = Field(gt=0)
    state_diff_throttle_ms: int = Field(gt=0)


class AppConfig(Strict):
    product: ProductCfg
    locales: LocalesCfg
    features: dict[str, bool]
    auth: AuthCfg
    api: ApiCfg
    refresh: dict[str, Any]
    ui: UiCfg
    latency_budgets_ms: dict[str, float]
    energy: dict[str, float]
    costs: dict[str, Any]
    blackbox: dict[str, float]
    edge: dict[str, float] = {}
    telemetry_retention: dict[str, float]
    site_calendar: dict[str, Any] = {}
    cab_notes: dict[str, Any] = {}
    fatigue: dict[str, Any] = {}
    wbv: dict[str, Any] = {}
    p2p: dict[str, Any] = {}
    walkaround_media_dir: str = "media/walkaround"


# ---------------------------------------------------------------- theme.yaml / units.yaml
class ThemeConfig(Strict):
    default_variant: str
    variants: dict[str, dict[str, dict[str, Any]]]
    space: dict[str, str]
    radius: dict[str, str]
    border_width: dict[str, str]
    font: dict[str, Any]
    target: dict[str, str]
    layout: dict[str, str]
    motion: dict[str, str]
    alert_behaviour: dict[str, dict[str, Any]]
    device_theme: dict[str, str]
    breakpoints: dict[str, str]

    @model_validator(mode="after")
    def _check(self) -> ThemeConfig:
        if self.default_variant not in self.variants:
            raise ValueError(f"default_variant '{self.default_variant}' is not a defined variant")
        for device, variant in self.device_theme.items():
            if variant not in self.variants:
                raise ValueError(f"device_theme.{device} references unknown variant '{variant}'")
        tiers = {"advisory", "caution", "warning"}
        for name, tokens in self.variants.items():
            missing = tiers - set(tokens.get("alert", {}))
            if missing:
                raise ValueError(f"variant '{name}' is missing alert tiers {sorted(missing)}")
        return self


class UnitQuantity(Strict):
    unit: str
    symbol: str
    factor: float
    precision: int = Field(ge=0)
    offset: float = 0.0


class UnitSystem(Strict):
    quantities: dict[str, UnitQuantity]


class UnitsConfig(Strict):
    systems: dict[str, UnitSystem]
    default_system: str
    system_by_locale: dict[str, str]


# ---------------------------------------------------------------- manifests
class SensorDef(Strict):
    id: str
    type: Literal["analog", "bool", "geo", "stream"] = "analog"
    unit: str | None = None
    range: tuple[float, float] | None = None
    hz: float | None = None
    bands: dict[str, tuple[float, float]] | None = None
    per_position: list[str] | None = None

    @model_validator(mode="after")
    def _check(self) -> SensorDef:
        if self.type == "analog" and self.unit is None:
            raise ValueError(f"sensor '{self.id}': analog sensors need a unit")
        return self


class MaintenanceSensorRef(Strict):
    id: str
    component: str
    limits_ref: str
    forecast: bool = False
    normalise_by: str | None = None


class TrainingReq(Strict):
    required_modules: list[str]
    cert_validity_days: int = Field(gt=0)
    expiry_grace_days: int = Field(ge=0)


class Manifest(Strict):
    id: str
    class_: str = Field(alias="class")
    name_key: str
    powertrain: Literal["diesel", "electric", "hybrid"]
    kinematics: str
    id_prefix: str
    specs: dict[str, Any]
    sensors: list[SensorDef]
    envelopes: dict[str, Any]
    proximity: dict[str, Any]
    motion: dict[str, float]
    seatbelt: dict[str, float]
    idle: dict[str, float]
    pre_shift: dict[str, bool]
    components: list[str]
    maintenance_sensors: list[MaintenanceSensorRef]
    service_intervals_ref: str
    energy: dict[str, Any]
    training: TrainingReq
    walkaround: Any
    controls: Any
    knowledge_scope: list[str]
    ui: dict[str, Any]

    @model_validator(mode="after")
    def _check(self) -> Manifest:
        ids = [s.id for s in self.sensors]
        dupes = {i for i in ids if ids.count(i) > 1}
        if dupes:
            raise ValueError(f"duplicate sensor ids: {sorted(dupes)}")
        for ms in self.maintenance_sensors:
            if ms.id not in ids:
                raise ValueError(f"maintenance sensor '{ms.id}' is not declared in sensors")
            if ms.component not in self.components:
                raise ValueError(f"maintenance sensor '{ms.id}' references unknown component '{ms.component}'")
        return self

    def sensor(self, sensor_id: str) -> SensorDef | None:
        return next((s for s in self.sensors if s.id == sensor_id), None)


# ---------------------------------------------------------------- rules
class Escalation(Strict):
    to: Tier
    after_s: float | str | None = None
    when: str | None = None


class SafetyRule(Strict):
    id: str
    applies_to: list[str]
    powertrain: list[str] | None = None
    inputs: list[str]
    when: str
    for_s: float | str = 0
    clear_after_s: float | str = 0
    severity: Tier
    escalate: Escalation | None = None
    message_key: str
    message_params: dict[str, str] | None = None
    actions: list[str] = []
    copilot_priority: int = Field(ge=0, le=100)


class MaintenanceRule(Strict):
    id: str
    applies_to: list[str]
    powertrain: list[str] | None = None
    sensor: str
    limits_ref: str
    tier: MaintTier
    severity: Tier
    message_key: str
    copilot_priority: int = Field(ge=0, le=100)


class BehaviorEpisode(Strict):
    applies_to: list[str] | None = None
    when: str
    min_s: float | str
    excessive_s: float | str | None = None


class BehaviorRules(Strict):
    episodes: dict[str, BehaviorEpisode]
    statistical: dict[str, float]
    ml: dict[str, Any]
    costs: dict[str, str]
    adaptive_assignment: list[dict[str, Any]]


# ---------------------------------------------------------------- UI
class GridCfg(Strict):
    columns: int = Field(gt=0)
    rows: int = Field(gt=0)
    gap_token: str


class ModeCfg(Strict):
    hide: list[str] = []
    trigger: str | None = None


class WidgetCfg(Strict):
    id: str
    type: str
    area: tuple[int, int, int, int]
    bind: str | None = None
    props: dict[str, Any] = {}
    max_visible_ref: str | None = None
    bands_ref: str | None = None
    sensor_ref: str | None = None
    zones_ref: str | None = None

    def refs(self) -> dict[str, str]:
        return {
            k: v
            for k, v in {
                "max_visible_ref": self.max_visible_ref,
                "bands_ref": self.bands_ref,
                "zones_ref": self.zones_ref,
            }.items()
            if v
        }


class Layout(Strict):
    screen: str
    device: Device
    machine_class: str | None = None
    grid: GridCfg
    modes: dict[str, ModeCfg]
    widgets: list[WidgetCfg]

    @model_validator(mode="after")
    def _check(self) -> Layout:
        ids = [w.id for w in self.widgets]
        if len(ids) != len(set(ids)):
            raise ValueError("duplicate widget ids")
        for w in self.widgets:
            col, row, cspan, rspan = w.area
            if col < 1 or row < 1 or cspan < 1 or rspan < 1:
                raise ValueError(f"widget '{w.id}': area values must be >= 1")
            if col + cspan - 1 > self.grid.columns or row + rspan - 1 > self.grid.rows:
                raise ValueError(
                    f"widget '{w.id}': area {list(w.area)} exceeds grid {self.grid.columns}x{self.grid.rows}"
                )
        occupied: dict[tuple[int, int], str] = {}
        for w in self.widgets:
            col, row, cspan, rspan = w.area
            for c in range(col, col + cspan):
                for r in range(row, row + rspan):
                    if (c, r) in occupied:
                        raise ValueError(f"widget '{w.id}' overlaps '{occupied[(c, r)]}' at column {c}, row {r}")
                    occupied[(c, r)] = w.id
        for mode, cfg in self.modes.items():
            unknown = set(cfg.hide) - set(ids)
            if unknown:
                raise ValueError(f"mode '{mode}' hides unknown widgets {sorted(unknown)}")
        return self


class ScreenCfg(Strict):
    path: str
    label_key: str
    public: bool = False
    chrome: bool = True
    requires: list[str] = []


class NavConfig(Strict):
    screens: dict[str, ScreenCfg]
    roles: dict[str, list[str]]
    menu_hidden: list[str] = []

    @model_validator(mode="after")
    def _check(self) -> NavConfig:
        for role, screens in self.roles.items():
            unknown = set(screens) - set(self.screens)
            if unknown:
                raise ValueError(f"role '{role}' references unknown screens {sorted(unknown)}")
        return self


class FormConfig(Strict):
    id: str
    title_key: str
    submit_key: str
    action: dict[str, str]
    errors: dict[int, str] = {}
    workflow_states: list[str] | None = None
    autofill: list[str] = []
    schema_: dict[str, Any] = Field(alias="schema")
    ui_schema: dict[str, Any] = {}


class WidgetsConfig(Strict):
    types: list[str]


# ---------------------------------------------------------------- llm.yaml
class ProviderCfg(Loose):
    pass


class ResponseFormat(Strict):
    type: Literal["json_schema", "json_object", "text"]
    schema_ref: str | None = None


class LlmTask(Strict):
    provider: Literal["groq", "ollama", "local", "template"]
    model: str
    temperature: float | None = None
    max_tokens: int | None = None
    timeout_ms: int | None = None
    retry: bool = True
    stream: bool = False
    response_format: ResponseFormat | None = None
    prompt: str | None = None
    cache: dict[str, Any] | None = None
    fallback: list[str] = []
    samples: int | None = None
    max_image_px: int | None = None
    fail_mode: Literal["open", "closed"] | None = None
    threshold: float | None = None
    batch_api: bool = False
    params: dict[str, Any] = {}  # provider-specific request params (e.g. reasoning_effort)
    subtasks: dict[str, dict[str, Any]] | None = None


class LlmLimit(Strict):
    rpm: int = Field(gt=0)
    tpm: int = Field(gt=0)


class LlmConfig(Strict):
    profile_env: str
    providers: dict[str, ProviderCfg]
    limits: dict[str, LlmLimit]
    priority_lanes: dict[str, int]
    low_headroom_fraction: float = Field(ge=0, le=1)
    resilience: dict[str, Any]
    cache: dict[str, Any]
    tasks: dict[str, LlmTask]
    offline_overrides: dict[str, dict[str, Any]] = {}
    redaction: dict[str, Any]
    content: dict[str, Any]

    @model_validator(mode="after")
    def _check(self) -> LlmConfig:
        for name, task in self.tasks.items():
            for fb in task.fallback:
                if ":" in fb and fb.split(":", 1)[0] not in self.providers:
                    raise ValueError(f"task '{name}': fallback '{fb}' uses unknown provider")
        return self


# ---------------------------------------------------------------- planning / models / media
class PlanningConfig(Loose):
    refresh_min: float
    start_time: dict[str, Any]
    readiness: dict[str, Any]
    maintenance_window: dict[str, Any]
    weather_windows: dict[str, Any]
    energy_per_task: dict[str, Any] = {}
    service_due: dict[str, Any] = {}
    shift_view: dict[str, Any] = {}

    @field_validator("readiness")
    @classmethod
    def _weights_sum(cls, v: dict[str, Any]) -> dict[str, Any]:
        total = sum(float(x) for x in v.get("weights", {}).values())
        if abs(total - 1.0) > 1e-6:
            raise ValueError(f"readiness.weights must sum to 1.0 (got {total:.3f})")
        return v


class ScenarioEvent(Loose):
    t: float


class Scenario(Loose):
    id: str
    machine: str
    operator: str
    site: str
    task: str
    duration_s: float | None = None
    tick_hz: float | None = None
    timeline: list[ScenarioEvent] = []
    expect: dict[str, Any] = {}


class FaultCatalogueEntry(Strict):
    code: str
    component: str
    severity: MaintTier
    classes: list[str]
    title_key: str
    description: str
    probable_causes: list[str]
    checks: list[str]
    safe_to_continue: Literal["yes", "limited", "no"]
    manual_ref: dict[str, str]
    part_numbers: list[str]


class Part(Strict):
    part_no: str
    component_kind: str
    description: str
    price: float = Field(ge=0)
    lead_time_days: int = Field(ge=0)
    stock: int = Field(ge=0)


class SensorLimit(Loose):
    unit: str
    direction: Literal["high", "low"]
    bands: dict[str, tuple[float | None, float | None]] | None = None
    debounce_s: float | None = None


class Signature(Strict):
    id: str
    component: str
    all_of: list[str]
    window_h: float = 24
    tier: MaintTier
    fault_catalogue_ref: str


class ServiceItem(Strict):
    item: str
    every_h: float = Field(gt=0)
    work: list[str]
    est_h: float = Field(gt=0)


class Lifecycle(Loose):
    states: list[str]
    initial: str
    transitions: dict[str, list[str]]
    tiers: list[str]

    @model_validator(mode="after")
    def _check(self) -> Lifecycle:
        for src, dsts in self.transitions.items():
            if src not in self.states or any(d not in self.states for d in dsts):
                raise ValueError(f"transition from '{src}' references unknown states")
        return self


class DatagenWorld(Loose):
    seed: int
    history_days: int = Field(gt=0)
    future_days: int = Field(ge=0)
    timezone: str
    shift: dict[str, Any]
    sites: list[dict[str, Any]]
    fleet: list[dict[str, Any]]
    operators: dict[str, Any]
    resolution: dict[str, Any]
    scales: dict[str, dict[str, Any]]

    @model_validator(mode="after")
    def _check(self) -> DatagenWorld:
        site_ids = {s["id"] for s in self.sites}
        for entry in self.fleet:
            placed = sum(entry.get("sites", {}).values())
            if placed != entry["count"]:
                raise ValueError(f"fleet '{entry['manifest']}': site counts sum to {placed}, count is {entry['count']}")
            unknown = set(entry.get("sites", {})) - site_ids
            if unknown:
                raise ValueError(f"fleet '{entry['manifest']}': unknown sites {sorted(unknown)}")
        for s in self.sites:
            mix = s.get("soil_mix", {})
            if abs(sum(mix.values()) - 1.0) > 1e-6:
                raise ValueError(f"site '{s['id']}': soil_mix must sum to 1.0")
        return self
