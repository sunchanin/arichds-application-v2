"""The HTTPS File Upload Destination transport (ADR 0025 decision 1; spec.md
"HTTPS contract"; ticket 03) — the first real transport behind the seam
:mod:`arichds.fileupload.transport` declares, and the first end-to-end demo:
an administrator saves this tab, presses Upload now, and files land on a
server over plain :mod:`urllib` — no ``httpx``/``requests`` in the product.

Reuses the Central Push client's own split-timeout opener
(:mod:`arichds.split_timeout_http`, factored out for this in ticket 03's own
prefactor) rather than a second hand-copied recipe.

**The three endpoints** (additive, Contract v1 unchanged): ``GET
{url}/v1/files/manifest`` (404 = no manifest), ``PUT
{url}/v1/files/{relative path}`` with the file body and its sha256 in the
:data:`SHA256_HEADER` header (any 2xx = stored), ``PUT
{url}/v1/files/manifest``. Every request carries ``Authorization: Bearer
<token>`` — the HTTPS tab's own token field, which may be the Push Token or
a different one (spec.md story 8); this module never verifies it as a Push
Token itself, since the receiving server, not this machine, decides what it
accepts.

**Remote root.** ADR 0025 decision 4's layout (``<remote_root>/export/…``,
``<remote_root>/captures/…``) is folded into the ``{relative path}`` segment
of a ``PUT .../v1/files/{relative path}`` request by :func:`_remote_path` —
the cycle (:mod:`arichds.fileupload.cycle`) knows nothing about *remote
root* itself, only the SFTP/FTPS-style relative path (``export/…``,
``captures/<serial>/…``) ADR 0025 decision 4 also names for those two
protocols, so this transport is where the operator's *remote root* setting
actually reaches the wire. The two manifest endpoints are **not** prefixed
by *remote_root* — the ticket's own literal contract names them as fixed
paths (``GET``/``PUT {url}/v1/files/manifest``, no path segment for a
relative path), so a receiving server scopes a manifest by the machine's
identity (its token / base URL), not by a client-chosen root; flagged as an
assumption for review (spec.md story 10 discusses remote root only for
"the folder tree", which the file paths are and the manifest endpoint is
not).
"""

from __future__ import annotations

import hashlib
import http.client
from dataclasses import dataclass
from pathlib import Path
from typing import Final, Literal
from urllib.error import HTTPError, URLError
from urllib.request import Request

from arichds.constants import (
    FILEUPLOAD_HTTPS_CONNECT_TIMEOUT_SEC,
    FILEUPLOAD_HTTPS_READ_TIMEOUT_SEC,
    FILEUPLOAD_HTTPS_TEST_CONNECT_TIMEOUT_SEC,
)
from arichds.fileupload.manifest import Manifest, decode_manifest, encode_manifest
from arichds.fileupload.transport import TransportError
from arichds.split_timeout_http import build_split_timeout_opener

#: The manifest endpoint — fixed, never prefixed by *remote_root* (see the
#: module docstring). The one place its literal path is spelled out; both
#: this transport and the published contract (`arichds.centralpush.contract`)
#: import it, so the two cannot drift apart on the string.
MANIFEST_PATH: Final[str] = "/v1/files/manifest"

#: The prefix every ``PUT {url}/v1/files/{relative path}`` request carries.
FILE_PATH_PREFIX: Final[str] = "/v1/files/"

#: The header a file `PUT` carries its sha256 digest in — named once here so
#: the published contract and this transport cannot drift apart on the
#: literal string (spec.md HTTPS contract: "its sha256 in a header", no name
#: given — chosen here).
SHA256_HEADER: Final[str] = "X-ARICHDS-File-Sha256"


def _remote_path(remote_root: str, relative_path: str) -> str:
    """*relative_path* (``export/…`` / ``captures/<serial>/…``) prefixed by
    *remote_root*, so several machines can share one server by choosing
    different roots (spec.md story 10) — an empty *remote_root* leaves
    *relative_path* untouched."""
    root = remote_root.strip("/")
    return f"{root}/{relative_path}" if root else relative_path


class HttpsTransport:
    """The :class:`~arichds.fileupload.transport.Transport` seam, implemented
    over HTTPS. Every method raises :class:`TransportError` — carrying only
    the failure's class name, never a host, credential or response body — on
    any failure; the cycle decides what that means (ticket 02)."""

    def __init__(
        self,
        url: str,
        token: str,
        remote_root: str = "",
        *,
        connect_timeout: float = FILEUPLOAD_HTTPS_CONNECT_TIMEOUT_SEC,
        read_timeout: float = FILEUPLOAD_HTTPS_READ_TIMEOUT_SEC,
    ) -> None:
        self._url = url.rstrip("/")
        self._token = token
        self._remote_root = remote_root
        self._connect_timeout = connect_timeout
        self._read_timeout = read_timeout

    def _round_trip(
        self, method: str, path: str, *, body: bytes | None = None, headers: dict[str, str] | None = None
    ) -> tuple[int, bytes]:
        """One request/response round trip against ``{self._url}{path}``.

        Returns ``(status, body)`` for **any** HTTP response, including a
        non-2xx one (the caller classifies it) — only a transport-level
        failure (unreachable, timed out, a malformed response) raises
        :class:`TransportError` here, carrying only the underlying
        exception's class name.
        """
        request = Request(
            f"{self._url}{path}",
            data=body,
            headers={"Authorization": f"Bearer {self._token}", **(headers or {})},
            method=method,
        )
        opener = build_split_timeout_opener(connect_timeout=self._connect_timeout, read_timeout=self._read_timeout)
        try:
            with opener.open(request) as response:
                return response.status, response.read()
        except HTTPError as exc:
            return exc.code, exc.read()
        except URLError as exc:
            raise TransportError(type(exc.reason).__name__ if exc.reason is not None else type(exc).__name__) from exc
        except (OSError, http.client.HTTPException) as exc:
            # A stalled connection surfaces here directly (TimeoutError, an
            # OSError subclass) — urllib only wraps the connect/request phase
            # in URLError, not `getresponse()`'s own read (the same split
            # `centralpush.client._round_trip` documents).
            raise TransportError(type(exc).__name__) from exc

    def read_manifest(self) -> Manifest | None:
        status, body = self._round_trip("GET", MANIFEST_PATH)
        if status == 404:
            return None
        if not 200 <= status < 300:
            raise TransportError("HTTPError")
        try:
            return decode_manifest(body)
        except ValueError:
            # manifest.py's own documented contract: an unreadable manifest
            # means "send everything", the same as a missing one — never a
            # crash reaching the cycle.
            return None

    def put_file(self, relative_path: str, local_path: Path) -> None:
        # Read once and digest that exact buffer — never a second, separate
        # read of *local_path* for the header (reviewer finding, ticket 03
        # round 1): `export/writer.py::replace_rows()` swaps the file with
        # an atomic `os.replace`, so a rewrite landing between two reads
        # would make the header describe a newer file than the body a
        # receiving server actually stores, and a server that validates the
        # digest would refuse it.
        body = local_path.read_bytes()
        status, _ = self._round_trip(
            "PUT",
            f"{FILE_PATH_PREFIX}{_remote_path(self._remote_root, relative_path)}",
            body=body,
            headers={SHA256_HEADER: hashlib.sha256(body).hexdigest()},
        )
        if not 200 <= status < 300:
            raise TransportError("HTTPError")

    def write_manifest(self, manifest: Manifest) -> None:
        status, _ = self._round_trip("PUT", MANIFEST_PATH, body=encode_manifest(manifest))
        if not 200 <= status < 300:
            raise TransportError("HTTPError")

    def describe(self) -> str:
        """One line naming the server's identity — Test connection's own
        check, run again here so ``describe()`` never gets out of sync with
        what `POST .../https/test` actually reports."""
        return check_https_connection(self._url, self._token, connect_timeout=self._connect_timeout).message


#: What `POST /api/settings/file-upload/https/test` can answer — the same
#: "every outcome is data, not an exception" shape
#: `dataout.destination.check_destination_connection` uses.
FilesTestResult = Literal["ok", "unreachable", "timed_out", "unauthorized", "other"]


@dataclass(frozen=True, slots=True)
class FilesConnectionCheck:
    """One Test connection result.

    Attributes:
        result: Which of :data:`FilesTestResult` this is.
        http_status: The HTTP status the server answered with, or ``None``
            when the request never got a response at all (unreachable,
            timed out).
        manifest_exists: Whether the server already holds a manifest.
        message: One operator-actionable English sentence.
    """

    result: FilesTestResult
    http_status: int | None
    manifest_exists: bool
    message: str


def check_https_connection(
    url: str, token: str, *, connect_timeout: float = FILEUPLOAD_HTTPS_TEST_CONNECT_TIMEOUT_SEC
) -> FilesConnectionCheck:
    """``GET {url}/v1/files/manifest`` with a short connect timeout,
    classified into one of :data:`FilesTestResult` — never raises, the same
    "always answers, HTTP 200 either way" shape
    :func:`arichds.dataout.destination.check_destination_connection` uses,
    so the endpoint calling this can report every outcome, failures
    included, without a 4xx/5xx swallowing the reason.
    """
    if not url.strip():
        return FilesConnectionCheck("other", None, False, "No URL is saved yet. Save the HTTPS tab first.")

    request = Request(f"{url.rstrip('/')}{MANIFEST_PATH}", headers={"Authorization": f"Bearer {token}"}, method="GET")
    opener = build_split_timeout_opener(connect_timeout=connect_timeout, read_timeout=connect_timeout)
    try:
        with opener.open(request) as response:
            status = response.status
    except HTTPError as exc:
        if exc.code in (401, 403):
            return FilesConnectionCheck(
                "unauthorized", exc.code, False, f"The server refused the token (HTTP {exc.code})."
            )
        if exc.code == 404:
            return FilesConnectionCheck("ok", exc.code, False, "Connected. The server has no manifest yet.")
        return FilesConnectionCheck("other", exc.code, False, f"The server answered HTTP {exc.code}.")
    except URLError as exc:
        if isinstance(exc.reason, TimeoutError):
            return FilesConnectionCheck("timed_out", None, False, "The connection timed out.")
        return FilesConnectionCheck(
            "unreachable", None, False, f"Could not reach the server ({type(exc.reason).__name__})."
        )
    except TimeoutError:
        return FilesConnectionCheck("timed_out", None, False, "The connection timed out.")
    except (OSError, http.client.HTTPException) as exc:
        return FilesConnectionCheck("other", None, False, f"The connection failed ({type(exc).__name__}).")
    except ValueError as exc:
        return FilesConnectionCheck("other", None, False, f"That URL could not be used ({type(exc).__name__}).")

    return FilesConnectionCheck("ok", status, True, "Connected. The server holds a manifest.")


__all__ = [
    "FILE_PATH_PREFIX",
    "MANIFEST_PATH",
    "SHA256_HEADER",
    "FilesConnectionCheck",
    "FilesTestResult",
    "HttpsTransport",
    "check_https_connection",
]
