"""``_special_day_entry_from_gx`` — the pure GXDate -> SpecialDayEntry
classification (M7-1, issue #28, finding 1).

Hand-builds real ``GXDLMSSpecialDay``/``GXDate`` objects — no meter, no
driver instance — and asserts the annual/public split the wire's
``DateTimeSkips.YEAR`` bit encodes. The wildcard-year case is the one a
``str(GXDate)``-based implementation (v1's own ``_parse_special_days``)
passes by accident, because a wildcard year renders as the literal string
"2000" either way; only inspecting ``.skip``/`.value`` directly tells the
two cases apart.
"""

from __future__ import annotations

from datetime import datetime

from gurux_dlms.enums import DateTimeSkips
from gurux_dlms.GXDate import GXDate
from gurux_dlms.objects.GXDLMSSpecialDay import GXDLMSSpecialDay

from arichds.acquisition.drivers._dlms import _special_day_entry_from_gx
from arichds.acquisition.drivers.base import SpecialDayEntry


def _entry(index: int, day_id: int, gx_date: GXDate | None) -> GXDLMSSpecialDay:
    entry = GXDLMSSpecialDay()
    entry.index = index
    entry.dayId = day_id
    entry.date = gx_date
    return entry


def _wildcard_year_date(month: int, day: int) -> GXDate:
    """A ``GXDate`` with the wire year skipped — the shape Gurux hands back
    for an annual Special Days entry (`_GXCommon.getDate`, finding 1): the
    year field is set to the ``2000`` placeholder and the ``YEAR`` skip bit
    is raised."""
    gx_date = GXDate(datetime(2000, month, day))
    gx_date.skip |= DateTimeSkips.YEAR
    return gx_date


class TestAnnualWildcardYear:
    def test_wildcard_year_classifies_as_annual_with_month_and_day(self) -> None:
        entry = _entry(1, 7, _wildcard_year_date(4, 13))

        result = _special_day_entry_from_gx(entry)

        assert result == SpecialDayEntry(index=1, day_id=7, year=None, month=4, day=13)

    def test_the_year_2000_placeholder_is_never_stored(self) -> None:
        """The single assertion finding 1 exists for: an implementation that
        forgets to check the skip bit and instead reads `.value.year`
        unconditionally would store 2000 here — this must be `None`."""
        entry = _entry(2, 9, _wildcard_year_date(12, 25))

        result = _special_day_entry_from_gx(entry)

        assert result is not None
        assert result.year is None
        assert result.year != 2000
        assert result.kind == "annual"


class TestPublicExactDate:
    def test_a_real_year_classifies_as_public(self) -> None:
        gx_date = GXDate(datetime(2026, 3, 3))
        entry = _entry(3, 12, gx_date)

        result = _special_day_entry_from_gx(entry)

        assert result == SpecialDayEntry(index=3, day_id=12, year=2026, month=3, day=3)
        assert result.kind == "public"


class TestNoDate:
    def test_a_none_date_survives_without_becoming_the_string_none(self) -> None:
        entry = _entry(4, 1, None)

        result = _special_day_entry_from_gx(entry)

        assert result is None


class TestEmptyTable:
    def test_reading_no_entries_at_all_is_not_an_error(self) -> None:
        # An empty `obj.entries` list is what a supported-but-unconfigured
        # meter answers with — nothing to classify, and this loop must not
        # choke on it. Modelled directly rather than through a driver
        # instance, matching this module's "pure function" scope.
        entries: list[GXDLMSSpecialDay] = []
        assert [e for e in (_special_day_entry_from_gx(x) for x in entries) if e is not None] == []
