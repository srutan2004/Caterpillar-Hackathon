"""Curated read-only views for text-to-SQL (§8). Only these are granted to `tp_ro`.

Column comments are fed to the SQL prompt in Phase 3, so they describe meaning and units.
Truth tables (`truth_*`) are never referenced here.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class View:
    name: str
    comment: str
    sql: str
    columns: dict[str, str] = field(default_factory=dict)


VIEWS: list[View] = [
    View(
        "v_machines",
        "Machines in the fleet with their site, model and status.",
        "SELECT id AS machine_id, site_id, manifest_id, machine_class, powertrain, status, hour_meter FROM machines",
        {
            "machine_id": "Machine id, e.g. EX-03",
            "hour_meter": "Engine/operating hours",
            "status": "available | in_use | maintenance | down",
        },
    ),
    View(
        "v_cycles",
        "One row per bucket/haul cycle.",
        "SELECT ts, machine_id, operator_id, task_id, cycle_s, payload_t, fill_factor, fuel_l, kwh, soil, depth_m FROM cycles",
        {
            "cycle_s": "Cycle duration in seconds",
            "payload_t": "Payload per cycle in tonnes",
            "fuel_l": "Diesel used in the cycle (litres)",
            "kwh": "Energy used in the cycle (kWh, electric machines)",
            "soil": "Soil type dug",
        },
    ),
    View(
        "v_tasks",
        "All tasks with planned and actual timing.",
        "SELECT t.id AS task_id, t.site_id, t.zone_id, t.machine_class, t.type, t.quantity, t.unit, t.planned_start, t.planned_end, "
        "t.deadline, t.priority, t.status, t.assigned_operator_id AS operator_id, t.assigned_machine_id AS machine_id, "
        "t.actual_start, t.actual_end, t.duration_min, t.progress_qty FROM tasks t",
        {"duration_min": "Actual task duration in minutes", "progress_qty": "Quantity completed so far"},
    ),
    View(
        "v_tasks_today",
        "Tasks planned for today in each site's local timezone.",
        "SELECT t.id AS task_id, t.site_id, t.machine_class, t.type, t.quantity, t.unit, t.planned_start, t.planned_end, t.deadline, "
        "t.priority, t.status, t.assigned_operator_id AS operator_id, t.assigned_machine_id AS machine_id "
        "FROM tasks t JOIN sites s ON s.id = t.site_id "
        "WHERE (t.planned_start AT TIME ZONE s.tz)::date = (now() AT TIME ZONE s.tz)::date",
        {"planned_start": "Planned start (UTC)", "deadline": "Latest acceptable finish (UTC)"},
    ),
    View(
        "v_idle_summary",
        "Idle time, fuel, cost and CO2 per operator, machine and day.",
        "SELECT operator_id, machine_id, (start_ts)::date AS day, count(*) AS episodes, "
        "sum(EXTRACT(EPOCH FROM (end_ts - start_ts)))/60.0 AS idle_min, "
        "sum((cost->>'fuel_l')::float) AS idle_fuel_l, sum((cost->>'cost')::float) AS idle_cost, "
        "sum((cost->>'co2_kg')::float) AS idle_co2_kg FROM behavior_events WHERE kind = 'idle' "
        "GROUP BY operator_id, machine_id, (start_ts)::date",
        {
            "idle_min": "Total idling minutes",
            "idle_fuel_l": "Fuel burnt while idling (litres)",
            "idle_cost": "Idle fuel cost in site currency",
            "idle_co2_kg": "CO2 from idling (kg)",
        },
    ),
    View(
        "v_behavior_events",
        "Detected operating-behaviour events (idle, harsh swing, overload, …).",
        "SELECT id AS event_id, machine_id, operator_id, task_id, kind, start_ts, end_ts, detector, score FROM behavior_events",
        {"kind": "Behaviour kind, e.g. idle, harsh_swing, cavitation, belt_off"},
    ),
    View(
        "v_seatbelt_compliance",
        "Seatbelt compliance per operator, machine and day.",
        "SELECT date, operator_id, machine_id, active_s, unbelted_active_s, events, "
        "CASE WHEN active_s > 0 THEN 1 - unbelted_active_s / active_s END AS compliance FROM seatbelt_compliance",
        {"compliance": "1 − unbelted active time / active time"},
    ),
    View(
        "v_alerts",
        "Safety alerts history.",
        "SELECT id AS alert_id, machine_id, rule_id, severity, opened_at, escalated_at, cleared_at, acked_by FROM alerts",
        {"severity": "advisory | caution | warning"},
    ),
    View(
        "v_fuel",
        "Daily fuel use per machine.",
        "SELECT machine_id, date, fuel_l, idle_fuel_l, refuel_l, fuel_pct_start, fuel_pct_end FROM fuel_log",
        {"fuel_l": "Fuel used that day (litres)", "idle_fuel_l": "Fuel used while idling (litres)"},
    ),
    View(
        "v_fault_history",
        "Fault code events with catalogue details.",
        "SELECT e.machine_id, e.code, e.ts, e.cleared_ts, e.occurrences, c.component, c.severity, c.safe_to_continue "
        "FROM fault_events e JOIN fault_codes c ON c.code = e.code",
        {"safe_to_continue": "yes | limited | no (from the fault catalogue)"},
    ),
    View(
        "v_maintenance_records",
        "Completed maintenance work.",
        "SELECT machine_id, component, ts, kind, work_type, fault_code, duration_h, downtime_h, labour_cost, parts_cost FROM maintenance_records",
        {"duration_h": "Technician hours", "downtime_h": "Machine downtime hours"},
    ),
    View(
        "v_maintenance_alerts",
        "Sensor-based maintenance alerts.",
        "SELECT id AS alert_id, machine_id, component, kind, tier, state, opened_at, updated_at, safe_to_continue FROM maintenance_alerts",
        {
            "tier": "monitor | service_soon | stop",
            "state": "open | acknowledged | scheduled | in_service | resolved | false_alarm",
        },
    ),
    View(
        "v_service_due",
        "Service interval counters with severity-adjusted due times.",
        "SELECT machine_id, item, last_done_hours, due_hours, severity_factor, due_eta FROM service_counters",
        {"due_hours": "Hour-meter reading at which the item is due", "due_eta": "Estimated due time (UTC)"},
    ),
    View(
        "v_start_recommendations",
        "Recommended task start times.",
        "SELECT task_id, computed_at, recommended_start, saving_vs_now_min, saving_vs_usual_min, feasible FROM start_recommendations",
        {"saving_vs_usual_min": "Minutes saved versus the usual duration"},
    ),
    View(
        "v_energy_estimates",
        "Energy/fuel needed per task and whether the current charge/fuel suffices.",
        "SELECT task_id, machine_id, kwh_or_l_p10, p50, p90, can_finish_on_current, recharge_min, refuel_min FROM energy_estimates",
        {"p50": "Median energy (kWh) or fuel (L) needed"},
    ),
    View(
        "v_weather",
        "Observed hourly weather per site.",
        "SELECT ts, site_id, temp_c, rh, rain_mm, wind_ms, gust_ms, visibility_m, lightning_km, pm10, heat_index FROM weather_hourly",
        {"rain_mm": "Rain in the hour (mm)", "gust_ms": "Peak gust (m/s)", "pm10": "Dust PM10 (µg/m³)"},
    ),
]
