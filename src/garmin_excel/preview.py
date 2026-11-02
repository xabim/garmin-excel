"""Human-readable preview of the week and of the sync plan."""

from __future__ import annotations

from .model import HeartRate, Item, Pace, RepeatGroup, Step, StepKind, Workout, WeekPlan
from .parser import fmt_pace

DAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
KIND = {StepKind.WARMUP: "Warm-up", StepKind.RUN: "Run", StepKind.RECOVERY: "Recovery", StepKind.COOLDOWN: "Cooldown"}


def fmt_duration(sec: float | None) -> str:
    if sec is None:
        return "n/a"
    sec = round(sec)
    h, rest = divmod(sec, 3600)
    return f"{h}h{rest // 60:02d}" if h else f"{rest // 60} min"


def _pace(p: Pace | None) -> str:
    if not p:
        return ""
    rng = f"{fmt_pace(p.fast_s)}-{fmt_pace(p.slow_s)}/km"
    return f"@ {fmt_pace(p.nominal_s)}/km ({rng} {'= sheet value ±tolerance' if p.derived else 'from sheet'})"


def _hr(h: HeartRate | None) -> str:
    if not h:
        return ""
    if h.zone:
        return f"HR zone {h.zone}"
    return f"HR {h.low:g}-{h.high:g} bpm" + (" (±tolerance)" if h.derived else "")


def step_line(s: Step) -> str:
    if s.distance_m is not None:
        amount = f"{s.distance_m / 1000:g} km"
    elif s.duration_s is not None:
        amount = f"{s.duration_s / 60:g} min"
    else:
        amount = "until lap button"
    return " ".join(x for x in (f"{KIND[s.kind]:<9}", amount, _pace(s.pace), _hr(s.hr)) if x)


def item_lines(item: Item, indent: str = "      ") -> list[str]:
    if isinstance(item, RepeatGroup):
        lines = [f"{indent}Repeat {item.iterations}x" + (" (no recovery after the last)" if item.skip_last_rest else "")]
        return lines + [f"{indent}  {step_line(s)}" for s in item.steps]
    return [f"{indent}{step_line(item)}"]


def render_week(week: WeekPlan, workouts: dict[int, Workout | None], week_no: int) -> str:
    out = ["Training plan import", "====================", "", f"Source: {week.source}", f"Week: S{week_no:02d}  ({week.start} to {week.days[-1].date if week.days else '?'})", ""]
    out += [f"! {w}" for w in week.warnings]
    if week.warnings:
        out.append("")
    n = rest = 0
    km = 0.0
    for day in week.days:
        w = workouts.get(day.iso_weekday)
        out.append(f"{DAYS[day.iso_weekday - 1]} {day.date}:")
        if w is None:
            out.append("  Rest day" if day.rest else "  No planned workout")
            out += [f"  ! {x}" for x in day.warnings + day.errors]
            rest += 1
            out.append("")
            continue
        n += 1
        km += w.distance_m / 1000
        out.append(f"  {w.name or '<AMBIGUOUS NAME>'}")
        out.append(f"  Distance: {w.distance_m / 1000:g} km   Est. duration: {fmt_duration(w.duration_s)}   Steps: {w.step_count}")
        for item in w.items:
            out += item_lines(item)
        out += [f"  ! {x}" for x in w.warnings]
        out += [f"  ERROR: {x}" for x in w.errors]
        out.append("")
    out += ["Total:", f"  {n} workouts", f"  {rest} rest/empty days", f"  {km:g} km planned"]
    return "\n".join(out)


def render_plan(items) -> str:
    out = ["Garmin Connect status:", ""]
    for it in items:
        extra = f"  ({it.reason})" if it.reason else ""
        out.append(f"  {it.workout.date}  {it.workout.name or '<ambiguous>':<36} -> {it.action.upper()}{extra}")
    return "\n".join(out)
