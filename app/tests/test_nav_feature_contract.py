"""``web/src/features.ts`` — the nav/feature contract between ``web/`` and
``app/`` (issue 012).

The left nav hides a page whose feature key is not in
``LicenseStatus.enabled_features``, and that key is written in TypeScript while
the set of real keys lives in :data:`~arichds.constants.FEATURE_KEYS`. Nothing
in either toolchain connects the two: a typo'd key (``billling``) or a key
renamed on the Python side leaves the TS compiling and the menu entry hiding
forever, on a machine whose API happily serves the page.

Same shape and the same honesty as ``test_capture_dom_contract.py``: ``web/src``
is committed, so this never skips — but **a grep can be fooled by a
commented-out line**. This is a cheap tripwire against a stale or misspelled
key, not proof the mapping is *live* in the running page. What proves the
mapping is live is ``AppShell``'s own use of it, which only a browser executes.

Two layers, and the difference matters:

* :class:`TestEveryMappedKeyIsReal` catches a key that does not exist
  (``billling``). It is **not** enough on its own — it passes happily with
  ``billing`` mapped to ``billing_excel_export``, a key that does exist, and the
  result is Billing vanishing from a customer who paid for it.
* :class:`TestEachPageIsGatedOnTheKeyItsMappingClaims` catches that: it asks
  the running app which key each page's own endpoint refuses on, and compares
  it with what ``features.ts`` claims. Only the *path* is hand-written
  (:data:`PAGE_API_PATHS`); the two keys both come from the code.

Neither layer proves the rendered menu ever *reads* the mapping. That is still
the render evidence's job.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from arichds.constants import FEATURE_KEYS

REPO_ROOT = Path(__file__).resolve().parents[2]
FEATURES_TS = REPO_ROOT / "web" / "src" / "features.ts"

#: A `{ kind: "feature", key: "…" }` arm of `PAGE_ENTITLEMENT`. The `always`
#: and `never` arms carry no key by construction and so cannot go stale.
_ENTITLEMENT_KEY = re.compile(r'\{\s*kind:\s*"feature",\s*key:\s*"([^"]+)"\s*\}')

#: One `key: "Label",` line inside the `FEATURE_LABELS` object literal.
_LABEL_KEY = re.compile(r'^\s*"?([A-Za-z_][A-Za-z0-9_]*)"?:\s*"', re.MULTILINE)

#: One `page: { kind: "…", key: "…" }` line of `PAGE_ENTITLEMENT` — page name,
#: kind, and the key when there is one (`always`/`never` carry none).
_ENTITLEMENT_LINE = re.compile(
    r'^\s*"?([a-z][a-z-]*)"?:\s*\{\s*kind:\s*"(feature|always|never)"(?:,\s*key:\s*"([^"]+)")?',
    re.MULTILINE,
)

APP_TSX = REPO_ROOT / "web" / "src" / "App.tsx"

#: The API path each feature-gated page actually calls, hand-written because
#: nothing in either tree records the association — this table *is* the claim
#: being tested. Only the path is duplicated: the key comes from `features.ts`
#: and the *expected* key comes from the server's own refusal, so a page wired
#: to a real-but-wrong key is caught, not merely a misspelled one.
PAGE_API_PATHS: dict[str, str] = {
    "load-profile": "/api/load-profile",
    "records": "/api/records",
    "billing": "/api/billing",
    "energy-summary": "/api/energy/summary",
    "holidays": "/api/holidays",
    "special-days": "/api/special-days",
    "battery": "/api/battery",
    "export-format": "/api/settings/export-format",
    "database-destination": "/api/settings/database-destination",
}

#: Feature-gated pages deliberately left out of the sweep, and why. `app_log`
#: is **ops-only and never in `SELLABLE_FEATURE_KEYS`**, so a licence with
#: `features=[]` does not refuse `/api/logs` at all — sweeping it would assert
#: something false about what that key means. Exactly the exclusion, for
#: exactly the reason, that `GATED_PREFIXES` documents in
#: `test_feature_entitlement.py`. Pinned below so it cannot quietly grow into
#: a way of dodging the sweep.
UNSWEPT_PAGES: frozenset[str] = frozenset({"app-log"})

#: Pages no licence governs — `always` or `never` — so they never reach the
#: sweep. Pinned for the same reason: flipping a page to `always` would
#: silently drop it out of every assertion below.
#:
#: `file-upload-destination` is here because it has no transport and no feature
#: key yet (D7, issue 012). Issue 013 reserves a `file_upload_destination` key
#: and revisits this row — **013's edit, not 012's**.
UNGOVERNED_PAGES: frozenset[str] = frozenset({"devices", "users", "settings", "file-upload-destination"})


def _source() -> str:
    assert FEATURES_TS.is_file(), f"{FEATURES_TS} is missing — did the module move?"
    return FEATURES_TS.read_text(encoding="utf-8")


def mapped_feature_keys() -> set[str]:
    """Every feature key the page mapping claims."""
    return set(_ENTITLEMENT_KEY.findall(_source()))


def _entitlement_body() -> str:
    """The ``PAGE_ENTITLEMENT`` object literal, without the rest of the file."""
    source = _source()
    start = source.index("PAGE_ENTITLEMENT: Record<Page, PageEntitlement> = {")
    return source[start : source.index("\n};", start)]


def page_entitlement_kinds() -> dict[str, str]:
    """Each page in ``PAGE_ENTITLEMENT`` mapped to its ``kind``."""
    return {page: kind for page, kind, _key in _ENTITLEMENT_LINE.findall(_entitlement_body())}


def page_feature_keys() -> dict[str, str]:
    """Each ``feature``-kind page mapped to the key it claims."""
    return {page: key for page, kind, key in _ENTITLEMENT_LINE.findall(_entitlement_body()) if kind == "feature"}


def labelled_feature_keys() -> set[str]:
    """Every key the License card has an English label for."""
    source = _source()
    start = source.index("FEATURE_LABELS: Record<string, string> = {")
    body = source[start : source.index("\n};", start)]
    return set(_LABEL_KEY.findall(body)) - {"FEATURE_LABELS"}


class TestTheRegexesFindSomething:
    """The tripwire's own tripwire: a regex that silently matches nothing turns
    every assertion below into a tautology over the empty set."""

    def test_the_mapping_yields_keys(self) -> None:
        assert len(mapped_feature_keys()) >= 5, mapped_feature_keys()

    def test_the_label_map_yields_keys(self) -> None:
        assert len(labelled_feature_keys()) == len(FEATURE_KEYS), labelled_feature_keys()

    def test_the_entitlement_line_regex_finds_every_page(self) -> None:
        """`PAGE_ENTITLEMENT` is `Record<Page, …>`, so its size is the page
        count — a regex that skipped the quoted (hyphenated) keys would make
        `TestThePagesALicenceMayNeverHide` assert over a half-empty dict."""
        kinds = page_entitlement_kinds()

        assert len(kinds) == 14, kinds
        assert set(kinds.values()) == {"feature", "always", "never"}, kinds


class TestEveryMappedKeyIsReal:
    def test_no_page_is_gated_on_a_key_the_backend_does_not_have(self) -> None:
        """A key here that `FEATURE_KEYS` lacks can never be in
        `enabled_features`, so that page's entry would be hidden on every
        machine ever licensed — silently, with the page itself still served."""
        unknown = sorted(mapped_feature_keys() - FEATURE_KEYS)

        assert unknown == [], f"{FEATURES_TS.name} maps a page to unknown feature key(s): {unknown}"


class TestEveryKeyHasALabel:
    def test_every_backend_key_is_labelled(self) -> None:
        """The License card renders `enabled_features` verbatim when a label is
        missing, so a new key would show as `billing_excel_export` to a
        customer. D12: all of `FEATURE_KEYS`, `app_log` included."""
        missing = sorted(FEATURE_KEYS - labelled_feature_keys())

        assert missing == [], f"{FEATURES_TS.name} has no FEATURE_LABELS entry for: {missing}"

    def test_no_label_names_a_key_that_no_longer_exists(self) -> None:
        """The other direction — a key removed from `FEATURE_KEYS` leaves a
        label behind that nothing will ever render."""
        stale = sorted(labelled_feature_keys() - FEATURE_KEYS)

        assert stale == [], f"{FEATURES_TS.name} labels feature key(s) the backend does not have: {stale}"


class TestThePageListMatchesTheMapping:
    """`Record<Page, PageEntitlement>` already makes a missing entry a `tsc`
    error, which is the real guard. This only checks the two lists that `tsc`
    cannot compare — the `Page` union and the `PAGES` array literal beneath
    it — because `toPage` reads the array while everything else reads the
    type, and a page missing from the array silently becomes Devices."""

    def test_every_page_in_the_union_is_in_the_pages_array(self) -> None:
        source = _source()
        union = source[source.index("export type Page =") : source.index("export const PAGES")]
        array = source[source.index("export const PAGES") : source.index("/** Read a menu key as a page")]

        union_pages = set(re.findall(r'"([a-z-]+)"', union))
        array_pages = set(re.findall(r'"([a-z-]+)"', array))

        assert union_pages, "the Page union regex matched nothing"
        assert union_pages == array_pages, {
            "in the union only": sorted(union_pages - array_pages),
            "in PAGES only": sorted(array_pages - union_pages),
        }


class TestThePagesALicenceMayNeverHide:
    """Issue 012's own list of what this change must not take away.

    A licence problem is exactly when the customer needs Settings — it holds
    the License card that says what they have and takes a replacement code
    (D9). Devices is never feature-gated at all (decision 7, issue #22), and
    User Management is role-gated. Gating any of the three on a feature key
    would lock a customer out of the page that fixes their lockout.
    """

    @pytest.mark.parametrize("page", ["settings", "devices", "users"])
    def test_it_is_marked_always(self, page: str) -> None:
        assert page_entitlement_kinds().get(page) == "always", page_entitlement_kinds()

    def test_file_upload_is_marked_never_rather_than_gated_on_a_key(self) -> None:
        """D7 — it has no transport and no feature key (ADR 0016, issue #37),
        so it is *unadvertised*, which is a different thing from *unlicensed*:
        `never` keeps the page rendering normally when reached."""
        assert page_entitlement_kinds().get("file-upload-destination") == "never"


class TestThePageToApiTableIsNotStale:
    """`PAGE_API_PATHS` is hand-written, so it is the part of the sweep below
    that can rot silently. Both directions are pinned: no feature-gated page
    may go unswept without being named in `UNSWEPT_PAGES`, and no path may
    404."""

    def test_every_feature_gated_page_is_swept_or_excluded_on_purpose(self) -> None:
        unswept = set(page_feature_keys()) - set(PAGE_API_PATHS)

        assert unswept == set(UNSWEPT_PAGES), (
            f"feature-gated page(s) missing from PAGE_API_PATHS and not named in UNSWEPT_PAGES: "
            f"{sorted(unswept - UNSWEPT_PAGES)}"
        )

    def test_the_pages_no_licence_governs_are_exactly_the_expected_four(self) -> None:
        """Otherwise flipping a page to `always` would remove it from the
        sweep without failing anything — the quiet way to dodge this test."""
        ungoverned = {page for page, kind in page_entitlement_kinds().items() if kind != "feature"}

        assert ungoverned == set(UNGOVERNED_PAGES)

    @pytest.mark.parametrize("page", sorted(PAGE_API_PATHS))
    def test_the_path_exists(self, page: str, admin_client: TestClient) -> None:
        """A renamed or typo'd route would make the sweep assert nothing —
        it would collect a 404 rather than a 403 and the failure would read
        like a gating bug. Same guard as
        `test_feature_entitlement.py::TestTheGatedPrefixTableIsNotStale`.

        `!= 404` rather than `== 200`: several of these routes require query
        parameters and answer 422, which is a live route.
        """
        response = admin_client.get(PAGE_API_PATHS[page])

        assert response.status_code != 404, (page, PAGE_API_PATHS[page], response.text)


class TestEachPageIsGatedOnTheKeyItsMappingClaims:
    """The key a page maps to must be the key its own API refuses on.

    `TestEveryMappedKeyIsReal` only proves a key *exists*: it passes happily
    with `billing` mapped to `billing_excel_export`, and the consequence is the
    failure issue 012 names as the one that will be got wrong — Billing
    vanishing from a customer who paid for it, on the very licence shape the
    owner issued for testing. The server names its own key in the refusal
    (`api/deps.py`'s `FeatureDisabledError`), so nothing is duplicated here
    except the path.

    This still does **not** prove the mapping is *reached* by the rendered
    menu — that remains the render evidence's job, as the module docstring
    says. It proves the mapping is *right*, given that it is read.
    """

    def test_the_server_refuses_with_the_key_the_mapping_names(self, admin_client: TestClient, relicense) -> None:
        relicense(admin_client, features=[])
        claimed = page_feature_keys()

        mismatches: list[tuple[str, str, int, str | None, str]] = []
        for page, path in PAGE_API_PATHS.items():
            response = admin_client.get(path)
            # `or {}` rather than a default: a success envelope carries
            # `error: null`, so an unexpected 200 here must produce a readable
            # mismatch row, not an AttributeError on None.
            reason = (response.json().get("error") or {}).get("reason")
            if response.status_code != 403 or reason != claimed[page]:
                mismatches.append((page, path, response.status_code, reason, claimed[page]))

        assert mismatches == [], "page → (path, status, server's key, features.ts's key)"

    @pytest.mark.parametrize("page", sorted(PAGE_API_PATHS))
    def test_a_licence_granting_only_that_key_is_not_refused(
        self, page: str, admin_client: TestClient, relicense
    ) -> None:
        """The other direction — otherwise a mapping pointing every page at a
        key nothing grants would pass the sweep above by never being right for
        the wrong reason.

        Asserts "not a FEATURE_DISABLED refusal" rather than `== 200`: a route
        missing a required query parameter answers 422, and the router-level
        feature dependency runs before FastAPI's own parameter validation
        anyway, so 422 already proves the gate let it through.
        """
        key = page_feature_keys()[page]
        relicense(admin_client, features=[key])

        response = admin_client.get(PAGE_API_PATHS[page])
        error = response.json().get("error") or {}

        assert not (response.status_code == 403 and error.get("code") == "FEATURE_DISABLED"), (
            f"{page} maps to {key!r}, but a licence granting exactly that key still refuses "
            f"{PAGE_API_PATHS[page]}: {response.text}"
        )


class TestTheNotEnabledFallbackReadsTheFeatureKey:
    """`App.tsx` must decide its "not enabled" message with `pageFeatureKey`,
    which answers `null` for both `always` and `never` — **not** with
    `isPageAdvertised`, which answers `false` for `never` too and would show
    the licence message on File Upload, a page no licence has any say over
    (D7/D10).

    `web/` has no test runner, so this is a grep and carries that file's
    limitation: it proves the call is written, not that it is reached.
    """

    def test_app_tsx_calls_page_feature_key(self) -> None:
        assert "pageFeatureKey(" in APP_TSX.read_text(encoding="utf-8")

    def test_app_tsx_does_not_gate_its_page_render_on_is_page_advertised(self) -> None:
        assert "isPageAdvertised" not in APP_TSX.read_text(encoding="utf-8")


@pytest.mark.parametrize("key", sorted(FEATURE_KEYS))
def test_each_backend_feature_key_is_labelled(key: str) -> None:
    """The same assertion as above, one test per key, so a failure names the
    key in its own test id rather than in a list."""
    assert key in labelled_feature_keys()
