"""M14 — the `energy_summary_days` table (ADR 0022, ticket 01)

One brand-new table, no data to carry over: `GET /api/energy/summary` moves
from a live aggregation of `load_profile_readings` (ADR 0012) to this stored
table, recomputed over the whole retention window every scheduler cycle. One
row per meter per **local** calendar day — `local_date` is a plain `DATE`,
never a `DATETIME`, because Time-of-Use days are local days (mirrors
`devices.energy_exported_through`, 0015). The eight Time-of-Use buckets match
`arichds.db.energy_query.EnergySummaryDay`'s own field names exactly, so the
recompute job writes them straight through with no translation.

`updated_at` mirrors `energy_register_readings.updated_at` (0010) for its
`server_default=func.now()` only — `onupdate` is an ORM-level default, not a
DDL one, so it has no place in this migration regardless. The ORM column
(`db/models.py::EnergySummaryDay`) does still declare `onupdate=func.now()`,
same as 0010's, but only as a defensive fallback: the recompute job
(`db/energy_summary_store.py`) never relies on it, because it stamps
`updated_at` explicitly, from the same `now` it was called with, whenever —
and only when — at least one bucket actually differs from what is already
stored.

This migration imports nothing from `arichds` and repeats its literals
verbatim — same rule as every migration since 0003.

Revision ID: 0017
Revises: 0016
Create Date: 2026-09-14

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0017"
down_revision: str | None = "0016"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "energy_summary_days",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("device_id", sa.Integer(), sa.ForeignKey("devices.id", ondelete="CASCADE"), nullable=False),
        sa.Column("local_date", sa.Date(), nullable=False),
        sa.Column("peak_import_kwh", sa.Float(), nullable=False),
        sa.Column("offpeak_import_kwh", sa.Float(), nullable=False),
        sa.Column("holiday_import_kwh", sa.Float(), nullable=False),
        sa.Column("total_import_kwh", sa.Float(), nullable=False),
        sa.Column("peak_export_kwh", sa.Float(), nullable=False),
        sa.Column("offpeak_export_kwh", sa.Float(), nullable=False),
        sa.Column("holiday_export_kwh", sa.Float(), nullable=False),
        sa.Column("total_export_kwh", sa.Float(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_energy_summary_days_device_id", "energy_summary_days", ["device_id"])
    op.create_index(
        "uq_energy_summary_days_device_local_date",
        "energy_summary_days",
        ["device_id", "local_date"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index("uq_energy_summary_days_device_local_date", table_name="energy_summary_days")
    op.drop_index("ix_energy_summary_days_device_id", table_name="energy_summary_days")
    op.drop_table("energy_summary_days")
