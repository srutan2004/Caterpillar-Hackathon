"""Operator day (§9.2 Tasks & day): shift view, task estimates, backward scheduling, walkaround, cab notes."""

from __future__ import annotations

import re
import uuid
from datetime import datetime
from pathlib import Path
from typing import Annotated, Any

from fastapi import APIRouter, File, Form, UploadFile, status
from pydantic import BaseModel, Field
from sqlalchemy import insert, select

from terrapilot.api.deps import ConfigDep, CurrentUser, DbDep, Principal, api_error
from terrapilot.core import clock
from terrapilot.core.config import ConfigBundle
from terrapilot.core.settings import get_settings
from terrapilot.db.schema import cab_notes, machines, service_requests, walkarounds
from terrapilot.planning.context import PlanningContext, invalidate_shared, shared_context
from terrapilot.planning.estimate import estimate_task, usual_duration
from terrapilot.planning.schedule import backschedule
from terrapilot.planning.shift import build_shift, todays_tasks

router = APIRouter(tags=["day"])
SAFE_NAME = re.compile(r"[^A-Za-z0-9._-]")


def planning_ctx(cfg: ConfigBundle, at: str | None = None) -> PlanningContext:
    ctx = shared_context(cfg)
    if at:
        ctx.now = clock.now(ctx.tz, at)
    return ctx


def _operator_for(principal: Principal, operator: str | None) -> str:
    if operator and operator != principal.user_id and principal.role == "operator":
        raise api_error(status.HTTP_403_FORBIDDEN, "forbidden")
    return operator or principal.user_id


@router.get("/api/me/shift")
def my_shift(
    principal: CurrentUser, cfg: ConfigDep, conn: DbDep, operator: str | None = None, at: str | None = None
) -> dict[str, Any]:
    """Today's assignment, tasks (ETC p10–p90 + factors, best start, energy, maintenance), pacing, readiness."""
    ctx = planning_ctx(cfg, at)
    return build_shift(ctx, conn, _operator_for(principal, operator))


@router.get("/api/tasks")
def list_tasks(
    principal: CurrentUser,
    cfg: ConfigDep,
    operator: str | None = None,
    status_: str | None = None,
    at: str | None = None,
) -> list[dict[str, Any]]:
    ctx = planning_ctx(cfg, at)
    rows = todays_tasks(ctx, _operator_for(principal, operator))
    return [r for r in rows if status_ is None or r.get("status") == status_]


@router.get("/api/tasks/{task_id}/estimate")
def task_estimate(
    task_id: str, _: CurrentUser, cfg: ConfigDep, start: str | None = None, at: str | None = None
) -> dict[str, Any]:
    ctx = planning_ctx(cfg, at)
    try:
        task = ctx.task(task_id)
    except KeyError as exc:
        raise api_error(status.HTTP_404_NOT_FOUND, "not_found") from exc
    s = clock.now(ctx.tz, start) if start else None
    est = estimate_task(ctx, task, s)
    return {"task_id": task_id, **est.as_dict(), "usual": usual_duration(ctx, task)}


class BackscheduleIn(BaseModel):
    task_ids: list[str] = Field(min_length=1)
    deadline: datetime
    quantile: str | None = None


@router.post("/api/tasks/backschedule")
def tasks_backschedule(body: BackscheduleIn, _: CurrentUser, cfg: ConfigDep, at: str | None = None) -> dict[str, Any]:
    ctx = planning_ctx(cfg, at)
    try:
        return backschedule(ctx, body.task_ids, body.deadline, body.quantile)
    except KeyError as exc:
        raise api_error(status.HTTP_404_NOT_FOUND, "not_found") from exc
    except ValueError as exc:
        raise api_error(status.HTTP_422_UNPROCESSABLE_ENTITY, "invalid") from exc


# ------------------------------------------------------------------ walkaround
def _walkaround_cfg(cfg: ConfigBundle, conn: Any, machine_id: str) -> dict[str, Any]:
    row = conn.execute(select(machines.c.manifest_id).where(machines.c.id == machine_id)).first()
    if row is None or row[0] not in cfg.manifests_raw:
        raise api_error(status.HTTP_404_NOT_FOUND, "not_found")
    wk = cfg.manifests_raw[row[0]].get("walkaround")
    if not isinstance(wk, dict):
        raise api_error(status.HTTP_404_NOT_FOUND, "not_found")
    return wk


@router.get("/api/walkaround/{machine_id}")
def get_walkaround(
    machine_id: str, _: CurrentUser, cfg: ConfigDep, conn: DbDep, at: str | None = None
) -> dict[str, Any]:
    """Checklist from the manifest's walkaround config plus today's latest submission."""
    wk = _walkaround_cfg(cfg, conn, machine_id)
    ctx = planning_ctx(cfg, at)
    return {"machine_id": machine_id, **wk, "latest": ctx.latest_walkaround(machine_id)}


class WalkItemIn(BaseModel):
    id: str
    status: str = Field(pattern="^(ok|issue)$")
    note: str | None = Field(default=None, max_length=2000)
    photo_uri: str | None = None


class WalkaroundIn(BaseModel):
    items: list[WalkItemIn]


@router.post("/api/walkaround/{machine_id}", status_code=status.HTTP_201_CREATED)
def post_walkaround(
    machine_id: str, body: WalkaroundIn, principal: CurrentUser, cfg: ConfigDep, conn: DbDep, at: str | None = None
) -> dict[str, Any]:
    """Issues auto-create a maintenance note (service request); a critical issue blocks the start."""
    wk = _walkaround_cfg(cfg, conn, machine_id)
    spec = {i["id"]: i for i in wk["items"]}
    unknown = [i.id for i in body.items if i.id not in spec]
    missing = [k for k in spec if k not in {i.id for i in body.items}]
    if unknown or missing:
        raise api_error(status.HTTP_422_UNPROCESSABLE_ENTITY, "walkaround_incomplete")
    issues = [i for i in body.items if i.status == "issue"]
    for i in issues:
        if spec[i.id].get("photo") == "on_issue" and not i.photo_uri:
            raise api_error(status.HTTP_422_UNPROCESSABLE_ENTITY, "walkaround_photo_required")
    critical = [i for i in issues if spec[i.id].get("critical")]
    result = "critical" if critical else "issues" if issues else "ok"
    now = clock.now(planning_ctx(cfg).tz, at) if at else clock.now()
    wid = f"WK-{machine_id}-{uuid.uuid4().hex[:10]}"
    conn.execute(
        insert(walkarounds).values(
            id=wid,
            machine_id=machine_id,
            operator_id=principal.user_id,
            ts=now,
            result=result,
            items=[i.model_dump() for i in body.items],
            photos=[i.photo_uri for i in body.items if i.photo_uri],
            blocks_start=bool(critical),
        )
    )
    notes = []
    for i in issues:
        sr_id = f"SR-{wid}-{i.id}"
        conn.execute(
            insert(service_requests).values(
                id=sr_id,
                machine_id=machine_id,
                requested_by=principal.user_id,
                kind="walkaround",
                fault_code=None,
                part_nos=[],
                diagnosis_ref=f"{wid}:{i.id}",
                status="open",
                eta=None,
            )
        )
        notes.append(sr_id)
    conn.commit()
    invalidate_shared()
    return {"id": wid, "result": result, "blocks_start": bool(critical), "service_requests": notes}


def _media_path(cfg: ConfigBundle, rel_dir: str, name: str) -> tuple[Path, str]:
    base = get_settings().data_dir / rel_dir
    base.mkdir(parents=True, exist_ok=True)
    safe = SAFE_NAME.sub("_", name)[-80:] or "upload"
    fname = f"{uuid.uuid4().hex[:12]}-{safe}"
    return base / fname, f"{rel_dir}/{fname}"


@router.post("/api/walkaround/{machine_id}/photos", status_code=status.HTTP_201_CREATED)
async def walkaround_photo(
    machine_id: str, _: CurrentUser, cfg: ConfigDep, file: Annotated[UploadFile, File()]
) -> dict[str, str]:
    media = cfg.media["uploads"]
    allowed, max_mb = list(media["image_types"]), float(media["image_max_mb"])
    if file.content_type not in allowed:
        raise api_error(status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, "unsupported_media")
    data = await file.read()
    if len(data) > max_mb * 1024 * 1024:
        raise api_error(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, "too_large")
    path, uri = _media_path(cfg, f"{cfg.app.walkaround_media_dir}/{machine_id}", file.filename or "photo")
    path.write_bytes(data)
    return {"uri": uri}


# ------------------------------------------------------------------ cab notes
def tag_note(cfg: ConfigBundle, text: str) -> list[str]:
    tags_cfg = cfg.app.cab_notes.get("tags", {})
    low = text.lower()
    tags = [tag for tag, words in tags_cfg.items() if any(re.search(rf"\b{re.escape(w)}", low) for w in words)]
    return tags or [str(cfg.app.cab_notes.get("default_tag", "other"))]


@router.post("/api/notes", status_code=status.HTTP_201_CREATED)
async def post_note(
    principal: CurrentUser,
    cfg: ConfigDep,
    conn: DbDep,
    text: Annotated[str | None, Form(max_length=4000)] = None,
    machine_id: Annotated[str | None, Form()] = None,
    audio: Annotated[UploadFile | None, File()] = None,
) -> dict[str, Any]:
    """Text or push-to-talk audio → Groq Whisper (`stt` task) → text → keyword tags."""
    audio_uri, stt = None, None
    if audio is not None:
        data = await audio.read()
        if len(data) > float(cfg.app.cab_notes.get("audio_max_mb", 10)) * 1024 * 1024:
            raise api_error(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, "too_large")
        path, audio_uri = _media_path(
            cfg, str(cfg.app.cab_notes.get("media_dir", "media/notes")), audio.filename or "note.webm"
        )
        path.write_bytes(data)
        stt = _transcribe(cfg, path)
        if stt.get("text"):
            text = stt["text"]
    if not text or not text.strip():
        raise api_error(status.HTTP_422_UNPROCESSABLE_ENTITY, "stt_unavailable" if audio is not None else "invalid")
    tags = tag_note(cfg, text)
    nid = f"CN-{uuid.uuid4().hex[:12]}"
    conn.execute(
        insert(cab_notes).values(
            id=nid,
            operator_id=principal.user_id,
            machine_id=machine_id,
            ts=clock.now(),
            text=text.strip(),
            audio_uri=audio_uri,
            tags=tags,
        )
    )
    conn.commit()
    return {"id": nid, "text": text.strip(), "tags": tags, "audio_uri": audio_uri, "stt": stt}


def _transcribe(cfg: ConfigBundle, path: Path) -> dict[str, Any]:
    task = cfg.llm.tasks.get("stt")
    key = get_settings().groq_key
    if task is None or key is None or get_settings().tp_profile == "offline":
        return {"status": "unavailable"}
    from terrapilot.llm.providers.groq_provider import GroqProvider

    base_url = cfg.llm.providers["groq"].model_dump().get("base_url")
    models = [task.model, *[f.split(":", 1)[1] for f in task.fallback or [] if f.startswith("groq:")]]
    for model in models:
        try:
            out = GroqProvider(key, base_url).transcribe(path, model)
            return {"status": "ok", "model": model, "text": out.get("text", "")}
        except Exception:
            continue
    return {"status": "unavailable"}


@router.get("/api/notes")
def list_notes(principal: CurrentUser, conn: DbDep, limit: int = 20) -> list[dict[str, Any]]:
    q = (
        select(cab_notes)
        .where(cab_notes.c.operator_id == principal.user_id)
        .order_by(cab_notes.c.ts.desc())
        .limit(min(limit, 100))
    )
    return [dict(r) for r in conn.execute(q).mappings()]
