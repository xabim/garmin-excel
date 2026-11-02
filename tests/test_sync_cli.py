import argparse
import datetime as dt

import pytest

from conftest import mmss
from fakes import FakeGateway
from garmin_excel import cli
from garmin_excel.model import Pace, Step, StepKind, Workout
from garmin_excel.payload import to_garmin
from garmin_excel.sync import BLOCKED, CREATE, SCHEDULE, SKIP, UPDATE, execute, plan_sync, verify


def wk(day=24, km=4000, name="RUN - S04D06 - Tirada larga", **kw):
    return Workout(dt.date(2026, 10, day), 6, 4, name, [Step(StepKind.RUN, distance_m=km, pace=Pace(410, 430, 420, True))], **kw)


def test_new_workout_created_and_scheduled_once():
    gw, w = FakeGateway(), wk()
    items = plan_sync([w], gw)
    assert items[0].action == CREATE
    execute(items, gw)
    assert gw.writes == [("create", w.name), ("schedule", w.name, "2026-10-24")]
    assert verify(items, gw) == []


def test_rerun_creates_no_duplicates():
    gw, w = FakeGateway(), wk()
    execute(plan_sync([w], gw), gw)
    gw.writes.clear()
    again = plan_sync([w], gw)
    assert again[0].action == SKIP
    execute(again, gw)
    assert gw.writes == [] and len(gw.workouts) == 1


def test_changed_workout_needs_explicit_update():
    gw = FakeGateway([(to_garmin(wk(km=4000)), ["2026-10-24"])])
    items = plan_sync([wk(km=5000)], gw)
    assert items[0].action == UPDATE
    execute(items, gw, allow_update=False)
    assert gw.writes == [] and "not confirmed" in items[0].result
    execute(items, gw, allow_update=True)
    assert gw.writes[0][0] == "update" and len(gw.workouts) == 1


def test_existing_but_unscheduled_only_schedules():
    gw = FakeGateway([(to_garmin(wk()), [])])
    items = plan_sync([wk()], gw)
    assert items[0].action == SCHEDULE
    execute(items, gw)
    assert [x[0] for x in gw.writes] == ["schedule"]


def test_foreign_workout_with_same_name_is_not_silently_overwritten():
    foreign = {"workoutName": "RUN - S04D06 - Tirada larga", "description": "made by hand", "workoutSegments": []}
    gw = FakeGateway([(foreign, [])])
    items = plan_sync([wk()], gw)
    assert items[0].action == UPDATE and "not created by this tool" in items[0].reason
    execute(items, gw)
    assert gw.writes == []


def test_duplicate_remote_names_block():
    p = to_garmin(wk())
    gw = FakeGateway([(p, []), (p, [])])
    assert plan_sync([wk()], gw)[0].action == BLOCKED


def test_ambiguous_or_errored_workouts_never_uploaded():
    gw = FakeGateway()
    items = plan_sync([wk(name=None), wk(day=25, errors=["bad km"])], gw)
    assert [i.action for i in items] == [BLOCKED, BLOCKED]
    execute(items, gw)
    assert gw.writes == []


def test_partial_failure_is_recoverable_without_duplicates():
    gw = FakeGateway()
    a, b = wk(), wk(day=22, name="RUN - S04D04 - Caminar")
    gw.fail_schedule_for = {a.name}
    items = plan_sync([a, b], gw)
    execute(items, gw)
    assert items[0].result.startswith("FAILED") and items[1].result == "created + scheduled"
    assert verify(items, gw) == []                     # failed ones are not verified, but...
    gw.fail_schedule_for = set()
    items = plan_sync([a, b], gw)                      # rerun
    assert [i.action for i in items] == [SCHEDULE, SKIP]
    execute(items, gw)
    assert len(gw.workouts) == 2 and len(gw.calendar) == 2


# ---- CLI ------------------------------------------------------------------------

@pytest.fixture
def sample(make_week):
    return make_week(days={"sabado": dict(blocks={
        0: dict(pace=mmss(7, 10), rows=[(1, None, 1, 3), (1, None, 3, 2)]),
        3: dict(pace=mmss(6, 40), rows=[(1, None, 2, 5)])})})


def args(path, **kw):
    base = dict(input=str(path), week_number=4, year=2026, config=None, name_override=None, dry_run=False, yes=False, update_changed=False)
    return argparse.Namespace(**{**base, **kw})


def test_preview_shows_names_and_never_connects(sample):
    lines = []
    assert cli.cmd_preview(args(sample), out=lines.append) == 0
    text = "\n".join(lines)
    assert "RUN - S04D06 - Controlado" in text and "Rest day" in text and "10 km planned" in text
    assert "Warm-up" in text and "Cooldown" in text


def test_dry_run_reads_but_never_writes(sample):
    gw = FakeGateway()
    code = cli.cmd_upload(args(sample, dry_run=True), out=lambda *_: None, ask=lambda _: pytest.fail("must not prompt"), gateway_factory=lambda: gw)
    assert code == 0 and gw.writes == [] and not gw.workouts


def test_upload_requires_typed_confirmation(sample):
    gw = FakeGateway()
    assert cli.cmd_upload(args(sample), out=lambda *_: None, ask=lambda _: "no", gateway_factory=lambda: gw) == 1
    assert gw.writes == []
    assert cli.cmd_upload(args(sample), out=lambda *_: None, ask=lambda _: "yes", gateway_factory=lambda: gw, interactive=False) == 0
    assert [w[0] for w in gw.writes] == ["create", "schedule"]
    assert gw.workouts[1001]["workoutName"] == "RUN - S04D06 - Controlado"
    assert ("RUN - S04D06 - Controlado" in str(gw.writes)) and gw.calendar == {(1001, "2026-10-24")}


def test_yes_flag_skips_prompt_but_second_run_is_noop(sample):
    gw = FakeGateway()
    run = lambda: cli.cmd_upload(args(sample, yes=True), out=lambda *_: None, ask=lambda _: pytest.fail("prompted"), gateway_factory=lambda: gw)
    assert run() == 0
    n = len(gw.writes)
    assert run() == 0 and len(gw.writes) == n


def test_yes_does_not_imply_overwrite(sample):
    gw = FakeGateway()
    cli.cmd_upload(args(sample, yes=True), out=lambda *_: None, gateway_factory=lambda: gw)
    changed = FakeGateway([({**gw.workouts[1001], "description": "[garmin-excel:000000000000]"}, [])])
    cli.cmd_upload(args(sample, yes=True), out=lambda *_: None, gateway_factory=lambda: changed, interactive=False)
    assert changed.writes == []
    cli.cmd_upload(args(sample, yes=True, update_changed=True), out=lambda *_: None, gateway_factory=lambda: changed)
    assert changed.writes[0][0] == "update"


def test_name_override_resolves_ambiguity(make_week):
    path = make_week(days={"sabado": dict(blocks={
        1: dict(pace=mmss(6, 45), rows=[(1, None, 1, 4)]), 2: dict(pace=mmss(7, 5), rows=[(1, None, 2, 4)])})})
    assert cli.cmd_preview(args(path), out=lambda *_: None) == 1
    lines = []
    assert cli.cmd_preview(args(path, name_override=["D06=Rodaje"]), out=lines.append) == 0
    assert "RUN - S04D06 - Rodaje" in "\n".join(lines)
