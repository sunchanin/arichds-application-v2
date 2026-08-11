"""The Logger 1/2 merge — one query, shared by the Load Profile page and the
CSV exporter (M7 slice 3, issue #30, D-2).

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

from sqlalchemy import Select, func, select
from sqlalchemy.orm import aliased

from arichds.db.models import LoadProfileReading

#: Logger 2, joined against the Logger 1 spine — never queried on its own here.
_Logger2 = aliased(LoadProfileReading)

#: The twelve measurement columns both callers render, in
#: COALESCE(logger1, logger2) order — Logger 1 wins. Formerly
#: ``api/load_profile.py``'s private ``_MEASUREMENT_COLUMNS``.
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
)


def merged_rows_select(device_id: int) -> Select:
    """Logger 1 spine, Logger 2 outer-joined on an exact ``read_at``, COALESCE per column.

    Selects ``read_at`` plus the twelve :data:`MERGED_COLUMNS`, filtered to
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
        .where(LoadProfileReading.device_id == device_id, LoadProfileReading.logger_id == 1)
    )
