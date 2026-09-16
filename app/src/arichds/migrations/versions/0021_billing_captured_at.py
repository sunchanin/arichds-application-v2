"""ui-audit ticket 03 — `billing_readings.captured_at`

The All-Meters View's **Captured** column used to echo the bill's `read_at`
whenever captures were switched on, so it named a document for a period that
had no file on disk. This column is stamped only when a Capture for the
period is actually written — by the automatic path for a new closed period
and by a hand-pressed Capture image — and stays NULL otherwise. Existing rows
are not backfilled from file timestamps: a NULL here means "not captured
since this build", which is the honest answer.

Imports nothing from `arichds` — same rule as every migration since 0003.

Revision ID: 0021
Revises: 0020
Create Date: 2026-09-16

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0021"
down_revision: str | None = "0020"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("billing_readings") as batch_op:
        batch_op.add_column(sa.Column("captured_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("billing_readings") as batch_op:
        batch_op.drop_column("captured_at")
