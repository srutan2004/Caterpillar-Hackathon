"""Pre-shift walkarounds and charger reservations (Phase 2B).

Revision ID: 0003
Revises: 0002
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None

JSON = sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql")
TEXT_LIST = sa.JSON().with_variant(postgresql.ARRAY(sa.Text()), "postgresql")


def upgrade() -> None:
    op.create_table(
        "walkarounds",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("machine_id", sa.String(length=64), nullable=False),
        sa.Column("operator_id", sa.String(length=64), nullable=False),
        sa.Column("ts", sa.DateTime(timezone=True), nullable=False),
        sa.Column("result", sa.String(length=16), nullable=False),
        sa.Column("items", JSON, nullable=True),
        sa.Column("photos", TEXT_LIST, nullable=True),
        sa.Column("blocks_start", sa.Boolean(), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_walkarounds")),
    )
    op.create_index(op.f("ix_walkarounds_machine_id"), "walkarounds", ["machine_id"], unique=False)
    op.create_table(
        "charger_reservations",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("station_id", sa.String(length=64), nullable=False),
        sa.Column("machine_id", sa.String(length=64), nullable=False),
        sa.Column("task_id", sa.String(length=64), nullable=True),
        sa.Column("start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("end", sa.DateTime(timezone=True), nullable=False),
        sa.Column("target_soc", sa.Float(), nullable=True),
        sa.Column("source", sa.String(length=32), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_charger_reservations")),
    )
    op.create_index(op.f("ix_charger_reservations_station_id"), "charger_reservations", ["station_id"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_charger_reservations_station_id"), table_name="charger_reservations")
    op.drop_table("charger_reservations")
    op.drop_index(op.f("ix_walkarounds_machine_id"), table_name="walkarounds")
    op.drop_table("walkarounds")
