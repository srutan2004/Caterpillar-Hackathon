"""Table access for training and serving: Postgres when reachable, else a `tp gen` parquet directory.

Training on a parquet directory (tests, offline) and serving from the DB go through the same readers, so
feature code never branches on the source.
"""

from __future__ import annotations

from functools import cached_property
from pathlib import Path
from typing import Any

import pandas as pd

from terrapilot.core.settings import get_settings


class Tables:
    def __init__(self, data_dir: Path | None = None, *, prefer_db: bool | None = None):
        self.data_dir = data_dir
        self.prefer_db = (data_dir is None) if prefer_db is None else prefer_db
        self._cache: dict[str, pd.DataFrame] = {}

    @cached_property
    def _engine(self) -> Any:
        if not self.prefer_db:
            return None
        try:
            from sqlalchemy import text

            from terrapilot.db.engine import get_engine

            eng = get_engine()
            with eng.connect() as c:
                c.execute(text("SELECT 1"))
            return eng
        except Exception:
            return None

    @property
    def source(self) -> str:
        return "db" if self._engine is not None else "parquet"

    def _dir(self) -> Path:
        return self.data_dir or get_settings().data_dir / "generated"

    def get(self, name: str, sql: str | None = None, params: dict[str, Any] | None = None) -> pd.DataFrame:
        """Whole table (cached) or, on the DB, a filtered query. Parquet falls back to the whole table."""
        if sql is None and name in self._cache:
            return self._cache[name]
        if self._engine is not None:
            from sqlalchemy import bindparam, text

            stmt = text(sql or f"SELECT * FROM {name}")
            expanding = [k for k, v in (params or {}).items() if isinstance(v, list | tuple)]
            if expanding:
                stmt = stmt.bindparams(*(bindparam(k, expanding=True) for k in expanding))
            with self._engine.connect() as conn:
                df = pd.read_sql(stmt, conn, params=params or {})
            df = _utc(df)
        else:
            path = self._dir() / f"{name}.parquet"
            df = pd.read_parquet(path) if path.is_file() else pd.DataFrame()
        if sql is None:
            self._cache[name] = df
        return df


def _utc(df: pd.DataFrame) -> pd.DataFrame:
    for col in df.columns:
        if pd.api.types.is_datetime64_any_dtype(df[col]):
            if df[col].dt.tz is None:
                df[col] = df[col].dt.tz_localize("UTC")
        elif col.endswith(("_at", "_start", "_end", "date", "time")) or col in ("ts", "valid_at", "issued_at"):
            try:
                df[col] = pd.to_datetime(df[col], utc=True)
            except Exception:
                pass
    return df

