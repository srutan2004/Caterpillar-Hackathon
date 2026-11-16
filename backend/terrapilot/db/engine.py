"""Engine/session factory. The API and loaders share one engine per process."""

from __future__ import annotations

from functools import lru_cache

from sqlalchemy import Engine, create_engine

from terrapilot.core.settings import get_settings


@lru_cache(maxsize=4)
def get_engine(url: str | None = None) -> Engine:
    url = url or get_settings().database_url
    kwargs: dict[str, object] = {"pool_pre_ping": True, "future": True}
    if url.startswith("sqlite"):
        kwargs["connect_args"] = {"check_same_thread": False}
    return create_engine(url, **kwargs)


def is_postgres(engine: Engine) -> bool:
    return engine.dialect.name == "postgresql"
