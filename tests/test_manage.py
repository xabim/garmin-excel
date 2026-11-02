import argparse
import datetime as dt

import pytest

from fakes import FakeGateway
from garmin_excel import cli
from garmin_excel.model import Pace, Step, StepKind, Workout
from garmin_excel.payload import to_garmin
from garmin_excel.sync import find_managed


def w(week, day, name):
    d = dt.date.today().replace(day=1) + dt.timedelta(days=day)
    return Workout(d, 2, week, f"RUN - S{week:02d}D02 - {name}", [Step(StepKind.RUN, distance_m=5000, pace=Pace(1, 2, 1.5, True))])


def seeded():
    a, b = w(5, 3, "Caminar"), w(6, 4, "Rodaje")
    hand_made = {"workoutName": "RUN - S05D04 - Mine", "description": "hand made", "workoutSegments": []}
    gw = FakeGateway([(to_garmin(a), [a.date.isoformat()]), (to_garmin(b), [b.date.isoformat()]), (hand_made, [])])
    return gw, a, b


def args(**kw):
    return argparse.Namespace(**{**dict(week=None, name=None, dry_run=False, config=None), **kw})


def test_find_managed_ignores_hand_made_workouts():
    gw, a, b = seeded()
    assert [m.name for m in find_managed(gw, "RUN")] == [a.name, b.name]
    assert [m.name for m in find_managed(gw, "RUN", week=5)] == [a.name]   # "Mine" is S05 but untagged
    assert find_managed(gw, "RUN", week=5)[0].dates == [a.date.isoformat()]


def test_list_writes_nothing():
    gw, *_ = seeded()
    lines = []
    assert cli.cmd_list(args(), out=lines.append, gateway_factory=lambda: gw) == 0
    assert gw.writes == [] and "Caminar" in "\n".join(lines) and "Mine" not in "\n".join(lines)


def test_delete_needs_a_selector():
    gw, *_ = seeded()
    assert cli.cmd_delete(args(), out=lambda *_: None, gateway_factory=lambda: gw) == 2 and gw.writes == []


def test_delete_dry_run_and_wrong_confirmation_delete_nothing():
    gw, *_ = seeded()
    cli.cmd_delete(args(week=5, dry_run=True), out=lambda *_: None, ask=lambda _: pytest.fail("prompted"), gateway_factory=lambda: gw)
    assert gw.writes == []
    for answer in ("", "yes", "no"):
        assert cli.cmd_delete(args(week=5), out=lambda *_: None, ask=lambda _: answer, gateway_factory=lambda: gw) == 1
    assert gw.writes == [] and len(gw.workouts) == 3


def test_delete_week_removes_only_that_week_and_its_calendar_entry():
    gw, a, b = seeded()
    assert cli.cmd_delete(args(week=5), out=lambda *_: None, ask=lambda _: "delete", gateway_factory=lambda: gw) == 0
    names = sorted(p["workoutName"] for p in gw.workouts.values())
    assert names == sorted([b.name, "RUN - S05D04 - Mine"])          # other week and hand-made one survive
    assert [x[0] for x in gw.writes] == ["unschedule", "delete"]
    assert {d for _, d in gw.calendar} == {b.date.isoformat()}


def test_delete_by_exact_name():
    gw, a, b = seeded()
    cli.cmd_delete(args(name=b.name), out=lambda *_: None, ask=lambda _: "delete", gateway_factory=lambda: gw)
    assert ("delete", b.name) in gw.writes and ("delete", a.name) not in gw.writes
