"""The Energy Summary aggregation — the Time-of-Use daily split (M7-1, issue
#28; extracted at M13, issue 02).

Extracted from ``api/energy.py`` for the reason
:mod:`arichds.db.billing_query` gives for its own extraction: the Energy
Summary export file needs exactly this result and must call it directly rather
than issue HTTP against its own process. Two implementations of the same
aggregation means one of them drifts one day with nothing to catch it, because
each side only tests itself.

The move was **forced** rather than chosen: the exporter importing
``api/energy`` closed a cycle through ``api/deps`` and the scheduler. A query
that both a route and a background job need was living in the route's module,
and the import graph said so.

**Nothing is stored and nothing is cached.** ADR 0012 makes this derived on
every request precisely so that adding a Holiday today changes what last
January reports tomorrow.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta

from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.orm import Session

from arichds.constants import (
    METER_LOCAL_UTC_OFFSET_HOURS,
    TOU_PEAK_END_UTC,
    TOU_PEAK_START_UTC,
)

#: Logger 1 carries the energy columns on every model (decision 6, `base.py`
#: D2 module docstring) — the only correct answer, so there is no logger
#: selector on the endpoint.
_LOGGER_ID = 1

#: SQLite date-modifier form of :data:`~arichds.constants.METER_LOCAL_UTC_OFFSET_HOURS`.
_TZ_SHIFT = f"{METER_LOCAL_UTC_OFFSET_HOURS:+d} hours"

#: A day is a Holiday when it is a Saturday/Sunday in ICT, or matches an
#: ``annual`` row on month+day, or matches a ``public`` row on the exact
#: date (CONTEXT.md — Holiday). ``strftime('%w', ...)`` is SQLite's
#: day-of-week, **0 = Sunday** (the MySQL ``DAYOFWEEK`` v1 used is 1 = Sunday
#: — the translation trap this predicate exists to get right).
_IS_HOLIDAY_PREDICATE = """(
            strftime('%w', date(lr.read_at, :tz_shift)) IN ('0', '6')
            OR EXISTS (
                SELECT 1 FROM holidays h
                WHERE h.kind = 'public' AND h.date = date(lr.read_at, :tz_shift)
            )
            OR EXISTS (
                SELECT 1 FROM holidays h
                WHERE h.kind = 'annual'
                  AND h.month = CAST(strftime('%m', date(lr.read_at, :tz_shift)) AS INTEGER)
                  AND h.day = CAST(strftime('%d', date(lr.read_at, :tz_shift)) AS INTEGER)
            )
        )"""

#: Every interval on a Holiday date is Holiday energy, including intervals
#: inside the peak window (CONTEXT.md — Energy Summary: "Holiday is one
#: bucket that swallows weekends and both kinds of Holiday alike"). The peak
#: hour test is **UTC, unshifted** on both sides — see the module docstring.
_ENERGY_SUMMARY_SQL = text(
    """
    SELECT
        date(lr.read_at, :tz_shift) AS record_date,

        SUM(CASE
            WHEN {is_holiday}                                          THEN 0
            WHEN CAST(strftime('%H', lr.read_at) AS INTEGER) >= :peak_start
             AND CAST(strftime('%H', lr.read_at) AS INTEGER) <  :peak_end THEN lr.import_active_kwh
            ELSE 0
        END)                    AS peak_import_kwh,

        SUM(CASE
            WHEN {is_holiday}                                          THEN 0
            WHEN CAST(strftime('%H', lr.read_at) AS INTEGER) <  :peak_start
              OR CAST(strftime('%H', lr.read_at) AS INTEGER) >= :peak_end THEN lr.import_active_kwh
            ELSE 0
        END)                    AS offpeak_import_kwh,

        SUM(CASE WHEN {is_holiday} THEN lr.import_active_kwh ELSE 0 END) AS holiday_import_kwh,
        SUM(lr.import_active_kwh)                                        AS total_import_kwh,

        SUM(CASE
            WHEN {is_holiday}                                          THEN 0
            WHEN CAST(strftime('%H', lr.read_at) AS INTEGER) >= :peak_start
             AND CAST(strftime('%H', lr.read_at) AS INTEGER) <  :peak_end THEN lr.export_active_kwh
            ELSE 0
        END)                    AS peak_export_kwh,

        SUM(CASE
            WHEN {is_holiday}                                          THEN 0
            WHEN CAST(strftime('%H', lr.read_at) AS INTEGER) <  :peak_start
              OR CAST(strftime('%H', lr.read_at) AS INTEGER) >= :peak_end THEN lr.export_active_kwh
            ELSE 0
        END)                    AS offpeak_export_kwh,

        SUM(CASE WHEN {is_holiday} THEN lr.export_active_kwh ELSE 0 END) AS holiday_export_kwh,
        SUM(lr.export_active_kwh)                                        AS total_export_kwh

    FROM load_profile_readings lr
    WHERE lr.device_id = :device_id
      AND lr.logger_id = :logger_id
      AND lr.read_at  >= :start_dt
      AND lr.read_at  <  :end_dt
    GROUP BY date(lr.read_at, :tz_shift)
    ORDER BY record_date
    """.replace("{is_holiday}", _IS_HOLIDAY_PREDICATE)
)


class EnergySummaryDay(BaseModel):
    """One local calendar day's Time-of-Use buckets, import and export
    (CONTEXT.md — Energy Summary). Only active energy — the reactive columns
    are deliberately never aggregated (decision 8)."""

    date: date
    peak_import_kwh: float
    offpeak_import_kwh: float
    holiday_import_kwh: float
    total_import_kwh: float
    peak_export_kwh: float
    offpeak_export_kwh: float
    holiday_export_kwh: float
    total_export_kwh: float


class EnergySummaryReport(BaseModel):
    """The Summary Report tab's whole answer — one row per local day that has
    at least one stored Interval Reading in range. A day with none is simply
    absent, mirroring v1's own ``GROUP BY`` (there is no capture period to
    judge completeness against here, unlike ``api/records.py``)."""

    days: list[EnergySummaryDay]


def _local_midnight_utc(day: date) -> datetime:
    """The UTC instant at which *day* begins in the meter's fixed local zone."""
    return datetime.combine(day, time.min, UTC) - timedelta(hours=METER_LOCAL_UTC_OFFSET_HOURS)


def energy_summary_rows(session: Session, device_id: int, start_date: date, end_date: date) -> list[EnergySummaryDay]:
    """Run the TOU aggregation over ``[start_date, end_date]`` (both local,
    inclusive) for *device_id*'s Logger 1.

    A thin wrapper around :data:`_ENERGY_SUMMARY_SQL` — the SQL does the
    whole classification; this only binds the range and shapes the response.
    """
    start_dt = _local_midnight_utc(start_date)
    end_dt = _local_midnight_utc(end_date + timedelta(days=1))

    rows = session.execute(
        _ENERGY_SUMMARY_SQL,
        {
            "device_id": device_id,
            "logger_id": _LOGGER_ID,
            "start_dt": start_dt,
            "end_dt": end_dt,
            "peak_start": TOU_PEAK_START_UTC,
            "peak_end": TOU_PEAK_END_UTC,
            "tz_shift": _TZ_SHIFT,
        },
    ).all()

    return [
        EnergySummaryDay(
            date=date.fromisoformat(row.record_date),
            peak_import_kwh=row.peak_import_kwh or 0.0,
            offpeak_import_kwh=row.offpeak_import_kwh or 0.0,
            holiday_import_kwh=row.holiday_import_kwh or 0.0,
            total_import_kwh=row.total_import_kwh or 0.0,
            peak_export_kwh=row.peak_export_kwh or 0.0,
            offpeak_export_kwh=row.offpeak_export_kwh or 0.0,
            holiday_export_kwh=row.holiday_export_kwh or 0.0,
            total_export_kwh=row.total_export_kwh or 0.0,
        )
        for row in rows
    ]
