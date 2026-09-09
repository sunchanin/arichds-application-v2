"""M13 — `devices.energy_exported_through` (issue 02)

One nullable `DATE` column on `devices` — the Energy Summary file's watermark.
A date rather than a datetime because the Energy Summary's row key is a local
calendar day, not an instant; storing it as an instant would invite a timezone
conversion that has no meaning for it.

This migration imports nothing from `arichds` and repeats its literals
verbatim — same rule as every migration since 0003.

Revision ID: 0015
Revises: 0014
Create Date: 2026-09-09

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0015"
down_revision: str | None = "0014"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("devices") as batch_op:
        batch_op.add_column(sa.Column("energy_exported_through", sa.Date(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("devices") as batch_op:
        batch_op.drop_column("energy_exported_through")
