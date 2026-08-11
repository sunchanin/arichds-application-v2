"""Key/value application settings (M6b, issue #22) — the `settings` table.

Deliberately named apart from :class:`arichds.config.Settings`, which is the
environment (``ARICHDS_*`` variables, immutable for the process's life). This
module is the table an admin can edit at runtime through the API — ADR 0010's
``capture_dir`` is the first key it holds, and more arrive module by module.

A missing key is not an error: :func:`get_setting` falls back to a documented
default, so a fresh install answers ``GET /api/billing/settings`` without a
seed migration.
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from arichds.db.models import Setting

#: The one key M6b introduces. `""` means "not configured" — capture is then
#: skipped with a log line rather than defaulting to a path under
#: %ProgramData% (ADR 0010; decision 16, issue #22).
CAPTURE_DIR_KEY = "capture_dir"
CAPTURE_DIR_DEFAULT = ""

#: The machine-wide display-unit setting (a CR, not part of any milestone's
#: original shape) — `"kilo"` (kW/kWh/kvar/kvarh, today's behaviour) or
#: `"base"` (W/Wh/var/varh). A missing key means `"kilo"`, so an existing
#: install is unchanged. Applied at render time only, in the web UI and the
#: capture renderers (:mod:`arichds.capture._render_shared`) — the database
#: and the API payloads never change (CLAUDE.md's write-time normalization
#: invariant).
DISPLAY_UNIT_SCALE_KEY = "display_unit_scale"
DISPLAY_UNIT_SCALE_DEFAULT = "kilo"


def get_setting(session: Session, key: str, default: str) -> str:
    """Return *key*'s stored value, or *default* if the row is absent."""
    row = session.get(Setting, key)
    if row is None or row.value is None:
        return default
    return row.value


def set_setting(session: Session, key: str, value: str) -> None:
    """Insert *key* if absent, or update it in place."""
    row = session.get(Setting, key)
    if row is None:
        session.add(Setting(key=key, value=value))
    else:
        row.value = value
