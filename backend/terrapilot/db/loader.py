"""`tp load`: generated parquet → Postgres/Timescale via COPY (§7.8).

Runs migrations first, truncates in one statement, then streams each table in FK-dependency order.
"""

from __future__ import annotations

import json
import math
import time
from datetime import date, datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from rich.console import Console
from sqlalchemy import ARRAY, JSON, Table, text
from sqlalchemy.dialects.postgresql import JSONB

from terrapilot.core.settings import get_settings
from terrapilot.db.engine import get_engine
from terrapilot.db.migrate import upgrade
from terrapilot.db.schema import metadata


def _kind(column: Any) -> str:
    impl = column.type
    variant = getattr(impl, "_variant_mapping", {}).get("postgresql")
    target = variant or impl
    if isinstance(target, ARRAY):
        return "array"
    if isinstance(target, JSONB | JSON):
        return "json"
    return "scalar"


def _convert(value: Any, kind: str) -> Any:  # noqa: PLR0911 - type dispatcher
    if value is None:
        return None
    if kind == "array":
        if isinstance(value, np.ndarray):
            return [None if v is None else str(v) for v in value.tolist()]
        return list(value) if isinstance(value, list | tuple) else None
    if kind == "json":
        return value if isinstance(value, str) else json.dumps(value, default=str)
    if isinstance(value, float) and math.isnan(value):
        return None
    if value is pd.NaT:
        return None
    if isinstance(value, pd.Timestamp):
        return value.round("us").to_pydatetime()  # Postgres stores microseconds
    if isinstance(value, np.generic):
        return value.item()
    if isinstance(value, datetime | date):
        return value
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    return value


def copy_table(raw_conn: Any, table: Table, df: pd.DataFrame) -> int:
    cols = [c for c in table.columns if c.name in df.columns]
    kinds = [_kind(c) for c in cols]
    names = ", ".join(f'"{c.name}"' for c in cols)
    frame = df[[c.name for c in cols]].astype(object).where(df[[c.name for c in cols]].notna(), None)
    with raw_conn.cursor() as cur, cur.copy(f'COPY "{table.name}" ({names}) FROM STDIN') as copy:
        for row in frame.itertuples(index=False, name=None):
            copy.write_row([_convert(v, k) for v, k in zip(row, kinds, strict=True)])
    return len(df)


def load_generated(
    from_dir: Path | None = None, truncate: bool = True, console: Console | None = None, database_url: str | None = None
) -> dict[str, int]:
    console = console or Console()
    src = from_dir or get_settings().data_dir / "generated"
    if not (src / "manifest.json").is_file():
        raise FileNotFoundError(f"{src} has no manifest.json — run `tp gen` first")
    upgrade("head", database_url)
    engine = get_engine(database_url)
    available = {p.stem for p in src.glob("*.parquet")}
    tables = [t for t in metadata.sorted_tables if t.name in available]
    counts: dict[str, int] = {}
    raw = engine.raw_connection()
    try:
        dbapi = raw.driver_connection
        assert dbapi is not None
        if truncate and tables:
            with dbapi.cursor() as cur:
                cur.execute("TRUNCATE " + ", ".join(f'"{t.name}"' for t in tables) + " CASCADE")
        for table in tables:
            t0 = time.perf_counter()
            df = pd.read_parquet(src / f"{table.name}.parquet")
            counts[table.name] = copy_table(dbapi, table, df) if len(df) else 0
            console.print(f"  • {table.name:<30} {counts[table.name]:>10,} rows {time.perf_counter() - t0:6.1f}s")
        dbapi.commit()
    except Exception:
        if raw.driver_connection is not None:
            raw.driver_connection.rollback()
        raise
    finally:
        raw.close()
    with engine.begin() as conn:
        conn.execute(text("ANALYZE"))
    return counts
