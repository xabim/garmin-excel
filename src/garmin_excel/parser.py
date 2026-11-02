"""Parser for the weekly training workbook.

Layout (verified on the real files): one sheet per weekday (lunes..domingo) plus
other sheets that are ignored. On each day sheet a header row holds 'Programado' (merged over
the planned columns) and 'Realizado' (completed data, ignored). Below it sit
column headers (series, rec, orden, km, Ritmo, HR) and fixed 3-row blocks whose
title is in column A ('Calentamiento y Soltar', 'Rodaje', ...). Ritmo/HR are
merged across a block. Columns are located by header text, never by letter.
"""

from __future__ import annotations

import datetime as dt
import re
from pathlib import Path
from typing import Any

import openpyxl
from openpyxl.worksheet.worksheet import Worksheet

from .config import Settings
from .model import DayPlan, HeartRate, Pace, RepeatGroup, Step, StepKind, WeekPlan
from .naming import DateError, classify_label, fold, parse_week_dates

WEEKDAYS = {"lunes": 1, "martes": 2, "miercoles": 3, "jueves": 4, "viernes": 5, "sabado": 6, "domingo": 7}
PLACEHOLDERS = {"", "-", "–", "—"}
PACE_MIN_S, PACE_MAX_S = 150, 720  # 2:30 .. 12:00 per km
MAX_STEP_KM = 60
MAX_HR = 230


class CellError(ValueError):
    pass


# ---- cell helpers -----------------------------------------------------------


def is_blank(v: Any) -> bool:
    return v is None or (isinstance(v, str) and v.strip() in PLACEHOLDERS)


def number(v: Any, what: str) -> float | None:
    if is_blank(v):
        return None
    if isinstance(v, bool):
        raise CellError(f"{what}: unexpected boolean")
    if isinstance(v, (int, float)):
        return float(v)
    if isinstance(v, str):
        try:
            return float(v.strip().replace(",", "."))
        except ValueError:
            pass
    raise CellError(f"{what}: cannot read {v!r} as a number")


def clock_seconds(v: Any) -> float | None:
    """Excel time cell -> seconds, reading it as mm:ss.

    Paces are typed as '7:10' into h:mm cells, so Excel stores 07:10:00. The hour
    field therefore means minutes and the minute field seconds. A cell already
    stored as 0:07:10 (h == 0 and s != 0) is read literally.
    """
    if isinstance(v, dt.datetime):
        v = v.time()
    if isinstance(v, dt.timedelta):
        total = int(v.total_seconds())
        h, m, s = total // 3600, total % 3600 // 60, total % 60
    elif isinstance(v, dt.time):
        h, m, s = v.hour, v.minute, v.second
    else:
        return None
    return float(m * 60 + s) if h == 0 and s != 0 else float(h * 60 + m)


def _mmss(text: str) -> float:
    m = re.fullmatch(r"(\d{1,2})[:'´’.](\d{2})(?:\s*(?:min)?/?\s*km)?", text.strip())
    if not m:
        raise CellError(f"cannot read {text!r} as a pace")
    return int(m.group(1)) * 60 + int(m.group(2))


def parse_pace(v: Any, tolerance_s: int) -> Pace | None:
    if is_blank(v):
        return None
    secs = clock_seconds(v)
    if secs is not None:
        lo = hi = nominal = secs
    elif isinstance(v, str):
        parts = re.split(r"\s*(?:-|–|—|a)\s*", v.strip().lower().replace("min/km", ""))
        vals = sorted(_mmss(p) for p in parts if p)
        if not 1 <= len(vals) <= 2:
            raise CellError(f"Ritmo: cannot read {v!r}")
        lo, hi = vals[0], vals[-1]
        nominal = (lo + hi) / 2
    else:
        raise CellError(f"Ritmo: cannot read {v!r}")
    derived = lo == hi
    if derived:
        lo, hi = lo - tolerance_s, hi + tolerance_s
    if not PACE_MIN_S <= nominal <= PACE_MAX_S:
        raise CellError(f"Ritmo {fmt_pace(nominal)}/km is outside the plausible range 2:30-12:00")
    return Pace(fast_s=lo, slow_s=hi, nominal_s=nominal, derived=derived)


def fmt_pace(sec: float) -> str:
    sec = round(sec)
    return f"{sec // 60}:{sec % 60:02d}"


def parse_hr(v: Any, tolerance: int) -> HeartRate | None:
    if is_blank(v):
        return None
    if isinstance(v, str):
        t = v.strip().lower()
        z = re.fullmatch(r"z\s*([1-5])", t)
        if z:
            return HeartRate(zone=int(z.group(1)))
        r = re.fullmatch(r"(\d{2,3})\s*[-–]\s*(\d{2,3})", t)
        if r:
            lo, hi = sorted((int(r.group(1)), int(r.group(2))))
            _check_hr(lo), _check_hr(hi)
            return HeartRate(low=lo, high=hi)
    n = number(v, "HR")
    _check_hr(n)
    return HeartRate(low=n - tolerance, high=n + tolerance, derived=True)


def _check_hr(n: float | None) -> None:
    if n is None or not 30 <= n <= MAX_HR:
        raise CellError(f"HR {n} is outside 30-{MAX_HR} bpm")


def rec_seconds(v: Any) -> float | None:
    if is_blank(v):
        return None
    secs = clock_seconds(v)
    if secs is not None:
        return secs
    if isinstance(v, str) and ":" in v:
        return float(_mmss(v))
    n = number(v, "rec")
    if n is None or n < 0 or n > 60:
        raise CellError(f"rec: {v!r} minutes is not plausible")
    return n * 60


# ---- sheet reading -----------------------------------------------------------


class Grid:
    """Cell access that resolves merged ranges to their top-left value."""

    def __init__(self, ws: Worksheet):
        self.ws = ws
        self.merged: dict[tuple[int, int], tuple[int, int]] = {}
        for rng in ws.merged_cells.ranges:
            for r in range(rng.min_row, rng.max_row + 1):
                for c in range(rng.min_col, rng.max_col + 1):
                    self.merged[(r, c)] = (rng.min_row, rng.min_col)

    def get(self, r: int, c: int) -> Any:
        r, c = self.merged.get((r, c), (r, c))
        return self.ws.cell(r, c).value


def _find(grid: Grid, text: str, max_row: int = 12) -> tuple[int, int] | None:
    for row in grid.ws.iter_rows(min_row=1, max_row=max_row):
        for c in row:
            if isinstance(c.value, str) and fold(c.value) == text:
                return c.row, c.column
    return None


COLS = {"series": "series", "rec": "rec", "orden": "orden", "km": "km", "ritmo": "ritmo", "hr": "hr"}


def _columns(grid: Grid, header_row: int, first: int, last: int) -> dict[str, int]:
    cols: dict[str, int] = {}
    for c in range(first, last):
        v = grid.get(header_row, c)
        if not isinstance(v, str):
            continue
        f = fold(v)
        for key in COLS:
            if f.startswith(key) and key not in cols:
                cols[key] = c
    missing = {"km", "ritmo"} - cols.keys()
    if missing:
        raise CellError(f"Programado header is missing columns {sorted(missing)}")
    return cols


def parse_day_sheet(ws: Worksheet, iso_weekday: int, day: dt.date, settings: Settings) -> DayPlan:
    grid = Grid(ws)
    plan = DayPlan(date=day, iso_weekday=iso_weekday, sheet=ws.title, rest=False, items=[], block_kinds=[])
    prog = _find(grid, "programado")
    real = _find(grid, "realizado")
    if prog is None:
        plan.errors.append("No 'Programado' header found on the sheet.")
        return plan
    head_row, prog_col = prog
    # The Programado columns end where Realizado starts (or after 8 columns).
    end_col = real[1] if real and real[1] > prog_col else prog_col + 8
    # Column headers sit on the first row below the header that has 'km'.
    hdr = next((r for r in range(head_row + 1, head_row + 4) if _has_km(grid, r, prog_col, end_col)), None)
    if hdr is None:
        plan.errors.append("No column header row (series/rec/orden/km/Ritmo/HR) under 'Programado'.")
        return plan
    try:
        cols = _columns(grid, hdr, prog_col, end_col)
    except CellError as e:
        plan.errors.append(str(e))
        return plan

    # Rest marker / free-text day note live above the table (column A).
    notes = [str(grid.get(r, 1)).strip() for r in range(1, head_row + 1) if not is_blank(grid.get(r, 1))]
    for n in notes:
        if fold(n).startswith("descanso"):
            plan.rest = True
        else:
            plan.note = n

    # Blocks: every non-blank title in column A between the header and 'km día'.
    last_row = ws.max_row
    stop = next((r for r in range(hdr + 1, ws.max_row + 1) if _is_total(grid.get(r, 1))), last_row + 1)
    titles = [r for r in range(hdr + 1, stop) if not is_blank(grid.get(r, 1))]
    raw_steps: list[dict[str, Any]] = []
    for i, start in enumerate(titles):
        end = titles[i + 1] if i + 1 < len(titles) else stop
        label = str(grid.get(start, 1)).strip()
        kind = classify_label(label)
        for r in range(start, end):
            try:
                row = _read_row(grid, r, cols, settings)
            except CellError as e:
                plan.errors.append(f"{ws.title} row {r} ({label}): {e}")
                continue
            if row is None:
                continue
            row.update(label=label, kind=kind, row=r)
            raw_steps.append(row)
            if kind is None:
                plan.warnings.append(f"Row {r}: unknown block label {label!r}; treated as plain running.")

    _assemble(plan, raw_steps)
    if plan.rest and plan.items:
        plan.warnings.append("Sheet is marked 'Descanso' but also has planned steps; treated as REST (nothing imported).")
    if not plan.items and plan.note and not plan.rest:
        plan.warnings.append(f"No planned steps, but the sheet has a note: {plan.note!r}. Nothing imported.")
    return plan


def _has_km(grid: Grid, r: int, c0: int, c1: int) -> bool:
    return any(isinstance(grid.get(r, c), str) and fold(grid.get(r, c)).startswith("km") for c in range(c0, c1))


def _is_total(v: Any) -> bool:
    return isinstance(v, str) and fold(v).startswith("km dia")


def _read_row(grid: Grid, r: int, cols: dict[str, int], settings: Settings) -> dict[str, Any] | None:
    def cell(key: str) -> Any:
        return grid.get(r, cols[key]) if key in cols else None

    km = number(cell("km"), "km")
    series = number(cell("series"), "series")
    rec = rec_seconds(cell("rec"))
    orden = number(cell("orden"), "orden")
    if km is None and series is None and orden is None:
        return None  # unused row of the template
    if km is None or km <= 0:
        raise CellError("row has series/orden but no km")
    if km > MAX_STEP_KM:
        raise CellError(f"{km:g} km is not plausible for one step")
    if series is not None and (series < 1 or series != int(series) or series > 50):
        raise CellError(f"series={series:g} is not a valid repetition count")
    return {
        "km": km,
        "series": int(series) if series else 1,
        "rec_s": rec,
        "orden": int(orden) if orden is not None else None,
        "pace": parse_pace(cell("ritmo"), settings.pace_tolerance_s),
        "hr": parse_hr(cell("hr"), settings.hr_tolerance_bpm),
    }


def _assemble(plan: DayPlan, raw: list[dict[str, Any]]) -> None:
    if not raw:
        return
    if any(r["orden"] is None for r in raw):
        plan.warnings.append("Some steps have no 'orden'; sheet order is used for them.")
    # stable sort: orden first, then sheet position (missing orden sorts last)
    ordered = sorted(raw, key=lambda r: (r["orden"] is None, r["orden"] or 0, r["row"]))
    seen = [r["orden"] for r in ordered if r["orden"] is not None]
    if len(seen) != len(set(seen)):
        plan.warnings.append("Duplicate 'orden' values; ties are broken by sheet row.")
    main_ordens = [r["orden"] for r in ordered if r["kind"] != "warm" and r["orden"] is not None]
    first_main = min(main_ordens, default=None)
    last_main = max(main_ordens, default=None)
    warm_seen = False
    for r in ordered:
        kind = StepKind.RUN
        if r["kind"] == "warm":
            if first_main is None or last_main is None:
                kind = StepKind.COOLDOWN if warm_seen else StepKind.WARMUP
                plan.warnings.append("Warm-up/cooldown block without a main block: first row = warm-up, later rows = cooldown.")
            elif r["orden"] is not None and r["orden"] < first_main:
                kind = StepKind.WARMUP
            elif r["orden"] is not None and r["orden"] > last_main:
                kind = StepKind.COOLDOWN
            else:
                kind = StepKind.WARMUP
                plan.warnings.append(f"Row {r['row']}: cannot tell warm-up from cooldown; assumed warm-up.")
            warm_seen = True
        else:
            plan.block_kinds.append(r["kind"] or "other")
        plan.items.append(_to_item(plan, r, kind))
    plan.block_kinds[:] = [k for k in dict.fromkeys(plan.block_kinds) if k != "other"]


def _to_item(plan: DayPlan, r: dict[str, Any], kind: StepKind):
    base = dict(distance_m=round(r["km"] * 1000), pace=r["pace"], hr=r["hr"], label=r["label"])
    n = r["series"]
    if n > 1:
        steps = [Step(kind=StepKind.RUN, **base)]
        if r["rec_s"]:
            steps.append(Step(kind=StepKind.RECOVERY, duration_s=r["rec_s"], label=r["label"]))
        plan.warnings.append(
            f"Row {r['row']} ({r['label']}): {n} series read as {n}x {r['km']:g} km"
            + (f" with {r['rec_s'] / 60:g} min recovery between" if r["rec_s"] else "")
            + " (assumed: km is per repetition)."
        )
        return RepeatGroup(iterations=n, steps=tuple(steps), skip_last_rest=bool(r["rec_s"]))
    if r["rec_s"]:
        plan.warnings.append(f"Row {r['row']} ({r['label']}): 'rec' given for a single repetition; ignored.")
    return Step(kind=kind, **base)


# ---- workbook ----------------------------------------------------------------


def parse_workbook(path: Path, settings: Settings, year: int | None = None) -> WeekPlan:
    wb = openpyxl.load_workbook(path, data_only=False)  # we never read formulas' values
    props = wb.properties
    meta = props.modified or props.created
    start, warnings = parse_week_dates(path.name, year or settings.year, meta.year if meta else None)
    days: dict[int, DayPlan] = {}
    for ws in wb.worksheets:
        wd = WEEKDAYS.get(fold(ws.title))
        if wd is None:
            continue
        if wd in days:
            warnings.append(f"Sheet {ws.title!r} duplicates weekday {wd}; ignored.")
            continue
        days[wd] = parse_day_sheet(ws, wd, start + dt.timedelta(days=wd - 1), settings)
    for wd in sorted(set(range(1, 8)) - days.keys()):
        warnings.append(f"No sheet found for ISO weekday {wd}.")
    return WeekPlan(source=path.name, start=start, days=[days[k] for k in sorted(days)], warnings=warnings)
