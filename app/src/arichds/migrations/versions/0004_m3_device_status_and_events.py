"""M3-2 device status columns and the `device_events` table

ADR 0004: a device's status is a pure function of the Poller's tick outcomes —
there is no health-check job and no heartbeat table. What that decision needs on
disk is four columns on ``devices`` and one small table beside them.

**The strike counter is a column, not a variable.** ``consecutive_failures``
lives here because ``Poller.restart()`` respawns every worker thread (adding one
device would otherwise reset the streak of every device on the site) and because
a Windows service restart must not hand a dead meter a fresh start either. It
also rides the same ``UPDATE devices`` that a tick already issues to refresh
``status_checked_at``, so it is written in the same transaction as the status it
produced and the two can never disagree.

``status`` is NOT NULL with a server_default of ``'unknown'``: the default is
what backfills existing rows as part of the ADD COLUMN, so no separate backfill
statement is needed. ``consecutive_failures`` works the same way with ``'0'``.
The three observable values are ``online`` / ``offline`` / ``unknown`` —
``paused`` is computed at read time from ``enabled`` and is never stored.

``device_events`` mirrors ``interval_readings``' index shape deliberately: one
index on ``device_id`` for the cascade and the per-device count, and one on
``(device_id, created_at)`` for the History drawer's newest-first page.

This migration imports nothing from ``arichds`` and repeats its literals
verbatim — same rule and same reasoning as 0003's docstring: a migration freezes
the world as it was when it was written, so it may not import anything that can
be edited later.

Revision ID: 0004
Revises: 0003
Create Date: 2026-08-05

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "device_events",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("device_id", sa.Integer(), sa.ForeignKey("devices.id", ondelete="CASCADE"), nullable=False),
        sa.Column("kind", sa.String(length=32), nullable=False),
        sa.Column("detail", sa.String(length=255), nullable=True),
        # NULL for an automatic transition: nobody changed the device, the meter
        # changed state. Only the five operator actions carry a username.
        sa.Column("actor", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_device_events_device_id", "device_events", ["device_id"])
    op.create_index("ix_device_events_device_created_at", "device_events", ["device_id", "created_at"])

    with op.batch_alter_table("devices") as batch_op:
        batch_op.add_column(sa.Column("status", sa.String(length=16), nullable=False, server_default="unknown"))
        batch_op.add_column(sa.Column("status_detail", sa.String(length=255), nullable=True))
        batch_op.add_column(sa.Column("status_checked_at", sa.DateTime(timezone=True), nullable=True))
        batch_op.add_column(sa.Column("consecutive_failures", sa.Integer(), nullable=False, server_default="0"))


def downgrade() -> None:
    with op.batch_alter_table("devices") as batch_op:
        batch_op.drop_column("consecutive_failures")
        batch_op.drop_column("status_checked_at")
        batch_op.drop_column("status_detail")
        batch_op.drop_column("status")

    op.drop_index("ix_device_events_device_created_at", table_name="device_events")
    op.drop_index("ix_device_events_device_id", table_name="device_events")
    op.drop_table("device_events")
