"""Stop the gurux ``GXNet`` TCP listener thread from busy-spinning on a dead socket.

Ported verbatim in behaviour from ``cewe-worker/src/drivers/_gurux_net_patch.py``
(v1 issue #130) — a production lesson, not a nicety.

When the link to a meter drops, gurux's socket-listener thread
(``GXNet._GXNet__listenerThread``) hits ``ConnectionAbortedError`` (WinError
10053). That falls into the method's generic ``except Exception`` branch which —
while ``self.__socket`` is still set — calls ``traceback.print_exc()`` and loops
with *no break and no sleep*. ``recv`` on a dead socket fails instantly, so a
single abort emits millions of stderr lines. On v1 that produced an 836 MB
service log in two days, and NSSM captures stderr directly, bypassing the app's
rotating + redacting logger entirely.

The offending loop lives in a name-mangled private method of an installed
library that is overwritten by any reinstall or repackage and cannot be cleanly
subclassed. So the method is replaced on the class at import time with a
faithful copy whose ONLY behavioural change is the socket-error path: on
``OSError`` (covering ``ConnectionAbortedError`` / ``ConnectionResetError``) it
logs once through the app logger and breaks out of the loop. A dead TCP client
socket is never recoverable by re-``recv``, so exiting the thread is correct —
the main thread then times out on its blocking read and the caller disconnects
as it already does.

Attribute access uses gurux's name-mangled internals (``self._GXNet__socket``)
because this replacement lives outside the class body, so ``__`` prefixes are
NOT auto-mangled here.
"""

from __future__ import annotations

import logging
import traceback

try:
    from gurux_net._GXNetConnectionEventArgs import _GXNetConnectionEventArgs
    from gurux_net.GXNet import GXNet
except ImportError:  # pragma: no cover - gurux_net absent (e.g. a stubbed env)
    _GXNetConnectionEventArgs = None  # type: ignore[assignment,misc]
    GXNet = None  # type: ignore[assignment,misc]

logger = logging.getLogger(__name__)

# Marks the class once patched so re-imports don't re-apply (idempotent).
_PATCH_FLAG = "_arichds_listener_patched"


def _patched_listener_thread(self, s):  # noqa: ANN001, ANN201
    """Drop-in replacement for ``GXNet._GXNet__listenerThread``.

    Faithful to the vendored loop except that terminal socket errors log once
    and break instead of printing a traceback and spinning.
    """
    while self._GXNet__socket and s:
        try:
            data = s.recv(1500)
            if data:
                data = bytearray(data)
                self._GXNet__handleReceivedData(data, s)
            elif self.server:
                arg = _GXNetConnectionEventArgs(s.getpeername()[0] + ":" + str(s.getpeername()[1]), s)
                self._GXNet__notifyClientDisconnected(arg)
                break
        except ConnectionResetError:
            # Server closed the connection — preserve the original close+break.
            if not self.server:
                self.close()
            break
        except OSError as exc:
            # A dead/aborted TCP socket is unrecoverable by re-recv. Log once
            # via the app logger (redacted + rotated) and exit the thread
            # instead of spinning. A deliberate close() clears the socket first,
            # so skip the log in that (expected) case.
            if self._GXNet__socket:
                logger.warning("GXNet listener socket error, stopping listener thread: %s", exc)
            break
        except Exception:  # noqa: BLE001 — parity with the vendored catch-all.
            if self._GXNet__socket:
                traceback.print_exc()
            else:
                break


def apply_gurux_net_patch() -> None:
    """Install the anti-spin listener on ``GXNet``. Idempotent."""
    if GXNet is None:
        return
    if getattr(GXNet, _PATCH_FLAG, False):
        return
    # gurux's open() starts self.__listenerThread → _GXNet__listenerThread.
    GXNet._GXNet__listenerThread = _patched_listener_thread
    GXNet._arichds_listener_patched = True


apply_gurux_net_patch()
