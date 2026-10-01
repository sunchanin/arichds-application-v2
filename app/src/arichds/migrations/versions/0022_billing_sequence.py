"""ADR 0029 — `billing_readings.sequence`

A meter can stamp two closed periods on one second (site TC's Prometer 100
did it six times, *Invocation of Scaling tariff*), and the vendor tool shows
both. A closed period's natural key becomes `(device_id, bill_date, sequence)`
— `sequence` is the row's position among the entries sharing its bill date,
counted from the newest, so a bill date with one period is `0` and every row
that exists today keeps its key.

Adds the column `NOT NULL DEFAULT 0` and rebuilds `uq_billing_readings_closed`
over the three columns, keeping its `WHERE record_status IS NULL`. The Open
Period index is untouched.

Imports nothing from `arichds` — same rule as every migration since 0003.

Revision ID: 0022
Revises: 0021
Create Date: 2026-09-22

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0022"
down_revision: str | None = "0021"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_CLOSED_INDEX = "uq_billing_readings_closed"
_CLOSED_WHERE = sa.text("record_status IS NULL")


def upgrade() -> None:
    with op.batch_alter_table("billing_readings") as batch_op:
        batch_op.add_column(sa.Column("sequence", sa.Integer(), nullable=False, server_default=sa.text("0")))
    op.drop_index(_CLOSED_INDEX, table_name="billing_readings")
    op.create_index(
        _CLOSED_INDEX,
        "billing_readings",
        ["device_id", "bill_date", "sequence"],
        unique=True,
        sqlite_where=_CLOSED_WHERE,
    )


def downgrade() -> None:
    op.drop_index(_CLOSED_INDEX, table_name="billing_readings")
    with op.batch_alter_table("billing_readings") as batch_op:
        batch_op.drop_column("sequence")
    op.create_index(
        _CLOSED_INDEX,
        "billing_readings",
        ["device_id", "bill_date"],
        unique=True,
        sqlite_where=_CLOSED_WHERE,
    )
