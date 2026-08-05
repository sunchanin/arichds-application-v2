"""Which paths Limited Mode guards — the allow-list, in isolation.

Pure function, no app needed. Worth pinning separately because getting this
wrong in either direction is bad: guard too much and the user cannot reach the
Activation page that would fix their machine; guard too little and an
unlicensed machine serves data.

Being off this list means only that the *license* gate steps aside. Every path
here still carries whatever auth guard its router declares — the two gates are
independent, and ``tests/test_api_license_auth.py`` covers where they meet.
"""

from __future__ import annotations

import pytest

from arichds.licensing.middleware import is_guarded_path


@pytest.mark.parametrize(
    "path",
    [
        "/api/devices",
        "/api/devices/1",
        "/api/devices/1/readings/latest",
        "/api/anything-future",
    ],
)
def test_api_paths_are_guarded(path: str) -> None:
    assert is_guarded_path(path)


@pytest.mark.parametrize(
    "path",
    [
        "/api/health",
        "/api/license/status",
        "/api/license/activate",
        # M2-1: activation is admin-only, so a machine whose lease lapsed has to
        # be loggable-into or it can never be re-activated (SPEC §3.2).
        "/api/auth/check-setup",
        "/api/auth/setup",
        "/api/auth/login",
        "/api/auth/logout",
        "/api/auth/me",
    ],
)
def test_health_license_and_auth_stay_open(path: str) -> None:
    assert not is_guarded_path(path)


@pytest.mark.parametrize(
    "path",
    [
        "/",
        "/index.html",
        "/assets/index-abc123.js",
        "/openapi.json",
        "/docs",
    ],
)
def test_non_api_paths_are_never_guarded(path: str) -> None:
    """The SPA must always load — it is the only way out of Limited Mode."""
    assert not is_guarded_path(path)


def test_a_path_merely_starting_with_an_allowed_name_is_still_guarded() -> None:
    """`/api/licenses` is not `/api/license` — prefix matching must be exact."""
    assert is_guarded_path("/api/licenses")
    assert is_guarded_path("/api/healthcheck")
    assert is_guarded_path("/api/authors")
