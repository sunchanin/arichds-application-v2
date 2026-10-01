"""The Logger 1/2 merge — one query, shared by the Load Profile page, the CSV
exporter (M7 slice 3, issue #30, D-2) and the Database Destination (ADR 0027).

Extracted from ``api/load_profile.py`` (owner ruling, 2026-08-11): the page's
``GET`` and the CSV export both need "Logger 1 is the spine, Logger 2 is
outer-joined on an exact ``read_at`` match, every measurement column is
``COALESCE(logger1, logger2)``". Two implementations of that rule means one
of them drifts one day with nothing to catch it, because each side only
tests itself.

It lives under ``db/`` rather than ``acquisition/`` for the same reason
``db/retention.py:11-12`` gives its own placement: it reads no meter, builds
no driver and takes no Transport Endpoint lock — its domain is the rows.

**No time window, no ordering, no paging.** Those belong to the caller: the
Load Profile page pages newest-first over an operator-picked range, the CSV
exporter walks oldest-first over a watermark-to-cap window. Baking either
into this module would make one of the two callers work around a decision
that was never theirs.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import Select, func, or_, select
from sqlalchemy.orm import Session, aliased

from arichds.db.models import LoadProfileReading
from arichds.interval_status import ALL_INVALID_MASK

#: Logger 2, joined against the Logger 1 spine — never queried on its own here.
_Logger2 = aliased(LoadProfileReading)

#: F5 — how far Logger 2 may lag Logger 1 before the staleness escape
#: releases held rows anyway (v1's `LP_L2_SKEW_MAX_HOURS`).
SKEW_CAP = timedelta(hours=24)

#: The measurement columns both callers render, in COALESCE(logger1, logger2)
#: order — Logger 1 wins. Formerly ``api/load_profile.py``'s private
#: ``_MEASUREMENT_COLUMNS``.
#:
#: **Twenty-three since M13 issue 06/07.** The COALESCE is what makes the three
#: line-to-line voltages work at all: on a Prometer 100 they are captured by
#: **Logger 2** while everything else here comes from Logger 1, so the spine row
#: holds NULL for them and the join supplies the value. The Prometer 100's
#: Logger 2 runs at 300 s against Logger 1's 900 s, so only every third Logger 2
#: row has an exact ``read_at`` match — that is the shipped merge behaviour and
#: it is unchanged here.
MERGED_COLUMNS = (
    "import_active_kwh",
    "import_reactive_kvarh",
    "export_active_kwh",
    "export_reactive_kvarh",
    "avg_geo_pf",
    "volt_l1",
    "volt_l2",
    "volt_l3",
    "current_l1",
    "current_l2",
    "current_l3",
    "freq",
    # M13, issue 06/07 — the eleven the customer asked for.
    "phase_angle_a",
    "phase_angle_b",
    "phase_angle_c",
    "interval_status_flag",
    "import_active_kw",
    "import_reactive_kvar",
    "export_active_kw",
    "export_reactive_kvar",
    "volt_l1_l2",
    "volt_l2_l3",
    "volt_l3_l1",
)


def merged_rows_select(device_id: int) -> Select:
    """Logger 1 spine, Logger 2 outer-joined on an exact ``read_at``, COALESCE per column.

    Selects ``read_at`` plus the twenty-three :data:`MERGED_COLUMNS`, filtered to
    *device_id* and ``logger_id == 1`` (Logger 1 is the spine the whole merge
    is keyed on — a device with only a Logger 2 shows nothing, matching the
    page's existing behaviour). The caller adds its own time window,
    ``order_by`` and paging.

    Args:
        device_id: Which device's rows to select.

    Returns:
        An unordered, unpaged ``Select`` yielding ``(read_at, *MERGED_COLUMNS)``.
    """
    merged_columns = [
        func.coalesce(getattr(LoadProfileReading, name), getattr(_Logger2, name)).label(name) for name in MERGED_COLUMNS
    ]
    return (
        select(LoadProfileReading.read_at, *merged_columns)
        .outerjoin(
            _Logger2,
            (_Logger2.device_id == LoadProfileReading.device_id)
            & (_Logger2.read_at == LoadProfileReading.read_at)
            & (_Logger2.logger_id == 2),
        )
        .where(
            LoadProfileReading.device_id == device_id,
            LoadProfileReading.logger_id == 1,
            # v1's INV-LP-06 — an interval the meter marked all-invalid is
            # excluded from both the page and the CSV
            # (`cewe/.../load_profile/repository.py:204,242,260,290,329`). A
            # NULL word means the model records none, and those rows stay.
            #
            # Applied here rather than at each caller on purpose, and for the
            # reason this function already exists: the page's rows, the page's
            # `total` and the CSV's rows all build on this Select, so a
            # predicate added at one caller would leave a page whose rows and
            # whose count disagree.
            or_(
                LoadProfileReading.interval_status_flag.is_(None),
                LoadProfileReading.interval_status_flag.op("&")(ALL_INVALID_MASK) == 0,
            ),
        )
    )


def _as_utc(value: datetime) -> datetime:
    """SQLite hands back naive datetimes; every stored timestamp is UTC."""
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


def _logger_max(session: Session, device_id: int, logger_id: int, column: str = "read_at") -> datetime | None:
    """``MAX(column)`` over one device's one Logger, UTC-aware, or ``None``."""
    newest = session.scalar(
        select(func.max(getattr(LoadProfileReading, column))).where(
            LoadProfileReading.device_id == device_id, LoadProfileReading.logger_id == logger_id
        )
    )
    return _as_utc(newest) if newest is not None else None


def merged_rows_l1_max(session: Session, device_id: int) -> datetime | None:
    """The spine's frontier — this device's ``MAX(read_at)`` on Logger 1.

    ``None`` when it holds no Logger 1 row: a brand-new device that has never
    reported, or one whose every Logger 1 row has aged out past
    ``RETENTION_DAYS``. Either way there is nothing to merge onto. One
    definition for both writers of merged rows (the CSV exporter and the
    Database Destination).
    """
    return _logger_max(session, device_id, 1)


def merged_rows_cap(
    session: Session,
    device_id: int,
    l1_max: datetime,
    has_secondary_logger: bool,
    *,
    never_rewritten: bool = False,
    now_utc: datetime | None = None,
) -> datetime:
    """F5 — the inclusive upper bound of what may be written out as merged rows.

    A merged row that has left the building is never rewritten — the Load
    Profile CSV only appends, and a Database Destination row never changes
    (ADR 0020) — so a Logger 1 row sent before its Logger 2 partner was read
    would stay half-empty for good. This holds Logger 1 rows back until Logger 2
    has caught up, and gives up after :data:`SKEW_CAP`. Moved here from
    ``export/csv_export.py`` (where it was ``_compute_cap``) when the Database
    Destination became the second writer that needs it: ``dataout/`` must not
    import ``export/`` (ADR 0021), and two copies of this rule would drift.

    **The 24 h escape means different things to the two writers**, which is what
    *never_rewritten* says. The load-profile walk reads Logger 1 to the present
    before Logger 2 gets more than one chunk per visit, so after a long backfill
    Logger 2 is *days* behind while still arriving — and the plain escape would
    release every Logger 1 row half-empty. The CSV can afford that: its daily
    whole-window rewrite (ADR 0023) fills them in. The Database Destination
    cannot — a sent row is never rewritten (ADR 0020) — so for it the escape
    fires only once Logger 2 has **stored nothing** for :data:`SKEW_CAP`, read
    off ``MAX(created_at)`` (first-store time; the upsert never touches it), and
    until then rows are released only up to Logger 2's own frontier. Stateless,
    as ADR 0008 requires.

    Args:
        session: Active DB session.
        device_id: The device being written out.
        l1_max: This device's ``MAX(read_at)`` on Logger 1 — never ``None``
            (a device with no Logger 1 rows has nothing to merge onto).
        has_secondary_logger: Whether the driver reports a Logger 2 (D-12) —
            from the driver, never from the data.
        never_rewritten: ``True`` for a writer that cannot repair a row it has
            sent — see above.
        now_utc: The present, for *never_rewritten*'s test of "still arriving";
            defaults to the wall clock.

    Returns:
        The inclusive upper-bound ``read_at``.
    """
    if not has_secondary_logger:
        return l1_max

    l2_max = _logger_max(session, device_id, 2)
    if l2_max is None:
        # Logger 2 never seen — hold everything within the skew window.
        return l1_max - SKEW_CAP
    if l2_max >= l1_max - SKEW_CAP:
        # Logger 2 present and within the window — hold rows past its frontier.
        return min(l1_max, l2_max)
    if never_rewritten:
        l2_last_stored = _logger_max(session, device_id, 2, "created_at")
        now = now_utc if now_utc is not None else datetime.now(UTC)
        if l2_last_stored is not None and l2_last_stored >= now - SKEW_CAP:
            # Far behind but still arriving — a backfill, not a dead Logger.
            return l2_max
    # Logger 2 stale beyond the window — staleness escape, release everything.
    return l1_max
