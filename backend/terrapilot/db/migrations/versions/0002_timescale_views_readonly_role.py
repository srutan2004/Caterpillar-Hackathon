"""Timescale hypertables, read-only text-to-SQL views (with column comments) and the tp_ro role (§8).

Revision ID: 0002
Revises: 0001
"""

from __future__ import annotations

from alembic import op
from sqlalchemy import text

from terrapilot.core.settings import get_settings
from terrapilot.db.schema import HYPERTABLES
from terrapilot.db.views import VIEWS

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def _timescale_available() -> bool:
    bind = op.get_bind()
    return bool(bind.execute(text("SELECT 1 FROM pg_available_extensions WHERE name = 'timescaledb'")).scalar())


def _retention_days() -> float:
    try:
        from terrapilot.core.config import get_config

        return float(get_config().app.telemetry_retention["raw_days"])
    except Exception:  # config problems must not block schema migrations
        return 3.0


def upgrade() -> None:
    if _timescale_available():
        op.execute("CREATE EXTENSION IF NOT EXISTS timescaledb")
        for table, column, chunk in HYPERTABLES:
            op.execute(
                f"SELECT create_hypertable('{table}', '{column}', chunk_time_interval => INTERVAL '{chunk}', "
                "if_not_exists => TRUE, migrate_data => TRUE)"
            )
        op.execute(
            f"SELECT add_retention_policy('telemetry_raw', INTERVAL '{_retention_days()} days', if_not_exists => TRUE)"
        )

    for view in VIEWS:
        op.execute(f"CREATE OR REPLACE VIEW {view.name} AS {view.sql}")
        op.execute(f"COMMENT ON VIEW {view.name} IS {_quote(view.comment)}")
        for column, comment in view.columns.items():
            op.execute(f"COMMENT ON COLUMN {view.name}.{column} IS {_quote(comment)}")

    password = get_settings().tp_ro_password.get_secret_value().replace("'", "''")
    op.execute(
        f"""
        DO $$
        BEGIN
          IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'tp_ro') THEN
            CREATE ROLE tp_ro LOGIN PASSWORD '{password}';
          ELSE
            ALTER ROLE tp_ro WITH LOGIN PASSWORD '{password}';
          END IF;
        END $$;
        """
    )
    op.execute("REVOKE ALL ON ALL TABLES IN SCHEMA public FROM tp_ro")
    op.execute("GRANT USAGE ON SCHEMA public TO tp_ro")
    for view in VIEWS:
        op.execute(f"GRANT SELECT ON {view.name} TO tp_ro")
    op.execute("ALTER ROLE tp_ro SET default_transaction_read_only = on")
    op.execute("ALTER ROLE tp_ro SET statement_timeout = '5s'")


def downgrade() -> None:
    for view in reversed(VIEWS):
        op.execute(f"DROP VIEW IF EXISTS {view.name}")
    op.execute(
        "DO $$ BEGIN IF EXISTS (SELECT FROM pg_roles WHERE rolname = 'tp_ro') THEN "
        "REVOKE ALL ON SCHEMA public FROM tp_ro; DROP ROLE tp_ro; END IF; END $$;"
    )


def _quote(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"
