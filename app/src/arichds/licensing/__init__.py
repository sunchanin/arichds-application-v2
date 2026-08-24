"""Licensing — Machine ID, Activation Codes, and Limited Mode enforcement.

Enforcement runs from M1 (SPEC §3.9). Anything holding license-derived state
must read it through :class:`~arichds.licensing.service.LicenseService`, never
cache it at import or startup (ADR 0001).
"""

from arichds.licensing.activation_code import (
    ActivationVerification,
    build_payload,
    encode_activation_code,
    verify_activation_code,
)
from arichds.licensing.fingerprint import FingerprintError, machine_id
from arichds.licensing.meter_activation_code import (
    WRONG_METER,
    MeterActivationVerification,
    build_meter_payload,
    verify_meter_activation_code,
)
from arichds.licensing.middleware import LimitedModeMiddleware
from arichds.licensing.service import STATE_ACTIVE, STATE_LIMITED, LicenseService, LicenseState

__all__ = [
    "STATE_ACTIVE",
    "STATE_LIMITED",
    "WRONG_METER",
    "ActivationVerification",
    "FingerprintError",
    "LicenseService",
    "LicenseState",
    "LimitedModeMiddleware",
    "MeterActivationVerification",
    "build_meter_payload",
    "build_payload",
    "encode_activation_code",
    "machine_id",
    "verify_activation_code",
    "verify_meter_activation_code",
]
