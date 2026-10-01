"""M13 — eleven new `load_profile_readings` columns (issue 06)

The three average phase angles, the three line-to-line voltages, the four
average power quantities and the meter's own Interval Status word. All
nullable: a model that does not record a quantity gets an empty column, never
a missing one, which is the shipped behaviour for `freq` already.

Ten are `FLOAT` like every other measurement column here. `interval_status_flag`
is an `INTEGER` — it is a bitmap the meter reports, stored raw and decoded at
render time, so it is never a measurement and never scaled.

No backfill. Every existing row was written before the driver mapped these
columns, so there is nothing on the meter side to recover them from at the
point this runs; they stay NULL for rows already stored and fill from the next
cycle onward.

This migration imports nothing from `arichds` and repeats its literals
verbatim — same rule as every migration since 0003.

Revision ID: 0016
Revises: 0015
Create Date: 2026-09-09

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0016"
down_revision: str | None = "0015"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_FLOAT_COLUMNS: tuple[str, ...] = (
    "phase_angle_a",
    "phase_angle_b",
    "phase_angle_c",
    "volt_l1_l2",
    "volt_l2_l3",
    "volt_l3_l1",
    "import_active_kw",
    "import_reactive_kvar",
    "export_active_kw",
    "export_reactive_kvar",
)

_INTEGER_COLUMNS: tuple[str, ...] = ("interval_status_flag",)


def upgrade() -> None:
    with op.batch_alter_table("load_profile_readings") as batch_op:
        for name in _FLOAT_COLUMNS:
            batch_op.add_column(sa.Column(name, sa.Float(), nullable=True))
        for name in _INTEGER_COLUMNS:
            batch_op.add_column(sa.Column(name, sa.Integer(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("load_profile_readings") as batch_op:
        for name in (*_FLOAT_COLUMNS, *_INTEGER_COLUMNS):
            batch_op.drop_column(name)
