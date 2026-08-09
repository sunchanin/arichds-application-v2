"""Runtime configuration — every knob is an ``ARICHDS_*`` environment variable.

On a real install the Inno Setup installer points ``ARICHDS_DATA_DIR`` at
``%ProgramData%\\ARICHDS`` (SPEC §3.1: program in ``Program Files\\ARICHDS``,
*all* data in ``%ProgramData%\\ARICHDS``). Locally it defaults to ``./data`` so a
dev checkout needs no environment at all.

Everything derived from the data directory (database file, license file, logs)
is a property here so there is exactly one place that decides where data lives.
"""

from __future__ import annotations

import logging
import os
from functools import lru_cache
from pathlib import Path

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from arichds.constants import FEATURE_KEYS

logger = logging.getLogger(__name__)


class Settings(BaseSettings):
    """Process configuration read from ``ARICHDS_*`` environment variables.

    Attributes:
        data_dir: Root of all runtime data. ``ARICHDS_DATA_DIR``.
        port: TCP port the API binds (SPEC §3.1 — 8000). ``ARICHDS_PORT``.
        host: Bind address. ``0.0.0.0`` so other machines on the site LAN can
            reach ``http://<ip>:8000`` (the installer opens the firewall rule).
        log_level: Root logger level. ``ARICHDS_LOG_LEVEL``.
        poll_enabled: Master switch for **all background work** — the Poller and
            every Scheduler job. Off in tests and dev runs that want the API
            without touching meters. ``ARICHDS_POLL_ENABLED``.
            **Still one variable, decided at M5c (issue #19).** That slice added
            the first two jobs that read no meter (retention and backup), which
            was the trigger to revisit this, and the answer is unchanged: this is
            a dev/test switch, unset on a real install, and a second variable
            would be missed by exactly the fixtures that already set this one.
            The cost, accepted: ``false`` also disables the daily purge and the
            daily backup — which on a dev box is what anyone setting it wants.
        token_expire_minutes: Access Token lifetime (SPEC §3.2 — 8 hours).
            ``ARICHDS_TOKEN_EXPIRE_MINUTES``.
        jwt_secret: Explicit JWT signing secret. ``ARICHDS_JWT_SECRET``. When
            unset the secret is generated per install and persisted under
            :attr:`jwt_secret_path` (ADR 0003).
        features: Comma-separated feature keys ``.env`` asks for. A plain
            ``str`` field, not ``list[str]`` — pydantic-settings parses
            complex-typed env vars as JSON, and a bare comma-separated value
            would fail to parse (v1 ``config.py:323-349`` makes the same
            choice). ``ARICHDS_FEATURES``. Empty/unset means every key in
            :data:`~arichds.constants.FEATURE_KEYS` is requested — see
            :meth:`enabled_feature_keys`.
        capture_allowlist: ``os.pathsep``-separated list of absolute roots
            ``capture_dir`` (a `settings` value, not an env var — ADR 0010)
            must resolve within. ``ARICHDS_CAPTURE_ALLOWLIST``. ``os.pathsep``
            because a bare ``:`` split would shred a Windows drive letter
            (e.g. ``C:`` would split from the rest of the path) — v1 makes
            the same choice (``config.py:274-283``). Empty/unset means no
            root restriction (decision 17, issue #22) — see
            :meth:`capture_allowlist_roots`.
    """

    model_config = SettingsConfigDict(env_prefix="ARICHDS_", env_file=".env", extra="ignore")

    data_dir: Path = Path("./data")
    port: int = 8000
    host: str = "0.0.0.0"
    log_level: str = "INFO"
    poll_enabled: bool = True
    token_expire_minutes: int = 480
    jwt_secret: str | None = None
    features: str = ""
    capture_allowlist: str = ""

    def capture_allowlist_roots(self) -> list[Path]:
        """Resolve ``ARICHDS_CAPTURE_ALLOWLIST`` into absolute root paths.

        Empty/unset means **no root restriction** on ``capture_dir`` (decision
        17, issue #22) — unlike v1, which defaulted the allowlist to its own
        env-configured ``capture_dir``. v2's ``capture_dir`` is an operator
        setting rather than an env var, so defaulting the allowlist to it
        would be circular (an operator could set both to whatever they like
        in the same action).
        """
        raw = self.capture_allowlist.strip()
        if not raw:
            return []
        return [Path(part.strip()).resolve() for part in raw.split(os.pathsep) if part.strip()]

    @field_validator("features")
    @classmethod
    def _warn_unknown_feature_keys(cls, value: str) -> str:
        """WARN about any ``ARICHDS_FEATURES`` key that gates nothing (a
        typo, or a key a newer portal knows and this build does not) — v1's
        exact shape (``config.py:329-344``), a ``field_validator`` so it
        fires **once, at construction**, not once per
        :meth:`enabled_feature_keys` call. ``get_settings()`` is
        ``lru_cache``d, so construction happens once per process — but
        :meth:`enabled_feature_keys` is called once per request by
        :func:`~arichds.api.deps.require_feature` on three routers, and a
        warning inside it would write the same line into a 10 MB × 5
        rotating log file once per HTTP request, burying the one signal an
        operator chasing a missing feature actually needs.
        """
        listed = {part.strip() for part in value.split(",") if part.strip()}
        unknown = listed - FEATURE_KEYS
        if unknown:
            logger.warning(
                "ARICHDS_FEATURES lists unknown key(s) %s that gate no feature. Known keys: %s",
                ", ".join(sorted(unknown)),
                ", ".join(sorted(FEATURE_KEYS)),
            )
        return value

    def enabled_feature_keys(self) -> frozenset[str]:
        """The feature keys ``ARICHDS_FEATURES`` asks for (M6b, issue #22).

        Empty/unset expands to every key in
        :data:`~arichds.constants.FEATURE_KEYS` (decision 2, issue #22) — on a
        real install the license alone is then the ceiling. Pure parsing —
        the unknown-key warning lives in :meth:`_warn_unknown_feature_keys`.
        """
        listed = {part.strip() for part in self.features.split(",") if part.strip()}
        return frozenset(listed) if listed else FEATURE_KEYS

    # ── Derived paths (single source of truth for "where does X live") ────────

    @property
    def db_path(self) -> Path:
        """Absolute path to the one SQLite database."""
        return self.data_dir.resolve() / "arichds.db"

    @property
    def db_url(self) -> str:
        """SQLAlchemy URL for :attr:`db_path` (POSIX slashes — Windows-safe)."""
        return f"sqlite:///{self.db_path.as_posix()}"

    @property
    def license_dir(self) -> Path:
        """Directory holding the activated license file."""
        return self.data_dir.resolve() / "license"

    @property
    def license_path(self) -> Path:
        """Absolute path to the persisted license (written on activation)."""
        return self.license_dir / "license.lic"

    @property
    def log_dir(self) -> Path:
        """Directory for rotating application logs."""
        return self.data_dir.resolve() / "logs"

    @property
    def backup_dir(self) -> Path:
        """Directory holding the daily database backups (M5c, issue #19).

        Fixed, not configurable — ADR 0010: a backup is written for the
        machine (its only consumer is a restore, performed by whoever is
        already at this command prompt), while `capture_dir` is written for a
        person who hands the file to someone else. Only the latter earns the
        cost of a user-choosable destination. Singular ``backup``, matching
        SPEC §5.
        """
        return self.data_dir.resolve() / "backup"

    @property
    def secret_dir(self) -> Path:
        """Directory holding process secrets generated on this install."""
        return self.data_dir.resolve() / "secret"

    @property
    def jwt_secret_path(self) -> Path:
        """Absolute path to the per-install JWT signing secret (ADR 0003).

        Deleting this file invalidates every issued Access Token — that is the
        rotation mechanism.
        """
        return self.secret_dir / "jwt_secret.key"

    def ensure_directories(self) -> None:
        """Create the data directory tree. Safe to call repeatedly.

        SQLite will not create a missing parent directory, and neither will the
        rotating log handler — so this runs before either is opened.
        """
        for directory in (self.data_dir.resolve(), self.license_dir, self.log_dir, self.secret_dir, self.backup_dir):
            directory.mkdir(parents=True, exist_ok=True)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the process-wide settings, constructed once.

    Cached because settings are immutable for the life of the process — unlike
    license state, which must stay re-evaluatable (ADR 0001) and therefore lives
    in :mod:`arichds.licensing.service`, never here.
    """
    return Settings()
