"""M5a-1 the load-profile schema: logger_id, interval_sec, four columns, one unique key

SPEC §3.5 settled the shape this table has to have before a load-profile writer
exists, and three of its decisions land here.

**``logger_id`` and ``interval_sec`` are NOT NULL with server defaults ``1`` and
``900``.** ``NULL`` is unusable for ``logger_id`` specifically: SQLite treats
``NULL != NULL``, so a nullable column would leave the unique key below unable
to prevent the duplicate it exists to prevent. The defaults are here so the
``ALTER`` cannot fail on a database that already holds rows — **not** as a value
any writer relies on; the job supplies both explicitly on every row. They stay
in place afterwards, and are declared identically on the model, because a server
default on disk that the model does not know about is exactly the drift 0005's
docstring says must never be allowed.

**The migration must not invent per-row values it cannot know.** ``1`` and
``900`` are the only shape a surviving pre-0006 row could have had — every model
scanned so far has one logger on a 900 s period
(``docs/meter-notes/load-profile-capture-objects.md``) — so back-filling them is
recording what was already true, not guessing. Anything less certain would have
to stay ``NULL``, and ``logger_id`` cannot.

**``interval`` (the String cadence label) is dropped.** It never had a reader,
and ``interval_sec`` replaces it with the meter's own capture period in seconds
— read from ProfileGeneric attr 4, never assumed (SPEC §3.5).

**Four measurement columns are added and stay empty for now.** The SMW110W4 does
not capture them; all three CEWE models do, and they arrive with M4c. Twelve
measurement columns is the corrected count — ``SPEC.md`` §3.5 supersedes the
"~24 COSEM columns" figure that ``REMAKE-PLAN`` carried.

**The downgrade reverses the shape, never the data** — 0005's rule. ``interval``
comes back **nullable**: its labels were dropped by the upgrade and there is no
single value this migration could put there without inventing one, which is the
same rule the defaults above obey in the other direction.

This migration imports nothing from ``arichds`` and repeats its literals
verbatim — same rule and same reasoning as 0003's, 0004's and 0005's docstrings:
a migration freezes the world as it was when it was written, so it may not
import anything that can be edited later.

Revision ID: 0006
Revises: 0005
Create Date: 2026-08-07

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

UNIQUE_KEY = "uq_load_profile_readings_device_logger_read_at"


def upgrade() -> None:
    with op.batch_alter_table("load_profile_readings") as batch_op:
        batch_op.add_column(sa.Column("logger_id", sa.Integer(), nullable=False, server_default="1"))
        batch_op.add_column(sa.Column("interval_sec", sa.Integer(), nullable=False, server_default="900"))
        batch_op.add_column(sa.Column("import_reactive_kvarh", sa.Float(), nullable=True))
        batch_op.add_column(sa.Column("export_active_kwh", sa.Float(), nullable=True))
        batch_op.add_column(sa.Column("export_reactive_kvarh", sa.Float(), nullable=True))
        batch_op.add_column(sa.Column("avg_geo_pf", sa.Float(), nullable=True))
        batch_op.drop_column("interval")
        batch_op.create_unique_constraint(UNIQUE_KEY, ["device_id", "logger_id", "read_at"])


def downgrade() -> None:
    with op.batch_alter_table("load_profile_readings") as batch_op:
        batch_op.drop_constraint(UNIQUE_KEY, type_="unique")
        batch_op.add_column(sa.Column("interval", sa.String(length=16), nullable=True))
        batch_op.drop_column("avg_geo_pf")
        batch_op.drop_column("export_reactive_kvarh")
        batch_op.drop_column("export_active_kwh")
        batch_op.drop_column("import_reactive_kvarh")
        batch_op.drop_column("interval_sec")
        batch_op.drop_column("logger_id")
