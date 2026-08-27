"""``arichds_vendor.py sign --models``/``--brands`` — issue 015, D8.

Same shape as ``test_vendor_sign_features.py``: the vendor CLI is the one
place a model or brand name is typed by a human, once per sale, with no
reviewer and no test between it and a customer. Where the harm lives is
``tools/``, not ``app/`` — the product-side gate (``devices.py``'s
``_require_licensed_model``) refuses correctly no matter what the licence
says; what a misspelled ``--models`` argument breaks is the licence itself,
silently, days before anyone notices the customer bought the wrong thing.

Drives the real ``tools/arichds_vendor.py`` through the ``vendor_cli``
fixture, exactly as ``test_vendor_sign_features.py`` does. Every rejection
asserts stdout is empty as well as the exit code.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import (
    Encoding,
    NoEncryption,
    PrivateFormat,
)

from arichds.acquisition.catalog import CATALOG
from arichds.licensing import activation_code as ac

TEST_MACHINE_ID = "c" * 64

#: The CLI's own source, for the "never restate a catalog name" guard below.
VENDOR_CLI_PATH = Path(__file__).resolve().parents[2] / "tools" / "arichds_vendor.py"

CEWE_MODELS = sorted(model for model, spec in CATALOG.items() if spec.brand.value == "cewe")


@pytest.fixture
def key_path(tmp_path: Path) -> Path:
    """A throwaway Ed25519 private key in ``tmp_path`` — see ``test_vendor_sign_features.py``."""
    private_key = Ed25519PrivateKey.generate()
    path = tmp_path / "vendor_private.pem"
    path.write_bytes(private_key.private_bytes(Encoding.PEM, PrivateFormat.PKCS8, NoEncryption()))
    return path


def sign(vendor_cli, key_path: Path, *extra_args: str) -> int:
    """Run ``sign`` with *extra_args* appended (e.g. ``--models``, ``--brands``)."""
    argv = ["sign", "--customer", "Acme Co", "--machine-id", TEST_MACHINE_ID, "--private-key", str(key_path)]
    argv.extend(extra_args)
    return vendor_cli.main(argv)


def payload_of(code: str) -> dict[str, Any]:
    """Decode the payload half of a signed Activation Code."""
    return json.loads(ac._b64url_decode(code.split(".")[0]))


class TestWhereTheCatalogLives:
    """Issue 010's rule, applied to the model list: ``tools/`` imports it and
    never restates it, so a tenth model needs no edit here."""

    def test_model_catalog_is_the_apps_own_object_not_a_copy(self, vendor_cli) -> None:
        """Identity, not equality — as ``sellable_feature_keys()`` proves for features."""
        assert vendor_cli.model_catalog() is CATALOG

    def test_the_cli_never_restates_a_model_key_or_brand_name(self) -> None:
        """A literal in ``tools/`` is a second copy someone must remember to
        update — exactly what issue 010 removed for the sellable feature list."""
        source = VENDOR_CLI_PATH.read_text(encoding="utf-8")
        for model in sorted(CATALOG):
            assert model not in source, f"{VENDOR_CLI_PATH.name} hand-copies the model key {model!r}"
        for brand in sorted({spec.brand.value for spec in CATALOG.values()}):
            assert brand not in source, f"{VENDOR_CLI_PATH.name} hand-copies the brand name {brand!r}"


class TestGrandfatheringPathIsUntouched:
    """``models: null`` means "every catalogued model" — omitting both flags."""

    def test_omitting_both_flags_signs_a_null_models_payload(self, vendor_cli, key_path: Path, capsys) -> None:
        exit_code = sign(vendor_cli, key_path)

        code = capsys.readouterr().out.strip()
        assert exit_code == 0
        assert payload_of(code)["models"] is None


class TestEmptyStringIsAHardError:
    """``--models ""``/``--brands ""`` must be refused, never read as "all"
    (D2/D13) — exactly the ``--features ""`` trap issue 014 records, which
    this issue must reproduce the fix for without touching 014 itself."""

    def test_an_empty_models_string_is_refused_and_nothing_is_signed(self, vendor_cli, key_path: Path, capsys) -> None:
        exit_code = sign(vendor_cli, key_path, "--models", "")

        captured = capsys.readouterr()
        assert exit_code == 1
        assert captured.out == ""

    def test_an_empty_brands_string_is_refused_and_nothing_is_signed(self, vendor_cli, key_path: Path, capsys) -> None:
        exit_code = sign(vendor_cli, key_path, "--brands", "")

        captured = capsys.readouterr()
        assert exit_code == 1
        assert captured.out == ""


class TestUnrecognisedNameIsRefused:
    def test_an_unknown_model_is_refused_before_signing(self, vendor_cli, key_path: Path, capsys) -> None:
        exit_code = sign(vendor_cli, key_path, "--models", "prometer100,not-a-model")

        captured = capsys.readouterr()
        assert exit_code == 1
        assert captured.out == ""
        assert "not-a-model" in captured.err

    def test_an_unknown_brand_is_refused_before_signing(self, vendor_cli, key_path: Path, capsys) -> None:
        exit_code = sign(vendor_cli, key_path, "--brands", "cewe,not-a-brand")

        captured = capsys.readouterr()
        assert exit_code == 1
        assert captured.out == ""
        assert "not-a-brand" in captured.err


class TestAcceptedModels:
    def test_a_single_model_signs(self, vendor_cli, key_path: Path, capsys) -> None:
        exit_code = sign(vendor_cli, key_path, "--models", "prometer100")

        code = capsys.readouterr().out.strip()
        assert exit_code == 0
        assert payload_of(code)["models"] == ["prometer100"]

    def test_whitespace_around_a_name_is_stripped(self, vendor_cli, key_path: Path, capsys) -> None:
        exit_code = sign(vendor_cli, key_path, "--models", "prometer100, saral305")

        code = capsys.readouterr().out.strip()
        assert exit_code == 0
        assert payload_of(code)["models"] == ["prometer100", "saral305"]

    def test_models_are_deduped_and_sorted(self, vendor_cli, key_path: Path, capsys) -> None:
        """Unlike ``--features``, deliberately (D8/G): D8 requires
        ``--brands cewe`` and the equivalent ``--models`` list to be
        byte-identical, which is only possible under a canonical order."""
        exit_code = sign(vendor_cli, key_path, "--models", "saral305,prometer100,saral305")

        code = capsys.readouterr().out.strip()
        assert exit_code == 0
        assert payload_of(code)["models"] == ["prometer100", "saral305"]


class TestBrandsExpandBeforeSigning:
    def test_a_brand_expands_to_its_catalogued_models(self, vendor_cli, key_path: Path, capsys) -> None:
        exit_code = sign(vendor_cli, key_path, "--brands", "cewe")

        code = capsys.readouterr().out.strip()
        assert exit_code == 0
        assert payload_of(code)["models"] == CEWE_MODELS

    def test_brands_and_models_are_the_union_deduped_and_sorted(self, vendor_cli, key_path: Path, capsys) -> None:
        exit_code = sign(vendor_cli, key_path, "--brands", "cewe", "--models", "smw110,prometer100")

        code = capsys.readouterr().out.strip()
        assert exit_code == 0
        assert payload_of(code)["models"] == sorted({*CEWE_MODELS, "smw110"})

    def test_naming_every_model_of_a_brand_matches_naming_the_brand_byte_for_byte(
        self, vendor_cli, key_path: Path, capsys
    ) -> None:
        """D8's own acceptance criterion, decoded and compared."""
        exit_code_a = sign(vendor_cli, key_path, "--brands", "cewe")
        code_a = capsys.readouterr().out.strip()

        exit_code_b = sign(vendor_cli, key_path, "--models", ",".join(CEWE_MODELS))
        code_b = capsys.readouterr().out.strip()

        assert exit_code_a == 0
        assert exit_code_b == 0
        payload_a = payload_of(code_a)
        payload_b = payload_of(code_b)
        # issued_at differs between the two signings; compare everything else.
        del payload_a["issued_at"]
        del payload_b["issued_at"]
        assert payload_a == payload_b


class TestStderrSummaryPrintsTheResolvedModels:
    def test_an_unrestricted_sale_says_so_in_words(self, vendor_cli, key_path: Path, capsys) -> None:
        sign(vendor_cli, key_path)

        err = capsys.readouterr().err
        assert "Models" in err
        assert "every catalogued model" in err.lower()

    def test_a_restricted_sale_prints_the_resolved_list_not_the_flags_as_typed(
        self, vendor_cli, key_path: Path, capsys
    ) -> None:
        sign(vendor_cli, key_path, "--brands", "cewe")

        err = capsys.readouterr().err
        assert "Models" in err
        for model in CEWE_MODELS:
            assert model in err


class TestModelsSummaryText:
    """``cmd_sign``'s formatting for the ``Models     :`` stderr line, exercised
    directly — ``models: []`` cannot be reached through the CLI itself (there
    is no combination of ``--models``/``--brands`` that resolves to "nothing
    licensed"; that state only exists once a code is *replaced by hand*), so
    the empty-list case is unit-tested here rather than through ``sign()``."""

    def test_none_reads_as_every_catalogued_model(self, vendor_cli) -> None:
        assert vendor_cli.models_summary_text(None) == "every catalogued model"

    def test_empty_list_reads_as_none(self, vendor_cli) -> None:
        assert vendor_cli.models_summary_text([]) == "none"

    def test_a_list_is_joined(self, vendor_cli) -> None:
        assert vendor_cli.models_summary_text(["premier550", "prometer100"]) == "premier550, prometer100"


class TestHelpText:
    def test_models_help_says_it_is_validated_against_the_catalog(self, vendor_cli, capsys) -> None:
        with pytest.raises(SystemExit):
            vendor_cli.main(["sign", "--help"])

        out = capsys.readouterr().out
        assert "--models" in out
        assert "--brands" in out
