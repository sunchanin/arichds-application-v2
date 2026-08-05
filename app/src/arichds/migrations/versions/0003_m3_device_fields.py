"""M3-1 device fields: the full v1 field set, plus the parked-orphan rule

SPEC §3.3 lifts v1's ``devices`` field set across in one go — identity
(``meter_serial``, ``site_name``, ``site_code``, ``customer``, ``meter_number``,
``group_name``), the two extra DLMS credentials M4 needs, and the billing-day
columns whose logic arrives in M6. Adding them all now means the model, the
form and the API are not revisited a second time for fields we already know
about.

``meter_serial`` gets a unique **index**, not a table constraint: SQLite permits
many NULLs in a unique index (so pre-M3 rows, which were never probed, coexist
happily) and creating an index needs no table rebuild.

Nothing is deleted (SPEC §3.3 — "migration ไม่ลบอะไร"). A row whose ``model``
has no driver in this build is parked with ``enabled = 0`` and keeps a NULL
``meter_serial``: ADR 0005's "not yet identified" state, which the next Update
resolves because Update always probes.

The model whitelist below is **hardcoded, deliberately**. It must not call
``supported_models()``: a migration freezes the world as it was when it was
written, and the day M4 registers eight more drivers this migration would
otherwise behave differently on any database that had not yet run it. The
``'Unknown site'`` placeholder is a literal here for the same reason.

Revision ID: 0003
Revises: 0002
Create Date: 2026-08-05

"""

from __future__ import annotations

import logging
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

logger = logging.getLogger("alembic.runtime.migration")

#: The models that had a registered driver when this migration was written.
#: Frozen on purpose — see the module docstring.
DRIVABLE_MODELS_AT_0003: tuple[str, ...] = ("prometer100",)


def upgrade() -> None:
    with op.batch_alter_table("devices") as batch_op:
        batch_op.add_column(sa.Column("meter_serial", sa.String(length=64), nullable=True))
        # NOT NULL with a server_default: SQLite fills every existing row as
        # part of the ADD COLUMN, so no separate backfill statement is needed.
        batch_op.add_column(
            sa.Column("site_name", sa.String(length=255), nullable=False, server_default="Unknown site")
        )
        batch_op.add_column(sa.Column("site_code", sa.String(length=80), nullable=True))
        batch_op.add_column(sa.Column("customer", sa.String(length=255), nullable=True))
        batch_op.add_column(sa.Column("meter_number", sa.String(length=80), nullable=True))
        batch_op.add_column(sa.Column("group_name", sa.String(length=80), nullable=True))
        # Unused in M3; the HLS models in M4 need them. Never logged, never
        # returned by the API.
        batch_op.add_column(sa.Column("block_cipher_key", sa.String(length=255), nullable=True))
        batch_op.add_column(sa.Column("authentication_key", sa.String(length=255), nullable=True))
        # Columns now, period logic in M6.
        batch_op.add_column(sa.Column("first_bill_date", sa.Date(), nullable=True))
        batch_op.add_column(sa.Column("bill_day_feb28", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("bill_day_feb29", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("bill_day_30", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("bill_day_31", sa.Integer(), nullable=True))

    op.create_index("ix_devices_meter_serial", "devices", ["meter_serial"], unique=True)
    op.create_index("ix_devices_group_name", "devices", ["group_name"])

    _park_undrivable_devices()


def _park_undrivable_devices() -> None:
    """Disable rows whose model has no driver, naming each one in the log.

    Selected before it updates so the log can say exactly which devices stopped
    being polled and why — otherwise the first symptom on a customer machine is
    a meter that silently went quiet after an update.
    """
    placeholders = ", ".join(f":m{i}" for i in range(len(DRIVABLE_MODELS_AT_0003)))
    params = {f"m{i}": model for i, model in enumerate(DRIVABLE_MODELS_AT_0003)}
    where = f"enabled = 1 AND lower(model) NOT IN ({placeholders})"

    connection = op.get_bind()
    affected = connection.execute(sa.text(f"SELECT id, name, model FROM devices WHERE {where}"), params).fetchall()
    if not affected:
        return

    for row in affected:
        logger.info(
            "Disabling device %s (%s): model %r has no driver — press Update to re-identify it",
            row.id,
            row.name,
            row.model,
        )
    connection.execute(sa.text(f"UPDATE devices SET enabled = 0 WHERE {where}"), params)


def downgrade() -> None:
    op.drop_index("ix_devices_group_name", table_name="devices")
    op.drop_index("ix_devices_meter_serial", table_name="devices")

    with op.batch_alter_table("devices") as batch_op:
        batch_op.drop_column("bill_day_31")
        batch_op.drop_column("bill_day_30")
        batch_op.drop_column("bill_day_feb29")
        batch_op.drop_column("bill_day_feb28")
        batch_op.drop_column("first_bill_date")
        batch_op.drop_column("authentication_key")
        batch_op.drop_column("block_cipher_key")
        batch_op.drop_column("group_name")
        batch_op.drop_column("meter_number")
        batch_op.drop_column("customer")
        batch_op.drop_column("site_code")
        batch_op.drop_column("site_name")
        batch_op.drop_column("meter_serial")
