"""Machine ID (fingerprint) — the formula is FROZEN from day one.

Ported from the Go implementation in
``cewe/modbus-logger/internal/license/fingerprint.go`` (+ ``_windows.go``):
collect components → canonical combine → SHA-256 hex.

These tests pin the combine rule byte-for-byte. Changing it invalidates every
Activation Code ever issued, so a failure here is never "just update the test".
"""

from __future__ import annotations

import hashlib

import pytest

from arichds.licensing.fingerprint import (
    ARICHDS_SALT_COMPONENT,
    Component,
    FingerprintError,
    combine,
    machine_id_from_components,
    sha256_hex,
)


class TestCombine:
    """`combine` mirrors the Go `combine()` exactly."""

    def test_single_component_is_key_equals_value(self) -> None:
        assert combine([Component("windows.MachineGuid", "abc-123")]) == "windows.MachineGuid=abc-123"

    def test_components_join_with_newline_in_order(self) -> None:
        result = combine([Component("a", "1"), Component("b", "2"), Component("c", "3")])
        assert result == "a=1\nb=2\nc=3"

    def test_value_is_trimmed_but_key_is_not(self) -> None:
        # Go: Key + "=" + strings.TrimSpace(Value)
        assert combine([Component("k", "  spaced  ")]) == "k=spaced"

    def test_empty_component_list_is_an_error(self) -> None:
        # Go returns an error so hash never runs on empty input.
        with pytest.raises(FingerprintError):
            combine([])

    def test_whitespace_only_value_is_an_error(self) -> None:
        with pytest.raises(FingerprintError):
            combine([Component("k", "   ")])

    def test_empty_value_is_an_error(self) -> None:
        with pytest.raises(FingerprintError):
            combine([Component("k", "")])


class TestHash:
    """`sha256_hex` is the lowercase hex SHA-256 of the canonical string."""

    def test_matches_hashlib(self) -> None:
        assert sha256_hex("windows.MachineGuid=abc") == hashlib.sha256(b"windows.MachineGuid=abc").hexdigest()

    def test_is_lowercase_hex_64_chars(self) -> None:
        digest = sha256_hex("anything")
        assert len(digest) == 64
        assert digest == digest.lower()
        assert all(c in "0123456789abcdef" for c in digest)


class TestMachineId:
    """The ARICHDS salt makes v2 Machine IDs distinct from v1's (SPEC §3.9)."""

    def test_salt_component_is_prepended(self) -> None:
        guid = Component("windows.MachineGuid", "11111111-2222-3333-4444-555555555555")
        expected = sha256_hex(combine([ARICHDS_SALT_COMPONENT, guid]))
        assert machine_id_from_components([guid]) == expected

    def test_differs_from_unsalted_v1_formula(self) -> None:
        guid = Component("windows.MachineGuid", "11111111-2222-3333-4444-555555555555")
        unsalted = sha256_hex(combine([guid]))
        assert machine_id_from_components([guid]) != unsalted

    def test_is_stable_for_the_same_machine(self) -> None:
        guid = Component("windows.MachineGuid", "same-guid")
        assert machine_id_from_components([guid]) == machine_id_from_components([guid])

    def test_changes_when_the_machine_changes(self) -> None:
        one = machine_id_from_components([Component("windows.MachineGuid", "guid-a")])
        two = machine_id_from_components([Component("windows.MachineGuid", "guid-b")])
        assert one != two

    def test_frozen_golden_vector(self) -> None:
        """A locked value. If this changes, every issued license is dead."""
        guid = Component("windows.MachineGuid", "11111111-2222-3333-4444-555555555555")
        canonical = "arichds.product=ARICHDS\nwindows.MachineGuid=11111111-2222-3333-4444-555555555555"
        assert combine([ARICHDS_SALT_COMPONENT, guid]) == canonical
        assert machine_id_from_components([guid]) == hashlib.sha256(canonical.encode("utf-8")).hexdigest()
