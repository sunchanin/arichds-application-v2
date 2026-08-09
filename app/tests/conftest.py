"""Shared test fixtures.

Every test gets its own data directory and its own SQLite file, so nothing
touches the developer's real ``./data`` and tests never see each other's rows.

The client fixtures form a ladder, each step adding one thing:

``unlicensed_client``
    A running app with no license and no users — a genuinely fresh machine.
``activated_client`` / ``anon_client``
    Setup has run and the machine is activated, but the client sends no
    ``Authorization`` header.
``admin_client`` / ``user_client``
    The same running app, seen through a client that carries a token for an
    ``admin`` or a ``user``.
"""

from __future__ import annotations

import sys
from collections.abc import Callable, Iterator
from pathlib import Path

import bcrypt
import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import (
    Encoding,
    NoEncryption,
    PrivateFormat,
    PublicFormat,
)
from fakes import FakeMeterDriver, FakeMeterState, FakeSmw110Driver, fake_meter_state, reset_fake_meter
from fastapi.testclient import TestClient

from arichds.auth import security
from arichds.auth.roles import Role
from arichds.config import Settings, get_settings
from arichds.db import session as db_session
from arichds.db.migrate import upgrade_to_head

REPO_ROOT = Path(__file__).resolve().parents[2]
TOOLS_DIR = REPO_ROOT / "tools"

#: Machine ID the licensing service is patched to report in tests.
TEST_MACHINE_ID = "e" * 64

#: The bootstrap admin every activated-app fixture creates through Setup.
ADMIN_CREDENTIALS = {"username": "admin", "password": "admin-password"}

#: A second, non-admin account, created by the admin through ``POST /api/users``.
USER_CREDENTIALS = {"username": "operator", "password": "operator-password"}


@pytest.fixture(scope="session", autouse=True)
def cheap_password_hashing() -> Iterator[None]:
    """Drop bcrypt's cost factor to its minimum for the test session only.

    Production hashes at bcrypt's default 12 rounds, and that slowness is the
    point: it is the login path's brake, and :mod:`arichds.auth.service` spends
    one verification against ``DUMMY_PASSWORD_HASH`` even for an unknown
    username so the cost does not leak whether an account exists (v1
    INV-AUTH-02/03). None of that is being changed here — this fixture is
    confined to the test session.

    It is worth doing because the auth fixtures are function-scoped: on this
    machine one hash or one verification is 0.187 s, every ``admin_client``
    test pays three of them and every ``user_client`` test pays five, which is
    ~93 s per suite run spent proving nothing. No test asserts the cost factor,
    and bcrypt's own key stretching is not ours to re-test.

    Four rounds is bcrypt's documented minimum and ~232x faster. Only the cost
    changes — same call, same salt handling, same ``$2b$`` format — so nothing
    a test can observe differs. ``DUMMY_PASSWORD_HASH`` is recomputed because
    it is a module constant baked at import time, before any fixture runs.
    """
    real_gensalt = bcrypt.gensalt
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(bcrypt, "gensalt", lambda rounds=4, prefix=b"2b": real_gensalt(rounds, prefix))
        mp.setattr(security, "DUMMY_PASSWORD_HASH", security.hash_password("arichds-dummy-password"))
        yield


@pytest.fixture(autouse=True)
def fake_meter(monkeypatch: pytest.MonkeyPatch) -> Iterator[FakeMeterState]:
    """Install the test-only fake meter as the ``prometer100`` AND ``smw110``
    drivers (M3-1; ``smw110`` added by issue #9).

    ADR 0005 took the simulated driver out of the product, and the test suite
    must never touch a real meter — so the driver registry is monkeypatched
    instead. ``factory._registry`` being a plain function that returns a fresh
    dict is exactly what makes one ``setattr`` enough, including for
    ``supported_models()``; that is why the factory has no registration API and
    must not grow one.

    Registered under the **real** model strings so the catalog endpoint, the
    registry and the API tests all agree on the product's vocabulary — one
    class each (:class:`FakeMeterDriver` / :class:`FakeSmw110Driver`) so
    ``model_name`` stays truthful for whichever key resolved to it.

    **Autouse on purpose.** A test that creates a device without asking for this
    fixture would fall through to the real driver and open a TCP socket or a
    COM port to whatever its payload happens to name. Nothing in the suite
    wants that, and the failure mode is silent, so the safe default is applied
    everywhere rather than remembered per test.

    Yields:
        The knob-set the fake reads — set ``connect_error``, ``meter_serial``,
        ``hold_read`` and friends on it to steer the meter's behaviour.
    """
    reset_fake_meter()
    monkeypatch.setattr(
        "arichds.acquisition.drivers.factory._registry",
        lambda: {"prometer100": FakeMeterDriver, "smw110": FakeSmw110Driver},
    )
    yield fake_meter_state()
    reset_fake_meter()


@pytest.fixture
def data_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    """Point ``ARICHDS_DATA_DIR`` at a temporary directory for one test."""
    target = tmp_path / "data"
    monkeypatch.setenv("ARICHDS_DATA_DIR", str(target))
    # Settings are cached for the life of the process; drop the cache so the
    # patched environment is actually read.
    get_settings.cache_clear()
    settings = get_settings()
    settings.ensure_directories()
    yield target
    get_settings.cache_clear()


@pytest.fixture
def settings(data_dir: Path) -> Settings:
    """The Settings object for the temporary data directory."""
    return get_settings()


@pytest.fixture
def migrated_db(settings: Settings) -> Iterator[Settings]:
    """A migrated, empty database at the temporary location."""
    upgrade_to_head(settings.db_url)
    db_session.init_engine()
    yield settings
    db_session.dispose_engine()


@pytest.fixture
def vendor_cli():
    """Import ``tools/arichds_vendor.py`` — the real issuer, not a stand-in.

    Testing against the actual CLI is the point: the canonical-payload rule is
    duplicated on both sides on purpose, and this is what catches them drifting.
    """
    if str(TOOLS_DIR) not in sys.path:
        sys.path.insert(0, str(TOOLS_DIR))
    import arichds_vendor

    return arichds_vendor


# ─── Client fixtures ──────────────────────────────────────────────────────────


@pytest.fixture
def unlicensed_client(migrated_db: Settings, monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    """A running app on a genuinely fresh machine: no users, no license.

    The Poller's master switch is off because these tests are about the HTTP
    surface — background workers writing rows underneath them would make every
    assertion about counts race the clock.
    """
    monkeypatch.setenv("ARICHDS_POLL_ENABLED", "false")
    get_settings.cache_clear()
    monkeypatch.setattr("arichds.licensing.service.machine_id", lambda: TEST_MACHINE_ID)

    from arichds.main import create_app

    with TestClient(create_app()) as client:
        yield client


@pytest.fixture
def sign_activation_code(monkeypatch: pytest.MonkeyPatch, vendor_cli) -> Callable[..., str]:
    """Issue Activation Codes for :data:`TEST_MACHINE_ID`, signed with one throwaway key.

    A factory rather than a single code so a test can re-license the running
    machine — which is the only honest way to prove ADR 0001's "applies live":
    a second, different license goes through the real activation endpoint and
    the next request must see it.
    """
    from arichds.licensing import activation_code as ac

    private_key = Ed25519PrivateKey.generate()
    private_pem = private_key.private_bytes(Encoding.PEM, PrivateFormat.PKCS8, NoEncryption())
    public_pem = private_key.public_key().public_bytes(Encoding.PEM, PublicFormat.SubjectPublicKeyInfo)
    monkeypatch.setattr(ac, "load_public_key_pem", lambda: public_pem)

    def issue(*, max_meters: int | None = None, features: list[str] | None = None) -> str:
        payload = vendor_cli.build_payload(
            customer="Acme Co", machine_id=TEST_MACHINE_ID, max_meters=max_meters, features=features
        )
        return vendor_cli.sign_payload(private_pem, payload)

    return issue


@pytest.fixture
def activation_code(sign_activation_code: Callable[..., str]) -> str:
    """A valid, unlimited Activation Code for :data:`TEST_MACHINE_ID`."""
    return sign_activation_code()


@pytest.fixture
def relicense(sign_activation_code: Callable[..., str]) -> Callable[..., None]:
    """Activate a fresh license on a running app, e.g. to change ``max_meters``
    or ``features`` (M6b, issue #22)."""

    def apply(client: TestClient, *, max_meters: int | None = None, features: list[str] | None = None) -> None:
        response = client.post(
            "/api/license/activate",
            json={"code": sign_activation_code(max_meters=max_meters, features=features)},
        )
        assert response.status_code == 200, response.text
        assert response.json()["success"] is True, response.text

    return apply


@pytest.fixture
def activated_client(unlicensed_client: TestClient, activation_code: str) -> TestClient:
    """A running, activated app — with **no** ``Authorization`` header.

    The fixture walks the real first-run flow (Setup → Login → Activation)
    because it has to: activation is admin-only from M2-1 on, so there is no
    way to license a machine before an admin exists.
    """
    assert unlicensed_client.post("/api/auth/setup", json=ADMIN_CREDENTIALS).status_code == 201
    token = login_token(unlicensed_client, ADMIN_CREDENTIALS)

    response = unlicensed_client.post(
        "/api/license/activate",
        json={"code": activation_code},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.json()["success"] is True
    return unlicensed_client


@pytest.fixture
def anon_client(activated_client: TestClient) -> TestClient:
    """An activated app seen by a caller with no token at all."""
    return activated_client


@pytest.fixture
def admin_client(activated_client: TestClient) -> TestClient:
    """The activated app, as the bootstrap admin."""
    return bearer_client(activated_client, login_token(activated_client, ADMIN_CREDENTIALS))


@pytest.fixture
def user_client(admin_client: TestClient, activated_client: TestClient) -> TestClient:
    """The activated app, as a plain ``user``.

    The account is created the way the product creates one — the admin posting
    to ``/api/users`` (M2-2). There is one path to a new account, and this
    fixture exercises it rather than reaching past it into a Session.
    """
    response = admin_client.post("/api/users", json={**USER_CREDENTIALS, "role": Role.USER.value})
    assert response.status_code == 201, response.text

    return bearer_client(activated_client, login_token(activated_client, USER_CREDENTIALS))


def login_token(client: TestClient, credentials: dict[str, str]) -> str:
    """Log in through the real endpoint and return the raw Access Token."""
    response = client.post("/api/auth/login", json=credentials)
    assert response.status_code == 200, response.text
    return response.json()["data"]["access_token"]


def bearer_client(client: TestClient, token: str) -> TestClient:
    """A second client over the *same running app*, carrying *token*.

    A separate TestClient rather than mutating ``client.headers`` so a test can
    hold an admin, a user and an anonymous view of one app at the same time.
    It is deliberately not entered as a context manager: the app's lifespan has
    already run under the base fixture, and running it twice would migrate and
    re-evaluate the license a second time.
    """
    return TestClient(client.app, headers={"Authorization": f"Bearer {token}"})
