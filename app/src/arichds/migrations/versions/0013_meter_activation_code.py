"""Meter Activation Code storage — `devices.meter_activation_code` (ADR 0019, issue #42)

One nullable column on `devices`, mirroring migration 0012's shape — the
per-meter licensing entitlement (a Meter Activation Code, signed for one
Meter Serial and one Machine ID) verified once at Create and stored on the
row. Nullable is what grandfathering existing rows means: a device created
before this gate landed holds no code and keeps working, never re-validated.

This migration imports nothing from `arichds` and repeats its literals
verbatim — same rule as every migration since 0003.

Revision ID: 0013
Revises: 0012
Create Date: 2026-08-24

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0013"
down_revision: str | None = "0012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("devices") as batch_op:
        batch_op.add_column(sa.Column("meter_activation_code", sa.String(length=1024), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("devices") as batch_op:
        batch_op.drop_column("meter_activation_code")
