import datetime as dt

import pytest

from conftest import mmss
from garmin_excel.config import Settings
from garmin_excel.model import RepeatGroup, StepKind
from garmin_excel.naming import DateError, parse_week_dates
from garmin_excel.parser import CellError, fmt_pace, parse_hr, parse_pace, parse_workbook, rec_seconds


# ---- synthetic layouts --------------------------------------------------------

def test_warmup_main_cooldown_order(make_week, settings):
    path = make_week(days={"sabado": dict(blocks={
        0: dict(pace=mmss(7, 10), rows=[(1, None, 1, 3), (1, None, 3, 2)]),
        3: dict(pace=mmss(6, 40), rows=[(1, None, 2, 5)]),
    })})
    sat = parse_workbook(path, settings).days[5]
    assert [(s.kind, s.distance_m, s.pace.nominal_s) for s in sat.items] == [
        (StepKind.WARMUP, 3000, 430), (StepKind.RUN, 5000, 400), (StepKind.COOLDOWN, 2000, 430)]
    assert not sat.errors


def test_realizado_columns_never_read(make_week, settings):
    path = make_week(days={"martes": dict(
        blocks={1: dict(pace=mmss(7), rows=[(1, None, 1, 7)])},
        realizado={"H9": 1, "J9": 1, "K9": dt.time(0, 49), "M8": mmss(5, 0), "L8": 149, "N9": 99})})
    items = parse_workbook(path, settings).days[1].items
    assert len(items) == 1 and items[0].distance_m == 7000


def test_intervals_with_recovery_become_repeat_group(make_week, settings):
    path = make_week(days={"viernes": dict(blocks={
        0: dict(pace=mmss(7, 0), rows=[(1, None, 1, 2), (1, None, 3, 1)]),
        4: dict(pace=mmss(5, 30), rows=[(4, 2, 2, 1)]),
    })})
    fri = parse_workbook(path, settings).days[4]
    warm, group, cool = fri.items
    assert isinstance(group, RepeatGroup) and group.iterations == 4
    assert [(s.kind, s.distance_m, s.duration_s) for s in group.steps] == [
        (StepKind.RUN, 1000, None), (StepKind.RECOVERY, None, 120)]
    assert (warm.kind, cool.kind) == (StepKind.WARMUP, StepKind.COOLDOWN)
    assert any("assumed" in w for w in fri.warnings)  # interpretation is documented in the preview


def test_rest_day_detection(make_week, settings):
    days = parse_workbook(make_week(), settings).days
    assert all(d.rest and not d.items for d in days)


def test_rest_marker_in_a2_and_conflict(make_week, settings):
    path = make_week(days={"lunes": dict(rest=True, blocks={2: dict(pace=mmss(6, 0), rows=[(1, None, 1, 5)])})})
    mon = parse_workbook(path, settings).days[0]
    assert mon.rest and any("treated as REST" in w for w in mon.warnings)


def test_malformed_rows_are_errors_not_crashes(make_week, settings):
    path = make_week(days={"martes": dict(blocks={2: dict(pace=mmss(6, 0), rows=[(1, None, 1, "abc"), (1, None, 2, 400)])})})
    tue = parse_workbook(path, settings).days[1]
    assert len(tue.errors) == 2 and not tue.items


def test_implausible_pace_is_error(make_week, settings):
    path = make_week(days={"martes": dict(blocks={2: dict(pace=mmss(1, 0), rows=[(1, None, 1, 5)])})})
    assert "plausible" in parse_workbook(path, settings).days[1].errors[0]


def test_missing_orden_warns_and_uses_sheet_order(make_week, settings):
    path = make_week(days={"martes": dict(blocks={2: dict(pace=mmss(6, 0), rows=[(1, None, None, 5)])})})
    tue = parse_workbook(path, settings).days[1]
    assert len(tue.items) == 1 and any("orden" in w for w in tue.warnings)


# ---- cell parsers ---------------------------------------------------------------

@pytest.mark.parametrize("value,nominal,fast,slow,derived", [
    (dt.time(6, 40), 400, 390, 410, True),        # typed style 06:40:00 == 6:40/km
    (dt.time(0, 6, 40), 400, 390, 410, True),     # stored literally as 0:06:40
    ("6:40", 400, 390, 410, True),
    ("6:30-6:50", 400, 390, 410, False),          # sheet range is preserved, not widened
    ("6:50 - 6:30", 400, 390, 410, False),
])
def test_parse_pace(value, nominal, fast, slow, derived):
    p = parse_pace(value, 10)
    assert (p.nominal_s, p.fast_s, p.slow_s, p.derived) == (nominal, fast, slow, derived)


def test_pace_tolerance_is_configurable():
    p = parse_pace(dt.time(7, 0), 5)
    assert (p.fast_s, p.slow_s) == (415, 425)


@pytest.mark.parametrize("bad", ["fast", dt.time(1, 0), "99:99x", 3.5])
def test_parse_pace_rejects(bad):
    with pytest.raises(CellError):
        parse_pace(bad, 10)


def test_pace_blank_values():
    assert parse_pace(None, 10) is None and parse_pace("-", 10) is None


def test_parse_hr_variants():
    assert parse_hr("130-145", 5).high == 145 and not parse_hr("130-145", 5).derived
    assert parse_hr(140, 5).low == 135 and parse_hr(140, 5).derived
    assert parse_hr("z2", 5).zone == 2
    with pytest.raises(CellError):
        parse_hr(400, 5)


def test_rec_seconds():
    assert rec_seconds(2) == 120 and rec_seconds(1.5) == 90 and rec_seconds("-") is None
    with pytest.raises(CellError):
        rec_seconds(-1)


def test_fmt_pace():
    assert fmt_pace(430) == "7:10"


# ---- dates ----------------------------------------------------------------------

@pytest.mark.parametrize("name,year,start", [
    ("Plan 19_25 oct.xlsx", 2026, dt.date(2026, 10, 19)),
    ("Plan 26 oct_1 nov.xlsx", 2026, dt.date(2026, 10, 26)),      # spans two months
    ("Plan 5_11 oct - Finalizado.xlsx", 2026, dt.date(2026, 10, 5)),
    ("Plan 29 dic_4 ene.xlsx", 2026, dt.date(2025, 12, 29)),              # spans New Year; year = year of the last day
])
def test_parse_week_dates(name, year, start):
    assert parse_week_dates(name, year)[0] == start


def test_nfd_filename_and_no_year():
    import unicodedata
    name = unicodedata.normalize("NFD", "Plan 19_25 oct.xlsx")
    with pytest.raises(DateError, match="no year"):
        parse_week_dates(name, None)
    start, warns = parse_week_dates(name, None, fallback_year=2026)
    assert start == dt.date(2026, 10, 19) and warns


def test_wrong_year_is_rejected():
    with pytest.raises(DateError, match="not Monday"):
        parse_week_dates("x 19_25 oct.xlsx", 2025)


def test_no_date_in_name():
    with pytest.raises(DateError):
        parse_week_dates("plan.xlsx", 2026)
