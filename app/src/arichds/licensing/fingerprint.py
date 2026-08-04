"""Machine ID — the stable fingerprint every license binds to.

**FROZEN FROM DAY ONE.** Changing anything in this module invalidates every
Activation Code ever issued (SPEC §3.1). Treat a failing fingerprint test as a
regression, never as a test to update.

Ported from the Go implementation that v1 shipped
(``cewe/modbus-logger/internal/license/fingerprint.go`` + ``_windows.go``):

    collect() -> combine() -> SHA-256 hex

``combine`` mirrors the Go function exactly: each component rendered as
``Key + "=" + TrimSpace(Value)``, in order, joined by ``"\\n"``; an empty list or
an empty value is an error so the hash never runs on empty input.

One thing changed on purpose (SPEC §3.9 — "ชื่อเชิง cryptographic ทั้งหมด
เปลี่ยนเป็น ARICHDS"): an ARICHDS salt component is prepended, so the same
physical machine yields a *different* Machine ID under ARICHDS than it did under
CEWE. That is the whole point of the salt — v1 licenses can never be replayed
against v2, and v2 is free to define its own contract.

On Windows the single component is ``MachineGuid`` from
``HKLM\\SOFTWARE\\Microsoft\\Cryptography`` (v1 dropped the disk serial). On other
platforms a portable fallback is used so the code stays testable off Windows —
Windows is the only shipped target (SPEC §2 Non-Goals).
"""

from __future__ import annotations

import hashlib
import platform
import re
import subprocess
from dataclasses import dataclass
from typing import Final

# The salt that separates ARICHDS fingerprints from v1 CEWE ones. FROZEN.
_SALT_KEY: Final[str] = "arichds.product"
_SALT_VALUE: Final[str] = "ARICHDS"

_MACHINE_GUID_KEY: Final[str] = "windows.MachineGuid"
_MACHINE_GUID_REGISTRY_PATH: Final[str] = r"HKLM\SOFTWARE\Microsoft\Cryptography"

# Extracts the value from a `reg query` line like:
#   MachineGuid    REG_SZ    11111111-2222-3333-4444-555555555555
_MACHINE_GUID_RE: Final[re.Pattern[str]] = re.compile(r"MachineGuid\s+REG_SZ\s+(\S+)")


class FingerprintError(RuntimeError):
    """Raised when the Machine ID cannot be computed from this machine."""


@dataclass(frozen=True)
class Component:
    """One named raw input to the fingerprint.

    Attributes:
        key: Stable identifier, e.g. ``"windows.MachineGuid"``.
        value: Raw value read from the machine.
    """

    key: str
    value: str


#: The ARICHDS salt, prepended to every component list. FROZEN.
ARICHDS_SALT_COMPONENT: Final[Component] = Component(_SALT_KEY, _SALT_VALUE)


def combine(components: list[Component]) -> str:
    """Build the canonical string fed to the hash.

    Mirrors the Go ``combine()`` byte for byte.

    Args:
        components: Ordered components. Order is part of the formula.

    Returns:
        ``"key=value"`` lines joined by ``"\\n"``, values trimmed.

    Raises:
        FingerprintError: On an empty list, or any component whose value is
            empty/whitespace — so the hash never runs on empty input.
    """
    if not components:
        raise FingerprintError("fingerprint: no components to combine")
    lines: list[str] = []
    for component in components:
        value = component.value.strip()
        if not value:
            raise FingerprintError(f"fingerprint: component {component.key!r} has empty value")
        lines.append(f"{component.key}={value}")
    return "\n".join(lines)


def sha256_hex(canonical: str) -> str:
    """Return the lowercase hex SHA-256 of *canonical* — the 64-char digest."""
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def machine_id_from_components(components: list[Component]) -> str:
    """Compute the Machine ID from already-collected *components*.

    Separated from :func:`collect` so the formula is testable without touching
    the registry.

    Args:
        components: Machine components, WITHOUT the salt (it is prepended here).

    Returns:
        The 64-character lowercase hex Machine ID.
    """
    return sha256_hex(combine([ARICHDS_SALT_COMPONENT, *components]))


def _read_windows_machine_guid() -> str:
    """Read ``HKLM\\SOFTWARE\\Microsoft\\Cryptography\\MachineGuid``.

    Uses ``reg query`` (as the Go original did) rather than ``winreg`` so the
    call site is identical across the 32/64-bit registry views the v1 formula
    was validated against.

    Raises:
        FingerprintError: If the query fails or the value is absent.
    """
    try:
        output = subprocess.check_output(  # noqa: S603
            ["reg", "query", _MACHINE_GUID_REGISTRY_PATH, "/v", "MachineGuid"],
            stderr=subprocess.DEVNULL,
            text=True,
        )
    except (OSError, subprocess.CalledProcessError) as exc:
        raise FingerprintError(f"fingerprint: reg query MachineGuid failed: {exc}") from exc

    match = _MACHINE_GUID_RE.search(output)
    if match is None:
        raise FingerprintError("fingerprint: MachineGuid not found in reg output")
    return match.group(1)


def collect() -> list[Component]:
    """Collect this machine's fingerprint components.

    Windows is the shipped target and has exactly one component, ``MachineGuid``
    — mirroring the Go ``collect()``. Off Windows a portable node identifier is
    used so the code runs (and is testable) on a dev machine; no ARICHDS build is
    shipped for those platforms.

    Returns:
        The component list, without the ARICHDS salt.

    Raises:
        FingerprintError: If no component could be read.
    """
    if platform.system() == "Windows":
        return [Component(_MACHINE_GUID_KEY, _read_windows_machine_guid())]

    node = platform.node().strip()
    if not node:
        raise FingerprintError("fingerprint: no machine identifier available on this platform")
    return [Component("portable.NodeName", node)]


def machine_id() -> str:
    """Return this machine's Machine ID.

    Shown to the user on the Activation page (with a copy button) and sent to
    the vendor, who binds the Activation Code to it.

    Returns:
        The 64-character lowercase hex Machine ID.

    Raises:
        FingerprintError: If the machine components cannot be read.
    """
    return machine_id_from_components(collect())
