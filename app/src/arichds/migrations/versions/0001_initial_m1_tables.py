"""M1 initial schema: devices + interval_readings

The first migration of the single Alembic set. Only the two tables the walking
skeleton needs — the remaining 11 of the 13-table target schema (SPEC §4) land
module by module in later milestones, never speculatively here.

Revision ID: 0001
Revises:
Create Date: 2026-08-04

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "devices",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("brand", sa.String(length=64), nullable=False),
        sa.Column("model", sa.String(length=64), nullable=False),
        sa.Column("transport", sa.JSON(), nullable=False),
        sa.Column("password", sa.String(length=128), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name"),
    )

    op.create_table(
        "interval_readings",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("device_id", sa.Integer(), nullable=False),
        # UTC always (REMAKE-PLAN §6.1 normalization contract).
        sa.Column("read_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("source", sa.String(length=16), nullable=False),
        sa.Column("interval", sa.String(length=16), nullable=False),
        sa.Column("volt_l1", sa.Float(), nullable=True),
        sa.Column("volt_l2", sa.Float(), nullable=True),
        sa.Column("volt_l3", sa.Float(), nullable=True),
        sa.Column("current_l1", sa.Float(), nullable=True),
        sa.Column("current_l2", sa.Float(), nullable=True),
        sa.Column("current_l3", sa.Float(), nullable=True),
        sa.Column("freq", sa.Float(), nullable=True),
        # kWh always — the driver divides the meter's raw Wh at write time.
        sa.Column("import_active_kwh", sa.Float(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["device_id"], ["devices.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_interval_readings_device_id", "interval_readings", ["device_id"])
    op.create_index("ix_interval_readings_device_read_at", "interval_readings", ["device_id", "read_at"])


def downgrade() -> None:
    op.drop_index("ix_interval_readings_device_read_at", table_name="interval_readings")
    op.drop_index("ix_interval_readings_device_id", table_name="interval_readings")
    op.drop_table("interval_readings")
    op.drop_table("devices")
