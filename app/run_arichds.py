#!/usr/bin/env python3
"""Console entrypoint for the frozen ``arichds.exe``.

This is what NSSM runs as the Windows service (SPEC §3.1). It starts uvicorn
in-process rather than shelling out, so the service has exactly one process to
supervise and NSSM's restart-on-exit applies to the real thing.

Migrations are NOT run here — the app lifespan runs ``alembic upgrade head``
before serving, so there is no separate migrate step for the installer or the
updater to forget.

Usage::

    arichds.exe              # serve on ARICHDS_PORT (default 8000)
    arichds.exe --version    # print the version and exit
"""

from __future__ import annotations

import sys
from pathlib import Path

# Running from a source checkout (not frozen): put src/ on the path.
if not getattr(sys, "frozen", False):
    _SRC = Path(__file__).resolve().parent / "src"
    if str(_SRC) not in sys.path:
        sys.path.insert(0, str(_SRC))


def main() -> int:
    """Serve the API and the SPA until the process is stopped."""
    import uvicorn

    from arichds import __version__
    from arichds.config import get_settings

    if "--version" in sys.argv:
        print(f"ARICHDS {__version__}")
        return 0

    settings = get_settings()
    settings.ensure_directories()

    # Import the app object rather than passing a string: under PyInstaller a
    # string target makes uvicorn re-import by name from a path that may not
    # resolve inside the bundle.
    from arichds.main import app

    uvicorn.run(
        app,
        host=settings.host,
        port=settings.port,
        # NSSM captures stdout/stderr to a rotating file; uvicorn's own access
        # log would double every line the app already logs.
        access_log=False,
        log_config=None,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
