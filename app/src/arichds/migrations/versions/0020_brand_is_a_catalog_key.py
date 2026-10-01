"""ui-audit ticket 01 — `devices.brand` is always a catalog key

A brand is a catalog key (SPEC §3.3). One row on the first real install stored
its brand as `CEWE` beside a catalog that says `cewe`; the device form compares
brands with `===`, so that device showed its own model as "not licensed on
this machine" and the Model filter carried a raw `CEWE · prometer100` entry.
This migration lowercases every brand that differs from a catalog key only by
case. A brand that matches no key even case-insensitively is left exactly as
it is — that is the "no driver in this build" case the form already names,
and rewriting it would invent a brand.

Repeats the three brand keys verbatim rather than importing `Brand` — same
rule as every migration since 0003. Data-only: no schema change, so the
downgrade is a no-op (the original casing is not recoverable and does not
need to be).

Revision ID: 0020
Revises: 0019
Create Date: 2026-09-16

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0020"
down_revision: str | None = "0019"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        sa.text(
            "UPDATE devices SET brand = lower(brand) "
            "WHERE brand != lower(brand) AND lower(brand) IN ('cewe', 'mitsu', 'smart_tcc')"
        )
    )


def downgrade() -> None:
    pass
