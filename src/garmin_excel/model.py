"""Normalized workout model, independent of both Excel and Garmin."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from enum import Enum


class StepKind(str, Enum):
    WARMUP = "warmup"
    RUN = "run"
    RECOVERY = "recovery"
    COOLDOWN = "cooldown"


@dataclass(frozen=True)
class Pace:
    """Target pace in seconds per km. fast_s <= slow_s."""

    fast_s: float
    slow_s: float
    nominal_s: float
    derived: bool  # True: range built from a single sheet value + tolerance

    @property
    def mean_s(self) -> float:
        return (self.fast_s + self.slow_s) / 2


@dataclass(frozen=True)
class HeartRate:
    """Target HR: bpm range, or a Garmin zone number."""

    low: float | None = None
    high: float | None = None
    zone: int | None = None
    derived: bool = False


@dataclass(frozen=True)
class Step:
    kind: StepKind
    distance_m: float | None = None
    duration_s: float | None = None  # both None => lap button
    pace: Pace | None = None
    hr: HeartRate | None = None
    label: str = ""  # block label from the sheet, for display only


@dataclass(frozen=True)
class RepeatGroup:
    iterations: int
    steps: tuple[Step, ...]
    skip_last_rest: bool = False


Item = Step | RepeatGroup


@dataclass
class Workout:
    date: date
    iso_weekday: int
    week: int
    name: str | None  # None => ambiguous, needs an override
    items: list[Item]
    notes: str | None = None
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    @property
    def distance_m(self) -> float:
        return sum(distance_m(i) for i in self.items)

    @property
    def duration_s(self) -> float | None:
        """Estimated duration, or None if some step cannot be estimated."""
        total = 0.0
        for item in self.items:
            d = duration_s(item)
            if d is None:
                return None
            total += d
        return total

    @property
    def step_count(self) -> int:
        return sum(1 + len(i.steps) if isinstance(i, RepeatGroup) else 1 for i in self.items)


@dataclass
class DayPlan:
    """What the parser found on one daily sheet (before naming)."""

    date: date
    iso_weekday: int
    sheet: str
    rest: bool
    items: list[Item]
    block_kinds: list[str]  # classified main block kinds, in execution order
    note: str | None = None
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


@dataclass
class WeekPlan:
    source: str
    start: date
    days: list[DayPlan]
    warnings: list[str] = field(default_factory=list)


def step_distance_m(s: Step) -> float:
    return s.distance_m or 0.0


def distance_m(item: Item) -> float:
    if isinstance(item, RepeatGroup):
        return item.iterations * sum(step_distance_m(s) for s in item.steps)
    return step_distance_m(item)


def _step_duration(s: Step) -> float | None:
    if s.duration_s is not None:
        return s.duration_s
    if s.distance_m is not None and s.pace is not None:
        return s.distance_m / 1000 * s.pace.nominal_s
    return None


def duration_s(item: Item) -> float | None:
    if isinstance(item, RepeatGroup):
        parts = [_step_duration(s) for s in item.steps]
        if any(p is None for p in parts):
            return None
        total = item.iterations * sum(parts)  # type: ignore[arg-type]
        if item.skip_last_rest:
            total -= sum(p for s, p in zip(item.steps, parts) if s.kind is StepKind.RECOVERY)  # type: ignore[misc]
        return total
    return _step_duration(item)
