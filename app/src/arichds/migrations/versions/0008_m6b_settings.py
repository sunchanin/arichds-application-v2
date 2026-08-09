"""M6b the `settings` table (issue #22)

SPEC §4: `settings` is a key/value table, the eleventh in the twelve-table
list — ADR 0010 explains why (`billing_captures` was counted before it and
was deliberately dropped: a capture's path is derived from convention, never
stored). This migration is one `CREATE TABLE`, no data to carry over.

`capture_dir` (ADR 0010) is the first key it holds; `db.app_settings` reads a
missing key as its documented default rather than raising, so this migration
does not need to seed a row.

This migration imports nothing from `arichds` and repeats its literals
verbatim — same rule as every migration since 0003: a migration freezes the
world as it was when it was written.

Revision ID: 0008
Revises: 0007
Create Date: 2026-08-09

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0008"
down_revision: str | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "settings",
        sa.Column("key", sa.String(length=64), primary_key=True),
        sa.Column("value", sa.String(length=1024), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )


def downgrade() -> None:
    op.drop_table("settings")
