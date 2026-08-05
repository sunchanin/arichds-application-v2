"""M2-1 auth schema: users + user_tokens

The slice that retrofits the JWT guard onto everything M1 left open. Two tables
only (SPEC §3.2): the role is an enum column, not a roles/permissions pair, and
tokens are stored as SHA-256 digests, never in the clear.

The ``role`` column is rendered as VARCHAR with no CHECK constraint
(``create_constraint=False`` on the model) so a future batch migration rebuilding
this table has no unnamed constraint to trip over, and it stores the enum
*values* (``admin``/``user``) rather than its member names — the vocabulary
CONTEXT.md and SPEC §3.2 define.

Revision ID: 0002
Revises: 0001
Create Date: 2026-08-05

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("username", sa.String(length=64), nullable=False),
        sa.Column("password_hash", sa.String(length=128), nullable=False),
        # Lowercase values, not the enum member names — see the note on
        # ``User.role``. This is what ``WHERE role = 'admin'`` will match.
        sa.Column(
            "role",
            sa.Enum("admin", "user", name="role", native_enum=False, length=16, create_constraint=False),
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("username"),
    )

    op.create_table(
        "user_tokens",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        # SHA-256 hex digest of the raw token — the raw JWT is never stored
        # (SPEC §3.2, v1 INV-AUTH-04).
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_user_tokens_token_hash", "user_tokens", ["token_hash"], unique=True)
    op.create_index("ix_user_tokens_user_id", "user_tokens", ["user_id"])


def downgrade() -> None:
    op.drop_index("ix_user_tokens_user_id", table_name="user_tokens")
    op.drop_index("ix_user_tokens_token_hash", table_name="user_tokens")
    op.drop_table("user_tokens")
    op.drop_table("users")
