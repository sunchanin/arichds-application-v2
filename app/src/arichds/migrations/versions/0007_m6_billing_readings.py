"""M6a the `billing_readings` table (issue #21)

ADR 0009: billing has one read path, and it reads the whole buffer every time —
there is no backfill endpoint and no `billing_backfilled_at` column, so this
migration is one `CREATE TABLE` with no data to carry over from anywhere.

**Forty measurement columns, all nullable, all `Float`** — energy
(`import_active_kwh_*`, `export_active_kwh_*`, `import_reactive_kvarh_*`,
`export_reactive_kvarh_*`) and maximum demand (the same four quantities as
`max_demand_*_kw`/`max_demand_*_kvar`), each with a `_total` plus four tariffs
(`_rate_a`..`_rate_d`). `C=5` (reactive Q1) is deliberately absent — no screen
ever showed it (SPEC §3.6).

**Two partial unique indexes, not one** (ADR 0009's "Consequences"):

* `uq_billing_readings_closed` on `(device_id, bill_date)` **WHERE
  `record_status IS NULL`** — a closed period's natural key, so reading the
  same buffer twice stores nothing new.
* `uq_billing_readings_open` on `device_id` **WHERE `record_status = 'open'`**
  — at most one Open Period slot per device, ever. v1 never enforced this at
  the database and needed an `is_latest` reconciler to heal the races that
  followed; this migration is what lets M6a delete that reconciler instead of
  porting it.

Both are `sqlite_where` partial indexes — SQLite supports them and Alembic's
batch mode is not needed here because this is a brand-new table, not an ALTER
of one that already holds rows.

`updated_at` exists because the Open Period slot is upserted in place on every
read (SPEC §3.8 / push needs a column that moves when a row is updated without
a new row appearing).

This migration imports nothing from `arichds` and repeats its literals
verbatim — same rule and same reasoning as 0003's through 0006's docstrings: a
migration freezes the world as it was when it was written, so it may not
import anything that can be edited later.

Revision ID: 0007
Revises: 0006
Create Date: 2026-08-09

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0007"
down_revision: str | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

#: The eight quantity prefixes the forty measurement columns are built from —
#: four energy (Wh-derived, ``_kwh``/``_kvarh``) and four maximum-demand
#: (``_kw``/``_kvar``). ``C=5`` (reactive Q1) is not one of them (SPEC §3.6).
_MEASUREMENT_PREFIXES = (
    "import_active_kwh",
    "export_active_kwh",
    "import_reactive_kvarh",
    "export_reactive_kvarh",
    "max_demand_import_active_kw",
    "max_demand_export_active_kw",
    "max_demand_import_reactive_kvar",
    "max_demand_export_reactive_kvar",
)

_RATE_SUFFIXES = ("total", "rate_a", "rate_b", "rate_c", "rate_d")


def _measurement_columns() -> list[sa.Column]:
    """The forty nullable ``Float`` measurement columns, in a fixed order."""
    return [
        sa.Column(f"{prefix}_{suffix}", sa.Float(), nullable=True)
        for prefix in _MEASUREMENT_PREFIXES
        for suffix in _RATE_SUFFIXES
    ]


def upgrade() -> None:
    op.create_table(
        "billing_readings",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("device_id", sa.Integer(), sa.ForeignKey("devices.id", ondelete="CASCADE"), nullable=False),
        sa.Column("bill_date", sa.DateTime(timezone=True), nullable=False),
        sa.Column("read_at", sa.DateTime(timezone=True), nullable=False),
        # NULL for a closed period, "open" for the one Open Period slot — the
        # encoding both partial indexes below key on.
        sa.Column("record_status", sa.String(length=16), nullable=True),
        sa.Column("source", sa.String(length=16), nullable=False),
        sa.Column("meter_serial", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        *_measurement_columns(),
    )
    op.create_index("ix_billing_readings_device_id", "billing_readings", ["device_id"])
    op.create_index("ix_billing_readings_device_bill_date", "billing_readings", ["device_id", "bill_date"])
    op.create_index(
        "uq_billing_readings_closed",
        "billing_readings",
        ["device_id", "bill_date"],
        unique=True,
        sqlite_where=sa.text("record_status IS NULL"),
    )
    op.create_index(
        "uq_billing_readings_open",
        "billing_readings",
        ["device_id"],
        unique=True,
        sqlite_where=sa.text("record_status = 'open'"),
    )


def downgrade() -> None:
    op.drop_index("uq_billing_readings_open", table_name="billing_readings")
    op.drop_index("uq_billing_readings_closed", table_name="billing_readings")
    op.drop_index("ix_billing_readings_device_bill_date", table_name="billing_readings")
    op.drop_index("ix_billing_readings_device_id", table_name="billing_readings")
    op.drop_table("billing_readings")
