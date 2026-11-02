import datetime as dt

from garmin_excel.model import HeartRate, Pace, RepeatGroup, Step, StepKind, Workout
from garmin_excel.payload import content_hash, hash_from_description, pace_to_mps, steps_payload, to_garmin


def pace(s, tol=10):
    return Pace(s - tol, s + tol, s, True)


def workout(items, name="RUN - S04D06 - Controlado"):
    return Workout(dt.date(2026, 10, 24), 6, 4, name, items)


CONTROLADO = [
    Step(StepKind.WARMUP, distance_m=3000, pace=pace(430)),
    Step(StepKind.RUN, distance_m=5000, pace=pace(400)),
    Step(StepKind.COOLDOWN, distance_m=2000, pace=pace(430)),
]


def test_pace_conversion_slow_end_first():
    assert pace_to_mps(400) == 2.5
    s = steps_payload([Step(StepKind.RUN, distance_m=5000, pace=pace(400))])[0]
    assert s["targetType"]["workoutTargetTypeKey"] == "pace.zone"
    assert s["targetValueOne"] < s["targetValueTwo"]          # 6:50/km (slow) .. 6:30/km (fast)
    assert round(1000 / s["targetValueOne"]) == 410 and round(1000 / s["targetValueTwo"]) == 390


def test_three_step_workout_shape():
    p = to_garmin(workout(CONTROLADO))
    steps = p["workoutSegments"][0]["workoutSteps"]
    assert p["workoutName"] == "RUN - S04D06 - Controlado" and p["sportType"]["sportTypeKey"] == "running"
    assert [s["stepType"]["stepTypeKey"] for s in steps] == ["warmup", "interval", "cooldown"]
    assert [s["endCondition"]["conditionTypeKey"] for s in steps] == ["distance"] * 3
    assert [s["endConditionValue"] for s in steps] == [3000, 5000, 2000]
    assert [s["stepOrder"] for s in steps] == [1, 2, 3]
    assert p["estimatedDistanceInMeters"] == 10000 and p["estimatedDurationInSecs"] == 3*430 + 5*400 + 2*430


def test_repeat_group_is_real_group_with_nested_numbering():
    items = [
        Step(StepKind.WARMUP, distance_m=2000),
        RepeatGroup(4, (Step(StepKind.RUN, distance_m=1000, pace=pace(330)), Step(StepKind.RECOVERY, duration_s=120)), skip_last_rest=True),
        Step(StepKind.COOLDOWN, distance_m=1000),
    ]
    steps = steps_payload(items)
    g = steps[1]
    assert g["type"] == "RepeatGroupDTO" and g["numberOfIterations"] == 4 and g["endConditionValue"] == 4.0
    assert [c["stepOrder"] for c in g["workoutSteps"]] == [3, 4] and steps[2]["stepOrder"] == 5
    run, rec = g["workoutSteps"]
    assert rec["endCondition"]["conditionTypeKey"] == "time" and rec["endConditionValue"] == 120
    assert rec["targetType"]["workoutTargetTypeKey"] == "no.target"
    assert steps[0]["targetType"]["workoutTargetTypeKey"] == "no.target"   # no target when sheet has none


def test_hr_secondary_and_zone_targets():
    s = steps_payload([Step(StepKind.RUN, distance_m=1000, pace=pace(400), hr=HeartRate(low=130, high=145))])[0]
    assert s["secondaryTargetType"]["workoutTargetTypeKey"] == "heart.rate.zone"
    assert (s["secondaryTargetValueOne"], s["secondaryTargetValueTwo"]) == (130, 145)
    z = steps_payload([Step(StepKind.RUN, distance_m=1000, hr=HeartRate(zone=2))])[0]
    assert z["targetType"]["workoutTargetTypeKey"] == "heart.rate.zone" and z["zoneNumber"] == 2


def test_lap_button_step():
    s = steps_payload([Step(StepKind.RUN)])[0]
    assert s["endCondition"]["conditionTypeKey"] == "lap.button" and "endConditionValue" not in s


def test_hash_ignores_date_and_notes_but_tracks_content():
    a, b = workout(CONTROLADO), workout(CONTROLADO)
    b.date, b.notes = dt.date(2027, 1, 1), "note"
    assert content_hash(a) == content_hash(b)
    c = workout([*CONTROLADO[:1], Step(StepKind.RUN, distance_m=6000, pace=pace(400)), CONTROLADO[2]])
    assert content_hash(a) != content_hash(c)
    assert hash_from_description(to_garmin(a)["description"]) == content_hash(a)
    assert hash_from_description("hand made") is None


def test_validates_against_library_models():
    pydantic = __import__("pytest").importorskip("pydantic")
    from garminconnect.workout import RunningWorkout
    items = [Step(StepKind.WARMUP, distance_m=2000), RepeatGroup(3, (Step(StepKind.RUN, distance_m=500, pace=pace(300)), Step(StepKind.RECOVERY, duration_s=60)))]
    RunningWorkout.model_validate(to_garmin(workout(items)))
