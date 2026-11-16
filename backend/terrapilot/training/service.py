"""Training hub (§10.8): modules and lessons, quizzes, instructor booking with conflict checks, adaptive
assignment from behaviour/maintenance signals, and the certification gating that machine select already uses.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta
from typing import Any

import pandas as pd
from sqlalchemy import Connection, insert, select, update

from terrapilot.db.schema import assignments, attempts, bookings
from terrapilot.planning.context import PlanningContext

DAYS_PER_WEEK = 7


# ------------------------------------------------------------------ catalogue
def modules(ctx: PlanningContext, machine_class: str | None = None) -> list[dict[str, Any]]:
    mods = ctx.t.get("modules")
    lessons = ctx.t.get("lessons")
    videos = ctx.t.get("video_assets").set_index("id") if not ctx.t.get("video_assets").empty else pd.DataFrame()
    quiz = ctx.t.get("quiz_questions")
    out = []
    for m in mods.to_dict("records"):
        if machine_class and m["machine_class"] not in (machine_class, "common"):
            continue
        rows = lessons[lessons["module_id"] == m["id"]].sort_values("order") if not lessons.empty else lessons
        items = []
        for row in rows.to_dict("records"):
            asset = row.get("asset_id")
            video = dict(videos.loc[asset]) if asset and not videos.empty and asset in videos.index else None
            items.append(
                {
                    "id": row["id"],
                    "kind": row["kind"],
                    "asset_id": asset,
                    "order": int(row["order"]),
                    "video": {
                        "uri": video["uri"],
                        "duration_s": float(video["duration_s"]),
                        "chapters": video["chapters"],
                        "status": video["status"],
                        "title_key": video["title_key"],
                    }
                    if video
                    else None,
                }
            )
        out.append(
            {
                **{k: m[k] for k in ("id", "title_key", "machine_class", "kind", "est_minutes")},
                "prerequisites": list(m.get("prerequisites") or []),
                "lessons": items,
                "quiz_questions": int((quiz["module_id"] == m["id"]).sum()) if not quiz.empty else 0,
            }
        )
    return out


def quiz_for(ctx: PlanningContext, module_id: str, limit: int | None = None) -> list[dict[str, Any]]:
    """Questions without the answer key; each keeps its source chunk so a wrong answer can cite the manual."""
    q = ctx.t.get("quiz_questions")
    rows = q[q["module_id"] == module_id] if not q.empty else q
    cfg = ctx.cfg.datagen.get("training", {}).get("completion", {})
    n = limit or int(cfg.get("questions_per_attempt", 4))
    picked = rows.sample(min(n, len(rows)), random_state=None) if len(rows) else rows
    return [
        {
            "id": r["id"],
            "stem": r["stem"],
            "options": list(r["options"]),
            "difficulty": r.get("difficulty"),
            "source_chunk_id": r.get("source_chunk_id"),
        }
        for r in picked.to_dict("records")
    ]


def grade_quiz(ctx: PlanningContext, module_id: str, answers: dict[str, str]) -> dict[str, Any]:
    """Score an attempt and return the manual excerpt for every wrong answer (§10.8.2)."""
    q = ctx.t.get("quiz_questions").set_index("id")
    pass_mark = float(ctx.cfg.datagen["training"]["completion"]["pass_mark"])
    detail, correct = [], 0
    kb = None
    try:
        from terrapilot.copilot.knowledge import KnowledgeBase

        kb = KnowledgeBase.load(ctx.cfg)
    except (FileNotFoundError, RuntimeError):
        kb = None
    for qid, given in answers.items():
        if qid not in q.index:
            continue
        row = q.loc[qid]
        ok = str(given) == str(row["answer"])
        correct += int(ok)
        excerpt = None
        if not ok and kb is not None and row.get("source_chunk_id"):
            chunk = next((c for c in kb.chunks if c.id == row["source_chunk_id"]), None)
            excerpt = {"chunk_id": chunk.id, "heading": chunk.heading, "text": chunk.text[:800]} if chunk else None
        detail.append(
            {"question_id": qid, "correct": ok, "answer": row["answer"] if not ok else None, "excerpt": excerpt}
        )
    score = correct / len(detail) if detail else 0.0
    return {
        "module_id": module_id,
        "score": round(score, 3),
        "passed": score >= pass_mark,
        "pass_mark": pass_mark,
        "detail": detail,
    }


def record_attempt(
    conn: Connection, user_id: str, lesson_id: str, score: float, detail: dict[str, Any], now: datetime
) -> str:
    aid = f"AT-{uuid.uuid4().hex[:14]}"
    conn.execute(
        insert(attempts).values(
            id=aid, user_id=user_id, lesson_id=lesson_id, score=score, started_at=now, completed_at=now, detail=detail
        )
    )
    conn.commit()
    return aid


# ------------------------------------------------------------------ my training
def my_training(ctx: PlanningContext, user_id: str, machine_id: str | None = None) -> dict[str, Any]:
    machine_class = (
        str(ctx.machines.loc[machine_id, "machine_class"]) if machine_id and machine_id in ctx.machines.index else None
    )
    mods = {m["id"]: m for m in modules(ctx, machine_class)}
    certs = ctx.t.get("certifications")
    mine = certs[certs["user_id"] == user_id] if not certs.empty else certs
    grace_days = 0.0
    if machine_id and machine_id in ctx.machines.index:
        training_cfg = ctx.manifest_raw(machine_id).get("training") or {}
        grace_days = float(training_cfg.get("expiry_grace_days") or 0)
    cert_rows = []
    for c in mine.to_dict("records"):
        expires = pd.Timestamp(c["expires_at"])
        days = (expires - pd.Timestamp(ctx.now)).total_seconds() / 86400
        status = "expired" if days < 0 else "expiring" if days <= grace_days + DAYS_PER_WEEK else "valid"
        cert_rows.append(
            {
                "module_id": c["module_id"],
                "machine_class": c["machine_class"],
                "expires_at": expires.isoformat(),
                "days_left": round(days, 1),
                "status": status,
            }
        )
    asg = ctx.t.get("assignments")
    mine_asg = asg[(asg["user_id"] == user_id) & (asg["status"] != "done")] if not asg.empty else asg
    att = ctx.t.get("attempts")
    mine_att = att[att["user_id"] == user_id] if not att.empty else att
    lessons = ctx.t.get("lessons")
    progress = {}
    for mod_id, mod in mods.items():
        ids = {lsn["id"] for lsn in mod["lessons"]}
        done = mine_att[mine_att["lesson_id"].isin(ids)] if not mine_att.empty else mine_att
        progress[mod_id] = {"lessons": len(ids), "completed": int(done["lesson_id"].nunique()) if not done.empty else 0}
    _ = lessons
    return {
        "user_id": user_id,
        "machine_class": machine_class,
        "modules": list(mods.values()),
        "progress": progress,
        "certifications": sorted(cert_rows, key=lambda c: c["days_left"]),
        "expiring": [c for c in cert_rows if c["status"] in ("expiring", "expired")],
        "assignments": [
            {
                "id": a["id"],
                "module_id": a["module_id"],
                "reason_kind": a["reason_kind"],
                "reason_ref": a.get("reason_ref"),
                "due_at": pd.Timestamp(a["due_at"]).isoformat() if a.get("due_at") is not None else None,
                "status": a["status"],
            }
            for a in mine_asg.to_dict("records")
        ],
    }


# ------------------------------------------------------------------ adaptive assignment (§10.8.5)
def sync_assignments(ctx: PlanningContext, conn: Connection, user_id: str) -> list[dict[str, Any]]:
    """Behaviour/maintenance signals → module assignments, with a priority and a due date from config."""
    from terrapilot.analytics.behavior import scorecard

    ac = ctx.cfg.datagen.get("training", {}).get("assignment", {})
    due_days = float(ac.get("due_days", 14))
    card = scorecard(ctx.cfg, ctx.t, user_id, ctx.now, int(ac.get("window_days", 30)))
    existing = ctx.t.get("assignments")
    open_mods = (
        set(existing[(existing["user_id"] == user_id) & (existing["status"] != "done")]["module_id"])
        if not existing.empty
        else set()
    )
    created = []
    for s in card["suggested_modules"]:
        if s["module"] in open_mods:
            continue
        observed = float(s["observed"]) if isinstance(s["observed"], int | float) else 0.0
        threshold = float(s["threshold"]) or 1.0
        priority = round(min(3.0, observed / threshold), 2)
        row = {
            "id": f"AS-{user_id}-{s['module']}-{int(ctx.now.timestamp())}",
            "user_id": user_id,
            "module_id": s["module"],
            "reason_kind": s["signal"],
            "reason_ref": f"scorecard:{card['days']}d",
            "due_at": ctx.now + timedelta(days=due_days),
            "status": "open",
            "created_at": ctx.now,
        }
        conn.execute(insert(assignments).values(**row))
        created.append(
            {
                **row,
                "priority": priority,
                "due_at": row["due_at"].isoformat(),
                "created_at": row["created_at"].isoformat(),
            }
        )
    # expiring certifications create assignments N days ahead (§10.8.5)
    lead = float(ac.get("cert_lead_days", 21))
    for c in my_training(ctx, user_id)["certifications"]:
        if c["status"] == "valid" and c["days_left"] > lead:
            continue
        if c["module_id"] in open_mods:
            continue
        row = {
            "id": f"AS-{user_id}-{c['module_id']}-cert-{int(ctx.now.timestamp())}",
            "user_id": user_id,
            "module_id": c["module_id"],
            "reason_kind": "cert_expiring",
            "reason_ref": c["expires_at"],
            "due_at": pd.Timestamp(c["expires_at"]).to_pydatetime(),
            "status": "open",
            "created_at": ctx.now,
        }
        conn.execute(insert(assignments).values(**row))
        created.append({**row, "priority": 3.0, "due_at": c["expires_at"], "created_at": row["created_at"].isoformat()})
    if created:
        conn.commit()
    return created


# ------------------------------------------------------------------ booking (§10.8.3)
def slots(
    ctx: PlanningContext, site_id: str | None, instructor: str | None, start: datetime | None, end: datetime | None
) -> list[dict[str, Any]]:
    s = ctx.t.get("instructor_slots")
    b = ctx.t.get("bookings")
    rows = s.copy()
    if site_id:
        rows = rows[rows["site_id"] == site_id]
    if instructor:
        rows = rows[rows["instructor_id"] == instructor]
    rows = rows[rows["start"] >= pd.Timestamp(start or ctx.now)]
    if end:
        rows = rows[rows["start"] <= pd.Timestamp(end)]
    booked = b[b["status"] == "booked"].groupby("slot_id").size().to_dict() if not b.empty else {}
    return [
        {
            "id": r["id"],
            "instructor_id": r["instructor_id"],
            "site_id": r["site_id"],
            "mode": r["mode"],
            "start": pd.Timestamp(r["start"]).isoformat(),
            "end": pd.Timestamp(r["end"]).isoformat(),
            "capacity": int(r["capacity"]),
            "booked": int(booked.get(r["id"], 0)),
            "free": int(r["capacity"]) - int(booked.get(r["id"], 0)),
        }
        for r in rows.sort_values("start").to_dict("records")
    ]


class BookingError(ValueError):
    def __init__(self, message_key: str):
        super().__init__(message_key)
        self.message_key = message_key


def book(ctx: PlanningContext, conn: Connection, user_id: str, slot_id: str, module_id: str) -> dict[str, Any]:
    """Rejects a full slot, a double booking, or a clash with the operator's assigned shift (§10.8.3)."""
    s = ctx.t.get("instructor_slots")
    row = s[s["id"] == slot_id]
    if row.empty:
        raise BookingError("training.error.slot_not_found")
    slot = row.iloc[0]
    slot_start, slot_end = pd.Timestamp(slot["start"]), pd.Timestamp(slot["end"])
    live = [dict(r) for r in conn.execute(select(bookings).where(bookings.c.slot_id == slot_id)).mappings()]
    if len([b for b in live if b["status"] == "booked"]) >= int(slot["capacity"]):
        raise BookingError("training.error.slot_full")
    if any(b["user_id"] == user_id and b["status"] == "booked" for b in live):
        raise BookingError("training.error.already_booked")
    sa = ctx.t.get("shift_assignments")
    mine = sa[sa["operator_id"] == user_id] if not sa.empty else sa
    for a in mine.to_dict("records"):
        if pd.Timestamp(a["shift_start"]) < slot_end and pd.Timestamp(a["shift_end"]) > slot_start:
            raise BookingError("training.error.shift_clash")
    bid = f"BK-{uuid.uuid4().hex[:12]}"
    conn.execute(
        insert(bookings).values(
            id=bid, slot_id=slot_id, user_id=user_id, module_id=module_id, status="booked", notes=None
        )
    )
    conn.commit()
    return {
        "id": bid,
        "slot_id": slot_id,
        "module_id": module_id,
        "status": "booked",
        "start": slot_start.isoformat(),
        "end": slot_end.isoformat(),
    }


def cancel(ctx: PlanningContext, conn: Connection, booking_id: str, user_id: str) -> dict[str, Any]:
    row = conn.execute(select(bookings).where(bookings.c.id == booking_id)).mappings().first()
    if row is None or row["user_id"] != user_id:
        raise BookingError("training.error.not_found")
    s = ctx.t.get("instructor_slots")
    slot = s[s["id"] == row["slot_id"]]
    cancel_h = float(ctx.cfg.datagen.get("training", {}).get("booking", {}).get("cancel_window_h", 12))
    if not slot.empty and pd.Timestamp(slot.iloc[0]["start"]) - pd.Timestamp(ctx.now) < pd.Timedelta(hours=cancel_h):
        raise BookingError("training.error.cancel_window")
    conn.execute(update(bookings).where(bookings.c.id == booking_id).values(status="cancelled"))
    conn.commit()
    return {**dict(row), "status": "cancelled"}
