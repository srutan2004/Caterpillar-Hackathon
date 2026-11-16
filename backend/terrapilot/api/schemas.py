"""API response models (exported through OpenAPI → TypeScript)."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class LoginRequest(BaseModel):
    username: str
    pin: str


class UserOut(BaseModel):
    id: str
    name: str
    role: str
    locale: str
    site_id: str | None = None


class LoginResponse(BaseModel):
    access_token: str
    token_type: Literal["bearer"] = "bearer"
    expires_in_s: int
    user: UserOut


class NavItem(BaseModel):
    id: str
    path: str
    label_key: str
    public: bool
    chrome: bool
    requires: list[str]
    in_menu: bool


class WsConfig(BaseModel):
    machine_path: str
    fleet_path: str
    heartbeat_s: float


class UiBootstrap(BaseModel):
    default_device: str
    devices: list[str]
    default_screen: str
    alert_stack_max: int
    state_diff_throttle_ms: int


class Bootstrap(BaseModel):
    product: dict[str, Any]
    locale: str
    locales: list[str]
    features: dict[str, bool]
    theme: dict[str, Any]
    i18n: dict[str, Any]
    units: dict[str, Any]
    nav: list[NavItem]
    ws: WsConfig
    refresh: dict[str, Any]
    ui: UiBootstrap
    timezone: str = "UTC"
    user: UserOut | None = None


class ResolvedWidget(BaseModel):
    id: str
    type: str
    area: tuple[int, int, int, int]
    bind: str | None = None
    props: dict[str, Any] = {}
    resolved: dict[str, Any] = {}


class LayoutOut(BaseModel):
    screen: str
    device: str
    machine_class: str | None
    grid: dict[str, Any]
    modes: dict[str, Any]
    widgets: list[ResolvedWidget]


class FormOut(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id: str
    title_key: str
    submit_key: str
    action: dict[str, str]
    errors: dict[int, str]
    schema_: dict[str, Any] = Field(alias="schema")
    ui_schema: dict[str, Any]


class MachineOut(BaseModel):
    id: str
    site_id: str
    manifest_id: str
    machine_class: str
    model_key: str
    powertrain: str
    status: str
    hour_meter: float


class GatingModule(BaseModel):
    module_id: str
    title_key: str | None
    status: Literal["valid", "expiring", "grace", "expired", "missing"]
    expires_at: datetime | None = None


class GatingResult(BaseModel):
    status: Literal["full", "restricted", "blocked"]
    modules: list[GatingModule]


class MachineSelectRequest(BaseModel):
    machine_id: str | None = None
    qr_token: str | None = None


class MachineSelectResponse(BaseModel):
    machine: MachineOut
    manifest: dict[str, Any]
    gating: GatingResult
