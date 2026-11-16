"""Auth: badge/PIN login → JWT with role; machine selection with certification gating (§10.1)."""

from __future__ import annotations

from datetime import datetime, timedelta

from fastapi import APIRouter, status
from sqlalchemy import or_, select

from terrapilot.api.deps import ConfigDep, CurrentUser, DbDep, api_error
from terrapilot.api.routers.machines import machine_out
from terrapilot.api.schemas import (
    GatingModule,
    GatingResult,
    LoginRequest,
    LoginResponse,
    MachineSelectRequest,
    MachineSelectResponse,
    UserOut,
)
from terrapilot.core.config import ConfigBundle
from terrapilot.core.security import create_token, verify_pin
from terrapilot.core.settings import get_settings
from terrapilot.core.timeutil import utcnow
from terrapilot.db.schema import certifications, machines, users

router = APIRouter(prefix="/api/auth", tags=["auth"])


@router.post("/login", response_model=LoginResponse)
def login(body: LoginRequest, cfg: ConfigDep, conn: DbDep) -> LoginResponse:
    row = (
        conn.execute(select(users).where(or_(users.c.id == body.username, users.c.badge_id == body.username)))
        .mappings()
        .first()
    )
    if row is None or not verify_pin(body.pin, row["pin_hash"]):
        raise api_error(status.HTTP_401_UNAUTHORIZED, "unauthorized")
    auth = cfg.app.auth
    token = create_token(
        row["id"],
        row["role"],
        get_settings().jwt_secret.get_secret_value(),
        auth.jwt_algorithm,
        auth.token_ttl_min,
        name=row["name"],
        site_id=row["site_id"],
        locale=row["locale"],
    )
    return LoginResponse(
        access_token=token,
        expires_in_s=auth.token_ttl_min * 60,
        user=UserOut(id=row["id"], name=row["name"], role=row["role"], locale=row["locale"], site_id=row["site_id"]),
    )


@router.get("/me", response_model=UserOut)
def me(principal: CurrentUser, cfg: ConfigDep) -> UserOut:
    return UserOut(
        id=principal.user_id,
        name=principal.name,
        role=principal.role,
        locale=principal.locale or cfg.app.locales.default,
        site_id=principal.site_id,
    )


def evaluate_gating(cfg: ConfigBundle, manifest_id: str, certs: list[dict[str, object]], now: datetime) -> GatingResult:
    """full = every required module valid; restricted = one expired within grace; blocked = missing/expired."""
    manifest = cfg.manifests[manifest_id]
    titles = {m["id"]: m["title_key"] for m in (cfg.datagen.get("training") or {}).get("modules", [])}
    grace = timedelta(days=manifest.training.expiry_grace_days)
    expiring_window = timedelta(
        days=float((cfg.datagen.get("training") or {}).get("certs", {}).get("expiring_window_days", 0))
    )
    latest: dict[str, datetime] = {}
    for c in certs:
        mod, exp = str(c["module_id"]), c["expires_at"]
        assert isinstance(exp, datetime)
        exp = exp if exp.tzinfo else exp.replace(tzinfo=now.tzinfo)
        if mod not in latest or exp > latest[mod]:
            latest[mod] = exp
    modules: list[GatingModule] = []
    for mod in manifest.training.required_modules:
        exp = latest.get(mod)
        if exp is None:
            st = "missing"
        elif exp >= now:
            st = "expiring" if exp - now <= expiring_window else "valid"
        elif now - exp <= grace:
            st = "grace"
        else:
            st = "expired"
        modules.append(GatingModule(module_id=mod, title_key=titles.get(mod), status=st, expires_at=exp))
    statuses = {m.status for m in modules}
    overall = "blocked" if statuses & {"missing", "expired"} else "restricted" if "grace" in statuses else "full"
    return GatingResult(status=overall, modules=modules)


@router.post("/machine-select", response_model=MachineSelectResponse)
def machine_select(
    body: MachineSelectRequest, principal: CurrentUser, cfg: ConfigDep, conn: DbDep
) -> MachineSelectResponse:
    if not body.machine_id and not body.qr_token:
        raise api_error(status.HTTP_422_UNPROCESSABLE_ENTITY, "not_found")
    cond = machines.c.id == body.machine_id if body.machine_id else machines.c.qr_token == body.qr_token
    row = conn.execute(select(machines).where(cond)).mappings().first()
    if row is None or row["manifest_id"] not in cfg.manifests:
        raise api_error(status.HTTP_404_NOT_FOUND, "not_found")
    certs = [
        dict(r)
        for r in conn.execute(select(certifications).where(certifications.c.user_id == principal.user_id)).mappings()
    ]
    gating = evaluate_gating(cfg, row["manifest_id"], certs, utcnow())
    return MachineSelectResponse(
        machine=machine_out(cfg, dict(row)), manifest=cfg.manifests_raw[row["manifest_id"]], gating=gating
    )
