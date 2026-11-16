"""Core domain models (§3.2 live loop, §8 schema, §12.1 copilot). All values are SI unless named."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

Severity = Literal["advisory", "caution", "warning"]
MaintenanceTier = Literal["monitor", "service_soon", "stop"]
AlertPhase = Literal["open", "update", "escalate", "clear"]
TaskStatus = Literal["planned", "in_progress", "completed", "carried_over", "cancelled"]
Powertrain = Literal["diesel", "electric", "hybrid"]


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=False)


class RawFrame(Contract):
    """One simulator/sensor tick published to Redis stream `tp:raw:{machine_id}`."""

    machine_id: str
    ts: datetime
    seq: int = Field(ge=0)
    signals: dict[str, float | bool | str | None]
    source: Literal["sim", "replay", "external"] = "sim"
    # person/object detections from vision adapters or the simulator, in site coordinates (m)
    detections: list[dict[str, Any]] = []
    # site conditions (weather, lux) as seen by the edge at this tick
    env: dict[str, float] = {}


class ProximityTrack(Contract):
    track_id: str
    kind: Literal["person", "machine", "object"]
    position_m: tuple[float, float]
    velocity_ms: tuple[float, float]
    distance_m: float
    ttc_s: float | None = None
    cpa_m: float | None = None
    zone: Severity | None = None
    ppe: dict[str, bool] | None = None
    static: bool = False


class StabilityState(Contract):
    margin: float
    limiting_axis: str
    hint: Literal["reduce_reach", "stop_slew", "lower_load", "none"] = "none"
    sensitivity: dict[str, float] = {}


class GeofenceState(Contract):
    utility_id: str | None = None
    utility_distance_m: float | None = None
    utility_clearance_m: float | None = None
    overhead_id: str | None = None
    overhead_distance_m: float | None = None
    overhead_clearance_m: float | None = None


class EnergyState(Contract):
    powertrain: Powertrain
    fuel_pct: float | None = None
    soc: float | None = None
    projected_min_soc: float | None = None
    power_mode: Literal["eco", "standard", "high"] | None = None


class TaskState(Contract):
    task_id: str
    phase: str
    progress_qty: float
    quantity: float
    unit: str
    etc: datetime | None = None
    etc_p10: datetime | None = None
    etc_p90: datetime | None = None


class MachineState(Contract):
    """Fused digital-twin state for one machine at one tick (§3.2 step 2)."""

    machine_id: str
    manifest_id: str
    ts: datetime
    signals: dict[str, float | bool | str | None] = {}
    bucket_tip_m: tuple[float, float, float] | None = None
    grade_deviation_m: float | None = None
    stability: StabilityState | None = None
    proximity: list[ProximityTrack] = []
    geofence: GeofenceState = GeofenceState()
    energy: EnergyState | None = None
    task: TaskState | None = None
    idle_s: float = 0.0
    wbv_dose_ms2: float | None = None
    perclos: float | None = None


class Alert(Contract):
    id: str
    machine_id: str
    rule_id: str
    severity: Severity
    opened_at: datetime
    escalated_at: datetime | None = None
    cleared_at: datetime | None = None
    acked_by: str | None = None
    message_key: str
    params: dict[str, Any] = {}
    copilot_priority: int = 0


class AlertEvent(Contract):
    phase: AlertPhase
    alert: Alert


class Candidate(Contract):
    """An advisory candidate produced by a deterministic generator (§12.1)."""

    key: str
    category: str
    severity: Severity
    base_priority: float
    facts: dict[str, Any]
    template_key: str
    ttl_s: float


class Advisory(Contract):
    id: str
    category: str
    severity: Severity
    text: str
    source: Literal["llm", "template"]
    facts: dict[str, Any]
    expires_in_s: float
    priority: float


class BehaviorEvent(Contract):
    id: str
    machine_id: str
    operator_id: str
    kind: str
    start_ts: datetime
    end_ts: datetime
    metrics: dict[str, float] = {}
    cost: dict[str, float] = {}
    detector: Literal["rule", "stat", "ml"] = "rule"
    score: float | None = None


class Task(Contract):
    id: str
    project_id: str
    zone_id: str | None = None
    machine_class: str
    type: str
    quantity: float
    unit: str
    design_ref: str | None = None
    planned_start: datetime
    planned_end: datetime
    deadline: datetime | None = None
    priority: int = Field(ge=1, le=5)
    depends_on: list[str] = []
    status: TaskStatus = "planned"
    assigned_operator_id: str | None = None
    assigned_machine_id: str | None = None
