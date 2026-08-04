"""Stop the vendored Gurux reader from writing an unredacted frame trace to disk.

``GXDLMSReader.__init__`` does ``self.logFile = open("logFile.txt", "w")`` and
``writeTrace`` then does::

    def writeTrace(self, line, level):
        if self.trace >= level:
            print(line)
        self.logFile.write(line + "\\n")

The trace-level check gates only the ``print``. **The file write is
unconditional**, so passing ``-t Error`` does not stop it. Three consequences,
all of which ARICHDS has to deal with:

1. **It leaks credentials.** The trace includes the raw AARQ frame, which
   carries the DLMS password in cleartext — e.g. ``41 42 43 44 30 30 30 31``
   for ``ABCD0001``. That file never passes
   :class:`~arichds.logging_config.CredentialRedactionFilter`, so it defeats the
   redaction guarantee SPEC §4 makes about every log.
2. **It writes to the current working directory.** Under NSSM the service's
   ``AppDirectory`` is ``Program Files\\ARICHDS``, so the trace would land inside
   Program Files — a directory nothing at runtime should be writing to.
3. **Concurrent pollers fight over one file.** A reader is constructed per
   connect, and ``"w"`` truncates, so n meter threads repeatedly truncate the
   same path.

The vendored file must not be edited (SPEC §4 — the ``GX*.py`` API is frozen),
so the handle is replaced at *our* seam, immediately after the reader is
constructed.

**Frame lines are dropped, not re-routed.** An earlier version of this module
forwarded every trace line to ``logger.debug``, on the theory that
:class:`~arichds.logging_config.CredentialRedactionFilter` would mask the
password. It would not: that filter matches ``key=value`` shapes such as
``password=…``, and a DLMS frame is bare hex — the password appears as
``41 42 43 44 30 30 30 31``, which no pattern can recognise without decoding the
frame. So forwarding merely moved the plaintext password from ``logFile.txt``
into ``logs/arichds.log``, NSSM's ``service.log`` and (from M7) the App Log
page, and made it *more* reachable, since ``ARICHDS_LOG_LEVEL=DEBUG`` is a
documented knob.

TX/RX frame lines are therefore discarded outright. The remaining trace lines
(profile column listings, index/value summaries) carry no association frame and
are forwarded at DEBUG, where they are genuinely useful. Set
:data:`ALLOW_FRAME_TRACE` to True **only on a bench, never on a customer
machine**, to see raw frames again.

v1 shipped with this file present (``cewe-worker/logFile.txt``). v2 does not.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

#: Where the vendored reader opens its trace, relative to the process CWD.
_VENDOR_TRACE_FILENAME = "logFile.txt"

#: Emit raw DLMS frames to the log. **Off, and must stay off in any build that
#: reaches a customer machine**: frames contain the association request, which
#: carries the meter password as plain hex that no redaction filter can mask.
#: A deliberate source-level constant rather than an env var, so it cannot be
#: turned on by accident in the field.
ALLOW_FRAME_TRACE = False

#: Prefixes the vendored reader uses for raw frame lines ("TX: …" / "RX: …").
_FRAME_PREFIXES = ("TX:", "RX:")


def _is_frame_line(line: str) -> bool:
    """True when *line* is a raw DLMS frame dump (and may carry credentials)."""
    return line.lstrip().startswith(_FRAME_PREFIXES)


class _RedactedTraceSink:
    """File-like sink standing in for the vendored reader's trace file.

    Only the handful of methods the vendored reader touches are implemented —
    it calls ``write`` and (on close) ``close``.
    """

    def write(self, line: str) -> int:
        """Drop frame lines; forward anything else at DEBUG.

        Returns the character count so the caller sees a normal file-like write.
        """
        stripped = line.rstrip("\n")
        if not stripped:
            return len(line)
        if _is_frame_line(stripped) and not ALLOW_FRAME_TRACE:
            # Never logged at any level — the password lives in these bytes.
            return len(line)
        logger.debug("dlms trace: %s", stripped)
        return len(line)

    def flush(self) -> None:
        """No-op: the logging handlers own flushing."""

    def close(self) -> None:
        """No-op: there is no real file to close."""


def silence_frame_trace(reader: Any) -> None:
    """Replace *reader*'s on-disk frame trace with the redacted logger sink.

    Call immediately after constructing a ``GXDLMSReader`` and before any frame
    is exchanged, so no credential-bearing line is ever written to disk.

    Best-effort by design: if closing or removing the vendored file fails, the
    sink is still installed — closing the leak matters more than tidying up.

    Args:
        reader: The freshly constructed ``GXDLMSReader``.
    """
    existing = getattr(reader, "logFile", None)
    try:
        if existing is not None and hasattr(existing, "close"):
            existing.close()
    except Exception:  # noqa: BLE001
        logger.debug("Could not close the vendored Gurux trace file", exc_info=True)

    reader.logFile = _RedactedTraceSink()

    # __init__ already created the (now empty) file in the CWD. Remove it so a
    # stray zero-byte logFile.txt does not accumulate next to the exe.
    try:
        stray = Path(_VENDOR_TRACE_FILENAME)
        if stray.is_file() and stray.stat().st_size == 0:
            stray.unlink()
    except OSError:
        logger.debug("Could not remove the empty %s", _VENDOR_TRACE_FILENAME, exc_info=True)
