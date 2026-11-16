"""Safety and operator-state records derived from the simulated shifts (§7.3 Safety, Operator state).

Condition alerts are labelled by evaluating the *actual* rule expressions from config/rules/conditions.yaml
on the hourly weather, so history and the live rules engine share one definition.
"""

from __future__ import annotations

import json
import math
from collections import defaultdict
from typing import Any

import numpy as np
import pandas as pd

from terrapilot.core.expr import ExprEvaluator
from terrapilot.datagen.context import GenContext
from terrapilot.datagen.fleet import STATE_WORK, MachineRt
from terrapilot.datagen.ground import ground_properties
from terrapilot.datagen.weather import HourlyWeather


def _ts(t: float) -> pd.Timestamp:
    return pd.Timestamp(t, unit="s", tz="UTC")


def _sigmoid(x: float) -> float:
    return 1 / (1 + math.exp(-x))


def work_intervals_by_day(ctx: GenContext, m: MachineRt) -> dict[Any, list[tuple[float, float]]]:
    out: dict[Any, list[tuple[float, float]]] = defaultdict(list)
    for t0, t1, state in m.activity:
        if state == STATE_WORK:
            out[_ts(t0).tz_convert(ctx.tz).date()].append((t0, t1))
    return out


def _random_time_in(intervals: list[tuple[float, float]], rng: np.random.Generator) -> float:
    lengths = np.array([b - a for a, b in intervals])
    i = int(rng.choice(len(intervals), p=lengths / lengths.sum()))
    return float(rng.uniform(*intervals[i]))


def generate_safety(ctx: GenContext) -> None:
    beh = ctx.dg["behavior"]
    machines: dict[str, MachineRt] = ctx.state["machines"]
    ops = ctx.state["operators"]
    opdays = pd.DataFrame(ctx.state.get("operator_days", []))
    alerts, behavior, truth_labels, compliance, encounters, ppe, incidents, clips = [], [], [], [], [], [], [], []
    counter = [0]

    def nid(prefix: str) -> str:
        counter[0] += 1
        return f"{prefix}-S{counter[0]:07d}"

    cond_rules = ctx.cfg.condition_rules
    gcfg = ctx.dg["ground"]
    for m in machines.values():
        rng = ctx.rng(f"safety:{m.id}")
        manifest = m.manifest
        wx: HourlyWeather = ctx.state["wx"][m.site_id]
        site = ctx.site(m.site_id)
        by_day = work_intervals_by_day(ctx, m)
        rows = opdays[opdays["machine_id"] == m.id] if len(opdays) else opdays
        zone_dig = ctx.state["zones_by_site"][m.site_id]["dig"][0]
        soil = gcfg["soils"][ctx.state["zone_soil"][zone_dig]]
        for od in rows.itertuples():
            intervals = by_day.get(od.date, [])
            if not intervals:
                continue
            op = ops[od.operator_id]
            active_h = sum(b - a for a, b in intervals) / 3600
            # ---- seatbelt episodes: rate = k × (1 − belt_compliance_p) per active hour
            rate = beh["seatbelt"]["unbelted_episodes_per_active_h"]["k"] * (1 - op.belt_compliance_p) * active_h
            unbelted = 0.0
            n_ep = int(rng.poisson(rate))
            for _ in range(n_ep):
                t0 = _random_time_in(intervals, rng)
                dur = float(
                    min(
                        1800,
                        rng.lognormal(
                            beh["seatbelt"]["episode_s"]["lognormal_mu"],
                            beh["seatbelt"]["episode_s"]["lognormal_sigma"],
                        ),
                    )
                )
                unbelted += dur
                grace, esc = manifest.seatbelt["grace_s"], manifest.seatbelt["escalate_after_s"]
                if dur >= grace:
                    label_id = nid("TL")
                    detected = rng.random() < beh["detection"]["recall"]["belt_off"]
                    ev_id = nid("BE") if detected else None
                    truth_labels.append(
                        {
                            "id": label_id,
                            "machine_id": m.id,
                            "operator_id": op.id,
                            "kind": "belt_off",
                            "start_ts": _ts(t0),
                            "end_ts": _ts(t0 + dur),
                            "detected_event_id": ev_id,
                        }
                    )
                    if detected:
                        behavior.append(
                            {
                                "id": ev_id,
                                "machine_id": m.id,
                                "operator_id": op.id,
                                "task_id": None,
                                "kind": "belt_off",
                                "start_ts": _ts(t0),
                                "end_ts": _ts(t0 + dur),
                                "metrics": json.dumps({"duration_s": round(dur, 1)}),
                                "cost": json.dumps({}),
                                "detector": "rule",
                                "score": None,
                            }
                        )
                    alerts.append(
                        {
                            "id": nid("AL"),
                            "machine_id": m.id,
                            "rule_id": "SEATBELT_UNFASTENED_ACTIVE",
                            "severity": "warning" if dur >= esc else "caution",
                            "opened_at": _ts(t0 + grace),
                            "escalated_at": _ts(t0 + esc) if dur >= esc else None,
                            "cleared_at": _ts(t0 + dur),
                            "acked_by": None,
                            "context": json.dumps({"operator_id": op.id}),
                        }
                    )
            compliance.append(
                {
                    "date": od.date,
                    "operator_id": op.id,
                    "machine_id": m.id,
                    "active_s": round(active_h * 3600, 1),
                    "unbelted_active_s": round(min(unbelted, active_h * 3600), 1),
                    "events": n_ep,
                }
            )

            # ---- proximity encounters + PPE
            zones = manifest.proximity["zones_m"]
            ttc_tiers = manifest.proximity["ttc_s"]
            ppe_p = beh["proximity"]["ppe_missing_prob"]
            for _ in range(int(rng.poisson(beh["proximity"]["encounters_per_h"][site["type"]] * active_h))):
                t0 = _random_time_in(intervals, rng)
                dist = float(
                    rng.uniform(beh["proximity"]["min_distance_m"]["min"], beh["proximity"]["min_distance_m"]["max"])
                )
                ttc = float(dist / rng.uniform(0.5, 2.0)) if rng.random() < 0.5 else None
                zone = next((tier for tier in ("warning", "caution", "advisory") if dist < zones[tier]), None)
                person_ppe = {
                    "helmet": bool(rng.random() > ppe_p["helmet"]),
                    "vest": bool(rng.random() > ppe_p["vest"]),
                }
                encounters.append(
                    {
                        "id": nid("PX"),
                        "machine_id": m.id,
                        "site_id": m.site_id,
                        "ts": _ts(t0),
                        "min_distance_m": round(dist, 2),
                        "min_ttc_s": round(ttc, 2) if ttc else None,
                        "zone": zone,
                        "person_ppe": json.dumps(person_ppe),
                    }
                )
                ppe.append(
                    {
                        "id": nid("PP"),
                        "site_id": m.site_id,
                        "machine_id": m.id,
                        "ts": _ts(t0),
                        "helmet": person_ppe["helmet"],
                        "vest": person_ppe["vest"],
                        "in_work_zone": zone is not None,
                    }
                )
                rule = None
                if zone == "warning":
                    rule, sev = "PERSON_IN_ZONE_WARNING", "warning"
                elif zone == "caution":
                    rule, sev = "PERSON_IN_ZONE_CAUTION", "caution"
                elif ttc is not None and ttc < ttc_tiers["caution"]:
                    rule, sev = "PERSON_TTC", "warning" if ttc < ttc_tiers["warning"] else "caution"
                if rule:
                    alerts.append(
                        {
                            "id": nid("AL"),
                            "machine_id": m.id,
                            "rule_id": rule,
                            "severity": sev,
                            "opened_at": _ts(t0),
                            "escalated_at": None,
                            "cleared_at": _ts(t0 + float(rng.uniform(3, 30))),
                            "acked_by": None,
                            "context": json.dumps(
                                {"distance_m": round(dist, 2), "ttc_s": round(ttc, 2) if ttc else None}
                            ),
                        }
                    )

            # ---- condition rules on hourly weather (real rule expressions)
            day_hours = sorted({wx.idx_s(a) + k for a, b in intervals for k in range(int((b - a) // 3600) + 1)})
            open_rules: dict[str, tuple[float, str]] = {}
            for hi in day_hours:
                w = {k: float(v[hi]) for k, v in wx.data.items()}
                moist = float(ctx.state["moist"][zone_dig][hi])
                risk = float(
                    ground_properties(
                        moist, soil, gcfg["ground_risk"]["weights"], gcfg["ground_risk"]["surface_class_risk"]
                    )["risk_score"]
                )
                ev = ExprEvaluator({"site": w, "task": {"lifting": False}, "ground": {"risk_score": risk}})
                t_hour = wx.t0.timestamp() + hi * 3600
                for crule in cond_rules:
                    if m.cls not in crule.applies_to:
                        continue
                    active = bool(ev.eval(crule.when))
                    if active and crule.id not in open_rules:
                        open_rules[crule.id] = (t_hour, crule.severity)
                    elif not active and crule.id in open_rules:
                        t_open, sev = open_rules.pop(crule.id)
                        alerts.append(
                            {
                                "id": nid("AL"),
                                "machine_id": m.id,
                                "rule_id": crule.id,
                                "severity": sev,
                                "opened_at": _ts(t_open),
                                "escalated_at": None,
                                "cleared_at": _ts(t_hour),
                                "acked_by": None,
                                "context": json.dumps({"source": "weather"}),
                            }
                        )
            for rid, (t_open, sev) in open_rules.items():
                alerts.append(
                    {
                        "id": nid("AL"),
                        "machine_id": m.id,
                        "rule_id": rid,
                        "severity": sev,
                        "opened_at": _ts(t_open),
                        "escalated_at": None,
                        "cleared_at": _ts(t_open + 3600),
                        "acked_by": None,
                        "context": json.dumps({"source": "weather"}),
                    }
                )

            # ---- incidents / near misses: logistic in unsafe rate, visibility, fatigue, ground risk
            unsafe_rate = od.unsafe / max(active_h, 0.1)
            vis_low = float(np.mean([wx.data["visibility_m"][h] < 250 for h in day_hours])) if day_hours else 0.0
            moist_mean = (
                float(np.mean([ctx.state["moist"][zone_dig][h] for h in day_hours])) if day_hours else soil["m_field"]
            )
            g_risk = float(
                ground_properties(
                    moist_mean, soil, gcfg["ground_risk"]["weights"], gcfg["ground_risk"]["surface_class_risk"]
                )["risk_score"]
            )
            for kind in ("near_miss", "incident"):
                c = beh["incidents"][kind]
                p = _sigmoid(
                    c["a"]
                    + c["unsafe_rate"] * unsafe_rate
                    + c["low_visibility"] * vis_low
                    + c["fatigue"] * od.fatigue_mean * 3
                    + c["ground_risk"] * g_risk
                )
                if rng.random() < p:
                    t0 = _random_time_in(intervals, rng)
                    auto = kind == "incident" or rng.random() < 0.5
                    clip_id = None
                    if auto:
                        clip_id = nid("BB")
                        clips.append(
                            {
                                "id": clip_id,
                                "machine_id": m.id,
                                "trigger_rule_id": "IMU_G_SPIKE" if kind == "incident" else "PERSON_IN_ZONE_WARNING",
                                "t0": _ts(t0),
                                "pre_s": ctx.cfg.app.blackbox["pre_s"],
                                "post_s": ctx.cfg.app.blackbox["post_s"],
                                "frames_uri": f"blackbox/{clip_id}.parquet",
                                "media_uri": None,
                            }
                        )
                    causes = beh["incidents"]["root_causes"]
                    cause = (
                        "fatigue"
                        if od.fatigue_mean > 0.5
                        else "visibility"
                        if vis_low > 0.3
                        else "ground_conditions"
                        if g_risk > 0.55
                        else str(rng.choice(causes))
                    )
                    sev_w = beh["incidents"]["severity_weights"]
                    incidents.append(
                        {
                            "id": nid("IN"),
                            "machine_id": m.id,
                            "operator_id": op.id,
                            "site_id": m.site_id,
                            "kind": kind,
                            "severity": str(
                                rng.choice(list(sev_w), p=np.array(list(sev_w.values())) / sum(sev_w.values()))
                            ),
                            "source": "auto" if auto else "manual",
                            "occurred_at": _ts(t0),
                            "location": json.dumps({"zone_id": zone_dig}),
                            "description": f"{kind.replace('_', ' ')} during {m.cls} operation",
                            "root_cause": cause,
                            "blackbox_clip_id": clip_id,
                            "status": "closed",
                            "reviewer_id": None,
                        }
                    )
            if rng.random() < beh["incidents"]["hazard_report_per_shift"]:
                incidents.append(
                    {
                        "id": nid("IN"),
                        "machine_id": m.id,
                        "operator_id": op.id,
                        "site_id": m.site_id,
                        "kind": "hazard",
                        "severity": "low",
                        "source": "manual",
                        "occurred_at": _ts(_random_time_in(intervals, rng)),
                        "location": json.dumps({"zone_id": zone_dig}),
                        "description": "hazard observation reported by operator",
                        "root_cause": None,
                        "blackbox_clip_id": None,
                        "status": "closed",
                        "reviewer_id": None,
                    }
                )

    ctx.emit("alerts", pd.DataFrame(alerts))
    ctx.emit("behavior_events", pd.DataFrame(behavior))
    ctx.emit("truth_behavior_labels", pd.DataFrame(truth_labels))
    ctx.emit("seatbelt_compliance", pd.DataFrame(compliance))
    ctx.emit("proximity_encounters", pd.DataFrame(encounters))
    ctx.emit("ppe_observations", pd.DataFrame(ppe))
    ctx.emit("incidents", pd.DataFrame(incidents))
    ctx.emit(
        "blackbox_clips",
        pd.DataFrame(
            clips, columns=["id", "machine_id", "trigger_rule_id", "t0", "pre_s", "post_s", "frames_uri", "media_uri"]
        ),
    )


def generate_operator_state(ctx: GenContext) -> None:
    """Fatigue samples (observable proxies + truth) and whole-body vibration A(8) per operator-day."""
    fcfg = ctx.dg["behavior"]["fatigue_signals"]
    wcfg = ctx.dg["behavior"]["wbv"]
    step = float(ctx.world["resolution"]["fatigue_step_min"]) * 60
    rng = ctx.rng("operator_state")
    truth = ctx.state.get("fatigue_truth", [])
    if truth:
        df = pd.DataFrame(truth, columns=["operator_id", "machine_id", "t", "fatigue"])
        df["bucket"] = (df["t"] // step) * step
        df = df.groupby(["operator_id", "machine_id", "bucket"], as_index=False)["fatigue"].mean()
        f = df["fatigue"].to_numpy()
        perclos = np.clip(fcfg["perclos_base"] + fcfg["perclos_k"] * f + rng.normal(0, fcfg["noise_sd"], len(f)), 0, 1)
        micro = rng.poisson(fcfg["microsleep_rate_k"] * f**2)
        nods = rng.poisson(fcfg["head_nod_rate_k"] * f**2)
        score = np.clip(1 / (1 + np.exp(-(12 * (perclos - 0.12) + 0.4 * micro))), 0, 1)
        stamps = pd.to_datetime(df["bucket"], unit="s", utc=True)
        ctx.emit(
            "fatigue_samples",
            pd.DataFrame(
                {
                    "ts": stamps,
                    "operator_id": df["operator_id"],
                    "machine_id": df["machine_id"],
                    "perclos": np.round(perclos, 4),
                    "microsleeps": micro,
                    "head_nods": nods,
                    "score": np.round(score, 4),
                }
            ),
        )
        ctx.emit(
            "truth_operator_state",
            pd.DataFrame({"ts": stamps, "operator_id": df["operator_id"], "fatigue": np.round(f, 4)}),
        )
    rows = []
    machines = ctx.state["machines"]
    for od in ctx.state.get("operator_days", []):
        m = machines[od["machine_id"]]
        soil = ctx.state["zone_soil"][ctx.state["zones_by_site"][m.site_id]["dig"][0]]
        a_w = (
            wcfg["a_w_ms2_base"][m.cls]
            * wcfg["roughness_by_soil"][soil]
            * wcfg["seat_transmissibility"][m.cls]
            * float(rng.lognormal(0, 0.12))
        )
        hours = od["active_s"] / 3600
        a8 = a_w * math.sqrt(hours / 8)
        rows.append(
            {
                "date": od["date"],
                "operator_id": od["operator_id"],
                "machine_id": m.id,
                "a8_ms2": round(a8, 3),
                "vdv": round(1.4 * a_w * (hours * 3600) ** 0.25, 3),
            }
        )
    ctx.emit("wbv_exposure", pd.DataFrame(rows))
