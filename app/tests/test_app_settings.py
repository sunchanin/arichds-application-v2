"""``db.app_settings`` — the key/value accessor over `settings` (M6b, issue #22).

Named apart from ``config.Settings`` deliberately — that module is the
environment; this one is the table.
"""

from __future__ import annotations

from arichds.config import Settings
from arichds.db.app_settings import CAPTURE_DIR_DEFAULT, CAPTURE_DIR_KEY, get_setting, set_setting
from arichds.db.session import session_scope


class TestGetSettingFallsBackToDefault:
    def test_a_missing_key_returns_the_default(self, migrated_db: Settings) -> None:
        with session_scope() as session:
            assert get_setting(session, CAPTURE_DIR_KEY, CAPTURE_DIR_DEFAULT) == CAPTURE_DIR_DEFAULT

    def test_capture_dir_default_is_the_empty_string(self) -> None:
        """Decision 16 — empty means "not configured", never a %ProgramData% path."""
        assert CAPTURE_DIR_DEFAULT == ""


class TestSetThenGet:
    def test_a_stored_value_round_trips(self, migrated_db: Settings) -> None:
        with session_scope() as session:
            set_setting(session, CAPTURE_DIR_KEY, "C:\\captures")

        with session_scope() as session:
            assert get_setting(session, CAPTURE_DIR_KEY, CAPTURE_DIR_DEFAULT) == "C:\\captures"

    def test_setting_it_twice_updates_in_place(self, migrated_db: Settings) -> None:
        with session_scope() as session:
            set_setting(session, CAPTURE_DIR_KEY, "C:\\first")
        with session_scope() as session:
            set_setting(session, CAPTURE_DIR_KEY, "C:\\second")

        with session_scope() as session:
            assert get_setting(session, CAPTURE_DIR_KEY, CAPTURE_DIR_DEFAULT) == "C:\\second"

        from sqlalchemy import func, select

        from arichds.db.models import Setting

        with session_scope() as session:
            count = session.scalar(select(func.count()).select_from(Setting))
        assert count == 1  # updated in place, not a second row
