"""Copilot chat (§9.2 Copilot): Ask mode over the LangGraph pipeline, sessions, and the VLM photo tool."""

from __future__ import annotations

import json
import uuid
from typing import Any

from fastapi import APIRouter, File, Form, UploadFile, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import insert, select

from terrapilot.api.deps import ConfigDep, CurrentUser, DbDep, Principal, api_error
from terrapilot.api.routers.day import _media_path, planning_ctx
from terrapilot.copilot.ask import AskResponse, ask
from terrapilot.copilot.guard_log import persist_guard
from terrapilot.copilot.tools import AskContext
from terrapilot.core.config import ConfigBundle
from terrapilot.core.settings import get_settings
from terrapilot.core.timeutil import utcnow
from terrapilot.db.schema import chat_messages, chat_sessions, machines

router = APIRouter(tags=["copilot"])


class ChatIn(BaseModel):
    message: str = Field(min_length=1, max_length=4000)
    session_id: str | None = None
    machine_id: str | None = None
    device: str = "mobile"


def _gateway() -> Any:
    from terrapilot.llm.gateway import get_gateway

    try:
        return get_gateway()
    except Exception:
        return None


def build_context(
    cfg: ConfigBundle, principal: Principal, conn: Any, question: str, machine_id: str | None, device: str
) -> AskContext:
    manifest = None
    if machine_id:
        row = conn.execute(select(machines.c.manifest_id).where(machines.c.id == machine_id)).first()
        if row is not None:
            manifest = cfg.manifests_raw.get(row[0])
    ctx = AskContext(
        cfg=cfg,
        user_id=principal.user_id,
        role=principal.role,
        site_id=principal.site_id,
        machine_id=machine_id,
        manifest=manifest,
        question=question,
        device=device,
        locale=principal.locale or cfg.app.locales.default,
        planning=planning_ctx(cfg),
    )
    try:
        from terrapilot.copilot.knowledge import KnowledgeBase

        ctx.kb = KnowledgeBase.load(cfg)
    except (FileNotFoundError, RuntimeError):
        ctx.kb = None
    return ctx


def _store(conn: Any, session_id: str, user_id: str, machine_id: str | None, question: str, resp: AskResponse) -> None:
    exists = conn.execute(select(chat_sessions.c.id).where(chat_sessions.c.id == session_id)).first()
    if not exists:
        conn.execute(insert(chat_sessions).values(id=session_id, user_id=user_id, machine_id=machine_id))
    now = utcnow().timestamp()
    conn.execute(
        insert(chat_messages).values(
            id=f"CM-{uuid.uuid4().hex[:14]}",
            session_id=session_id,
            role="user",
            content=question,
            tool_calls=None,
            citations=None,
            confidence=None,
            guard_actions=None,
        )
    )
    conn.execute(
        insert(chat_messages).values(
            id=f"CM-{uuid.uuid4().hex[:14]}",
            session_id=session_id,
            role="assistant",
            content=resp.text,
            tool_calls=resp.trace,
            citations=resp.citations,
            confidence=resp.confidence,
            guard_actions=[
                {"layer": g["layer"], "rule_id": g["rule_id"], "action": g["action"]} for g in resp.guard_events
            ],
        )
    )
    for g in resp.guard_events:
        persist_guard(conn, g)
    conn.commit()
    _ = now


@router.post("/api/chat")
def chat(body: ChatIn, principal: CurrentUser, cfg: ConfigDep, conn: DbDep) -> dict[str, Any]:
    if not cfg.app.features.get("copilot_ask", True):
        raise api_error(status.HTTP_404_NOT_FOUND, "not_found")
    ctx = build_context(cfg, principal, conn, body.message, body.machine_id, body.device)
    resp = ask(cfg, ctx, _gateway())
    session_id = body.session_id or f"CS-{uuid.uuid4().hex[:14]}"
    _store(conn, session_id, principal.user_id, body.machine_id, body.message, resp)
    return {"session_id": session_id, **resp.as_dict()}


@router.post("/api/chat/stream")
def chat_stream(body: ChatIn, principal: CurrentUser, cfg: ConfigDep, conn: DbDep) -> StreamingResponse:
    """SSE: `trace` events as the graph runs, then one `answer` event. The graph itself is not token-streamed;
    the UI shows the reasoning trace while it works."""
    ctx = build_context(cfg, principal, conn, body.message, body.machine_id, body.device)
    session_id = body.session_id or f"CS-{uuid.uuid4().hex[:14]}"

    def events() -> Any:
        yield f"event: start\ndata: {json.dumps({'session_id': session_id})}\n\n"
        resp = ask(cfg, ctx, _gateway())
        for step in resp.trace:
            yield f"event: trace\ndata: {json.dumps(step, default=str)}\n\n"
        _store(conn, session_id, principal.user_id, body.machine_id, body.message, resp)
        yield f"event: answer\ndata: {json.dumps({'session_id': session_id, **resp.as_dict()}, default=str)}\n\n"

    return StreamingResponse(events(), media_type="text/event-stream")


@router.get("/api/chat/sessions/{session_id}")
def get_session(session_id: str, principal: CurrentUser, conn: DbDep) -> dict[str, Any]:
    s = conn.execute(select(chat_sessions).where(chat_sessions.c.id == session_id)).mappings().first()
    if s is None or (s["user_id"] != principal.user_id and principal.role == "operator"):
        raise api_error(status.HTTP_404_NOT_FOUND, "not_found")
    msgs = conn.execute(
        select(chat_messages).where(chat_messages.c.session_id == session_id).order_by(chat_messages.c.created_at)
    ).mappings()
    return {"session": dict(s), "messages": [dict(m) for m in msgs]}


@router.post("/api/troubleshoot/photo")
async def troubleshoot_photo(
    principal: CurrentUser,
    cfg: ConfigDep,
    conn: DbDep,
    file: UploadFile = File(...),  # noqa: B008 — FastAPI dependency default
    machine_id: str = Form(...),
    note: str = Form(default=""),
) -> dict[str, Any]:
    """VLM troubleshooting (§10.7.3): closed label set, self-consistency confidence, escalation guard."""
    from terrapilot.copilot.vlm import diagnose

    media = cfg.media["uploads"]
    if file.content_type not in media["image_types"]:
        raise api_error(status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, "unsupported_media")
    data = await file.read()
    if len(data) > float(media["image_max_mb"]) * 1024 * 1024:
        raise api_error(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, "too_large")
    row = conn.execute(select(machines.c.manifest_id).where(machines.c.id == machine_id)).first()
    if row is None:
        raise api_error(status.HTTP_404_NOT_FOUND, "not_found")
    path, uri = _media_path(
        cfg, f"{cfg.app.cab_notes.get('media_dir', 'media/notes')}/troubleshoot", file.filename or "photo.jpg"
    )
    path.write_bytes(data)
    out = diagnose(cfg, path, str(row[0]), machine_id, note, _gateway())
    for g in out.get("guard_events", []):
        persist_guard(conn, g)
    conn.commit()
    _ = get_settings()
    return {**out, "image_uri": uri}
