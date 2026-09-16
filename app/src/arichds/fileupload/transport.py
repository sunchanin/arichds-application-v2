"""The one transport seam every File Upload Destination cycle talks through
(ADR 0025 decision 5, spec.md "One seam: the transport"): read the manifest,
put one file, write the manifest, describe yourself. Three real
implementations land in tickets 03-05 (SFTP/FTPS/HTTPS); this ticket proves
the cycle (:mod:`arichds.fileupload.cycle`) against an in-memory one that
lives in the test suite — everything the cycle decides (which files, in
what order, the budget, the status) is protocol-blind.
"""

from __future__ import annotations

from pathlib import Path
from typing import Protocol

from arichds.fileupload.manifest import Manifest


class TransportError(Exception):
    """Any transport failure — refused, unreachable, timed out, a rejected
    certificate or host key, a non-2xx response.

    ``str(self)`` is always **the failure's class name alone** — never a
    host, a credential, or any other message component that might carry
    one. A review of ticket 01 named the exact hazard this is built to
    avoid: the redaction filter's patterns only catch text shaped like
    ``password=``/``token=``/``passphrase=``, not an arbitrary exception
    message, so the failure carried on this exception must never be one.
    Mirrors :class:`arichds.centralpush.client.PushRequestError`'s own rule.
    """


class Transport(Protocol):
    """What the cycle needs from any of the three real transports.

    Every method may raise :class:`TransportError`; the cycle decides what
    that means — a :meth:`read_manifest` failure collapses to "send
    everything", a :meth:`put_file`/:meth:`write_manifest` failure ends the
    cycle ``skipped`` — nothing here decides that.
    """

    def read_manifest(self) -> Manifest | None:
        """The manifest at the remote root, or ``None`` when it does not
        exist yet (a fresh root). **Not** the same as raising
        :class:`TransportError`, which means the read itself failed — the
        cycle treats both the same way (ADR 0025: "a missing or unreadable
        manifest means 'send everything'"), so a real transport is free to
        choose whichever is natural for it (an HTTP 404 is a clean
        ``None``; a malformed remote file is naturally a raise)."""
        ...

    def put_file(self, relative_path: str, local_path: Path) -> None:
        """Copy *local_path* to *relative_path* under the remote root,
        creating any directory on the way as needed."""
        ...

    def write_manifest(self, manifest: Manifest) -> None:
        """Write *manifest* to the remote root, replacing whatever is
        there."""
        ...

    def describe(self) -> str:
        """One line naming the server's identity — a host-key fingerprint,
        a certificate subject, an HTTP status — for Test connection
        (tickets 03-05). The cycle itself never calls this."""
        ...


__all__ = ["Transport", "TransportError"]
