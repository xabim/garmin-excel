"""Normalized Workout -> Garmin Connect workout JSON (dict).

Constants come from python-garminconnect so ids stay in sync with the library;
the dicts are built here because the library's step helpers cannot express
distance-based warm-up/cooldown steps or secondary (HR) targets cleanly.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

from garminconnect.workout import ConditionType, SportType, StepType, TargetType

from .model import HeartRate, Pace, RepeatGroup, Step, StepKind, Workout

TAG = "garmin-excel"

_STEP = {
    StepKind.WARMUP: (StepType.WARMUP, "warmup", 1),
    StepKind.RUN: (StepType.INTERVAL, "interval", 3),
    StepKind.RECOVERY: (StepType.RECOVERY, "recovery", 4),
    StepKind.COOLDOWN: (StepType.COOLDOWN, "cooldown", 2),
}
_NO_TARGET = {"workoutTargetTypeId": TargetType.NO_TARGET, "workoutTargetTypeKey": "no.target", "displayOrder": 1}
_PACE = {"workoutTargetTypeId": TargetType.PACE_ZONE, "workoutTargetTypeKey": "pace.zone", "displayOrder": 6}
_HR = {"workoutTargetTypeId": TargetType.HEART_RATE_ZONE, "workoutTargetTypeKey": "heart.rate.zone", "displayOrder": 4}
_SPORT = {"sportTypeId": SportType.RUNNING, "sportTypeKey": "running", "displayOrder": 1}


def pace_to_mps(sec_per_km: float) -> float:
    return round(1000 / sec_per_km, 6)


def _end_condition(step: Step) -> tuple[dict[str, Any], float | None]:
    if step.distance_m is not None:
        return {"conditionTypeId": ConditionType.DISTANCE, "conditionTypeKey": "distance", "displayOrder": 3, "displayable": True}, step.distance_m
    if step.duration_s is not None:
        return {"conditionTypeId": ConditionType.TIME, "conditionTypeKey": "time", "displayOrder": 2, "displayable": True}, step.duration_s
    return {"conditionTypeId": ConditionType.LAP_BUTTON, "conditionTypeKey": "lap.button", "displayOrder": 1, "displayable": True}, None


def _targets(pace: Pace | None, hr: HeartRate | None) -> list[dict[str, Any]]:
    """Primary target first: pace if present, else HR. Pace goes in m/s, slow end first."""
    out: list[dict[str, Any]] = []
    if pace:
        out.append({"type": _PACE, "one": pace_to_mps(pace.slow_s), "two": pace_to_mps(pace.fast_s), "zone": None})
    if hr:
        if hr.zone:
            out.append({"type": _HR, "one": None, "two": None, "zone": hr.zone})
        else:
            out.append({"type": _HR, "one": hr.low, "two": hr.high, "zone": None})
    return out


def _step_dict(step: Step, order: int, child: int | None) -> dict[str, Any]:
    type_id, key, display = _STEP[step.kind]
    cond, value = _end_condition(step)
    d: dict[str, Any] = {
        "type": "ExecutableStepDTO",
        "stepOrder": order,
        "stepType": {"stepTypeId": type_id, "stepTypeKey": key, "displayOrder": display},
        "endCondition": cond,
        "endConditionValue": value,
        "targetType": _NO_TARGET,
    }
    if child is not None:
        d["childStepId"] = child
    targets = _targets(step.pace, step.hr) if step.kind is not StepKind.RECOVERY else []
    if targets:
        first = targets[0]
        d.update(targetType=first["type"], targetValueOne=first["one"], targetValueTwo=first["two"])
        if first["zone"]:
            d["zoneNumber"] = first["zone"]
    if len(targets) > 1:
        second = targets[1]
        d.update(secondaryTargetType=second["type"], secondaryTargetValueOne=second["one"], secondaryTargetValueTwo=second["two"])
        if second["zone"]:
            d["secondaryZoneNumber"] = second["zone"]
    return {k: v for k, v in d.items() if v is not None}


def steps_payload(items) -> list[dict[str, Any]]:
    """Garmin numbers every step, including those nested in repeat groups."""
    order = 0
    out: list[dict[str, Any]] = []
    for item in items:
        order += 1
        if isinstance(item, RepeatGroup):
            group_order = order
            children = []
            for s in item.steps:
                order += 1
                children.append(_step_dict(s, order, group_order))
            out.append({
                "type": "RepeatGroupDTO",
                "stepOrder": group_order,
                "stepType": {"stepTypeId": StepType.REPEAT, "stepTypeKey": "repeat", "displayOrder": 6},
                "numberOfIterations": item.iterations,
                "workoutSteps": children,
                "endCondition": {"conditionTypeId": ConditionType.ITERATIONS, "conditionTypeKey": "iterations", "displayOrder": 7, "displayable": False},
                "endConditionValue": float(item.iterations),
                "childStepId": group_order,
                "smartRepeat": False,
                "skipLastRestStep": item.skip_last_rest,
            })
        else:
            out.append(_step_dict(item, order, None))
    return out


def content_hash(workout: Workout) -> str:
    """Hash of what the watch would execute (name + steps), not of dates or notes."""
    body = json.dumps({"name": workout.name, "steps": steps_payload(workout.items)}, sort_keys=True)
    return hashlib.sha256(body.encode()).hexdigest()[:12]


def to_garmin(workout: Workout) -> dict[str, Any]:
    desc = (workout.notes + "\n" if workout.notes else "") + f"[{TAG}:{content_hash(workout)}]"
    return {
        "workoutName": workout.name,
        "description": desc,
        "sportType": _SPORT,
        "estimatedDurationInSecs": int(workout.duration_s or 0),
        "estimatedDistanceInMeters": workout.distance_m,
        "workoutSegments": [{"segmentOrder": 1, "sportType": _SPORT, "workoutSteps": steps_payload(workout.items)}],
    }


def hash_from_description(description: str | None) -> str | None:
    if not description or f"[{TAG}:" not in description:
        return None
    return description.split(f"[{TAG}:", 1)[1].split("]", 1)[0]
