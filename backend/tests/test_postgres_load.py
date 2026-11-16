"""Integration: migrations + COPY load + read-only views on a real Postgres/Timescale (skipped if unreachable)."""

from __future__ import annotations

from pathlib import Path

import pytest
from rich.console import Console
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

from terrapilot.core.settings import get_settings

pytestmark = pytest.mark.postgres
TEST_DB = "terrapilot_test"


@pytest.fixture(scope="module")
def pg_url() -> str:
    url = make_url(get_settings().database_url)
    if not url.drivername.startswith("postgresql"):
        pytest.skip("DATABASE_URL is not Postgres")
    admin = create_engine(url.set(database="postgres"), isolation_level="AUTOCOMMIT")
    try:
        with admin.connect() as conn:
            exists = conn.execute(text("SELECT 1 FROM pg_database WHERE datname = :d"), {"d": TEST_DB}).scalar()
            if not exists:
                conn.execute(text(f'CREATE DATABASE "{TEST_DB}"'))
    except Exception as exc:  # no server running locally
        pytest.skip(f"Postgres unreachable: {exc.__class__.__name__}")
    finally:
        admin.dispose()
    return url.set(database=TEST_DB).render_as_string(hide_password=False)


def test_load_tiny_world(pg_url: str, tiny_data: Path) -> None:
    from terrapilot.db.engine import get_engine
    from terrapilot.db.loader import load_generated

    counts = load_generated(tiny_data, console=Console(quiet=True), database_url=pg_url)
    assert counts["cycles"] > 0 and counts["sensor_1min"] > 0
    engine = create_engine(pg_url)
    with engine.connect() as conn:
        assert conn.execute(text("SELECT count(*) FROM cycles")).scalar() == counts["cycles"]
        assert conn.execute(text("SELECT count(*) FROM v_fault_history")).scalar() is not None
        jsonb = conn.execute(text("SELECT count(*) FROM cycles WHERE phase_durations ? 'dig'")).scalar()
        assert jsonb and jsonb > 0
        tasks_today = conn.execute(text("SELECT count(*) FROM v_tasks WHERE task_id = 'T-2031'")).scalar()
        assert tasks_today == 1
    engine.dispose()
    get_engine(pg_url).dispose()
