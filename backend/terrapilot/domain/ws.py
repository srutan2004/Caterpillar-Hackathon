"""WebSocket message contract (§9.3). Pydantic → JSON Schema → TypeScript via OpenAPI."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from terrapilot.domain.models import Advisory, AlertEvent, MaintenanceTier, TaskState


class _Msg(BaseModel):
    model_config = ConfigDict(extra="forbid")
    ts: datetime


class StateDiffMessage(_Msg):
    type: Literal["state_diff"] = "state_diff"
    machine_id: str
    seq: int
    changes: dict[str, Any]
    full: bool = False


class AlertMessage(_Msg):
    type: Literal["alert"] = "alert"
    event: AlertEvent


class AdvisoryMessage(_Msg):
    type: Literal["advisory"] = "advisory"
    advisory: Advisory


class TaskUpdateMessage(_Msg):
    type: Literal["task_update"] = "task_update"
    task: TaskState


class NoticeMessage(_Msg):
    type: Literal["notice"] = "notice"
    code: str
    message_key: str
    params: dict[str, Any] = {}


class MaintenanceAlertMessage(_Msg):
    type: Literal["maintenance_alert"] = "maintenance_alert"
    phase: Literal["open", "update", "clear"]
    alert_id: str
    machine_id: str
    component: str
    tier: MaintenanceTier


class RecommendationMessage(_Msg):
    type: Literal["recommendation"] = "recommendation"
    task_id: str | None = None
    machine_id: str | None = None
    kind: Literal["start_time", "readiness"]
    payload: dict[str, Any]


class PlanUpdateMessage(_Msg):
    type: Literal["plan_update"] = "plan_update"
    plan_id: str
    payload: dict[str, Any]


WsMessage = Annotated[
    StateDiffMessage
    | AlertMessage
    | AdvisoryMessage
    | TaskUpdateMessage
    | NoticeMessage
    | MaintenanceAlertMessage
    | RecommendationMessage
    | PlanUpdateMessage,
    Field(discriminator="type"),
]


class WsEnvelope(BaseModel):
    """Wrapper used only to publish the union's JSON Schema through OpenAPI."""

    message: WsMessage
