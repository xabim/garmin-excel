import datetime as dt

import pytest

from conftest import mmss
from garmin_excel.config import Settings
from garmin_excel.naming import DateError, build_workout, plan_week_number, workout_name
from garmin_excel.parser import parse_workbook


def week_of(path, settings):
    return {d.iso_weekday: d for d in parse_workbook(path, settings).days}


def test_name_format():
    s = Settings()
    assert workout_name(s, 4, 7, "Suave") == "RUN - S04D07 - Suave"
    assert workout_name(Settings(prefix="XYZ", week_digits=3), 4, 1, "Rodaje") == "XYZ - S004D01 - Rodaje"


def test_week_number_sources():
    mon = dt.date(2026, 10, 19)
    assert plan_week_number(mon, Settings(week_number=4)) == 4
    assert plan_week_number(mon, Settings(week_number=4), cli_week=9) == 9
    assert plan_week_number(mon, Settings(plan_start=dt.date(2026, 9, 30))) == 4   # start is mid-week (Wed)
    assert plan_week_number(mon, Settings(plan_start=dt.date(2026, 10, 19))) == 1
    with pytest.raises(DateError):
        plan_week_number(mon, Settings())
    with pytest.raises(DateError, match="before"):
        plan_week_number(mon, Settings(plan_start=dt.date(2026, 11, 2)))


def test_main_block_names_the_workout_not_the_warmup(make_week, settings):
    path = make_week(days={"sabado": dict(blocks={
        0: dict(pace=mmss(7, 10), rows=[(1, None, 1, 3), (1, None, 3, 2)]),
        3: dict(pace=mmss(6, 40), rows=[(1, None, 2, 5)])})})
    w = build_workout(week_of(path, settings)[6], 4, settings)
    assert w.name == "RUN - S04D06 - Controlado" and not w.warnings


def test_series_wins_over_other_blocks(make_week, settings):
    path = make_week(days={"viernes": dict(blocks={
        0: dict(pace=mmss(7, 0), rows=[(1, None, 1, 2)]),
        4: dict(pace=mmss(5, 30), rows=[(4, 2, 2, 1)])})})
    assert build_workout(week_of(path, settings)[5], 4, settings).name.endswith("Series")


def test_progressive_inferred_when_paces_accelerate(make_week, settings):
    path = make_week(days={"sabado": dict(blocks={
        1: dict(pace=mmss(7, 5), rows=[(1, None, 1, 4)]),
        2: dict(pace=mmss(6, 55), rows=[(1, None, 2, 4)]),
        3: dict(pace=mmss(6, 45), rows=[(1, None, 3, 4)])})})
    w = build_workout(week_of(path, settings)[6], 4, settings)
    assert w.name.endswith("Progresivo") and any("inferred" in x for x in w.warnings)


def test_ambiguous_type_is_not_guessed(make_week, settings):
    path = make_week(days={"sabado": dict(blocks={
        1: dict(pace=mmss(6, 45), rows=[(1, None, 1, 4)]),
        2: dict(pace=mmss(7, 5), rows=[(1, None, 2, 4)])})})   # slowing down: not progressive
    day = week_of(path, settings)[6]
    w = build_workout(day, 4, settings)
    assert w.name is None and any("Ambiguous" in x for x in w.warnings)
    assert build_workout(day, 4, settings, override="Rodaje").name == "RUN - S04D06 - Rodaje"


def test_warmup_only_is_ambiguous(make_week, settings):
    path = make_week(days={"sabado": dict(blocks={0: dict(pace=mmss(7, 0), rows=[(1, None, 1, 2)])})})
    assert build_workout(week_of(path, settings)[6], 4, settings).name is None


def test_name_map_from_config(make_week):
    s = Settings(year=2026, names={"caminar": "Suave"})
    path = make_week(days={"martes": dict(blocks={1: dict(title="Caminar", pace=mmss(7, 0), rows=[(1, None, 1, 7)])})})
    assert build_workout(week_of(path, s)[2], 4, s).name == "RUN - S04D02 - Suave"
