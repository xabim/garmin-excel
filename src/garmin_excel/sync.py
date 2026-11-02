"""Idempotent sync: compare planned workouts with Garmin, then apply the plan."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from typing import Any

from .gateway import Gateway
from .model import Workout
from .payload import content_hash, hash_from_description, to_garmin

CREATE, SKIP, SCHEDULE, UPDATE, BLOCKED = "create", "skip", "schedule-only", "update", "blocked"


@dataclass
class PlanItem:
    workout: Workout
    action: str
    reason: str = ""
    remote_id: int | None = None
    result: str = ""  # filled by execute()


def plan_sync(workouts: list[Workout], gw: Gateway) -> list[PlanItem]:
    """Read-only: decide create / skip / schedule-only / update / blocked per workout."""
    remote: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for w in gw.list_workouts():
        remote[w.get("workoutName", "")].append(w)

    months = {(w.date.year, w.date.month) for w in workouts}
    scheduled: set[tuple[int, str]] = set()
    for y, m in months:
        scheduled |= {(int(i["workoutId"]), i["date"]) for i in gw.scheduled(y, m) if i.get("workoutId")}

    items: list[PlanItem] = []
    for w in workouts:
        if w.errors or w.name is None:
            items.append(PlanItem(w, BLOCKED, "; ".join(w.errors) or "ambiguous workout type"))
            continue
        matches = remote.get(w.name, [])
        if len(matches) > 1:
            items.append(PlanItem(w, BLOCKED, f"{len(matches)} workouts with this name already exist in Garmin"))
            continue
        if not matches:
            items.append(PlanItem(w, CREATE))
            continue
        wid = int(matches[0]["workoutId"])
        old = hash_from_description(gw.get_workout(wid).get("description"))
        if old != content_hash(w):
            why = "content differs from Garmin" if old else "existing workout was not created by this tool"
            items.append(PlanItem(w, UPDATE, why, wid))
        elif (wid, w.date.isoformat()) in scheduled:
            items.append(PlanItem(w, SKIP, "unchanged and already scheduled", wid))
        else:
            items.append(PlanItem(w, SCHEDULE, "exists, not on this date", wid))
    return items


def execute(items: list[PlanItem], gw: Gateway, allow_update: bool = False) -> None:
    """Apply the plan. Each workout is independent, so a rerun resumes after a failure."""
    for it in items:
        w, day = it.workout, it.workout.date.isoformat()
        try:
            if it.action == CREATE:
                it.remote_id = gw.create(to_garmin(w))
                gw.schedule(it.remote_id, day)
                it.result = "created + scheduled"
            elif it.action == UPDATE:
                if not allow_update:
                    it.result = "skipped (changed; update not confirmed)"
                    continue
                gw.update(it.remote_id, to_garmin(w))  # type: ignore[arg-type]
                gw.schedule(it.remote_id, day)  # type: ignore[arg-type]
                it.result = "updated + scheduled"
            elif it.action == SCHEDULE:
                gw.schedule(it.remote_id, day)  # type: ignore[arg-type]
                it.result = "scheduled"
            else:
                it.result = "skipped" if it.action == SKIP else f"not imported ({it.reason})"
        except Exception as e:  # report and keep going; rerun is safe
            it.result = f"FAILED: {type(e).__name__}: {e}"


def verify(items: list[PlanItem], gw: Gateway) -> list[str]:
    """Re-read Garmin and report workouts that are not scheduled where planned."""
    wanted = [i for i in items if i.action != BLOCKED and i.result and not i.result.startswith(("FAILED", "skipped ("))]
    names = {w["workoutName"]: int(w["workoutId"]) for w in gw.list_workouts()}
    sched: set[tuple[int, str]] = set()
    for y, m in {(i.workout.date.year, i.workout.date.month) for i in wanted}:
        sched |= {(int(s["workoutId"]), s["date"]) for s in gw.scheduled(y, m) if s.get("workoutId")}
    problems = []
    for i in wanted:
        wid = names.get(i.workout.name)  # type: ignore[arg-type]
        if wid is None or (wid, i.workout.date.isoformat()) not in sched:
            problems.append(f"{i.workout.name}: not found on {i.workout.date} after upload")
    return problems
