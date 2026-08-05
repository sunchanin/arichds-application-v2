"""M3-4 drop the 60 s rows and rename `interval_readings` to `load_profile_readings`

ADR 0007: the Poller's tick proves liveness, not data. Nothing instantaneous is
persisted any more, which leaves this migration two jobs — and the order between
them is load-bearing.

**Delete first, rename second.** The DELETE is written against the old table
name, so it must run before the rename; doing it the other way round would work
only until someone read this file and believed the order was arbitrary.

**The DELETE is scoped to ``interval = '60s'``.** That label is the only thing
the Poller ever wrote. Everything else in the table is an interval the *meter*
recorded — 15-minute load profile (M5) and the Modbus cadences (M4b) — and must
survive untouched. An unscoped DELETE would look identical in an empty database
and lose a customer's data in a full one.

**Both indexes are renamed, not just the composite one.** ``device_id`` carries
``index=True`` on the model, so SQLAlchemy's implicit name is
``ix_<table>_device_id``. Leaving the old name behind would leave a migrated
customer database silently disagreeing with the model's metadata forever, in a
way nothing would ever fail on.

**The downgrade reverses the shape, never the data.** It renames the table and
both indexes back; the deleted rows are gone for good. There is nowhere to keep
them that would not reintroduce the very thing this migration removes.

This migration imports nothing from ``arichds`` and repeats its literals
verbatim — same rule and same reasoning as 0003's and 0004's docstrings: a
migration freezes the world as it was when it was written, so it may not import
anything that can be edited later.

Revision ID: 0005
Revises: 0004
Create Date: 2026-08-05

"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("DELETE FROM interval_readings WHERE interval = '60s'")

    op.drop_index("ix_interval_readings_device_read_at", table_name="interval_readings")
    op.drop_index("ix_interval_readings_device_id", table_name="interval_readings")
    op.rename_table("interval_readings", "load_profile_readings")
    op.create_index("ix_load_profile_readings_device_id", "load_profile_readings", ["device_id"])
    op.create_index(
        "ix_load_profile_readings_device_read_at",
        "load_profile_readings",
        ["device_id", "read_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_load_profile_readings_device_read_at", table_name="load_profile_readings")
    op.drop_index("ix_load_profile_readings_device_id", table_name="load_profile_readings")
    op.rename_table("load_profile_readings", "interval_readings")
    op.create_index("ix_interval_readings_device_id", "interval_readings", ["device_id"])
    op.create_index("ix_interval_readings_device_read_at", "interval_readings", ["device_id", "read_at"])
