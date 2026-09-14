"""M14 — the `holiday_changes` table (ADR 0022, ticket 06)

One brand-new table, no data to carry over: every Holiday mutation — add,
edit, delete, CSV import, Import from meter — now writes one row here in the
same transaction as the mutation itself, recording who made it, when, and
which day it names (or how many Holidays an import brought in). No
`device_id` — the calendar is machine-wide, same as `holidays` itself.

This migration imports nothing from `arichds` and repeats its literals
verbatim — same rule as every migration since 0003.

Revision ID: 0019
Revises: 0018
Create Date: 2026-09-14

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0019"
down_revision: str | None = "0018"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "holiday_changes",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("username", sa.String(length=64), nullable=False),
        sa.Column("action", sa.String(length=16), nullable=False),
        sa.Column("holiday_kind", sa.String(length=16), nullable=True),
        sa.Column("holiday_name", sa.String(length=128), nullable=True),
        sa.Column("holiday_date", sa.Date(), nullable=True),
        sa.Column("holiday_month", sa.Integer(), nullable=True),
        sa.Column("holiday_day", sa.Integer(), nullable=True),
        sa.Column("count", sa.Integer(), nullable=True),
    )
    op.create_index("ix_holiday_changes_created_at", "holiday_changes", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_holiday_changes_created_at", table_name="holiday_changes")
    op.drop_table("holiday_changes")
