"""Training hub (§9.2 Training)."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from fastapi import APIRouter, status
from pydantic import BaseModel, Field

from terrapilot.api.deps import ConfigDep, CurrentUser, DbDep, api_error
from terrapilot.api.routers.day import planning_ctx
from terrapilot.training.service import (
    BookingError,
    book,
    cancel,
    grade_quiz,
    modules,
    my_training,
    quiz_for,
    record_attempt,
    slots,
    sync_assignments,
)

router = APIRouter(prefix="/api/training", tags=["training"])


@router.get("/me")
def training_me(
    principal: CurrentUser, cfg: ConfigDep, machine: str | None = None, at: str | None = None
) -> dict[str, Any]:
    ctx = planning_ctx(cfg, at)
    return my_training(ctx, principal.user_id, machine)


@router.post("/me/sync")
def training_sync(principal: CurrentUser, cfg: ConfigDep, conn: DbDep, at: str | None = None) -> dict[str, Any]:
    """Adaptive assignment (§10.8.5): behaviour signals and expiring certs create module assignments."""
    ctx = planning_ctx(cfg, at)
    created = sync_assignments(ctx, conn, principal.user_id)
    return {"created": created}


@router.get("/modules")
def training_modules(_: CurrentUser, cfg: ConfigDep, machine_class: str | None = None) -> list[dict[str, Any]]:
    return modules(planning_ctx(cfg), machine_class)


@router.get("/modules/{module_id}/quiz")
def training_quiz(module_id: str, _: CurrentUser, cfg: ConfigDep) -> dict[str, Any]:
    questions = quiz_for(planning_ctx(cfg), module_id)
    if not questions:
        raise api_error(status.HTTP_404_NOT_FOUND, "quiz_unavailable")
    return {"module_id": module_id, "questions": questions}


class QuizIn(BaseModel):
    answers: dict[str, str]
    lesson_id: str | None = None


@router.post("/modules/{module_id}/attempts", status_code=status.HTTP_201_CREATED)
def training_attempt(
    module_id: str, body: QuizIn, principal: CurrentUser, cfg: ConfigDep, conn: DbDep
) -> dict[str, Any]:
    ctx = planning_ctx(cfg)
    result = grade_quiz(ctx, module_id, body.answers)
    attempt_id = record_attempt(
        conn, principal.user_id, body.lesson_id or f"{module_id}_quiz", result["score"], result, ctx.now
    )
    return {"attempt_id": attempt_id, **result}


@router.get("/slots")
def training_slots(
    _: CurrentUser,
    cfg: ConfigDep,
    site: str | None = None,
    instructor: str | None = None,
    start: datetime | None = None,
    end: datetime | None = None,
) -> list[dict[str, Any]]:
    return slots(planning_ctx(cfg), site, instructor, start, end)


class BookingIn(BaseModel):
    slot_id: str = Field(min_length=1)
    module_id: str = Field(min_length=1)


@router.post("/bookings", status_code=status.HTTP_201_CREATED)
def training_book(body: BookingIn, principal: CurrentUser, cfg: ConfigDep, conn: DbDep) -> dict[str, Any]:
    try:
        return book(planning_ctx(cfg), conn, principal.user_id, body.slot_id, body.module_id)
    except BookingError as exc:
        raise api_error(status.HTTP_409_CONFLICT, exc.message_key.split(".")[-1]) from exc


@router.delete("/bookings/{booking_id}")
def training_cancel(booking_id: str, principal: CurrentUser, cfg: ConfigDep, conn: DbDep) -> dict[str, Any]:
    try:
        return cancel(planning_ctx(cfg), conn, booking_id, principal.user_id)
    except BookingError as exc:
        raise api_error(status.HTTP_409_CONFLICT, exc.message_key.split(".")[-1]) from exc
