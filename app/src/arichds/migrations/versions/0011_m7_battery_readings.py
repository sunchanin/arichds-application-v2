"""M7-2 the `battery_readings` table (issue #29)

One brand-new table, no data to carry over. Mirrors
`energy_register_readings`' shape (0010) for its identity columns and its
`(device_id, read_at)` upsert constraint, but carries only `status` —
D7 narrows the earlier `remaining_seconds`/`remaining_minutes` idea away
entirely: nothing in v2 can produce a remaining-time value (see the model
docstring in `db/models.py`).

This migration imports nothing from `arichds` and repeats its literals
verbatim — same rule as every migration since 0003.

Revision ID: 0011
Revises: 0010
Create Date: 2026-08-11

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0011"
down_revision: str | None = "0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "battery_readings",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("device_id", sa.Integer(), sa.ForeignKey("devices.id", ondelete="CASCADE"), nullable=False),
        sa.Column("read_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_battery_readings_device_id", "battery_readings", ["device_id"])
    op.create_index(
        "uq_battery_readings_device_read_at",
        "battery_readings",
        ["device_id", "read_at"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index("uq_battery_readings_device_read_at", table_name="battery_readings")
    op.drop_index("ix_battery_readings_device_id", table_name="battery_readings")
    op.drop_table("battery_readings")
