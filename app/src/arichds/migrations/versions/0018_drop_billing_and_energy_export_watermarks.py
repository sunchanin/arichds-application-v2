"""M14, ticket 04 — drop `devices.billing_exported_through` and
`devices.energy_exported_through` (ADR 0023).

Both watermarks (0014, 0015) existed so the Billing and Energy export files
could append without repeating a row. Since ADR 0023's every-cycle rewrite
(ticket 04), both files are replaced whole on every export cycle — the Billing
file from every closed `billing_readings` period (never purged, ADR 0009),
the Energy file from `energy_summary_days` (ADR 0022) over the retention
window — so there is nothing left for either watermark to track: a rewrite
recomputes the file's entire content from the source tables every time,
regardless of what was written before. `devices.csv_exported_through` (0012)
is untouched — the Load Profile CSV still appends (ticket 05 is what trims it).

This migration imports nothing from `arichds` and repeats its literals
verbatim — same rule as every migration since 0003.

Revision ID: 0018
Revises: 0017
Create Date: 2026-09-14

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0018"
down_revision: str | None = "0017"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("devices") as batch_op:
        batch_op.drop_column("billing_exported_through")
        batch_op.drop_column("energy_exported_through")


def downgrade() -> None:
    with op.batch_alter_table("devices") as batch_op:
        batch_op.add_column(sa.Column("energy_exported_through", sa.Date(), nullable=True))
        batch_op.add_column(sa.Column("billing_exported_through", sa.DateTime(timezone=True), nullable=True))
