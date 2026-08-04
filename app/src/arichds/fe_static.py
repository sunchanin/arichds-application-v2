"""Locate the built SPA so FastAPI can serve it from the same origin.

SPEC §3.1: "SPA เสิร์ฟจาก FastAPI origin เดียวกัน — ไม่มี nginx, ไม่มี CORS".
One process serves both the API and the web UI, so there is no cross-origin
story to configure, secure, or debug.

Ported from ``cewe-worker/src/fe_static.py``. The resolution contract is relied
on by the PyInstaller spec — keep it stable.
"""

from __future__ import annotations

import logging
import os
import sys
from pathlib import Path

logger = logging.getLogger(__name__)

#: Environment override, authoritative when set.
FE_DIST_ENV = "ARICHDS_FE_DIST"


def _has_index(candidate: Path) -> bool:
    """A dist directory is servable iff it contains an ``index.html`` file."""
    return (candidate / "index.html").is_file()


def resolve_fe_dist() -> Path | None:
    """Resolve the frontend dist directory to serve, or None for API-only.

    Resolution order:

    1. **Override — authoritative.** If ``ARICHDS_FE_DIST`` is set and
       non-empty, it is the *only* candidate: returned when it contains
       ``index.html``, else ``None``. No fallback — this keeps tests
       deterministic on a dev machine that also has a real ``web/dist``.
    2. **Frozen bundle.** Under PyInstaller (``sys._MEIPASS`` set), try
       ``<_MEIPASS>/fe_dist``.
    3. **Dev default.** The repo-relative ``<repo>/web/dist``.
    4. **API-only.** Otherwise ``None`` — the API still runs and ``GET /``
       simply has nothing to serve. A missing frontend must never be a crash.

    Returns:
        The directory to serve, or None.
    """
    override = os.getenv(FE_DIST_ENV)
    if override:
        candidate = Path(override)
        return candidate if _has_index(candidate) else None

    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        frozen = Path(meipass) / "fe_dist"
        return frozen if _has_index(frozen) else None

    # <repo>/app/src/arichds/fe_static.py → parents[3] is <repo>.
    dev_default = Path(__file__).resolve().parents[3] / "web" / "dist"
    if _has_index(dev_default):
        return dev_default

    return None
