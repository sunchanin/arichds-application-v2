"""M7 slice 3 — `devices.csv_exported_through` (issue #30, D-8)

One nullable column on `devices`, mirroring `status_checked_at`'s own shape
(0004) — the Load Profile CSV export watermark. Not a table: it may drift
without losing data, because the rows it counts stay in
`load_profile_readings` regardless (SPEC §3.5/§3.7).

This migration imports nothing from `arichds` and repeats its literals
verbatim — same rule as every migration since 0003.

Revision ID: 0012
Revises: 0011
Create Date: 2026-08-11

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0012"
down_revision: str | None = "0011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("devices") as batch_op:
        batch_op.add_column(sa.Column("csv_exported_through", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("devices") as batch_op:
        batch_op.drop_column("csv_exported_through")
