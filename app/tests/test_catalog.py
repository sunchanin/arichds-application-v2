"""The nine-model catalog (M3-1).

Ported from v1's ``cewe-worker/src/catalog.py``, whose keys, brands, dropdown
order and fixed passwords are customer-confirmed. These tests exist to stop a
future edit from quietly disagreeing with what the operator sees on site.
"""

from __future__ import annotations

from arichds.acquisition.catalog import (
    CATALOG,
    CEWE_FIXED_PASSWORD,
    DLMS_DEFAULT_TCP_PORT,
    MITSU_SMW110_FIXED_PASSWORD,
    Brand,
    get_model_spec,
)

# Imported directly (not through `factory.supported_models()`) so this module
# sees the REAL driver registry rather than the fake one the suite's autouse
# `fake_meter` fixture installs for every other test (conftest.py) — that
# fixture patches the `factory` module's own `_registry` attribute, which a
# direct `from ... import _registry` here does not go through (M4c, issue #24,
# D22b: "the catalog endpoint marks all three CEWE models drivable").
from arichds.acquisition.drivers.factory import _registry


class TestTheThreeCeweModelsAreDrivable:
    """D22b — narrows the "created, probed and read from the UI" acceptance
    criterion to what an agent can verify without a live device: the driver
    registry (which `GET /api/devices/catalog` filters `CATALOG` against,
    `api/devices.py:760`) actually carries all three new models."""

    def test_all_three_cewe_models_are_registered(self) -> None:
        assert {"prometer100", "saral305", "premier550"} <= set(_registry())

    def test_smw110_is_still_registered(self) -> None:
        """The registry grew — it must not have lost anything on the way."""
        assert "smw110" in _registry()

    def test_every_registered_model_is_in_the_catalog(self) -> None:
        """The registry and the catalog must agree on the product's
        vocabulary — a driver for a model the catalog does not know would be
        undrivable from the UI regardless."""
        assert set(_registry()) <= set(CATALOG)


class TestCatalogShape:
    def test_nine_models(self) -> None:
        assert len(CATALOG) == 9

    def test_the_exact_key_set(self) -> None:
        assert set(CATALOG) == {
            "st3c",
            "st3cl",
            "st33tl",
            "st3tl",
            "st3dh",
            "smw110",
            "prometer100",
            "saral305",
            "premier550",
        }

    def test_dropdown_order_is_tcc_then_mitsubishi_then_cewe(self) -> None:
        """The customer's confirmed dropdown order (v1, 2026-07)."""
        assert list(CATALOG) == [
            "st3c",
            "st3cl",
            "st33tl",
            "st3tl",
            "st3dh",
            "smw110",
            "prometer100",
            "saral305",
            "premier550",
        ]

    def test_brand_per_model_matches_v1(self) -> None:
        assert {model: spec.brand for model, spec in CATALOG.items()} == {
            "st3c": Brand.SMART_TCC,
            "st3cl": Brand.SMART_TCC,
            "st33tl": Brand.SMART_TCC,
            "st3tl": Brand.SMART_TCC,
            "st3dh": Brand.SMART_TCC,
            "smw110": Brand.MITSU,
            "prometer100": Brand.CEWE,
            "saral305": Brand.CEWE,
            "premier550": Brand.CEWE,
        }

    def test_brand_values_are_v1s(self) -> None:
        assert [brand.value for brand in Brand] == ["cewe", "mitsu", "smart_tcc"]

    def test_the_dropped_v1_fields_are_gone(self) -> None:
        """``driver_status`` duplicated the registry; ``protocol`` said one thing."""
        spec = CATALOG["prometer100"]
        assert not hasattr(spec, "driver_status")
        assert not hasattr(spec, "protocol")


class TestFixedPasswords:
    def test_cewe_models_share_one_password(self) -> None:
        assert CEWE_FIXED_PASSWORD == "ABCD0001"
        for model in ("prometer100", "saral305", "premier550"):
            assert CATALOG[model].fixed_password == CEWE_FIXED_PASSWORD

    def test_smw110_has_its_own(self) -> None:
        assert MITSU_SMW110_FIXED_PASSWORD == "00000000000000000003"
        assert CATALOG["smw110"].fixed_password == MITSU_SMW110_FIXED_PASSWORD

    def test_smart_tcc_has_none(self) -> None:
        """TCC authenticates with HighGMAC keys owned by its driver, not a password."""
        for model in ("st3c", "st3cl", "st33tl", "st3tl", "st3dh"):
            assert CATALOG[model].fixed_password is None


class TestCatalogCarriesNoTransportInformation:
    """Issue #9 — a field probe of two live SMW110W4 units, one serial one TCP,
    otherwise identical, proved transport is a property of the installation,
    not of the model (docs/meter-notes/smw110w4-scan.md). This is the
    invariant that stops the binding creeping back — it replaces the old
    ``TestPorts`` class, whose ``supports_serial``/``default_port``
    assertions are now false by construction.
    """

    def test_dlms_default_tcp_port_is_a_protocol_constant_not_a_model_field(self) -> None:
        assert DLMS_DEFAULT_TCP_PORT == 4059

    def test_no_model_spec_carries_transport_information(self) -> None:
        for field_name in ("default_port", "supports_serial"):
            for model, spec in CATALOG.items():
                assert not hasattr(spec, field_name), f"{model}.{field_name} should not exist"


class TestLabelsAndCapabilities:
    def test_prometer100_label(self) -> None:
        assert CATALOG["prometer100"].ui_label == "Prometer 100"

    def test_every_model_has_a_label(self) -> None:
        assert all(spec.ui_label for spec in CATALOG.values())

    def test_every_model_reports_battery(self) -> None:
        assert all(spec.supports_battery for spec in CATALOG.values())

    def test_cewe_models_have_no_energy_summary_or_special_days(self) -> None:
        for model in ("prometer100", "saral305", "premier550"):
            assert CATALOG[model].supports_energy_summary is False
            assert CATALOG[model].supports_special_days is False

    def test_the_new_brands_have_both(self) -> None:
        for model in ("st3c", "st3cl", "st33tl", "st3tl", "st3dh", "smw110"):
            assert CATALOG[model].supports_energy_summary is True
            assert CATALOG[model].supports_special_days is True


class TestLookup:
    def test_is_case_insensitive(self) -> None:
        assert get_model_spec("PROMETER100") is CATALOG["prometer100"]

    def test_unknown_returns_none(self) -> None:
        assert get_model_spec("no-such-meter") is None

    def test_sim_is_not_in_the_catalog(self) -> None:
        """ADR 0005 — a fake meter has no place in the product's model list."""
        assert get_model_spec("sim") is None
