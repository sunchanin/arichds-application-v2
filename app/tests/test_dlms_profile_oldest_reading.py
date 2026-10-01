"""``DlmsProfileDriver.load_profile_oldest_reading`` — the backfill clamp, driven
against the **real** method with a scripted reader.

The suite-wide fake overrides this method (``fakes.py``), so until this file no
test executed a line of it — and a customer site (TC, 2026-09-20) found the hole:
a CEWE meter two days into service refused **every** entry-access read of its
load profile (``Access Error : Other Reason``), so the clamp answered ``None``,
the walk kept its full 90-day window, and the first chunk — 88 days before the
meter's oldest row — came back ``Data Block Unavailable``, which is how a
Prometer 100 says "no entries in that window" (measured on the healthy lab unit
the same day: a 24 h range in 2020 is refused, not answered with ``[]``). Every
cycle re-walked the same refused chunk and nothing was ever stored.

The fix is a **fallback, not a replacement**: when entry 1 cannot be read but the
profile's own attributes can, the oldest row is *estimated* from
``entries_in_use x capture_period``. Measured on the lab Prometer 100 — which
refuses entry access exactly as the site's unit does — the estimate lands 20 min
(Logger 1) and 10 min (Logger 2) *before* the true oldest row over ~100 days of
buffer; it is late by the downtime on a meter that stopped logging, which is why
a meter that answers entry 1 never reaches it. The site's numbers, from
``scripts/probe_lp_buffer.py``: 176 entries x 900 s = 44 h, and a range starting
*before* the oldest row is answered as long as it overlaps the buffer.
``docs/meter-notes/prometer100-load-profile-access.md`` holds the measurements.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any

import pytest
from gurux_dlms.objects import GXDLMSProfileGeneric

from arichds.acquisition import load_profile
from arichds.acquisition.connection_params import ConnectionParams
from arichds.acquisition.drivers._dlms_profile import DlmsProfileDriver
from arichds.acquisition.obis import INSTANTANEOUS_OBIS
from arichds.constants import LOAD_PROFILE_BACKFILL_DAYS, METER_LOCAL_UTC_OFFSET_HOURS

CLOCK_OBIS = "0.0.1.0.0.255"


class _RefusedError(Exception):
    """Stands in for ``GXDLMSException`` — the driver must not care which class
    a refusal arrives as, only that the read did not answer."""


class _OneLoggerDriver(DlmsProfileDriver):
    """A minimal concrete driver declaring Logger 1 — not a real meter family."""

    LOAD_PROFILE_COLUMN_MAP = {1: {}}

    def _protocol_args(self) -> list[str]:
        return []

    def _read_timeout_ms(self) -> int:
        return 1000

    @property
    def model_name(self) -> str:
        return "fake_lp"

    def get_obis_map(self) -> dict[str, tuple[str, int]]:
        return dict(INSTANTANEOUS_OBIS)


class _ScriptedReader:
    """The ``GXDLMSReader`` subset the clamp calls, each answer scripted.

    Any attribute or the entry read can be told to raise, which is the whole
    point: the site's meter answered attrs 3, 4 and 7 and refused the rows.
    """

    def __init__(
        self,
        *,
        entries_in_use: Any = 176,
        capture_period: Any = 900,
        oldest_local: datetime | None = None,
        refuse_entry: bool = False,
        refuse_attrs: frozenset[int] = frozenset(),
    ) -> None:
        self._entries_in_use = entries_in_use
        self._capture_period = capture_period
        self._oldest_local = oldest_local
        self._refuse_entry = refuse_entry
        self._refuse_attrs = refuse_attrs
        self.attrs_read: list[int] = []
        self.entry_reads: list[tuple[int, int]] = []

    def read(self, obj: Any, attr: int) -> Any:
        assert isinstance(obj, GXDLMSProfileGeneric)
        self.attrs_read.append(attr)
        if attr in self._refuse_attrs:
            raise _RefusedError(f"attr {attr} refused")
        if attr == 3:
            obj.captureObjects = [(SimpleNamespace(logicalName=CLOCK_OBIS), SimpleNamespace(attributeIndex=2))]
            return obj.captureObjects
        if attr == 4:
            return self._capture_period
        if attr == 7:
            return self._entries_in_use
        raise AssertionError(f"unexpected ProfileGeneric attr {attr}")

    def readRowsByEntry(self, pg: Any, index: int, count: int) -> list[list[Any]]:  # noqa: N802
        self.entry_reads.append((index, count))
        if self._refuse_entry:
            raise _RefusedError("Access Error : Other Reason.")
        return [[self._oldest_local]] if self._oldest_local is not None else []


def _driver(reader: _ScriptedReader) -> _OneLoggerDriver:
    driver = _OneLoggerDriver(ConnectionParams.net("198.51.100.9", 4059), password="secret")
    driver._reader = reader  # noqa: SLF001
    driver._client = SimpleNamespace(objects=[])  # noqa: SLF001
    return driver


class TestTheExactPathIsUnchanged:
    """A meter that answers entry 1 is clamped to that row's own clock, exactly
    as before — the fallback must cost such a meter nothing."""

    def test_entry_one_clock_is_returned_as_utc(self) -> None:
        oldest_local = datetime(2026, 9, 18, 23, 45, 0)
        reader = _ScriptedReader(oldest_local=oldest_local)

        oldest = _driver(reader).load_profile_oldest_reading(1)

        assert oldest == (oldest_local - timedelta(hours=METER_LOCAL_UTC_OFFSET_HOURS)).replace(tzinfo=UTC)

    def test_a_readable_entry_never_pays_for_the_capture_period_read(self) -> None:
        reader = _ScriptedReader(oldest_local=datetime(2026, 9, 18, 23, 45, 0))

        _driver(reader).load_profile_oldest_reading(1)

        assert 4 not in reader.attrs_read
        assert reader.entry_reads == [(1, 1)]


class TestARefusedEntryReadFallsBackToAnEstimate:
    def test_the_estimate_is_entries_times_period_plus_one_period_of_margin(self) -> None:
        """176 x 900 s is the site's own Logger 1. One extra period keeps the
        oldest row inside the window despite a few seconds of clock skew —
        starting early is free (an overlapping range is answered), starting
        late loses the row."""
        reader = _ScriptedReader(entries_in_use=176, capture_period=900, refuse_entry=True)
        before = datetime.now(UTC)

        oldest = _driver(reader).load_profile_oldest_reading(1)

        after = datetime.now(UTC)
        span = timedelta(seconds=(176 + 1) * 900)
        assert oldest is not None
        assert before - span <= oldest <= after - span

    def test_the_estimate_follows_the_loggers_own_period(self) -> None:
        """Logger 2 on the same meter is 300 s — 528 entries, the same 44 h. A
        hardcoded 900 would put its start 132 h back instead."""
        reader = _ScriptedReader(entries_in_use=528, capture_period=300, refuse_entry=True)
        before = datetime.now(UTC)

        oldest = _driver(reader).load_profile_oldest_reading(1)

        assert oldest is not None
        assert abs((before - oldest) - timedelta(seconds=529 * 300)) < timedelta(seconds=5)

    def test_the_log_names_the_refusal_and_says_the_start_is_estimated(self, caplog: pytest.LogCaptureFixture) -> None:
        """The old line said only "could not read" — the site needed a probe exe
        carried in by hand to learn the exception the log had already seen."""
        reader = _ScriptedReader(refuse_entry=True)

        with caplog.at_level(logging.INFO):
            _driver(reader).load_profile_oldest_reading(1)

        assert "_RefusedError" in caplog.text
        assert "Other Reason" in caplog.text
        assert "estimat" in caplog.text.lower()

    def test_a_capture_period_of_zero_gives_no_estimate(self) -> None:
        """A profile that is not logging has no span to compute — and ``0`` would
        otherwise "estimate" the start at *now*, narrowing the walk to nothing."""
        reader = _ScriptedReader(capture_period=0, refuse_entry=True)

        assert _driver(reader).load_profile_oldest_reading(1) is None

    def test_an_unreadable_capture_period_gives_no_estimate(self) -> None:
        reader = _ScriptedReader(refuse_entry=True, refuse_attrs=frozenset({4}))

        assert _driver(reader).load_profile_oldest_reading(1) is None

    def test_a_capture_period_that_is_not_a_number_gives_no_estimate(self) -> None:
        reader = _ScriptedReader(capture_period=None, refuse_entry=True)

        assert _driver(reader).load_profile_oldest_reading(1) is None


class TestWhatStillAnswersNone:
    def test_an_empty_buffer_is_not_estimated_and_not_read(self) -> None:
        reader = _ScriptedReader(entries_in_use=0, refuse_entry=True)

        assert _driver(reader).load_profile_oldest_reading(1) is None
        assert reader.entry_reads == []

    @pytest.mark.parametrize("attr", [3, 7])
    def test_an_unreadable_profile_attribute_leaves_the_walk_alone(
        self, attr: int, caplog: pytest.LogCaptureFixture
    ) -> None:
        reader = _ScriptedReader(refuse_attrs=frozenset({attr}))

        with caplog.at_level(logging.INFO):
            assert _driver(reader).load_profile_oldest_reading(1) is None

        assert "_RefusedError" in caplog.text  # the class is named here too
        assert reader.entry_reads == []

    def test_a_logger_the_model_does_not_declare(self) -> None:
        assert _driver(_ScriptedReader()).load_profile_oldest_reading(2) is None


class TestTheWalkActuallyUsesTheEstimate:
    """``_backfill_start`` is the clamp's one caller — the estimate is only
    worth anything if it survives that function's own sanity window."""

    def test_a_two_day_buffer_starts_the_walk_two_days_back_not_ninety(self) -> None:
        now_utc = datetime.now(UTC)
        driver = _driver(_ScriptedReader(entries_in_use=176, capture_period=900, refuse_entry=True))

        start = load_profile._backfill_start(driver, 1, "CEWE", now_utc)  # noqa: SLF001

        assert abs((now_utc - start) - timedelta(seconds=177 * 900)) < timedelta(seconds=5)

    def test_a_full_ring_longer_than_the_window_keeps_the_full_window(self) -> None:
        """9600 entries x 900 s is 100 days — older than the floor, so the
        estimate must not *widen* the walk past it."""
        now_utc = datetime.now(UTC)
        driver = _driver(_ScriptedReader(entries_in_use=9600, capture_period=900, refuse_entry=True))

        start = load_profile._backfill_start(driver, 1, "CEWE", now_utc)  # noqa: SLF001

        assert start == now_utc - timedelta(days=LOAD_PROFILE_BACKFILL_DAYS)
