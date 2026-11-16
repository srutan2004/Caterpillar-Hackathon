"""Shared FastAPI dependencies: config, DB connection, auth."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from typing import Annotated, Any

import jwt
from fastapi import Depends, Header, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy import Connection

from terrapilot.core.config import ConfigBundle, get_config
from terrapilot.core.security import decode_token
from terrapilot.core.settings import get_settings
from terrapilot.db.engine import get_engine


class Principal(BaseModel):
    user_id: str
    role: str
    name: str
    site_id: str | None = None
    locale: str | None = None


ANONYMOUS = Principal(user_id="anonymous", role="anonymous", name="")


def api_error(status_code: int, code: str) -> HTTPException:
    """Errors carry an i18n key, never user-facing text."""
    return HTTPException(status_code=status_code, detail={"code": code, "message_key": f"error.{code}"})


def config_dep() -> ConfigBundle:
    return get_config()


ConfigDep = Annotated[ConfigBundle, Depends(config_dep)]


def db_conn() -> Iterator[Connection]:
    with get_engine().connect() as conn:
        yield conn


DbDep = Annotated[Connection, Depends(db_conn)]


def _principal_from_token(token: str, cfg: ConfigBundle) -> Principal:
    try:
        claims: dict[str, Any] = decode_token(
            token, get_settings().jwt_secret.get_secret_value(), cfg.app.auth.jwt_algorithm
        )
    except jwt.PyJWTError as exc:
        raise api_error(status.HTTP_401_UNAUTHORIZED, "unauthorized") from exc
    return Principal(
        user_id=claims["sub"],
        role=claims["role"],
        name=claims.get("name", ""),
        site_id=claims.get("site_id"),
        locale=claims.get("locale"),
    )


def optional_principal(cfg: ConfigDep, authorization: Annotated[str | None, Header()] = None) -> Principal:
    if not authorization:
        return ANONYMOUS
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token:
        raise api_error(status.HTTP_401_UNAUTHORIZED, "unauthorized")
    return _principal_from_token(token, cfg)


def current_principal(principal: Annotated[Principal, Depends(optional_principal)]) -> Principal:
    if principal.role == "anonymous":
        raise api_error(status.HTTP_401_UNAUTHORIZED, "unauthorized")
    return principal


def ws_principal(cfg: ConfigBundle, token: str | None = Query(default=None)) -> Principal:
    if not token:
        raise api_error(status.HTTP_401_UNAUTHORIZED, "unauthorized")
    return _principal_from_token(token, cfg)


OptionalUser = Annotated[Principal, Depends(optional_principal)]
CurrentUser = Annotated[Principal, Depends(current_principal)]


def require_roles(*roles: str) -> Callable[[Principal], Principal]:
    def dep(principal: CurrentUser) -> Principal:
        if principal.role not in roles:
            raise api_error(status.HTTP_403_FORBIDDEN, "forbidden")
        return principal

    return dep
