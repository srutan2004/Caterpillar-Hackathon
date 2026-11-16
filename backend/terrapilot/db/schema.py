"""Database schema (§8), SQLAlchemy Core.

Postgres types (JSONB, ARRAY, TIMESTAMPTZ) are declared as variants of portable types so API tests
can run on SQLite. Time-series tables are converted to Timescale hypertables by migrations
(`HYPERTABLES`). Hypertables have no surrogate primary key because Timescale requires every unique
index to include the time column.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    Column,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    MetaData,
    String,
    Table,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB

metadata = MetaData(
    naming_convention={
        "ix": "ix_%(column_0_label)s",
        "uq": "uq_%(table_name)s_%(column_0_name)s",
        "ck": "ck_%(table_name)s_%(constraint_name)s",
        "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
        "pk": "pk_%(table_name)s",
    }
)

Json = JSON().with_variant(JSONB(), "postgresql")
TextList = JSON().with_variant(ARRAY(Text()), "postgresql")
TS = DateTime(timezone=True)


def _id() -> Column[str]:
    return Column("id", String(64), primary_key=True)


def _created() -> Column[Any]:
    return Column("created_at", TS, server_default=func.now(), nullable=False)


# ------------------------------------------------------------------------------------------ org
sites = Table(
    "sites",
    metadata,
    _id(),
    Column("name", Text, nullable=False),
    Column("type", String(32), nullable=False),
    Column("climate_zone", String(32), nullable=False),
    Column("altitude_m", Float),
    Column("tz", String(64), nullable=False),
    Column("lat", Float),
    Column("lon", Float),
    Column("geom", Json),
    _created(),
)
zones = Table(
    "zones",
    metadata,
    _id(),
    Column("site_id", ForeignKey("sites.id"), nullable=False, index=True),
    Column("kind", String(16), nullable=False),
    Column("soil", String(16)),
    Column("polygon", Json),
    Column("design_surface_id", String(64)),
    _created(),
)
geofences = Table(
    "geofences",
    metadata,
    _id(),
    Column("site_id", ForeignKey("sites.id"), nullable=False, index=True),
    Column("kind", String(24), nullable=False),
    Column("geom3d", Json),
    Column("clearance_m", Float),
    Column("depth_m", Float),
    Column("depth_uncertainty_m", Float),
    Column("height_m", Float),
    Column("source", String(16)),
    _created(),
)
design_surfaces = Table(
    "design_surfaces",
    metadata,
    _id(),
    Column("site_id", ForeignKey("sites.id"), nullable=False),
    Column("zone_id", String(64)),
    Column("kind", String(16)),
    Column("cell_m", Float),
    Column("origin", Json),
    Column("grid", Json),
    _created(),
)
charging_stations = Table(
    "charging_stations",
    metadata,
    _id(),
    Column("site_id", ForeignKey("sites.id"), nullable=False),
    Column("kind", String(16), nullable=False),
    Column("power_kw", Float, nullable=False),
    Column("position", Json),
    _created(),
)

# ------------------------------------------------------------------------------------------ fleet & people
machines = Table(
    "machines",
    metadata,
    _id(),
    Column("site_id", ForeignKey("sites.id"), nullable=False, index=True),
    Column("manifest_id", String(64), nullable=False),
    Column("machine_class", String(32), nullable=False),
    Column("serial", String(64), nullable=False),
    Column("qr_token", Text, nullable=False),
    Column("hour_meter", Float, nullable=False),
    Column("powertrain", String(16), nullable=False),
    Column("status", String(16), nullable=False),
    Column("commissioned_at", TS),
    _created(),
)
components = Table(
    "components",
    metadata,
    _id(),
    Column("machine_id", ForeignKey("machines.id"), nullable=False, index=True),
    Column("kind", String(32), nullable=False),
    Column("installed_at", TS),
    Column("hours", Float),
    _created(),
)
users = Table(
    "users",
    metadata,
    _id(),
    Column("name", Text, nullable=False),
    Column("role", String(16), nullable=False),
    Column("locale", String(8), nullable=False),
    Column("pin_hash", Text, nullable=False),
    Column("badge_id", String(32), unique=True),
    Column("site_id", String(64)),
    _created(),
)
operator_profiles = Table(
    "operator_profiles",
    metadata,
    Column("user_id", ForeignKey("users.id"), primary_key=True),
    Column("experience_years", Float, nullable=False),
    Column("home_site_id", String(64)),
    Column("certified_classes", TextList),
)
certifications = Table(
    "certifications",
    metadata,
    _id(),
    Column("user_id", ForeignKey("users.id"), nullable=False, index=True),
    Column("module_id", String(64), nullable=False),
    Column("machine_class", String(32)),
    Column("issued_at", TS, nullable=False),
    Column("expires_at", TS, nullable=False),
    Column("status", String(16), nullable=False),
)

# ------------------------------------------------------------------------------------------ planning & execution
projects = Table(
    "projects",
    metadata,
    _id(),
    Column("site_id", ForeignKey("sites.id"), nullable=False),
    Column("name", Text, nullable=False),
    _created(),
)
tasks = Table(
    "tasks",
    metadata,
    _id(),
    Column("project_id", ForeignKey("projects.id"), nullable=False),
    Column("site_id", String(64), nullable=False, index=True),
    Column("zone_id", String(64)),
    Column("machine_class", String(32), nullable=False),
    Column("type", String(32), nullable=False),
    Column("quantity", Float, nullable=False),
    Column("unit", String(16), nullable=False),
    Column("depth_m", Float),
    Column("haul_distance_m", Float),
    Column("grade_pct", Float),
    Column("design_ref", String(64)),
    Column("planned_start", TS, nullable=False),
    Column("planned_end", TS, nullable=False),
    Column("deadline", TS),
    Column("priority", Integer, nullable=False),
    Column("depends_on", TextList),
    Column("status", String(16), nullable=False),
    Column("assigned_operator_id", String(64), index=True),
    Column("assigned_machine_id", String(64), index=True),
    Column("actual_start", TS),
    Column("actual_end", TS),
    Column("duration_min", Float),
    Column("progress_qty", Float),
    _created(),
)
Index("ix_tasks_planned_start", tasks.c.planned_start)
shift_assignments = Table(
    "shift_assignments",
    metadata,
    _id(),
    Column("date", Date, nullable=False, index=True),
    Column("operator_id", String(64), nullable=False),
    Column("machine_id", String(64), nullable=False),
    Column("site_id", String(64), nullable=False),
    Column("shift_start", TS, nullable=False),
    Column("shift_end", TS, nullable=False),
)
task_start_context = Table(
    "task_start_context",
    metadata,
    Column("task_id", String(64), primary_key=True),
    Column("soc", Float),
    Column("fuel_pct", Float),
    Column("health_index", Float),
    Column("open_alerts", Integer),
    Column("ground_moisture", Float),
    Column("rain_last_12h_mm", Float),
    Column("forecast_ref", String(64)),
)
cycles = Table(
    "cycles",
    metadata,
    Column("ts", TS, nullable=False),
    Column("machine_id", String(64), nullable=False),
    Column("operator_id", String(64)),
    Column("task_id", String(64)),
    Column("cycle_s", Float, nullable=False),
    Column("phase_durations", Json),
    Column("payload_t", Float),
    Column("fill_factor", Float),
    Column("fuel_l", Float),
    Column("kwh", Float),
    Column("soil", String(16)),
    Column("depth_m", Float),
)
Index("ix_cycles_machine_ts", cycles.c.machine_id, cycles.c.ts)
telemetry_1min = Table(
    "telemetry_1min",
    metadata,
    Column("ts", TS, nullable=False),
    Column("machine_id", String(64), nullable=False),
    Column("state", String(8)),
    Column("rpm", Float),
    Column("load_pct", Float),
    Column("fuel_rate_lph", Float),
    Column("power_kw", Float),
    Column("speed_kph", Float),
    Column("hyd_pressure_bar", Float),
    Column("fuel_pct", Float),
    Column("soc", Float),
)
Index("ix_telemetry_1min_machine_ts", telemetry_1min.c.machine_id, telemetry_1min.c.ts)
telemetry_raw = Table(
    "telemetry_raw",
    metadata,
    Column("ts", TS, nullable=False),
    Column("machine_id", String(64), nullable=False),
    Column("frame", Json, nullable=False),
)

# ------------------------------------------------------------------------------------------ environment
weather_hourly = Table(
    "weather_hourly",
    metadata,
    Column("ts", TS, nullable=False),
    Column("site_id", String(64), nullable=False),
    Column("temp_c", Float),
    Column("rh", Float),
    Column("rain_mm", Float),
    Column("wind_ms", Float),
    Column("gust_ms", Float),
    Column("visibility_m", Float),
    Column("lightning_km", Float),
    Column("pm10", Float),
    Column("heat_index", Float),
)
Index("ix_weather_hourly_site_ts", weather_hourly.c.site_id, weather_hourly.c.ts)
ground_conditions = Table(
    "ground_conditions",
    metadata,
    Column("date", Date, nullable=False),
    Column("zone_id", String(64), nullable=False),
    Column("site_id", String(64), nullable=False),
    Column("soil", String(16)),
    Column("moisture", Float),
    Column("density", Float),
    Column("bearing_kpa", Float),
    Column("slope_fos", Float),
    Column("risk_score", Float),
)
Index("ix_ground_conditions_zone_date", ground_conditions.c.zone_id, ground_conditions.c.date)
weather_forecast = Table(
    "weather_forecast",
    metadata,
    Column("issued_at", TS, nullable=False),
    Column("site_id", String(64), nullable=False),
    Column("valid_at", TS, nullable=False),
    Column("var", String(16), nullable=False),
    Column("value", Float),
    Column("spread", Float),
)
Index("ix_weather_forecast_site_issued", weather_forecast.c.site_id, weather_forecast.c.issued_at)
ground_moisture_forecast = Table(
    "ground_moisture_forecast",
    metadata,
    Column("issued_at", TS, nullable=False),
    Column("zone_id", String(64), nullable=False),
    Column("valid_at", TS, nullable=False),
    Column("moisture", Float),
    Column("spread", Float),
)
truck_availability_forecast = Table(
    "truck_availability_forecast",
    metadata,
    Column("issued_at", TS, nullable=False),
    Column("site_id", String(64), nullable=False),
    Column("valid_at", TS, nullable=False),
    Column("trucks_p50", Float),
    Column("trucks_p10", Float),
)

# ------------------------------------------------------------------------------------------ safety & behaviour
alerts = Table(
    "alerts",
    metadata,
    _id(),
    Column("machine_id", String(64), nullable=False, index=True),
    Column("rule_id", String(64), nullable=False),
    Column("severity", String(16), nullable=False),
    Column("opened_at", TS, nullable=False),
    Column("escalated_at", TS),
    Column("cleared_at", TS),
    Column("acked_by", String(64)),
    Column("context", Json),
)
behavior_events = Table(
    "behavior_events",
    metadata,
    _id(),
    Column("machine_id", String(64), nullable=False, index=True),
    Column("operator_id", String(64), nullable=False, index=True),
    Column("task_id", String(64)),
    Column("kind", String(32), nullable=False),
    Column("start_ts", TS, nullable=False),
    Column("end_ts", TS, nullable=False),
    Column("metrics", Json),
    Column("cost", Json),
    Column("detector", String(8), nullable=False),
    Column("score", Float),
)
seatbelt_compliance = Table(
    "seatbelt_compliance",
    metadata,
    Column("date", Date, nullable=False),
    Column("operator_id", String(64), nullable=False),
    Column("machine_id", String(64), nullable=False),
    Column("active_s", Float),
    Column("unbelted_active_s", Float),
    Column("events", Integer),
)
proximity_encounters = Table(
    "proximity_encounters",
    metadata,
    _id(),
    Column("machine_id", String(64), nullable=False),
    Column("site_id", String(64), nullable=False),
    Column("ts", TS, nullable=False),
    Column("min_distance_m", Float),
    Column("min_ttc_s", Float),
    Column("zone", String(16)),
    Column("person_ppe", Json),
)
ppe_observations = Table(
    "ppe_observations",
    metadata,
    _id(),
    Column("site_id", String(64), nullable=False),
    Column("machine_id", String(64)),
    Column("ts", TS, nullable=False),
    Column("helmet", Boolean),
    Column("vest", Boolean),
    Column("in_work_zone", Boolean),
)
incidents = Table(
    "incidents",
    metadata,
    _id(),
    Column("machine_id", String(64)),
    Column("operator_id", String(64)),
    Column("site_id", String(64)),
    Column("kind", String(16), nullable=False),
    Column("severity", String(16), nullable=False),
    Column("source", String(8), nullable=False),
    Column("occurred_at", TS, nullable=False),
    Column("location", Json),
    Column("description", Text),
    Column("root_cause", String(64)),
    Column("blackbox_clip_id", String(64)),
    Column("status", String(24), nullable=False),
    Column("reviewer_id", String(64)),
    _created(),
)
blackbox_clips = Table(
    "blackbox_clips",
    metadata,
    _id(),
    Column("machine_id", String(64), nullable=False),
    Column("trigger_rule_id", String(64)),
    Column("t0", TS, nullable=False),
    Column("pre_s", Float),
    Column("post_s", Float),
    Column("frames_uri", Text),
    Column("media_uri", Text),
)
fatigue_samples = Table(
    "fatigue_samples",
    metadata,
    Column("ts", TS, nullable=False),
    Column("operator_id", String(64), nullable=False),
    Column("machine_id", String(64)),
    Column("perclos", Float),
    Column("microsleeps", Integer),
    Column("head_nods", Integer),
    Column("score", Float),
)
wbv_exposure = Table(
    "wbv_exposure",
    metadata,
    Column("date", Date, nullable=False),
    Column("operator_id", String(64), nullable=False),
    Column("machine_id", String(64)),
    Column("a8_ms2", Float),
    Column("vdv", Float),
)

# ------------------------------------------------------------------------------------------ maintenance
fault_codes = Table(
    "fault_codes",
    metadata,
    Column("code", String(32), primary_key=True),
    Column("component", String(32), nullable=False),
    Column("severity", String(16), nullable=False),
    Column("classes", TextList),
    Column("title_key", String(64), nullable=False),
    Column("description", Text),
    Column("probable_causes", TextList),
    Column("checks", TextList),
    Column("safe_to_continue", String(8), nullable=False),
    Column("manual_ref", Json),
    Column("part_numbers", TextList),
)
fault_events = Table(
    "fault_events",
    metadata,
    _id(),
    Column("machine_id", String(64), nullable=False, index=True),
    Column("code", String(32), nullable=False),
    Column("ts", TS, nullable=False),
    Column("cleared_ts", TS),
    Column("occurrences", Integer, nullable=False),
)
fluid_samples = Table(
    "fluid_samples",
    metadata,
    _id(),
    Column("machine_id", String(64), nullable=False, index=True),
    Column("compartment", String(24), nullable=False),
    Column("ts", TS, nullable=False),
    Column("fe_ppm", Float),
    Column("cu_ppm", Float),
    Column("si_ppm", Float),
    Column("na_ppm", Float),
    Column("iso_4406", String(16)),
    Column("viscosity_cst", Float),
    Column("soot_pct", Float),
    Column("lab_rating", String(16)),
)
maintenance_records = Table(
    "maintenance_records",
    metadata,
    _id(),
    Column("machine_id", String(64), nullable=False, index=True),
    Column("component_id", String(64)),
    Column("component", String(32)),
    Column("ts", TS, nullable=False),
    Column("kind", String(16), nullable=False),
    Column("work_type", String(16)),
    Column("work_done", Text),
    Column("parts", TextList),
    Column("fault_code", String(32)),
    Column("technician_id", String(64)),
    Column("duration_h", Float),
    Column("downtime_h", Float),
    Column("labour_cost", Float),
    Column("parts_cost", Float),
)
parts = Table(
    "parts",
    metadata,
    Column("part_no", String(32), primary_key=True),
    Column("component_kind", String(32), nullable=False),
    Column("description", Text),
    Column("price", Float),
    Column("lead_time_days", Integer),
    Column("stock", Integer),
)
service_requests = Table(
    "service_requests",
    metadata,
    _id(),
    Column("machine_id", String(64), nullable=False),
    Column("requested_by", String(64)),
    Column("kind", String(16), nullable=False),
    Column("fault_code", String(32)),
    Column("part_nos", TextList),
    Column("diagnosis_ref", String(64)),
    Column("status", String(16), nullable=False),
    Column("eta", TS),
    _created(),
)
service_counters = Table(
    "service_counters",
    metadata,
    Column("machine_id", String(64), primary_key=True),
    Column("item", String(32), primary_key=True),
    Column("last_done_hours", Float),
    Column("due_hours", Float),
    Column("severity_factor", Float),
    Column("due_eta", TS),
)
technician_slots = Table(
    "technician_slots",
    metadata,
    _id(),
    Column("technician_id", String(64), nullable=False),
    Column("site_id", String(64)),
    Column("start", TS, nullable=False),
    Column("end", TS, nullable=False),
    Column("skills", TextList),
)
sensor_1min = Table(
    "sensor_1min",
    metadata,
    Column("ts", TS, nullable=False),
    Column("machine_id", String(64), nullable=False),
    Column("sensor_id", String(48), nullable=False),
    Column("value", Float),
    Column("resid", Float),
)
Index("ix_sensor_1min_machine_sensor_ts", sensor_1min.c.machine_id, sensor_1min.c.sensor_id, sensor_1min.c.ts)
sensor_forecasts = Table(
    "sensor_forecasts",
    metadata,
    _id(),
    Column("machine_id", String(64), nullable=False),
    Column("sensor_id", String(48), nullable=False),
    Column("issued_at", TS, nullable=False),
    Column("horizon_h", Float),
    Column("threshold_tier", String(16)),
    Column("eta_p10", TS),
    Column("eta_p50", TS),
    Column("eta_p90", TS),
    Column("p_cross_h", Float),
    Column("model", String(32)),
)
maintenance_alerts = Table(
    "maintenance_alerts",
    metadata,
    _id(),
    Column("machine_id", String(64), nullable=False, index=True),
    Column("component", String(32), nullable=False),
    Column("sensor_ids", TextList),
    Column("kind", String(16), nullable=False),
    Column("tier", String(16), nullable=False),
    Column("opened_at", TS, nullable=False),
    Column("updated_at", TS),
    Column("state", String(16), nullable=False),
    Column("evidence", Json),
    Column("eta", Json),
    Column("recommended_action_ref", String(64)),
    Column("safe_to_continue", String(8)),
    Column("parts", TextList),
    Column("est_repair", Json),
    Column("window_id", String(64)),
    Column("work_order_id", String(64)),
    Column("explanation", Json),
    Column("feedback", String(16)),
)
maintenance_windows = Table(
    "maintenance_windows",
    metadata,
    _id(),
    Column("machine_id", String(64), nullable=False),
    Column("alert_ids", TextList),
    Column("start", TS),
    Column("end", TS),
    Column("est_duration", Json),
    Column("est_cost", Json),
    Column("production_impact", Json),
    Column("status", String(16)),
    Column("rationale", Json),
)

# ------------------------------------------------------------------------------------------ energy
battery_log = Table(
    "battery_log",
    metadata,
    Column("ts", TS, nullable=False),
    Column("machine_id", String(64), nullable=False),
    Column("soc", Float),
    Column("kwh", Float),
    Column("power_kw", Float),
    Column("temp_c", Float),
)
charging_sessions = Table(
    "charging_sessions",
    metadata,
    _id(),
    Column("machine_id", String(64), nullable=False),
    Column("station_id", String(64)),
    Column("start", TS, nullable=False),
    Column("end", TS, nullable=False),
    Column("kwh", Float),
    Column("start_soc", Float),
    Column("end_soc", Float),
    Column("planned_by_schedule_id", String(64)),
)
charge_schedules = Table(
    "charge_schedules",
    metadata,
    _id(),
    Column("created_at", TS, server_default=func.now()),
    Column("horizon", Json),
    Column("solver_status", String(24)),
    Column("objective", Float),
    Column("plan", Json),
)
charger_reservations = Table(
    "charger_reservations",
    metadata,
    _id(),
    Column("station_id", String(64), nullable=False, index=True),
    Column("machine_id", String(64), nullable=False),
    Column("task_id", String(64)),
    Column("start", TS, nullable=False),
    Column("end", TS, nullable=False),
    Column("target_soc", Float),
    Column("source", String(32)),
    Column("status", String(16), nullable=False),
    _created(),
)
fuel_log = Table(
    "fuel_log",
    metadata,
    _id(),
    Column("machine_id", String(64), nullable=False),
    Column("date", Date, nullable=False),
    Column("fuel_l", Float),
    Column("idle_fuel_l", Float),
    Column("refuel_l", Float),
    Column("fuel_pct_start", Float),
    Column("fuel_pct_end", Float),
)
idle_windows = Table(
    "idle_windows",
    metadata,
    _id(),
    Column("machine_id", String(64), nullable=False),
    Column("start", TS, nullable=False),
    Column("end", TS, nullable=False),
    Column("kind", String(24)),
)

# ------------------------------------------------------------------------------------------ training
modules = Table(
    "modules",
    metadata,
    _id(),
    Column("title_key", String(64), nullable=False),
    Column("machine_class", String(32)),
    Column("kind", String(16)),
    Column("prerequisites", TextList),
    Column("est_minutes", Integer),
)
video_assets = Table(
    "video_assets",
    metadata,
    _id(),
    Column("title_key", String(64)),
    Column("uri", Text),
    Column("duration_s", Float),
    Column("chapters", Json),
    Column("licence", String(64)),
    Column("status", String(16)),
)
lessons = Table(
    "lessons",
    metadata,
    _id(),
    Column("module_id", String(64), nullable=False),
    Column("kind", String(16), nullable=False),
    Column("asset_id", String(64)),
    Column("order", Integer, nullable=False),
)
quiz_questions = Table(
    "quiz_questions",
    metadata,
    _id(),
    Column("module_id", String(64), nullable=False),
    Column("stem", Text, nullable=False),
    Column("options", Json),
    Column("answer", Integer),
    Column("difficulty", String(8)),
    Column("source_chunk_id", String(128)),
)
attempts = Table(
    "attempts",
    metadata,
    _id(),
    Column("user_id", String(64), nullable=False, index=True),
    Column("lesson_id", String(64), nullable=False),
    Column("score", Float),
    Column("started_at", TS),
    Column("completed_at", TS),
    Column("detail", Json),
)
assignments = Table(
    "assignments",
    metadata,
    _id(),
    Column("user_id", String(64), nullable=False, index=True),
    Column("module_id", String(64), nullable=False),
    Column("reason_kind", String(16), nullable=False),
    Column("reason_ref", String(64)),
    Column("due_at", TS),
    Column("status", String(16), nullable=False),
    _created(),
)
instructor_slots = Table(
    "instructor_slots",
    metadata,
    _id(),
    Column("instructor_id", String(64), nullable=False),
    Column("start", TS, nullable=False),
    Column("end", TS, nullable=False),
    Column("site_id", String(64)),
    Column("mode", String(16)),
    Column("capacity", Integer),
)
bookings = Table(
    "bookings",
    metadata,
    _id(),
    Column("slot_id", String(64), nullable=False),
    Column("user_id", String(64), nullable=False),
    Column("module_id", String(64)),
    Column("status", String(16), nullable=False),
    Column("notes", Text),
)
sim_sessions = Table(
    "sim_sessions",
    metadata,
    _id(),
    Column("user_id", String(64), nullable=False),
    Column("drill_id", String(64), nullable=False),
    Column("score", Float),
    Column("metrics", Json),
    Column("ts", TS, nullable=False),
)
walkarounds = Table(
    "walkarounds",
    metadata,
    _id(),
    Column("machine_id", String(64), nullable=False, index=True),
    Column("operator_id", String(64), nullable=False),
    Column("ts", TS, nullable=False),
    Column("result", String(16), nullable=False),
    Column("items", Json),
    Column("photos", TextList),
    Column("blocks_start", Boolean, nullable=False),
)
cab_notes = Table(
    "cab_notes",
    metadata,
    _id(),
    Column("operator_id", String(64), nullable=False),
    Column("machine_id", String(64)),
    Column("ts", TS, nullable=False),
    Column("text", Text, nullable=False),
    Column("audio_uri", Text),
    Column("tags", TextList),
)

# ------------------------------------------------------------------------------------------ AI / audit
chat_sessions = Table(
    "chat_sessions",
    metadata,
    _id(),
    Column("user_id", String(64), nullable=False),
    Column("machine_id", String(64)),
    _created(),
)
chat_messages = Table(
    "chat_messages",
    metadata,
    _id(),
    Column("session_id", String(64), nullable=False, index=True),
    Column("role", String(16), nullable=False),
    Column("content", Text),
    Column("tool_calls", Json),
    Column("citations", Json),
    Column("confidence", String(8)),
    Column("guard_actions", Json),
    _created(),
)
guard_events = Table(
    "guard_events",
    metadata,
    _id(),
    Column("ts", TS, nullable=False),
    Column("layer", String(24)),
    Column("rule_id", String(64)),
    Column("input_hash", String(64)),
    Column("action", String(24)),
    Column("detail", Json),
)
predictions = Table(
    "predictions",
    metadata,
    _id(),
    Column("model", String(48), nullable=False),
    Column("entity", String(64), nullable=False),
    Column("ts", TS, nullable=False),
    Column("horizon", String(32)),
    Column("p10", Float),
    Column("p50", Float),
    Column("p90", Float),
    Column("calibrated", Boolean),
    Column("explain", Json),
)
llm_calls = Table(
    "llm_calls",
    metadata,
    _id(),
    Column("ts", TS, nullable=False),
    Column("task", String(32), nullable=False),
    Column("provider", String(16), nullable=False),
    Column("model", String(96)),
    Column("prompt_version", String(96)),
    Column("input_tokens", Integer),
    Column("output_tokens", Integer),
    Column("latency_ms", Float),
    Column("status", String(12), nullable=False),
    Column("fallback_used", String(96)),
    Column("guard_flags", Json),
    Column("trace_id", String(64)),
    Column("error", Text),
)

# ------------------------------------------------------------------------------------------ planning & estimation (rev 2)
start_recommendations = Table(
    "start_recommendations",
    metadata,
    _id(),
    Column("task_id", String(64), nullable=False, index=True),
    Column("computed_at", TS, nullable=False),
    Column("recommended_start", TS),
    Column("alt_starts", Json),
    Column("duration", Json),
    Column("usual_duration", Json),
    Column("saving_vs_now_min", Float),
    Column("saving_vs_usual_min", Float),
    Column("preconditions", Json),
    Column("factors", Json),
    Column("constraints", Json),
    Column("feasible", Boolean),
    Column("explanation", Json),
    Column("accepted_by", String(64)),
    Column("accepted_at", TS),
    Column("outcome_duration", Float),
)
energy_estimates = Table(
    "energy_estimates",
    metadata,
    _id(),
    Column("task_id", String(64), nullable=False),
    Column("machine_id", String(64), nullable=False),
    Column("kwh_or_l_p10", Float),
    Column("p50", Float),
    Column("p90", Float),
    Column("can_finish_on_current", Boolean),
    Column("recharge_min", Float),
    Column("refuel_min", Float),
)
readiness_scores = Table(
    "readiness_scores",
    metadata,
    Column("ts", TS, nullable=False),
    Column("machine_id", String(64), nullable=False),
    Column("score", Float),
    Column("components", Json),
    Column("band", String(16)),
)
availability_forecast = Table(
    "availability_forecast",
    metadata,
    Column("date", Date, nullable=False),
    Column("machine_id", String(64), nullable=False),
    Column("p_available", Float),
    Column("planned_downtime_h", Float),
    Column("risk_downtime_h", Float),
)
task_cost_estimates = Table(
    "task_cost_estimates",
    metadata,
    Column("task_id", String(64), primary_key=True),
    Column("fuel_cost", Float),
    Column("wear_cost", Float),
    Column("maintenance_accrual", Float),
    Column("cost_per_unit", Float),
)

# ------------------------------------------------------------------------------------------ ground truth (eval only)
truth_component_health = Table(
    "truth_component_health",
    metadata,
    Column("date", Date, nullable=False),
    Column("machine_id", String(64), nullable=False),
    Column("component", String(32), nullable=False),
    Column("health", Float),
    Column("age_h", Float),
    Column("failed", Boolean),
)
truth_behavior_labels = Table(
    "truth_behavior_labels",
    metadata,
    _id(),
    Column("machine_id", String(64), nullable=False),
    Column("operator_id", String(64), nullable=False),
    Column("kind", String(32), nullable=False),
    Column("start_ts", TS, nullable=False),
    Column("end_ts", TS, nullable=False),
    Column("detected_event_id", String(64)),
)
truth_operator_state = Table(
    "truth_operator_state",
    metadata,
    Column("ts", TS, nullable=False),
    Column("operator_id", String(64), nullable=False),
    Column("fatigue", Float),
)
truth_operator_traits = Table(
    "truth_operator_traits",
    metadata,
    Column("operator_id", String(64), primary_key=True),
    Column("skill", Float),
    Column("idle_propensity", Float),
    Column("belt_compliance_p", Float),
    Column("aggression", Float),
    Column("fatigue_susceptibility", Float),
)
truth_fault_modes = Table(
    "truth_fault_modes",
    metadata,
    _id(),
    Column("machine_id", String(64), nullable=False),
    Column("mode", String(32), nullable=False),
    Column("component", String(32)),
    Column("sensor_id", String(48)),
    Column("onset", TS, nullable=False),
    Column("first_detectable", TS),
    Column("failure_time", TS),
    Column("resolved_at", TS),
    Column("outcome", String(24)),
)
truth_weather_hourly = Table(
    "truth_weather_hourly",
    metadata,
    Column("ts", TS, nullable=False),
    Column("site_id", String(64), nullable=False),
    Column("temp_c", Float),
    Column("rh", Float),
    Column("rain_mm", Float),
    Column("wind_ms", Float),
    Column("gust_ms", Float),
    Column("visibility_m", Float),
    Column("lightning_km", Float),
    Column("pm10", Float),
    Column("heat_index", Float),
)
truth_ground_hourly = Table(
    "truth_ground_hourly",
    metadata,
    Column("ts", TS, nullable=False),
    Column("zone_id", String(64), nullable=False),
    Column("moisture", Float),
)
truth_task_execution = Table(
    "truth_task_execution",
    metadata,
    Column("task_id", String(64), primary_key=True),
    Column("skill", Float),
    Column("fatigue_mean", Float),
    Column("health_index", Float),
    Column("wait_min", Float),
    Column("stoppage_min", Float),
    Column("charge_stop_min", Float),
    Column("n_cycles", Integer),
)

# Tables converted to Timescale hypertables: (table, time column, chunk interval)
HYPERTABLES: list[tuple[str, str, str]] = [
    ("cycles", "ts", "7 days"),
    ("telemetry_1min", "ts", "1 day"),
    ("telemetry_raw", "ts", "1 day"),
    ("weather_hourly", "ts", "30 days"),
    ("sensor_1min", "ts", "7 days"),
    ("battery_log", "ts", "7 days"),
    ("fatigue_samples", "ts", "7 days"),
]

TRUTH_TABLES = [t.name for t in metadata.sorted_tables if t.name.startswith("truth_")]
