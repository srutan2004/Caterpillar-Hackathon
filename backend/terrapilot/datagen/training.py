"""Training records (§7.3 Training, §10.8): modules, lessons, videos, certifications (some expiring soon
so gating shows in the demo), attempts correlated with skill, adaptive assignments, instructor slots,
bookings and simulator sessions.
"""

from __future__ import annotations

import json
import math
from collections import Counter
from datetime import timedelta
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from terrapilot.core.settings import REPO_ROOT
from terrapilot.datagen.context import GenContext


def generate_training(ctx: GenContext) -> None:
    tcfg = ctx.dg["training"]
    rng = ctx.rng("training")
    modules = tcfg["modules"]
    videos = {v["module"]: v for v in (ctx.cfg.media or {}).get("videos", [])}
    ctx.emit(
        "modules",
        pd.DataFrame(
            [
                {
                    "id": m["id"],
                    "title_key": m["title_key"],
                    "machine_class": m["machine_class"],
                    "kind": m["kind"],
                    "prerequisites": m["prerequisites"],
                    "est_minutes": m["est_minutes"],
                }
                for m in modules
            ]
        ),
    )
    ctx.emit(
        "video_assets",
        pd.DataFrame(
            [
                {
                    "id": v["id"],
                    "title_key": v["title_key"],
                    "uri": v["uri"],
                    "duration_s": v["duration_s"],
                    "chapters": json.dumps(v["chapters"]),
                    "licence": v["licence"],
                    "status": v["status"],
                }
                for v in videos.values()
            ]
        ),
    )
    lessons = []
    for mod in modules:
        order = 0
        for kind, count in tcfg["lessons_per_module"].items():
            for i in range(int(count)):
                order += 1
                asset = videos.get(mod["id"], {}).get("id") if kind == "video" else None
                lessons.append(
                    {
                        "id": f"L-{mod['id']}-{kind}-{i + 1}",
                        "module_id": mod["id"],
                        "kind": kind,
                        "asset_id": asset,
                        "order": order,
                    }
                )
    ctx.emit("lessons", pd.DataFrame(lessons))

    # certifications per operator for every required module of the classes they operate
    comp = tcfg["completion"]
    ccfg = tcfg["certs"]
    fixtures = (ctx.dg.get("demo_fixtures") or {}).get("operators", {})
    certs, attempts, assignments = [], [], []
    now = ctx.now
    for op in ctx.state["operators"].values():
        required: set[str] = {"safety_basics"}
        for m in ctx.cfg.manifests.values():
            if m.class_ in op.classes:
                required |= set(m.training.required_modules)
        pinned_exp = fixtures.get(op.id, {}).get("cert_expiring")
        for mod_id in sorted(required):
            validity = 365
            if pinned_exp and pinned_exp["module"] == mod_id:
                issued = now + timedelta(days=pinned_exp["days"]) - timedelta(days=validity)
            elif rng.random() < ccfg["expiring_soon_fraction"]:
                issued = now - timedelta(days=validity - float(rng.uniform(1, ccfg["expiring_window_days"])))
            else:
                issued = now - timedelta(
                    days=float(
                        rng.uniform(ccfg["issued_days_ago"]["min"], min(ccfg["issued_days_ago"]["max"], validity - 25))
                    )
                )
            expires = issued + timedelta(days=validity)
            certs.append(
                {
                    "id": f"CERT-{op.id}-{mod_id}",
                    "user_id": op.id,
                    "module_id": mod_id,
                    "machine_class": next((m["machine_class"] for m in modules if m["id"] == mod_id), None),
                    "issued_at": issued,
                    "expires_at": expires,
                    "status": "valid" if expires > now else "expired",
                }
            )
            if expires - now < timedelta(days=ccfg["expiring_window_days"]):
                assignments.append(
                    {
                        "id": f"AS-{op.id}-{mod_id}-exp",
                        "user_id": op.id,
                        "module_id": mod_id,
                        "reason_kind": "cert_expiry",
                        "reason_ref": f"CERT-{op.id}-{mod_id}",
                        "due_at": expires,
                        "status": "open",
                        "created_at": now,
                    }
                )
            for les in (x for x in lessons if x["module_id"] == mod_id):
                started = issued - timedelta(days=float(rng.uniform(1, 10)))
                if les["kind"] == "quiz":
                    logit = (
                        math.log(comp["pass_mark"] / (1 - comp["pass_mark"]))
                        + comp["quiz_score_k"] * (op.skill - 0.5) * 4
                        + 0.6
                    )
                    score = float(np.clip(1 / (1 + math.exp(-logit)) + rng.normal(0, 0.06), 0, 1))
                    detail = {"passed": score >= comp["pass_mark"]}
                elif les["kind"] == "video":
                    score = float(np.clip(rng.normal(0.97, 0.03), comp["completion_ratio"], 1))
                    detail = {"watched_ratio": round(score, 3)}
                else:
                    score, detail = 1.0, {}
                attempts.append(
                    {
                        "id": f"AT-{op.id}-{les['id']}",
                        "user_id": op.id,
                        "lesson_id": les["id"],
                        "score": round(score, 3),
                        "started_at": started,
                        "completed_at": started + timedelta(minutes=float(rng.uniform(5, 40))),
                        "detail": json.dumps(detail),
                    }
                )
    ctx.emit("certifications", pd.DataFrame(certs))
    ctx.emit("attempts", pd.DataFrame(attempts))

    # adaptive assignments from the last 7/30 days of detected behaviour (§10.8.5)
    be = ctx.tables.get("behavior_events", pd.DataFrame())
    rules = ctx.cfg.behavior_rules.adaptive_assignment
    if len(be):
        recent7 = be[be["start_ts"] >= pd.Timestamp(now - timedelta(days=7))]
        counts = Counter(zip(recent7["operator_id"], recent7["kind"], strict=False))
        idle = recent7[recent7["kind"].isin(["idle", "high_rpm_idle"])]
        idle_s = (idle["end_ts"] - idle["start_ts"]).dt.total_seconds().groupby(idle["operator_id"]).sum()
        active = pd.DataFrame(ctx.state.get("operator_days", []))
        active7 = (
            active[pd.to_datetime(active["date"]) >= pd.Timestamp(ctx.anchor - timedelta(days=7))]
            .groupby("operator_id")["active_s"]
            .sum()
            if len(active)
            else pd.Series(dtype=float)
        )
        incidents = ctx.tables.get("incidents", pd.DataFrame())
        for op_id in ctx.state["operators"]:
            for rule in rules:
                sig = rule["signal"]
                hit = False
                if sig == "idle" and "min_ratio_7d" in rule:
                    denom = float(active7.get(op_id, 0.0))
                    hit = denom > 0 and float(idle_s.get(op_id, 0.0)) / denom >= rule["min_ratio_7d"]
                elif sig == "near_miss_pedestrian":
                    hit = len(incidents) > 0 and bool(
                        (
                            (incidents["operator_id"] == op_id)
                            & (incidents["kind"] == "near_miss")
                            & (incidents["occurred_at"] >= pd.Timestamp(now - timedelta(days=30)))
                        ).any()
                    )
                else:
                    hit = counts.get((op_id, sig), 0) >= rule.get("min_count_7d", 1)
                if hit:
                    assignments.append(
                        {
                            "id": f"AS-{op_id}-{rule['module']}-{sig}",
                            "user_id": op_id,
                            "module_id": rule["module"],
                            "reason_kind": "anomaly",
                            "reason_ref": sig,
                            "due_at": now + timedelta(days=tcfg["assignments"]["due_days"]),
                            "status": "open",
                            "created_at": now,
                        }
                    )
    ctx.emit("assignments", pd.DataFrame(assignments).drop_duplicates("id"))

    # instructor slots + bookings
    scfg = tcfg["slots"]
    instructors = ctx.tables["users"][ctx.tables["users"]["role"] == "instructor"]
    modes = list(scfg["modes"])
    mode_p = np.array(list(scfg["modes"].values()), dtype=float)
    slots, bookings = [], []
    op_ids = sorted(ctx.state["operators"])
    for ins in instructors.itertuples():
        for week in range(-int(scfg["weeks_back"]), int(scfg["weeks_ahead"]) + 1):
            for k in range(int(scfg["per_instructor_per_week"])):
                d = ctx.anchor + timedelta(days=7 * week + int(rng.integers(0, 6)))
                if not ctx.is_workday(d):
                    continue
                mode = str(rng.choice(modes, p=mode_p / mode_p.sum()))
                start = ctx.local_dt(d, f"{int(rng.integers(8, 16)):02d}:00")
                sid = f"SL-{ins.id}-{d.isoformat()}-{k}"
                slots.append(
                    {
                        "id": sid,
                        "instructor_id": ins.id,
                        "start": start,
                        "end": start + timedelta(hours=scfg["duration_h"][mode]),
                        "site_id": ins.site_id,
                        "mode": mode,
                        "capacity": scfg["capacity"][mode],
                    }
                )
                for _ in range(int(rng.binomial(scfg["capacity"][mode], scfg["booking_fill_rate"]))):
                    user = str(rng.choice(op_ids))
                    past = start < ctx.now
                    bookings.append(
                        {
                            "id": f"BK-{sid}-{user}",
                            "slot_id": sid,
                            "user_id": user,
                            "module_id": str(rng.choice([m["id"] for m in modules])),
                            "status": ("completed" if rng.random() < 0.9 else "cancelled") if past else "booked",
                            "notes": None,
                        }
                    )
    ctx.emit("instructor_slots", pd.DataFrame(slots))
    ctx.emit("bookings", pd.DataFrame(bookings).drop_duplicates("id"))

    sim = tcfg["sim_sessions"]
    drills = tcfg["drills"]
    sessions = []
    months = ctx.history_days / 30
    for op in ctx.state["operators"].values():
        for i in range(int(rng.poisson(sim["per_operator_per_month"] * months))):
            drill = drills[int(rng.integers(len(drills)))]
            score = float(
                np.clip(
                    sim["score_base"] + sim["score_skill_k"] * op.skill + rng.normal(0, sim["score_noise_sd"]), 0, 100
                )
            )
            sessions.append(
                {
                    "id": f"SIM-{op.id}-{i}",
                    "user_id": op.id,
                    "drill_id": drill["id"],
                    "score": round(score, 1),
                    "metrics": json.dumps({"module": drill["module"]}),
                    "ts": ctx.now - timedelta(days=float(rng.uniform(0, ctx.history_days))),
                }
            )
    ctx.emit("sim_sessions", pd.DataFrame(sessions))
    _quiz_questions(ctx)


def _quiz_questions(ctx: GenContext) -> None:
    """Quiz questions come only from human-approved content (`tp content` → `tp review approve`)."""
    approved = REPO_ROOT / "knowledge" / "quizzes"
    rows: list[dict[str, Any]] = []
    for path in sorted(approved.glob("*.json")) if approved.is_dir() else []:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        for i, q in enumerate(data.get("questions", [])):
            rows.append(
                {
                    "id": f"Q-{path.stem}-{i}",
                    "module_id": data["module_id"],
                    "stem": q["stem"],
                    "options": json.dumps(q["options"]),
                    "answer": int(q["answer_index"]),
                    "difficulty": q.get("difficulty"),
                    "source_chunk_id": data.get("source_chunk_id"),
                }
            )
    ctx.emit(
        "quiz_questions",
        pd.DataFrame(rows, columns=["id", "module_id", "stem", "options", "answer", "difficulty", "source_chunk_id"]),
    )
