"""The File Upload Destination cycle (ADR 0025; spec.md "The cycle sends
what the Upload Manifest lacks"; ticket 02).

Every fifteen minutes, on the scheduler's one thread, **last** in the
registry — one job behind the Central Push
(:func:`arichds.centralpush.cycle.central_push_cycle`), because it is the
THIRD job that talks to a machine we do not own (ADR 0025 decision 5). A
machine with no active protocol, or an active protocol with no host/URL
configured, makes no attempt at all.

**No state on our side** (ADR 0008, ADR 0025 decision 2). Every cycle reads
the **Upload Manifest** the server holds first; a missing or unreadable one
means "send everything". Digests are computed for every local candidate
every cycle, and only the files whose digest is absent or differs from the
manifest are actually sent — the manifest is then written back naming what
it read plus what this cycle actually sent, **never** a full local
inventory, and **nothing is ever removed from it**.

**This module imports nothing from the export package or the capture
package** (ADR 0021's reasoning for :mod:`arichds.dataout` applies here too
— spec.md "Module"). It reads the export folder and the capture folder as
folders: the file on disk is the contract — the export group is found by
**listing** ``export_dir`` and matching each entry against the three
filename templates, never by predicting a name and hoping it exists on disk
(reviewer finding, ticket 02 round 1: a hand-computed name silently stops
matching the moment the product's naming rule changes, and permanently
hides an earlier day's file once an operator's template carries ``[date]``).
The token substitution itself lives in :mod:`arichds.filename_tokens`, at
the top of the package like :mod:`arichds.interval_status` — the one place
this module and ``export/format.py::render_filename`` (which now delegates
to it) can both reach without either importing the other.

**One transport seam** (:mod:`arichds.fileupload.transport`). Everything
this module decides — which files, in what order, the budget, the status —
is protocol-blind; the three real transports land in tickets 03-05. Until
then :func:`_build_transport` always answers ``None``, so a fully configured
page still moves no bytes (spec.md ticket 02's own scope line) — the cycle
below is reachable in production only once a real transport exists, and in
tests today only through the ``transport`` parameter.
"""

from __future__ import annotations

import hashlib
import logging
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

import sqlalchemy as sa

from arichds.config import get_settings
from arichds.constants import FILEUPLOAD_BUDGET_SEC
from arichds.db.app_settings import (
    CAPTURE_DIR_DEFAULT,
    CAPTURE_DIR_KEY,
    EXPORT_BILLING_FILENAME_TMPL_DEFAULT,
    EXPORT_BILLING_FILENAME_TMPL_KEY,
    EXPORT_CSV_FILENAME_TMPL_DEFAULT,
    EXPORT_CSV_FILENAME_TMPL_KEY,
    EXPORT_ENERGY_FILENAME_TMPL_DEFAULT,
    EXPORT_ENERGY_FILENAME_TMPL_KEY,
    EXPORT_OUTPUT_DIR_DEFAULT,
    EXPORT_OUTPUT_DIR_KEY,
    get_setting,
)
from arichds.db.models import Device
from arichds.db.session import session_scope
from arichds.filename_tokens import export_filename_pattern
from arichds.fileupload.config import FileUploadConfig, load_config
from arichds.fileupload.manifest import MANIFEST_VERSION, Manifest, ManifestEntry
from arichds.fileupload.status import CycleStatus, set_last_cycle
from arichds.fileupload.transport import Transport, TransportError
from arichds.licensing.current import current_license_service
from arichds.licensing.features import feature_enabled

if TYPE_CHECKING:
    from collections.abc import Sequence

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class _Candidate:
    """One local file this cycle might send — its remote-relative path
    (ADR 0025 decision 4's layout) and where it lives on disk."""

    relative_path: str
    local_path: Path


class _Counts:
    """One cycle's running totals, so a partial cycle still reports honestly
    — the same shape ``dataout/sync.py::_Counts``/``centralpush/cycle.py::_Counts``
    use."""

    __slots__ = (
        "bytes_sent",
        "files_sent",
        "files_skipped_budget",
        "files_skipped_no_serial",
        "files_skipped_unchanged",
    )

    def __init__(self) -> None:
        self.files_sent = 0
        self.bytes_sent = 0
        self.files_skipped_unchanged = 0
        self.files_skipped_budget = 0
        self.files_skipped_no_serial = 0


def _active_configured(config: FileUploadConfig) -> bool:
    """Whether the active protocol has enough to attempt a connection —
    "an active protocol with no host/URL means the cycle does nothing"."""
    if config.active_protocol == "sftp":
        return bool(config.sftp.host)
    if config.active_protocol == "ftps":
        return bool(config.ftps.host)
    if config.active_protocol == "https":
        return bool(config.https.url)
    return False


def _build_transport(config: FileUploadConfig) -> Transport | None:
    """Build the real transport for *config*'s active protocol.

    Real transports land in tickets 03-05 (SFTP/FTPS/HTTPS, ADR 0025). Until
    then this always returns ``None`` — a configured page still moves no
    bytes (spec.md ticket 02: "after this ticket a configured page still
    moves no bytes") — so the cycle below is reached in production only
    once a real transport exists; today it is reached only through the
    ``transport`` parameter (tests, and ``Upload now`` once a real
    transport lands).
    """
    del config  # unused until tickets 03-05 register a builder per protocol
    return None


def _is_export_temp_file(name: str) -> bool:
    """Whether *name* is one of ``export/writer.py``'s own atomic-replace
    temp files (``.{stem}.{random}.tmp`` — ``export/writer.py:249``,
    ``tempfile.mkstemp(dir=path.parent, prefix=f".{path.stem}.",
    suffix=".tmp")``) — never a real export file, and never a candidate
    (reviewer finding, ticket 02 round 1: a folder-listing implementation
    must not treat one as a device's export file)."""
    return name.startswith(".") and name.endswith(".tmp")


def _export_candidates(
    export_dir: Path, *, csv_tmpl: str, billing_tmpl: str, energy_tmpl: str, devices: Sequence[Device], counts: _Counts
) -> list[_Candidate]:
    """The export files each device with a Meter Serial currently has on
    disk under *export_dir* — found by **listing** the folder once and
    matching each entry against the three filename templates
    (:func:`~arichds.filename_tokens.export_filename_pattern`), never by
    predicting a name and hoping it exists (spec.md "Files in scope": "the
    three export files the export folder holds for it" — the file on disk
    is the contract, module docstring). A device with no Meter Serial
    contributes nothing and is counted once, not once per template (SPEC
    story 12 / spec.md Testing Decisions: "a device without a Meter Serial
    is skipped and counted").

    Non-recursive — `export_dir` holds no subfolders, unlike the capture
    folder. ``export/writer.py``'s own atomic-replace temp files are
    excluded; nothing else under `export_dir` is ever a candidate.

    Every match for a device's *csv_tmpl* precedes every match for its
    *billing_tmpl*, which precedes every match for its *energy_tmpl* — the
    ordering ``TestTransportErrorMidCycle`` relies on. A template carrying
    ``[date]`` can legitimately match more than one file (one per day it
    was written), and every match is a candidate — a name predicted for
    "today" alone is exactly the bug this design replaces (an earlier
    day's file was permanently invisible to the cycle).

    De-duplicated by relative path as candidates are collected — belt and
    braces (reviewer finding, ticket 02 round 2): two of the three
    templates can only ever collide on the same file if neither carries
    ``[meter]``/``[serial]`` at all, which already breaks the export writer
    itself, so this is unreachable with any template this product's own
    settings validation accepts. Without it, a colliding file would be
    digested, ``put_file``'d and counted twice in one cycle, since the
    in-cycle compare only consults the manifest as read, never
    ``sent_entries``.
    """
    if not export_dir.is_dir():
        return []

    try:
        entries = sorted(
            entry.name for entry in export_dir.iterdir() if entry.is_file() and not _is_export_temp_file(entry.name)
        )
    except OSError:
        return []

    candidates: list[_Candidate] = []
    seen: set[str] = set()
    for device in devices:
        if not device.meter_serial:
            counts.files_skipped_no_serial += 1
            continue
        token = device.meter_serial
        for template in (csv_tmpl, billing_tmpl, energy_tmpl):
            # `export_filename_pattern` escapes *token* before compiling
            # (ADR 0005: a meter-supplied serial is device identity, not
            # operator input), so it cannot widen the match with a regex
            # metacharacter — this plays the role an earlier version's
            # path-containment check did when it built a path by string
            # concatenation; every name here already came from `iterdir()`
            # above, so there is no path left to escape out of.
            pattern = export_filename_pattern(template, token)
            for name in entries:
                if not pattern.match(name):
                    continue
                relative_path = f"export/{name}"
                if relative_path in seen:
                    continue
                seen.add(relative_path)
                candidates.append(_Candidate(relative_path=relative_path, local_path=export_dir / name))
    return candidates


def _capture_candidates(capture_dir: Path) -> list[_Candidate]:
    """Every file under *capture_dir*, mirrored one-to-one under
    ``captures/`` (ADR 0025 decision 4). Not filtered by device — ADR 0015's
    own layout (``<capture_dir>/<serial>/<bill_date>.{pdf,xlsx,png}``)
    already names each file's Meter Serial in its own path, so walking the
    folder whole reproduces the remote layout with no correlation logic."""
    if not capture_dir.is_dir():
        return []
    candidates: list[_Candidate] = []
    for path in sorted(capture_dir.rglob("*")):
        if path.is_file():
            relative = path.relative_to(capture_dir).as_posix()
            candidates.append(_Candidate(relative_path=f"captures/{relative}", local_path=path))
    return candidates


def _digest_and_size(path: Path) -> tuple[str, int]:
    """*path*'s sha256 and size, read in chunks so a large capture document
    is never loaded whole into memory."""
    hasher = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            hasher.update(chunk)
    return hasher.hexdigest(), path.stat().st_size


def _out_of_budget(deadline: float) -> bool:
    return time.monotonic() >= deadline


def file_upload_cycle(transport: Transport | None = None) -> None:
    """Send every export file and capture document the server's Upload
    Manifest does not already have.

    The Scheduler's ``file_upload`` job (:func:`arichds.jobs.scheduler.default_jobs`),
    registered last. *transport* lets a caller inject one directly — the
    cycle tests' in-memory transport, and ``POST .../upload-now``'s manual
    trigger once a real transport exists; the scheduler job itself always
    calls this with no argument, so :func:`_build_transport` decides.

    Nothing propagates: a failure is recorded on the in-memory status
    (:mod:`arichds.fileupload.status`) and the job runs again in fifteen
    minutes, the same contract ``central_push_cycle``/
    ``database_destination_cycle`` already keep.
    """
    settings = get_settings()
    license_service = current_license_service()
    if license_service is None:
        # No LicenseService published means "not booted yet" or "running
        # outside the app" — `centralpush.cycle`'s own reasoning. Without it
        # there is no Machine ID for the manifest either, so the cycle
        # cannot run at all.
        return
    if not feature_enabled("file_upload_destination", license_service=license_service, settings=settings):
        return

    with session_scope() as session:
        config = load_config(session)
        export_dir_str = get_setting(session, EXPORT_OUTPUT_DIR_KEY, EXPORT_OUTPUT_DIR_DEFAULT).strip()
        capture_dir_str = get_setting(session, CAPTURE_DIR_KEY, CAPTURE_DIR_DEFAULT).strip()
        csv_tmpl = get_setting(session, EXPORT_CSV_FILENAME_TMPL_KEY, EXPORT_CSV_FILENAME_TMPL_DEFAULT)
        billing_tmpl = get_setting(session, EXPORT_BILLING_FILENAME_TMPL_KEY, EXPORT_BILLING_FILENAME_TMPL_DEFAULT)
        energy_tmpl = get_setting(session, EXPORT_ENERGY_FILENAME_TMPL_KEY, EXPORT_ENERGY_FILENAME_TMPL_DEFAULT)
        devices = list(session.scalars(sa.select(Device).order_by(Device.id)))

    if not config.active_protocol or not _active_configured(config):
        logger.debug("File Upload Destination: not configured — nothing to do")
        # Published even though no transport was ever touched (reviewer
        # finding, ticket 02 round 1): the criterion is "the cycle does
        # nothing and REPORTS that it was not configured" — without this,
        # `GET .../status` cannot tell "judged unconfigured" apart from
        # "has never run since start", and the page shows the same
        # "Not yet run since start" copy either way.
        set_last_cycle(CycleStatus(ran_at=datetime.now(UTC), protocol=config.active_protocol, outcome="not_configured"))
        return

    if transport is None:
        transport = _build_transport(config)
    if transport is None:
        logger.debug(
            "File Upload Destination: protocol %r is configured but no transport implementation exists yet "
            "(tickets 03-05) — nothing sent",
            config.active_protocol,
        )
        return

    machine_id = license_service.machine_id

    _run_cycle(
        transport,
        protocol=config.active_protocol,
        machine_id=machine_id,
        export_dir_str=export_dir_str,
        capture_dir_str=capture_dir_str,
        csv_tmpl=csv_tmpl,
        billing_tmpl=billing_tmpl,
        energy_tmpl=energy_tmpl,
        devices=devices,
    )


def _run_cycle(
    transport: Transport,
    *,
    protocol: str,
    machine_id: str,
    export_dir_str: str,
    capture_dir_str: str,
    csv_tmpl: str,
    billing_tmpl: str,
    energy_tmpl: str,
    devices: Sequence[Device],
) -> None:
    started = time.monotonic()
    deadline = started + FILEUPLOAD_BUDGET_SEC
    counts = _Counts()
    outcome = "success"
    error: str | None = None

    candidates: list[_Candidate] = []
    if export_dir_str:
        candidates.extend(
            _export_candidates(
                Path(export_dir_str),
                csv_tmpl=csv_tmpl,
                billing_tmpl=billing_tmpl,
                energy_tmpl=energy_tmpl,
                devices=devices,
                counts=counts,
            )
        )
    if capture_dir_str:
        candidates.extend(_capture_candidates(Path(capture_dir_str)))

    # A missing or unreadable manifest means "send everything" (ADR 0025
    # decision 2) — the read failing is not the same fact as a put/write
    # failing below, so it is caught here alone and never ends the cycle
    # `skipped` by itself.
    try:
        manifest = transport.read_manifest()
        manifest_was_read = manifest is not None
    except TransportError:
        manifest = None
        manifest_was_read = False
    if manifest is None:
        manifest = Manifest(version=MANIFEST_VERSION, machine_id=machine_id, files={})

    sent_entries: dict[str, ManifestEntry] = {}
    try:
        for index, candidate in enumerate(candidates):
            if _out_of_budget(deadline):
                counts.files_skipped_budget += len(candidates) - index
                break
            digest, size = _digest_and_size(candidate.local_path)
            existing = manifest.files.get(candidate.relative_path)
            if existing is not None and existing.sha256 == digest:
                counts.files_skipped_unchanged += 1
                continue
            transport.put_file(candidate.relative_path, candidate.local_path)
            sent_entries[candidate.relative_path] = ManifestEntry(
                sha256=digest, size=size, uploaded_at=datetime.now(UTC)
            )
            counts.files_sent += 1
            counts.bytes_sent += size
    except TransportError as exc:
        outcome = "skipped"
        error = type(exc).__name__
        logger.warning("File Upload Destination cycle ended skipped — %s", error)
    except Exception as exc:  # noqa: BLE001 — a misbehaving transport must never strand the scheduler.
        outcome = "skipped"
        error = type(exc).__name__
        # `logger.warning`, never `logger.exception` — the latter attaches
        # the full traceback (`exc_info`), which the redaction filter does
        # NOT scrub (it only rewrites `record.getMessage()`), so it would
        # print `str(exc)` — and any secret it happens to carry — straight
        # to the log. Only the class name is ever named here, the same as
        # the `TransportError` branch above.
        logger.warning("File Upload Destination cycle ended skipped — %s", error)

    # Computed **outside** the try/except above and considered unconditionally
    # — even after a `put_file` failure ends the loop early, whatever landed
    # in `sent_entries` before the failure must still reach the manifest
    # (spec.md Testing Decisions: "a transport error mid-cycle ends skipped
    # and the manifest still names what arrived"). Names only what was read
    # plus what was actually sent this cycle — never a full local inventory.
    # An entry already in `manifest.files` for a file no longer among
    # `candidates` (deleted locally, or unreached this pass) survives
    # untouched: nothing is ever removed (ADR 0025 decision 3).
    #
    # The write itself is skipped entirely when the read succeeded intact
    # and nothing was sent (reviewer finding, ticket 02 round 1, problem 6):
    # the merged manifest would then be byte-identical to what the server
    # already holds, so writing it is a round trip that buys nothing every
    # fifteen minutes on a quiet machine. A fresh or unreadable root
    # (`manifest_was_read` False) still gets a write even with nothing sent,
    # so it is never left un-visited.
    if not (manifest_was_read and not sent_entries):
        new_manifest = Manifest(
            version=manifest.version, machine_id=machine_id, files={**manifest.files, **sent_entries}
        )
        try:
            transport.write_manifest(new_manifest)
        except TransportError as exc:
            outcome = "skipped"
            error = type(exc).__name__
            logger.warning("File Upload Destination cycle ended skipped — %s", error)
        except Exception as exc:  # noqa: BLE001 — a misbehaving transport must never strand the scheduler.
            outcome = "skipped"
            error = type(exc).__name__
            # See the identical comment on the loop's own `except Exception`
            # branch above — no `logger.exception`, for the same reason.
            logger.warning("File Upload Destination cycle ended skipped — %s", error)

    set_last_cycle(
        CycleStatus(
            ran_at=datetime.now(UTC),
            protocol=protocol,
            outcome=outcome,
            files_sent=counts.files_sent,
            bytes_sent=counts.bytes_sent,
            files_skipped_unchanged=counts.files_skipped_unchanged,
            files_skipped_budget=counts.files_skipped_budget,
            files_skipped_no_serial=counts.files_skipped_no_serial,
            duration_sec=round(time.monotonic() - started, 3),
            error=error,
        )
    )
    logger.info(
        "File Upload Destination cycle: %d file(s) sent (%d byte(s)), %d unchanged, %d left for the next cycle by "
        "budget, %d device(s) with no Meter Serial, in %.2fs%s",
        counts.files_sent,
        counts.bytes_sent,
        counts.files_skipped_unchanged,
        counts.files_skipped_budget,
        counts.files_skipped_no_serial,
        time.monotonic() - started,
        "" if outcome == "success" else f" ({outcome}: {error})",
    )


__all__ = ["file_upload_cycle"]
