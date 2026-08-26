"""``arichds_vendor.py sign --features`` refuses a name that is not sellable.

Local issue 010: the vendor CLI is the one place a feature key is typed by a
human, once per sale, with no reviewer and no test between it and a customer.
A misspelling used to be signed into a perfectly valid Activation Code, and the
failure surfaced days later as "we bought that, why is it not there".

Drives the real ``tools/arichds_vendor.py`` through the ``vendor_cli`` fixture,
the ``test_meter_activation_code.py::TestSignMeterCli`` pattern. Every rejection
asserts stdout is empty as well as the exit code: the Activation Code is the
only thing this command ever puts on stdout, so an empty stdout is what proves
nothing was signed.
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

from arichds.constants import RESERVED_FEATURE_KEYS, SELLABLE_FEATURE_KEYS
from arichds.licensing import activation_code as ac

TEST_MACHINE_ID = "c" * 64

#: The CLI's own source, for the "never restate the list" guard below.
VENDOR_CLI_PATH = Path(__file__).resolve().parents[2] / "tools" / "arichds_vendor.py"


@pytest.fixture
def key_path(tmp_path: Path) -> Path:
    """A throwaway Ed25519 private key in ``tmp_path``.

    Never the real ``tools/.arichds_private_key.pem``: these tests only need a
    signature to exist, not one anybody trusts.
    """
    private_key = Ed25519PrivateKey.generate()
    path = tmp_path / "vendor_private.pem"
    path.write_bytes(private_key.private_bytes(Encoding.PEM, PrivateFormat.PKCS8, NoEncryption()))
    return path


def sign(vendor_cli, key_path: Path, *features: str) -> int:
    """Run ``sign`` with (or, given no ``features``, without) ``--features``."""
    argv = ["sign", "--customer", "Acme Co", "--machine-id", TEST_MACHINE_ID, "--private-key", str(key_path)]
    argv.extend(features)
    return vendor_cli.main(argv)


def payload_of(code: str) -> dict[str, Any]:
    """Decode the payload half of a signed Activation Code.

    Uses the app's own base64url helper, as ``test_license_roundtrip.py`` does,
    rather than a second hand-rolled decoder.
    """
    return json.loads(ac._b64url_decode(code.split(".")[0]))


class TestUnrecognisedFeatureName:
    def test_unknown_name_is_refused_and_nothing_is_signed(self, vendor_cli, key_path: Path, capsys) -> None:
        exit_code = sign(vendor_cli, key_path, "--features", "load_profile,databse_destination")

        captured = capsys.readouterr()
        assert exit_code == 1
        assert captured.out == ""
        assert "unrecognised feature name" in captured.err
        assert "databse_destination" in captured.err
        assert ", ".join(sorted(SELLABLE_FEATURE_KEYS)) in captured.err


class TestAppLogIsOpsOnly:
    def test_app_log_alone_is_refused_as_not_sellable(self, vendor_cli, key_path: Path, capsys) -> None:
        exit_code = sign(vendor_cli, key_path, "--features", "app_log")

        captured = capsys.readouterr()
        assert exit_code == 1
        assert captured.out == ""
        assert "app_log" in captured.err
        assert "ops-only" in captured.err
        assert "not sellable" in captured.err
        # Reported as ops-only *instead of* unknown, never as well as it.
        assert "unrecognised feature name" not in captured.err


class TestEmptyEntry:
    """An empty entry is refused, never silently dropped.

    Silently cleaning up ``"billing,,records"`` would be the same failure this
    issue is about, one size smaller: the tool reporting success while signing
    something other than what was typed.
    """

    @pytest.mark.parametrize("raw", ["billing,,records", "billing,records,", "   ", ","])
    def test_empty_entry_is_refused_and_nothing_is_signed(self, vendor_cli, key_path: Path, capsys, raw: str) -> None:
        exit_code = sign(vendor_cli, key_path, "--features", raw)

        captured = capsys.readouterr()
        assert exit_code == 1
        assert captured.out == ""
        assert "empty feature name" in captured.err
        # A blank name must never be reported as an unrecognised one.
        assert "unrecognised feature name" not in captured.err


class TestAcceptedLists:
    def test_whitespace_around_a_name_is_stripped_and_the_name_accepted(
        self, vendor_cli, key_path: Path, capsys
    ) -> None:
        exit_code = sign(vendor_cli, key_path, "--features", "billing, records")

        code = capsys.readouterr().out.strip()
        assert exit_code == 0
        assert payload_of(code)["features"] == ["billing", "records"]

    def test_every_sellable_key_at_once_signs(self, vendor_cli, key_path: Path, capsys) -> None:
        names = sorted(SELLABLE_FEATURE_KEYS)

        exit_code = sign(vendor_cli, key_path, "--features", ",".join(names))

        code = capsys.readouterr().out.strip()
        assert exit_code == 0
        assert payload_of(code)["features"] == names

    def test_a_repeated_name_is_neither_deduped_nor_sorted(self, vendor_cli, key_path: Path, capsys) -> None:
        """The payload is a signed wire format; re-shaping what was typed is not this tool's job."""
        exit_code = sign(vendor_cli, key_path, "--features", "records,billing,billing")

        code = capsys.readouterr().out.strip()
        assert exit_code == 0
        assert payload_of(code)["features"] == ["records", "billing", "billing"]


class TestHelpText:
    def test_features_help_says_the_names_are_validated(self, vendor_cli, capsys) -> None:
        """The one line a human reads before typing the thing that broke."""
        with pytest.raises(SystemExit):
            vendor_cli.main(["sign", "--help"])

        assert "sellable" in capsys.readouterr().out


class TestGrandfatheringPathIsUntouched:
    """``features: None`` means "every sellable key"; ``[]`` means "nothing sold".

    ``licensing/features.py:47`` reads them as opposites, so normalising either
    of these to ``[]`` would silently sell nothing on every license issued
    without the flag.
    """

    def test_omitting_features_signs_a_null_features_payload(self, vendor_cli, key_path: Path, capsys) -> None:
        exit_code = sign(vendor_cli, key_path)

        code = capsys.readouterr().out.strip()
        assert exit_code == 0
        assert payload_of(code)["features"] is None

    def test_an_empty_features_string_signs_a_null_features_payload(self, vendor_cli, key_path: Path, capsys) -> None:
        exit_code = sign(vendor_cli, key_path, "--features", "")

        code = capsys.readouterr().out.strip()
        assert exit_code == 0
        assert payload_of(code)["features"] is None


class TestEveryProblemIsReportedInOnePass:
    def test_two_unknown_names_are_both_named(self, vendor_cli, key_path: Path, capsys) -> None:
        exit_code = sign(vendor_cli, key_path, "--features", "databse_destination,batery")

        captured = capsys.readouterr()
        assert exit_code == 1
        assert captured.out == ""
        assert "databse_destination" in captured.err
        assert "batery" in captured.err

    def test_app_log_mixed_with_a_valid_key_is_still_refused_as_ops_only(
        self, vendor_cli, key_path: Path, capsys
    ) -> None:
        exit_code = sign(vendor_cli, key_path, "--features", "billing,app_log")

        captured = capsys.readouterr()
        assert exit_code == 1
        assert captured.out == ""
        assert "ops-only" in captured.err
        assert "not sellable" in captured.err
        # Reported as ops-only *instead of* unknown, never as well as it.
        assert "unrecognised feature name" not in captured.err

    def test_the_valid_key_list_is_printed_in_sorted_order(self, vendor_cli, key_path: Path, capsys) -> None:
        """A frozenset has no order, and an unstable error message is not a message."""
        sign(vendor_cli, key_path, "--features", "nope")

        assert ", ".join(sorted(SELLABLE_FEATURE_KEYS)) in capsys.readouterr().err


class TestCaseSensitivity:
    def test_a_capitalised_name_is_refused(self, vendor_cli, key_path: Path, capsys) -> None:
        """The keys are lowercase identifiers, and the error lists them, so the fix is obvious."""
        exit_code = sign(vendor_cli, key_path, "--features", "Billing")

        captured = capsys.readouterr()
        assert exit_code == 1
        assert captured.out == ""
        assert "Billing" in captured.err


class TestAReservedKeyIsSignableButAnnounced:
    """A reserved key signs, and says so — issue 013, fix round.

    `file_upload_destination` **must stay signable** (criterion 3): a refusal
    here would break the thing the reservation is for, which is that a licence
    signed today can already carry it. But nothing implements it, and this CLI
    is the only path by which a customer can come to own it. The product side
    of *"a customer who bought this key would be buying a form that discards
    what they type"* has five guards; without this the purchase side had none,
    and the CLI presented the key as an ordinary thing to sell.

    So: warn, never refuse, and warn at the moment the name is typed rather
    than in a source comment the person making the sale does not open.
    """

    def test_a_reserved_key_still_signs_and_reaches_the_payload(self, vendor_cli, key_path: Path, capsys) -> None:
        exit_code = sign(vendor_cli, key_path, "--features", "file_upload_destination")

        captured = capsys.readouterr()
        assert exit_code == 0
        assert payload_of(captured.out.strip())["features"] == ["file_upload_destination"]

    def test_naming_a_reserved_key_warns_on_stderr(self, vendor_cli, key_path: Path, capsys) -> None:
        """stderr, so the Activation Code on stdout still pipes cleanly."""
        sign(vendor_cli, key_path, "--features", "file_upload_destination")

        captured = capsys.readouterr()
        assert "WARNING" in captured.err
        assert "file_upload_destination" in captured.err
        assert "reserved" in captured.err.lower()
        assert "invoice" in captured.err.lower()
        # The warning must not contaminate the one line the customer pastes.
        assert "WARNING" not in captured.out

    def test_selling_only_implemented_keys_is_not_warned_about(self, vendor_cli, key_path: Path, capsys) -> None:
        """Otherwise the warning is noise on every sale, and the next person
        learns to ignore it — which is the failure mode, not the guard."""
        exit_code = sign(vendor_cli, key_path, "--features", "billing,records")

        assert exit_code == 0
        assert "reserved" not in capsys.readouterr().err.lower()

    def test_the_valid_name_list_marks_which_key_is_reserved(self, vendor_cli, key_path: Path, capsys) -> None:
        """The refusal path prints every sellable name as a menu to choose
        from. A reader choosing off that menu must be able to see which entry
        is not actually for sale."""
        sign(vendor_cli, key_path, "--features", "nope")

        captured = capsys.readouterr()
        assert "file_upload_destination" in captured.err
        assert "reserved" in captured.err.lower()

    def test_the_features_help_mentions_the_reserved_set(self, vendor_cli, capsys) -> None:
        """`--help` is read before the name is typed, the error only after."""
        with pytest.raises(SystemExit):
            vendor_cli.main(["sign", "--help"])

        assert "reserved" in capsys.readouterr().out.lower()


class TestWhereTheReservedSetLives:
    """Issue 010's rule, applied to the second set: `tools/` imports it and
    never restates it, so un-reserving the key at M8 is one edit, not two."""

    def test_the_reserved_set_is_the_apps_own_object_not_a_copy(self, vendor_cli) -> None:
        """Identity, not equality — as for the sellable set above."""
        assert vendor_cli.reserved_feature_keys() is RESERVED_FEATURE_KEYS

    def test_every_reserved_key_is_also_sellable(self) -> None:
        """A reserved key outside the sellable set could never be signed at
        all, so the warning would guard a path that does not exist and would
        rot unnoticed."""
        assert RESERVED_FEATURE_KEYS <= SELLABLE_FEATURE_KEYS, sorted(RESERVED_FEATURE_KEYS - SELLABLE_FEATURE_KEYS)

    def test_the_cli_never_restates_a_reserved_key_name(self) -> None:
        """A literal in `tools/` is a second copy someone must remember to
        delete at M8 — exactly what issue 010 removed for the sellable list."""
        source = VENDOR_CLI_PATH.read_text(encoding="utf-8")

        for key in sorted(RESERVED_FEATURE_KEYS):
            assert key not in source, f"{VENDOR_CLI_PATH.name} hand-copies the reserved key {key!r}"


class TestWhereTheCheckLives:
    def test_the_valid_set_is_the_apps_own_object_not_a_copy(self, vendor_cli) -> None:
        """Identity, not equality: a hand-copied literal would be equal but not identical."""
        assert vendor_cli.sellable_feature_keys() is SELLABLE_FEATURE_KEYS

    def test_build_payload_does_not_validate(self, vendor_cli) -> None:
        """The check belongs to the CLI, not the payload builder.

        ``build_payload`` is duplicated verbatim from the app's own function and
        ``test_license_roundtrip.py`` exists to catch the two drifting; putting
        validation here is what drift looks like.
        """
        payload = vendor_cli.build_payload(customer="Acme Co", machine_id=TEST_MACHINE_ID, features=["not_a_feature"])

        assert payload["features"] == ["not_a_feature"]

    def test_a_bad_expiry_is_reported_before_features_are_looked_at(self, vendor_cli, key_path: Path, capsys) -> None:
        """The feature check sits after the ``--expires`` block, immediately before signing."""
        exit_code = sign(vendor_cli, key_path, "--expires", "not-a-date", "--features", "nope")

        captured = capsys.readouterr()
        assert exit_code == 1
        assert captured.out == ""
        assert "Invalid --expires" in captured.err
        assert "unrecognised feature name" not in captured.err
