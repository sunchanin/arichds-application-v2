"""M2-1 auth schema — the two tables the guard rests on.

The migration is what ships, so the migration is what gets tested: every
assertion here runs against a SQLite file produced by ``alembic upgrade head``,
never by ``create_all``.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import inspect, select, text

from arichds.auth.roles import Role
from arichds.config import Settings
from arichds.db.models import User, UserToken
from arichds.db.session import get_engine, session_scope


def make_user(username: str = "admin", role: Role = Role.ADMIN) -> User:
    """Build an unsaved user row with a stand-in hash."""
    return User(username=username, password_hash="not-a-real-hash", role=role)


class TestAuthTables:
    def test_upgrade_head_creates_the_m2_1_tables(self, migrated_db: Settings) -> None:
        tables = set(inspect(get_engine()).get_table_names())
        assert {"users", "user_tokens"} <= tables

    def test_users_columns(self, migrated_db: Settings) -> None:
        columns = {c["name"] for c in inspect(get_engine()).get_columns("users")}
        assert columns == {"id", "username", "password_hash", "role", "created_at"}

    def test_user_tokens_columns(self, migrated_db: Settings) -> None:
        columns = {c["name"] for c in inspect(get_engine()).get_columns("user_tokens")}
        assert columns == {"id", "user_id", "token_hash", "expires_at", "revoked_at", "created_at"}

    def test_no_is_active_or_api_token_columns(self, migrated_db: Settings) -> None:
        """v1 had both; CLAUDE.md and D9 rule them out — pin it, do not re-port."""
        columns = {c["name"] for c in inspect(get_engine()).get_columns("users")}
        assert "is_active" not in columns
        assert "api_token" not in columns

    def test_username_is_unique(self, migrated_db: Settings) -> None:
        constraints = inspect(get_engine()).get_unique_constraints("users")
        assert any(c["column_names"] == ["username"] for c in constraints)

    def test_token_hash_is_uniquely_indexed(self, migrated_db: Settings) -> None:
        indexes = inspect(get_engine()).get_indexes("user_tokens")
        token_hash_index = next(i for i in indexes if i["column_names"] == ["token_hash"])
        # SQLite reflection reports the flag as 1, not True.
        assert token_hash_index["unique"]


class TestUserRows:
    def test_role_round_trips_as_the_enum(self, migrated_db: Settings) -> None:
        """Stored as VARCHAR, read back as :class:`Role` — no CHECK constraint."""
        with session_scope() as session:
            session.add(make_user("someone", Role.USER))

        with session_scope() as session:
            user = session.scalars(select(User)).one()
            assert user.role is Role.USER

    def test_the_role_is_stored_lowercase_on_disk(self, migrated_db: Settings) -> None:
        """The column holds ``admin``/``user``, not ``ADMIN``/``USER``.

        SQLAlchemy's ``Enum`` persists member *names* unless given
        ``values_callable``, which would put the disk at odds with everything
        else that names a Role: the API payload, the JWT ``role`` claim,
        SPEC §3.2 and the **Role** entry in CONTEXT.md — the vocabulary
        authority. It also has to be read deliberately: the ORM coerces in both
        directions, so ``test_role_round_trips_as_the_enum`` above passes either
        way and cannot catch this.

        A support query or an M7 App Log filter doing ``WHERE role = 'admin'``
        is the thing that would silently match nothing.
        """
        with session_scope() as session:
            session.add(make_user("an-admin", Role.ADMIN))
            session.add(make_user("a-user", Role.USER))

        with session_scope() as session:
            stored = session.execute(text("SELECT username, role FROM users ORDER BY username")).all()

        assert stored == [("a-user", "user"), ("an-admin", "admin")]

    def test_usernames_are_unique(self, migrated_db: Settings) -> None:
        import sqlalchemy.exc

        with session_scope() as session:
            session.add(make_user("duplicate"))

        try:
            with session_scope() as session:
                session.add(make_user("duplicate"))
        except sqlalchemy.exc.IntegrityError:
            pass
        else:
            raise AssertionError("expected a unique-constraint violation")

    def test_deleting_a_user_deletes_their_tokens(self, migrated_db: Settings) -> None:
        """M2-2 locks an account out by deleting it — its tokens must go too."""
        with session_scope() as session:
            user = make_user()
            session.add(user)
            session.flush()
            session.add(
                UserToken(
                    user_id=user.id,
                    token_hash="a" * 64,
                    expires_at=datetime.now(UTC) + timedelta(hours=8),
                )
            )

        with session_scope() as session:
            session.delete(session.scalars(select(User)).one())

        with session_scope() as session:
            assert session.scalars(select(UserToken)).all() == []
