"""Feature entitlement (M6b, issue #22) — ``.env FEATURES ∩ license features``.

SPEC §3.9: enabled = ``.env FEATURES ∩ license features``. Root cause of every
test below is decision 1-2 in the issue: ``None`` license features grandfathers
every sellable key (the shape of every license issued before this landed —
``conftest.sign_activation_code`` never sets ``features``), and an *empty*
list is meaningfully different — it enables no sellable key at all.
"""

from __future__ import annotations

import pytest
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient

from arichds.config import Settings
from arichds.constants import FEATURE_KEYS, SELLABLE_FEATURE_KEYS
from arichds.licensing.features import effective_features, feature_enabled
from arichds.licensing.service import LicenseState

#: The routers M6b/M7-1/M7-2 gate (decision 6, issue #22; decision 18, issue
#: #28; D6, issue #29) and the feature key each one requires. `/api/devices`
#: is deliberately absent (decision 7). `/api/energy` and `/api/holidays`
#: share `energy_summary` (decision 18 — both tabs and the calendar);
#: `/api/special-days` gates on its own `special_days` key; `/api/battery`
#: gates on its own `battery` key too — the job that fills it is not
#: feature-gated (D6), only the read-back API is.
GATED_PREFIXES: dict[str, str] = {
    "/api/billing": "billing",
    "/api/load-profile": "load_profile",
    "/api/records": "records",
    "/api/energy": "energy_summary",
    "/api/holidays": "energy_summary",
    "/api/special-days": "special_days",
    "/api/battery": "battery",
}


def api_routes(client: TestClient) -> list[tuple[str, str]]:
    """Every ``(method, path)`` under ``/api`` in the live route table.

    Same walk as ``test_auth_guard.py::api_routes`` — duplicated rather than
    imported, since pytest test modules are not a package other tests should
    depend on.
    """
    found: list[tuple[str, str]] = []

    def walk(routes: object) -> None:
        for route in routes:  # type: ignore[attr-defined]
            included = getattr(route, "original_router", None)
            if included is not None:
                walk(included.routes)
                continue
            if isinstance(route, APIRoute) and route.path.startswith("/api"):
                found.extend((method, route.path) for method in sorted(route.methods - {"HEAD", "OPTIONS"}))

    walk(client.app.routes)
    return sorted(found)


def concrete_path(path: str) -> str:
    """Substitute ``1`` for every ``{param}`` segment."""
    return "/".join(
        "1" if segment.startswith("{") and segment.endswith("}") else segment for segment in path.split("/")
    )


class TestEffectiveFeatures:
    def test_none_license_grandfathers_every_sellable_key(self) -> None:
        assert effective_features(FEATURE_KEYS, None) == FEATURE_KEYS

    def test_empty_license_features_enables_no_sellable_key(self) -> None:
        result = effective_features(FEATURE_KEYS, [])

        assert result == FEATURE_KEYS - SELLABLE_FEATURE_KEYS
        assert "app_log" in result  # ops-only key survives — never license-governed

    def test_a_key_in_the_license_but_absent_from_env_is_off(self) -> None:
        env_enabled = FEATURE_KEYS - {"billing"}

        result = effective_features(env_enabled, ["billing", "records"])

        assert "billing" not in result

    def test_a_key_in_env_but_absent_from_the_license_is_off(self) -> None:
        result = effective_features(FEATURE_KEYS, ["records"])  # billing not sold

        assert "billing" not in result
        assert "records" in result

    def test_ops_only_key_ignores_the_license_entirely(self) -> None:
        """`app_log` is never in `SELLABLE_FEATURE_KEYS` — a license that omits
        it (every license does; it's ops-only) must not turn it off."""
        result = effective_features(FEATURE_KEYS, [])  # nothing sellable licensed

        assert "app_log" in result


class _StubLicenseService:
    """A minimal stand-in for `LicenseService`, satisfying `feature_enabled`'s
    one call — `.current_state()` — without a real activation flow."""

    def __init__(self, *, valid: bool, features: list[str] | None) -> None:
        self._valid = valid
        self._features = features

    def current_state(self) -> LicenseState:
        return LicenseState(
            state="active" if self._valid else "limited",
            reason=None if self._valid else "LEASE_EXPIRED",
            features=self._features,
        )


class TestFeatureEnabledRefusesAnInvalidLicenseState:
    """`feature_enabled` must check `state.valid` itself, not just
    `state.features`. `LicenseService._limited()` builds a `LicenseState`
    with `features=None` (nothing was ever parsed from an unverified/expired
    license) — and `effective_features(_, None)` grandfathers every sellable
    key. Without an explicit validity check, a machine whose lease lapses
    *between* ticks would still answer `auto_capture` enabled and the eager
    capture path (which has no middleware in front of it — that gate only
    guards `/api/*`) would write customer-facing PDFs for a machine no
    longer licensed to have them.
    """

    def test_an_invalid_state_disables_every_feature_even_with_none_features(self) -> None:
        service = _StubLicenseService(valid=False, features=None)

        assert feature_enabled("auto_capture", license_service=service, settings=Settings()) is False

    def test_an_invalid_state_disables_an_ops_only_key_too(self) -> None:
        """Not just sellable keys — `app_log` is `.env`-only by design, but
        the invalid-license guard runs before `effective_features` is even
        consulted, so it must refuse everything alike."""
        service = _StubLicenseService(valid=False, features=None)

        assert feature_enabled("app_log", license_service=service, settings=Settings()) is False

    def test_a_valid_state_with_none_features_still_grandfathers(self) -> None:
        """The control: the same `features=None` shape, but `valid=True`,
        must behave exactly as `TestEffectiveFeatures` already proves."""
        service = _StubLicenseService(valid=True, features=None)

        assert feature_enabled("auto_capture", license_service=service, settings=Settings()) is True


class TestUnknownFeatureKeyWarnsOnceAtConstruction:
    """`get_settings()` is `lru_cache`d (once per process), but
    `enabled_feature_keys()` is called once per request by `require_feature`
    on three routers — a warning inside *that* method would write the same
    line into the rotating log once per HTTP request. The warning must live
    where construction happens instead."""

    def test_the_warning_fires_once_regardless_of_how_many_times_the_method_is_called(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        with caplog.at_level("WARNING"):
            settings = Settings(features="not_a_real_key")
            settings.enabled_feature_keys()
            settings.enabled_feature_keys()
            settings.enabled_feature_keys()

        unknown_warnings = [r for r in caplog.records if "unknown key" in r.message]
        assert len(unknown_warnings) == 1

    def test_a_known_key_warns_nothing(self, caplog: pytest.LogCaptureFixture) -> None:
        with caplog.at_level("WARNING"):
            Settings(features="billing,records")

        assert [r for r in caplog.records if "unknown key" in r.message] == []


class TestTheGatedPrefixTableIsNotStale:
    def test_every_gated_prefix_has_at_least_one_route(self, admin_client: TestClient) -> None:
        """A typo'd or renamed prefix in `GATED_PREFIXES` must fail loudly here
        rather than let the sweep below silently test nothing."""
        routes = api_routes(admin_client)
        for prefix in GATED_PREFIXES:
            assert any(path == prefix or path.startswith(f"{prefix}/") for _method, path in routes), (
                f"{prefix} has no route in the live table — GATED_PREFIXES is stale"
            )


class TestRouteSweepWithNoSellableFeatures:
    """Every route under a gated prefix must 403 FEATURE_DISABLED when the
    license carries an empty ``features`` list — the license that grandfathers
    nothing sellable (decision 1)."""

    def test_every_gated_route_answers_feature_disabled(self, admin_client: TestClient, relicense) -> None:
        relicense(admin_client, features=[])

        offenders: list[tuple[str, str, int]] = []
        for method, path in api_routes(admin_client):
            if not any(path == prefix or path.startswith(f"{prefix}/") for prefix in GATED_PREFIXES):
                continue
            response = admin_client.request(method, concrete_path(path), json={})
            body = response.json()
            if response.status_code != 403 or body.get("error", {}).get("code") != "FEATURE_DISABLED":
                offenders.append((method, path, response.status_code))

        assert offenders == []

    def test_the_reason_names_the_missing_feature_key(self, admin_client: TestClient, relicense) -> None:
        """Every gated prefix's own key, not just `billing`'s — a route
        wired to the wrong key (`records` gated by `load_profile`, say)
        would still 403 FEATURE_DISABLED and pass a test that only checked
        `billing`. `GATED_PREFIXES.items()` is the same table
        `TestTheGatedPrefixTableIsNotStale` already proves isn't stale.

        Hits the first live GET route under each prefix rather than the bare
        prefix path itself — `/api/energy` (issue #28) has no route at the
        bare prefix (only `/api/energy/summary` etc.), unlike
        `/api/billing`/`/api/load-profile`/`/api/records`/`/api/holidays`/
        `/api/special-days`, which all declare `@router.get("")`. Missing
        query parameters on the picked route are never reached: the
        router-level `require_feature` dependency fires before FastAPI's own
        parameter validation, exactly as it already does for `/api/billing`'s
        `status`-requiring bare route.
        """
        relicense(admin_client, features=[])
        routes = api_routes(admin_client)

        for prefix, key in GATED_PREFIXES.items():
            method, path = next((m, p) for m, p in routes if m == "GET" and (p == prefix or p.startswith(f"{prefix}/")))
            response = admin_client.get(concrete_path(path))

            assert response.status_code == 403, (prefix, path, response.text)
            body = response.json()
            assert body["error"]["code"] == "FEATURE_DISABLED", (prefix, path, body)
            assert body["error"]["reason"] == key, (prefix, path, body)

    def test_devices_is_not_gated_by_any_feature(self, admin_client: TestClient, relicense) -> None:
        """Decision 7 — `/api/devices` is a device operation, never feature-gated."""
        relicense(admin_client, features=[])

        response = admin_client.get("/api/devices")

        assert response.status_code == 200, response.text


class TestLimitedModeOutranksFeatureGating:
    def test_an_unlicensed_machine_gets_license_invalid_not_feature_disabled(
        self, unlicensed_client: TestClient
    ) -> None:
        """A machine with no license at all must still fail with
        LICENSE_INVALID — the feature gate only refines an ALREADY-valid
        license (decision 5)."""
        response = unlicensed_client.get("/api/health")
        assert response.status_code == 200, response.text  # sanity: app is up

        response = unlicensed_client.get("/api/billing", params={"status": "closed"})

        assert response.status_code in (401, 403)
        # Limited Mode 403s before auth even runs, so an anonymous unlicensed
        # client never reaches the feature gate at all.
        if response.status_code == 403:
            assert response.json()["error"]["code"] == "LICENSE_INVALID"
