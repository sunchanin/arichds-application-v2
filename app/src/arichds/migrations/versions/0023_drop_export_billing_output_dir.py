"""Owner decision ก (2026-09-23) — the Billing page has one folder

`export_billing_output_dir` lived for one build (0.8.2, the same day): the billing
file now follows `capture_dir`, the Billing page's one folder, so the row is
removed rather than left unread in `settings`. Nothing reads it any more;
`downgrade` cannot know what it held and restores nothing (0.8.2's reader
treats a missing row as "use the Load Profile folder").

Imports nothing from `arichds` — same rule as every migration since 0003.

Revision ID: 0023
Revises: 0022
Create Date: 2026-09-23

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0023"
down_revision: str | None = "0022"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(sa.text("DELETE FROM settings WHERE key = 'export_billing_output_dir'"))


def downgrade() -> None:
    pass
