"""M7-1 the `holidays` and `energy_register_readings` tables (issue #28)

Two brand-new tables, no data to carry over. ``holidays`` is the calendar the
Energy Summary's Holiday bucket is judged against — machine-wide (no
``device_id``), two kinds discriminated by which pair of columns is
populated, and enforced by two partial unique indexes so a JSON import's
duplicate collision is a database-enforced 422:

* ``uq_holidays_public_date`` on ``(date)`` **WHERE ``kind = 'public'``**.
* ``uq_holidays_annual_month_day`` on ``(month, day)`` **WHERE
  ``kind = 'annual'``**.

``energy_register_readings`` mirrors ``billing_readings``' column-naming
convention for its twenty measurement columns (a total plus four tariffs for
each of import/export x active/reactive), and is upserted on
``(device_id, read_at)`` — the unique constraint that makes two Read-now
clicks inside one second the same row (decision 10, issue #28).

This migration imports nothing from ``arichds`` and repeats its literals
verbatim — same rule as every migration since 0003.

Revision ID: 0010
Revises: 0009
Create Date: 2026-08-11

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0010"
down_revision: str | None = "0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

#: The four quantity prefixes the twenty ``energy_register_readings``
#: measurement columns are built from.
_ENERGY_PREFIXES = (
    "import_active_kwh",
    "export_active_kwh",
    "import_reactive_kvarh",
    "export_reactive_kvarh",
)
_RATE_SUFFIXES = ("total", "rate_a", "rate_b", "rate_c", "rate_d")


def _energy_columns() -> list[sa.Column]:
    """The twenty nullable ``Float`` measurement columns, in a fixed order."""
    return [
        sa.Column(f"{prefix}_{suffix}", sa.Float(), nullable=True)
        for prefix in _ENERGY_PREFIXES
        for suffix in _RATE_SUFFIXES
    ]


def upgrade() -> None:
    op.create_table(
        "holidays",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("date", sa.Date(), nullable=True),
        sa.Column("month", sa.Integer(), nullable=True),
        sa.Column("day", sa.Integer(), nullable=True),
    )
    op.create_index(
        "uq_holidays_public_date",
        "holidays",
        ["date"],
        unique=True,
        sqlite_where=sa.text("kind = 'public'"),
    )
    op.create_index(
        "uq_holidays_annual_month_day",
        "holidays",
        ["month", "day"],
        unique=True,
        sqlite_where=sa.text("kind = 'annual'"),
    )

    op.create_table(
        "energy_register_readings",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("device_id", sa.Integer(), sa.ForeignKey("devices.id", ondelete="CASCADE"), nullable=False),
        sa.Column("read_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("source", sa.String(length=16), nullable=False),
        sa.Column("meter_serial", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        *_energy_columns(),
    )
    op.create_index("ix_energy_register_readings_device_id", "energy_register_readings", ["device_id"])
    op.create_index(
        "uq_energy_register_readings_device_read_at",
        "energy_register_readings",
        ["device_id", "read_at"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index("uq_energy_register_readings_device_read_at", table_name="energy_register_readings")
    op.drop_index("ix_energy_register_readings_device_id", table_name="energy_register_readings")
    op.drop_table("energy_register_readings")

    op.drop_index("uq_holidays_annual_month_day", table_name="holidays")
    op.drop_index("uq_holidays_public_date", table_name="holidays")
    op.drop_table("holidays")
