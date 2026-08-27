"""LicenseService — the one re-evaluatable holder of license state.

ADR 0001 is the whole design constraint here: activation applies **live, with no
process restart**. v1 loaded enforcement state once at startup and therefore had
to require a restart; v2 never caches license-derived state at import time.
Everything that needs to know whether the license is valid asks this service,
and this service can re-evaluate itself at any moment.

Three things trigger a re-evaluation:

1. :meth:`activate` — the user pasted a code on the Activation page.
2. The staleness TTL — a lease that lapses while the process runs must take
   effect without anybody doing anything (SPEC §4 lists "license recheck" as a
   scheduler job; the TTL is M1's lean version of it).
3. An explicit :meth:`re_evaluate` call.

State changes fire registered listeners, which is how the Poller starts the
moment a machine is activated and stops when the license lapses.
"""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from arichds.constants import LICENSE_RECHECK_INTERVAL_SEC
from arichds.licensing.activation_code import (
    NO_LICENSE,
    ActivationVerification,
    verify_activation_code,
)
from arichds.licensing.fingerprint import FingerprintError, machine_id

logger = logging.getLogger(__name__)

#: The two states a machine can be in. "limited" is Limited Mode (CONTEXT.md).
STATE_ACTIVE = "active"
STATE_LIMITED = "limited"


@dataclass(frozen=True)
class LicenseState:
    """A snapshot of license state at one instant.

    Immutable on purpose: callers hold a snapshot and cannot mutate the
    service's view of the world through it.

    Attributes:
        state: ``"active"`` or ``"limited"``.
        reason: Why it is limited (a reason code from
            :mod:`arichds.licensing.activation_code`), or ``None`` when active.
        customer: Licensed customer name, when a license parsed.
        mode: ``"offline"`` or ``"leased"``, when a license parsed.
        expires_at: Lease end (UTC), or ``None``.
        max_meters: Device quota, or ``None`` for unlimited.
        features: Licensed feature names, or ``None``.
        models: Licensed meter model keys (issue 015), or ``None`` for every
            catalogued model. Carried through the **valid** branch only —
            an invalid state leaves it ``None``, which grandfathers; that is
            harmless because ``LimitedModeMiddleware`` blocks ``/api/*``
            wholesale before any device handler runs, so nothing ever reads
            this field off an invalid state.
        evaluated_at: Monotonic timestamp of the evaluation that produced this.
    """

    state: str
    reason: str | None
    customer: str | None = None
    mode: str | None = None
    expires_at: datetime | None = None
    max_meters: int | None = None
    features: list[str] | None = None
    models: list[str] | None = None
    evaluated_at: float = field(default_factory=time.monotonic)

    @property
    def valid(self) -> bool:
        """True when the machine is licensed and enforcement should stand down."""
        return self.state == STATE_ACTIVE


def _limited(reason: str) -> LicenseState:
    """Build a Limited Mode state carrying *reason*."""
    return LicenseState(state=STATE_LIMITED, reason=reason)


def _from_verification(result: ActivationVerification) -> LicenseState:
    """Translate a verification result into a :class:`LicenseState`."""
    if not result.valid:
        return LicenseState(
            state=STATE_LIMITED,
            reason=result.reason,
            customer=result.customer,
            mode=result.mode,
            expires_at=result.expires_at,
        )
    return LicenseState(
        state=STATE_ACTIVE,
        reason=None,
        customer=result.customer,
        mode=result.mode,
        expires_at=result.expires_at,
        max_meters=result.max_meters,
        features=result.features,
        models=result.models,
    )


class LicenseService:
    """Holds current license state behind a lock, re-evaluatable on demand.

    Thread-safe: the Poller, the enforcement middleware and the API all read it
    concurrently, and :meth:`activate` writes it from a request thread.
    """

    def __init__(
        self,
        license_path: Path,
        *,
        recheck_interval_sec: float = LICENSE_RECHECK_INTERVAL_SEC,
    ) -> None:
        """Initialise the service.

        Args:
            license_path: Where the activated license is persisted.
            recheck_interval_sec: How stale a state may get before a read
                re-evaluates it. Keeps a lapsing lease honest without a restart.
        """
        self._license_path = license_path
        self._recheck_interval_sec = recheck_interval_sec
        self._lock = threading.RLock()
        self._state: LicenseState | None = None
        self._machine_id: str | None = None
        self._listeners: list[Callable[[LicenseState], None]] = []

    # ── Machine identity ─────────────────────────────────────────────────────

    @property
    def machine_id(self) -> str:
        """This machine's Machine ID, computed once (a machine property).

        Unlike license state this genuinely cannot change while the process
        runs, so caching it does not violate ADR 0001.

        Returns:
            The 64-char Machine ID, or ``""`` if it could not be read (the
            Activation page then shows the error rather than crashing).
        """
        with self._lock:
            if self._machine_id is None:
                try:
                    self._machine_id = machine_id()
                except FingerprintError:
                    logger.exception("Could not compute Machine ID")
                    self._machine_id = ""
            return self._machine_id

    # ── State ────────────────────────────────────────────────────────────────

    def add_listener(self, listener: Callable[[LicenseState], None]) -> None:
        """Register a callback fired whenever the state is re-evaluated.

        This is how the Poller reacts to activation without polling for it.
        Listeners must not raise; exceptions are logged and swallowed so a bad
        listener can never wedge activation.
        """
        with self._lock:
            self._listeners.append(listener)

    def current_state(self) -> LicenseState:
        """Return the current state, re-evaluating if it has gone stale.

        Never returns a state that was computed at import or startup and then
        frozen — that is exactly the v1 behaviour ADR 0001 reverses.
        """
        with self._lock:
            state = self._state
            if state is None or (time.monotonic() - state.evaluated_at) >= self._recheck_interval_sec:
                return self.re_evaluate()
            return state

    def is_valid(self) -> bool:
        """True when enforcement should let ``/api/*`` through."""
        return self.current_state().valid

    def re_evaluate(self) -> LicenseState:
        """Re-read the license from disk and recompute state. Fires listeners.

        Returns:
            The freshly computed state.
        """
        with self._lock:
            new_state = self._evaluate()
            previous = self._state
            self._state = new_state
            changed = previous is None or previous.state != new_state.state or previous.reason != new_state.reason
            listeners = list(self._listeners)

        if changed:
            logger.info(
                "License state: %s%s",
                new_state.state,
                f" ({new_state.reason})" if new_state.reason else "",
            )
            for listener in listeners:
                try:
                    listener(new_state)
                except Exception:  # noqa: BLE001
                    logger.exception("License state listener failed")
        return new_state

    def _evaluate(self) -> LicenseState:
        """Compute state from the persisted license file. Caller holds the lock."""
        if not self._license_path.is_file():
            return _limited(NO_LICENSE)

        try:
            code = self._license_path.read_text(encoding="utf-8")
        except OSError:
            logger.exception("Could not read the license file at %s", self._license_path)
            return _limited(NO_LICENSE)

        this_machine = self.machine_id
        if not this_machine:
            # No Machine ID means nothing can be verified against it. Staying in
            # Limited Mode is the only honest answer.
            return _limited("MACHINE_ID_UNAVAILABLE")

        return _from_verification(verify_activation_code(code, machine_id=this_machine))

    # ── Activation ───────────────────────────────────────────────────────────

    def activate(self, code: str) -> LicenseState:
        """Verify *code* against this machine and, if valid, activate immediately.

        The license is only persisted **after** it verifies, so a bad paste can
        never knock a working machine into Limited Mode. On success the state is
        re-evaluated in place and listeners fire — no restart (ADR 0001).

        Args:
            code: The pasted Activation Code.

        Returns:
            The resulting state. Its ``reason`` explains a rejection.
        """
        this_machine = self.machine_id
        if not this_machine:
            return _limited("MACHINE_ID_UNAVAILABLE")

        result = verify_activation_code(code, machine_id=this_machine)
        if not result.valid:
            # Report the rejection WITHOUT touching the stored license or the
            # cached state: a fat-fingered paste must not knock an already
            # licensed machine into Limited Mode.
            logger.warning("Activation rejected: %s", result.reason)
            return LicenseState(
                state=STATE_LIMITED,
                reason=result.reason,
                customer=result.customer,
                mode=result.mode,
                expires_at=result.expires_at,
            )

        self._license_path.parent.mkdir(parents=True, exist_ok=True)
        self._license_path.write_text(code.strip(), encoding="utf-8")
        logger.info("Activation accepted for customer %s", result.customer)
        return self.re_evaluate()
