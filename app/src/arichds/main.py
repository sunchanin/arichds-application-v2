"""Application entrypoint — one process serving the API and the SPA.

Boot order matters and is fixed (SPEC §3.1):

1. Create the data directory tree and configure logging (with the credential
   redaction filter attached to every handler).
2. Run ``alembic upgrade head`` **before** anything serves. The installer and
   updater therefore have no migrate step of their own.
3. Build the LicenseService and evaluate the license once.
4. Build the Poller and the Scheduler and subscribe **both** to the license
   state, so they start if the machine is already licensed — and start *the
   instant* one is activated, with no restart (ADR 0001). Between them they are
   SPEC §4's fixed two background threads plus one Poller worker per meter.
5. Serve.

Run it with ``fastapi dev`` / ``fastapi run`` (the entrypoint is declared in
``pyproject.toml``), or point uvicorn at ``arichds.main:app``.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from arichds import __version__
from arichds.acquisition.poller import Poller
from arichds.api import (
    auth,
    battery,
    billing,
    devices,
    energy,
    health,
    holidays,
    license,
    load_profile,
    logs,
    records,
    special_days,
    users,
)
from arichds.api import settings as settings_router
from arichds.api.deps import FeatureDisabledError
from arichds.api.envelope import ApiResponse
from arichds.config import Settings, get_settings
from arichds.constants import ERROR_FEATURE_DISABLED
from arichds.db.migrate import upgrade_to_head
from arichds.db.session import dispose_engine, init_engine
from arichds.fe_static import resolve_fe_dist
from arichds.jobs.scheduler import Scheduler
from arichds.licensing.current import set_current_license_service
from arichds.licensing.middleware import LimitedModeMiddleware
from arichds.licensing.service import LicenseService
from arichds.logging_config import configure_logging

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Bring the process up, then tear it down cleanly."""
    settings: Settings = get_settings()
    settings.ensure_directories()
    configure_logging(level=settings.log_level, log_dir=settings.log_dir)

    logger.info("ARICHDS %s starting — data dir %s", __version__, settings.data_dir.resolve())

    # Schema first: nothing may read the database before it is at head.
    upgrade_to_head(settings.db_url)
    init_engine()

    license_service = LicenseService(settings.license_path)
    poller = Poller(enabled=settings.poll_enabled)
    scheduler = Scheduler(enabled=settings.poll_enabled)
    app.state.license_service = license_service
    app.state.poller = poller
    app.state.scheduler = scheduler
    # Published for background code with no Request — the eager capture path
    # in acquisition/billing.py (M6b, issue #22). Holds the service, never a
    # state snapshot (ADR 0001) — see arichds.licensing.current.
    set_current_license_service(license_service)

    # Subscribing BEFORE the first evaluation means an already-licensed machine
    # starts polling on boot, and a freshly activated one starts on activation.
    license_service.add_listener(poller.on_license_state)
    license_service.add_listener(scheduler.on_license_state)
    license_service.re_evaluate()

    try:
        yield
    finally:
        set_current_license_service(None)
        poller.stop()
        # Stopped here and not only on the license listener: a thread that
        # outlives its app keeps reading meters and writing rows into a database
        # nobody is serving from any more.
        scheduler.stop()
        dispose_engine()
        logger.info("ARICHDS stopped")


def create_app() -> FastAPI:
    """Build the FastAPI application.

    Returns:
        The configured app: API routers, Limited Mode enforcement, and the SPA.
    """
    app = FastAPI(
        title="ARICHDS",
        version=__version__,
        summary="Local meter monitoring — API and web UI on one origin.",
        lifespan=lifespan,
    )

    app.include_router(health.router)
    app.include_router(auth.router)
    app.include_router(license.router)
    app.include_router(devices.router)
    app.include_router(load_profile.router)
    app.include_router(billing.router)
    app.include_router(records.router)
    app.include_router(energy.router)
    app.include_router(holidays.router)
    app.include_router(special_days.router)
    app.include_router(battery.router)
    app.include_router(logs.router)
    app.include_router(users.router)
    app.include_router(settings_router.router)

    @app.exception_handler(FeatureDisabledError)
    async def handle_feature_disabled(_request: Request, exc: FeatureDisabledError) -> JSONResponse:
        """403 in the ``{success, data, error}`` envelope (decision 5, issue #22).

        A ``reason`` naming the missing feature key so the SPA (or an operator
        reading the response) knows exactly what to ask for.
        """
        envelope = ApiResponse.failed(
            ERROR_FEATURE_DISABLED,
            "This feature is not enabled for this deployment.",
            reason=exc.feature,
        )
        return JSONResponse(status_code=403, content=envelope.model_dump())

    # Enforcement wraps everything but only guards /api/* minus health and
    # license (see arichds.licensing.middleware). The service is resolved per
    # request off app.state, because it does not exist until the lifespan runs.
    app.add_middleware(
        LimitedModeMiddleware,
        service_provider=lambda: getattr(app.state, "license_service", None),
    )

    # The SPA is registered last and matches at low priority, so API routes
    # always win. Absent in a dev checkout that has not run `pnpm build` — the
    # API then serves alone.
    dist = resolve_fe_dist()
    if dist is not None:
        app.frontend("/", directory=str(dist))
        logger.info("Serving the web UI from %s", dist)
    else:
        logger.info("No built web UI found — running API-only (GET / has nothing to serve)")

    return app


app = create_app()
