"""M4c the twenty new `billing_readings` columns (issue #24)

Demand Time and Cumulative Demand, for max-demand **import** active and
reactive, each as ``total`` + ``rate_a``..``rate_d`` — the columns v1's Billing
page has always shown that v2's forty-column schema (migration 0007) did not
yet carry. The criterion is the one SPEC §3.6 already uses: does a v1 screen
show it. Export-side times and cumulatives are **not** added — no screen shows
them and no meter known to this build carries them (D10, F2).

All twenty are nullable, all-``NULL``-safe for a surviving pre-0009 row —
nothing here is a value any writer needs to invent. The ten Demand Time
columns are ``DateTime(timezone=True)``: **never scaled, never divided** (D11)
— a capture-time cell reaching ``raw * multiplier`` would be the bug this
column shape exists to prevent by construction (a datetime column cannot hold
a float).

This migration imports nothing from ``arichds`` and repeats its literals
verbatim — same rule as every migration since 0003: a migration freezes the
world as it was when it was written.

Revision ID: 0009
Revises: 0008
Create Date: 2026-08-09

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0009"
down_revision: str | None = "0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

#: The four prefixes this migration adds, each expanded to total + rate_a..d.
_NEW_PREFIXES = (
    "max_demand_import_active_time",
    "max_demand_import_reactive_time",
    "cumul_demand_import_active_kw",
    "cumul_demand_import_reactive_kvar",
)
_RATE_SUFFIXES = ("total", "rate_a", "rate_b", "rate_c", "rate_d")
#: (column name, is it a datetime column) — the Demand Time prefixes are
#: DateTime(timezone=True); the Cumulative Demand prefixes are Float, exactly
#: like every other measurement column migration 0007 already added.
_DEMAND_TIME_PREFIXES = ("max_demand_import_active_time", "max_demand_import_reactive_time")


def _columns() -> list[sa.Column]:
    columns = []
    for prefix in _NEW_PREFIXES:
        is_datetime = prefix in _DEMAND_TIME_PREFIXES
        for suffix in _RATE_SUFFIXES:
            name = f"{prefix}_{suffix}"
            col_type = sa.DateTime(timezone=True) if is_datetime else sa.Float()
            columns.append(sa.Column(name, col_type, nullable=True))
    return columns


def upgrade() -> None:
    with op.batch_alter_table("billing_readings") as batch_op:
        for column in _columns():
            batch_op.add_column(column)


def downgrade() -> None:
    with op.batch_alter_table("billing_readings") as batch_op:
        for column in reversed(_columns()):
            batch_op.drop_column(column.name)
