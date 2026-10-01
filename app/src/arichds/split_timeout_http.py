"""A ``urllib`` opener with a connect timeout distinct from its read timeout
— something plain ``urllib.request.urlopen(..., timeout=)`` cannot express,
since its one ``timeout`` covers the whole call.

Extracted from :mod:`arichds.centralpush.client` (ADR 0024, ticket 08) so the
File Upload Destination's HTTPS transport (ADR 0025, ticket 03) can reuse the
exact same recipe with its own timeouts, rather than a second hand-copied
implementation. At the package top, like :mod:`arichds.interval_status` and
:mod:`arichds.filename_tokens`: it is the one piece both callers need and
neither owns.

The split is implemented the way the standard library documents for exactly
this need: an :class:`http.client.HTTPConnection` subclass that fixes
``self.timeout`` before :meth:`~http.client.HTTPConnection.connect` (the
connect timeout) and then calls the live socket's own ``settimeout`` again
immediately after (the read timeout), wired into :mod:`urllib.request`
through a custom opener.

**The HTTPS handler must not pass ``check_hostname`` to ``do_open``** — read
via ``inspect.getsource`` against the installed stdlib (3.14): only
``context=self._context`` goes to :meth:`~urllib.request.AbstractHTTPHandler.do_open`.
``check_hostname`` is not a ``do_open``/``HTTPSConnection`` keyword argument
(removed in 3.12) and is instead applied to ``self._context`` by
``HTTPSHandler.__init__`` before this method ever runs. An earlier version of
the Central Push client passed it anyway, which made every ``https://``
request raise ``TypeError`` before connecting — a blocker a review caught,
since a real receiving server is HTTPS and that ``TypeError`` is not an
``OSError``/``URLError``, so it escaped the caller's own error handling
uncaught (ADR 0025 ticket 03 note; the fix here is the same one
``centralpush.client`` already carried, now shared rather than duplicated).
"""

from __future__ import annotations

import http.client
from urllib.request import HTTPHandler, HTTPSHandler, OpenerDirector, build_opener


def build_split_timeout_opener(*, connect_timeout: float, read_timeout: float) -> OpenerDirector:
    """A fresh :class:`~urllib.request.OpenerDirector` whose HTTP(S)
    connections use *connect_timeout* for the TCP connect (and, for HTTPS,
    the TLS handshake) and *read_timeout* for every read after.

    Stateless and cheap enough at either caller's cadence (fifteen minutes
    for a cycle, once per Test connection press) that there is nothing to
    gain from caching one — a fresh opener per call, exactly as
    :mod:`arichds.centralpush.client` built its own before this move.
    """

    class _SplitTimeoutMixin:
        """The connect/read-timeout split itself, mixed into both connection
        subclasses below rather than copied into each (reviewer finding,
        ticket 03 round 1): the one test that reaches ``https_open`` fails
        inside ``super().connect()`` (a refused certificate), so
        ``self.sock.settimeout(read_timeout)`` was never executed for HTTPS
        by any test while the two ``connect`` bodies were separate — a
        read-timeout bug introduced into the HTTPS copy alone would have
        shipped untested. One body now, exercised in full by the plain-HTTP
        tests, and reused — not merely mirrored — by the HTTPS path.
        """

        def connect(self) -> None:
            self.timeout = connect_timeout
            super().connect()
            if self.sock is not None:
                self.sock.settimeout(read_timeout)

    class _SplitTimeoutHTTPConnection(_SplitTimeoutMixin, http.client.HTTPConnection):
        pass

    class _SplitTimeoutHTTPSConnection(_SplitTimeoutMixin, http.client.HTTPSConnection):
        pass

    class _SplitTimeoutHTTPHandler(HTTPHandler):
        def http_open(self, req):  # noqa: ANN001, ANN201 — matches urllib.request's own untyped signature.
            return self.do_open(_SplitTimeoutHTTPConnection, req)

    class _SplitTimeoutHTTPSHandler(HTTPSHandler):
        def https_open(self, req):  # noqa: ANN001, ANN201 — matches urllib.request's own untyped signature.
            return self.do_open(_SplitTimeoutHTTPSConnection, req, context=self._context)

    return build_opener(_SplitTimeoutHTTPHandler(), _SplitTimeoutHTTPSHandler())


__all__ = ["build_split_timeout_opener"]
