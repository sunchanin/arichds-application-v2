"""M13 — `devices.billing_exported_through` (issue 01)

One nullable column on `devices`, the same shape and the same reasoning as
`csv_exported_through` (0012): the billing export file's watermark. A column,
not a table (ADR 0008) — it may drift without losing anything, because the
periods it counts stay in `billing_readings` regardless.

This migration imports nothing from `arichds` and repeats its literals
verbatim — same rule as every migration since 0003.

Revision ID: 0014
Revises: 0013
Create Date: 2026-09-09

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0014"
down_revision: str | None = "0013"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("devices") as batch_op:
        batch_op.add_column(sa.Column("billing_exported_through", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("devices") as batch_op:
        batch_op.drop_column("billing_exported_through")
