"""Dates from the file name, plan-week numbers and workout names."""

from __future__ import annotations

import re
import unicodedata
from datetime import date, timedelta

from .config import Settings
from .model import DayPlan, Pace, RepeatGroup, Step, Workout

MONTHS = {
    "ene": 1, "feb": 2, "mar": 3, "abr": 4, "may": 5, "jun": 6,
    "jul": 7, "ago": 8, "sep": 9, "set": 9, "oct": 10, "nov": 11, "dic": 12,
}  # fmt: skip

_RANGE = re.compile(r"(\d{1,2})\s*([a-z]+)?\s*[_\-]\s*(\d{1,2})\s*([a-z]+)")


def fold(text: str) -> str:
    """Lowercase, accent-free, whitespace-trimmed (also normalizes NFC/NFD)."""
    nfd = unicodedata.normalize("NFD", text)
    return "".join(c for c in nfd if not unicodedata.combining(c)).casefold().strip()


class DateError(ValueError):
    pass


def parse_week_dates(
    filename: str, year: int | None, fallback_year: int | None = None
) -> tuple[date, list[str]]:
    """Return (monday, warnings) for names like '19_25 oct' or '26 oct_1 nov'.

    `year` is authoritative. Without it, `fallback_year` (workbook metadata) is
    used and a warning is emitted; the result must still start on a Monday.
    """
    m = _RANGE.search(fold(filename))
    if not m:
        raise DateError(f"No date range like '19_25 oct' found in file name {filename!r}")
    d1, mon1, d2, mon2 = m.group(1), m.group(2), m.group(3), m.group(4)
    month2 = MONTHS.get(mon2[:3])
    month1 = MONTHS.get(mon1[:3]) if mon1 else month2
    if month1 is None or month2 is None:
        raise DateError(f"Unknown Spanish month in file name {filename!r}")
    if not mon1 and int(d1) > int(d2):  # '28_3 ene' style: start is in previous month
        month1 = 12 if month2 == 1 else month2 - 1

    def build(y: int) -> tuple[date, date]:
        y1 = y - 1 if month1 > month2 else y  # week spans New Year
        return date(y1, month1, int(d1)), date(y, month2, int(d2))

    warnings: list[str] = []
    if year is None:
        if fallback_year is None:
            raise DateError("The file name has no year; pass --year or set plan.year")
        candidates = [fallback_year, fallback_year - 1, fallback_year + 1]
        for y in candidates:
            try:
                s, e = build(y)
            except ValueError:
                continue
            if s.weekday() == 0 and (e - s).days == 6:
                year = y
                break
        else:
            raise DateError("Could not infer the year; pass --year or set plan.year")
        warnings.append(f"Year {year} inferred from workbook metadata; pass --year to be explicit.")
    start, end = build(year)
    if (end - start).days != 6:
        raise DateError(f"{filename!r} with year {year} spans {(end - start).days + 1} days, not 7")
    if start.weekday() != 0:
        raise DateError(f"Week would start on {start:%A} {start}, not Monday; is the year {year} right?")
    return start, warnings


def monday_of(d: date) -> date:
    return d - timedelta(days=d.weekday())


def plan_week_number(week_start: date, settings: Settings, cli_week: int | None = None) -> int:
    if cli_week is not None:
        return cli_week
    if settings.week_number is not None:
        return int(settings.week_number)
    if settings.plan_start is not None:
        weeks = (week_start - monday_of(settings.plan_start)).days // 7 + 1
        if weeks < 1:
            raise DateError(f"{week_start} is before the plan start {settings.plan_start}")
        return weeks
    raise DateError("Plan week unknown: pass --week-number or set plan.start_date / plan.week_number_override")


def workout_name(settings: Settings, week: int, iso_weekday: int, label: str) -> str:
    return (
        f"{settings.prefix} - S{week:0{settings.week_digits}d}"
        f"D{iso_weekday:0{settings.day_digits}d} - {label}"
    )


# Block-label classification -------------------------------------------------

# (substring in folded label, kind), first match wins
_KINDS = [
    ("calentamiento", "warm"),
    ("soltar", "warm"),
    ("serie", "series"),
    ("progresivo", "progresivo"),
    ("controlado", "controlado"),
    ("largo", "largo"),
    ("tirada", "largo"),
    ("rodaje", "rodaje"),
    ("suave", "suave"),
    ("recuperacion", "recuperacion"),
    ("caminar", "caminar"),
]
LABELS = {
    "series": "Series", "progresivo": "Progresivo", "controlado": "Controlado",
    "largo": "Tirada larga", "rodaje": "Rodaje", "suave": "Suave",
    "recuperacion": "Recuperación", "caminar": "Caminar",
}  # fmt: skip
PRIORITY = ["series", "progresivo", "controlado", "largo", "rodaje", "suave", "recuperacion", "caminar"]
# kinds that are plain continuous running at different intensities
_CONTINUOUS = {"largo", "rodaje", "controlado", "suave"}


def classify_label(label: str) -> str | None:
    f = fold(label)
    for needle, kind in _KINDS:
        if needle in f:
            return kind
    return None


def _all_steps(items):
    for i in items:
        yield from (i.steps if isinstance(i, RepeatGroup) else (i,))


def decide_kind(day: DayPlan) -> tuple[str | None, list[str]]:
    """Pick the main workout kind. Returns (kind or None if ambiguous, warnings)."""
    kinds = list(dict.fromkeys(k for k in day.block_kinds if k != "warm"))
    if not kinds:
        return None, ["Only warm-up/cooldown steps found; cannot tell the workout type."]
    if len(kinds) == 1:
        return kinds[0], []
    if "series" in kinds:  # intervals dominate (e.g. series + easy running around them)
        return "series", [f"Several block kinds {kinds}; named after 'series'."]
    if set(kinds) <= _CONTINUOUS:
        paces = _ordered_main_paces(day)
        if len(paces) == len(kinds) and all(a.mean_s > b.mean_s for a, b in zip(paces, paces[1:])):
            return "progresivo", [f"Blocks {kinds} get steadily faster: named 'Progresivo' (inferred)."]
    best = next(k for k in PRIORITY if k in kinds)
    return None, [f"Ambiguous workout type {kinds} (suggestion: {LABELS[best]}); use --name-override."]


def _ordered_main_paces(day: DayPlan) -> list[Pace]:
    paces = []
    for s in _all_steps(day.items):
        if s.label and classify_label(s.label) != "warm":
            if s.pace is None:
                return []
            paces.append(s.pace)
    return paces


def build_workout(day: DayPlan, week: int, settings: Settings, override: str | None = None) -> Workout | None:
    """DayPlan -> Workout (None for rest days / days without programmed steps)."""
    if day.rest or not day.items:
        return None
    warnings = list(day.warnings)
    if override:
        label: str | None = override
    else:
        kind, w = decide_kind(day)
        warnings += w
        label = settings.names.get(kind, LABELS[kind]) if kind else None
    return Workout(
        date=day.date,
        iso_weekday=day.iso_weekday,
        week=week,
        name=workout_name(settings, week, day.iso_weekday, label) if label else None,
        items=day.items,
        notes=day.note,
        warnings=warnings,
        errors=list(day.errors),
    )
