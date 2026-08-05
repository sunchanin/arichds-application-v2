"""Every ``/api`` route is closed unless it is on the exempt list.

This sweep is what buys the "closed by default" property that middleware would
have given us. The guard is a dependency (see ``arichds.api.deps``), so nothing
structurally forces a *future* router to carry it — this test does, by walking
the live route table rather than a hand-maintained list of paths. Add a router
without a guard and the suite goes red.

It runs against an **activated** app on purpose: on a limited machine the
Limited Mode middleware answers 403 before any auth dependency runs, so a 401
is only observable once the machine is licensed.

A 422 from any route here means the guard is attached too deep — inside a
handler signature that is solved after the request body — and the fix is to move
it to the router or the route, never to special-case this test.
"""

from __future__ import annotations

import pytest
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient

#: The only endpoints reachable without a token (SPEC §3.2). Anything else must
#: be added here deliberately, in a change that says why.
EXEMPT_ROUTES: frozenset[tuple[str, str]] = frozenset(
    {
        ("GET", "/api/health"),
        ("GET", "/api/auth/check-setup"),
        ("POST", "/api/auth/setup"),
        ("POST", "/api/auth/login"),
    }
)

#: Never interesting: FastAPI generates them and neither carries a body or a guard.
IGNORED_METHODS: frozenset[str] = frozenset({"HEAD", "OPTIONS"})


def api_routes(client: TestClient) -> list[tuple[str, str]]:
    """Return every ``(method, path)`` under ``/api`` in the live route table.

    FastAPI keeps an included router as a single node in ``app.routes`` rather
    than flattening its routes into it, so the walk has to recurse through
    ``original_router``. ``test_the_sweep_sees_everything_openapi_documents``
    is the tripwire for that shape changing under a FastAPI upgrade.
    """
    found: list[tuple[str, str]] = []

    def walk(routes: object) -> None:
        for route in routes:  # type: ignore[attr-defined]
            included = getattr(route, "original_router", None)
            if included is not None:
                walk(included.routes)
                continue
            if isinstance(route, APIRoute) and route.path.startswith("/api"):
                found.extend((method, route.path) for method in sorted(route.methods - IGNORED_METHODS))

    walk(client.app.routes)
    return sorted(found)


def documented_api_routes(client: TestClient) -> set[tuple[str, str]]:
    """Return every ``/api`` ``(method, path)`` pair OpenAPI advertises."""
    schema = client.app.openapi()
    return {
        (method.upper(), path)
        for path, operations in schema["paths"].items()
        if path.startswith("/api")
        for method in operations
        if method.upper() not in IGNORED_METHODS
    }


def concrete_path(path: str) -> str:
    """Substitute ``1`` for every ``{param}`` segment."""
    return "/".join(
        "1" if segment.startswith("{") and segment.endswith("}") else segment for segment in path.split("/")
    )


def test_the_route_table_is_not_empty(activated_client: TestClient) -> None:
    """Guards against the sweep silently passing because it found nothing."""
    assert len(api_routes(activated_client)) > 5


def test_the_sweep_sees_everything_openapi_documents(activated_client: TestClient) -> None:
    """The walker must not quietly miss routes after a FastAPI upgrade.

    OpenAPI is FastAPI's own account of its surface; if the route-table walk
    ever returns less than that, the sweep below would pass while leaving
    endpoints untested.
    """
    assert documented_api_routes(activated_client) <= set(api_routes(activated_client))


def test_every_exempt_route_still_exists(activated_client: TestClient) -> None:
    """A renamed endpoint must not silently leave a stale exemption behind."""
    assert set(api_routes(activated_client)) >= EXEMPT_ROUTES


def test_no_api_route_answers_without_a_token(anon_client: TestClient) -> None:
    """The sweep itself: every guarded ``/api`` route answers 401 unauthenticated."""
    offenders: list[tuple[str, str, int]] = []

    for method, path in api_routes(anon_client):
        if (method, path) in EXEMPT_ROUTES:
            continue
        response = anon_client.request(method, concrete_path(path))
        if response.status_code != 401:
            offenders.append((method, path, response.status_code))

    assert offenders == []


@pytest.mark.parametrize(("method", "path"), sorted(EXEMPT_ROUTES))
def test_exempt_routes_are_reachable_without_a_token(anon_client: TestClient, method: str, path: str) -> None:
    """They must not merely be *listed* as exempt — they must actually answer."""
    response = anon_client.request(method, path, json={})

    assert response.status_code != 401
