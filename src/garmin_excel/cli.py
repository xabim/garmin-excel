"""Command line: garmin-excel preview | upload | login."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Callable

from .config import Settings, load_settings
from .gateway import Gateway, GarminGateway
from .model import WeekPlan, Workout
from .naming import DateError, build_workout, plan_week_number
from .parser import parse_workbook
from .preview import render_plan, render_week
from .sync import CREATE, SCHEDULE, SKIP, UPDATE, delete_managed, execute, find_managed, plan_sync, verify


def build(args, settings: Settings) -> tuple[WeekPlan, dict[int, Workout | None], int]:
    week = parse_workbook(Path(args.input), settings, year=args.year)
    week_no = plan_week_number(week.start, settings, args.week_number)
    overrides = {}
    for spec in args.name_override or []:
        key, _, label = spec.partition("=")
        overrides[int(key.upper().lstrip("D"))] = label.strip()
    workouts = {d.iso_weekday: build_workout(d, week_no, settings, overrides.get(d.iso_weekday)) for d in week.days}
    return week, workouts, week_no


def cmd_preview(args, out=print) -> int:
    settings = load_settings(args.config)
    week, workouts, week_no = build(args, settings)
    out(render_week(week, workouts, week_no))
    bad = [w for w in workouts.values() if w and (w.errors or w.name is None)]
    return 1 if bad else 0


def cmd_upload(
    args,
    out=print,
    ask: Callable[[str], str] = input,
    gateway_factory: Callable[[], Gateway] = GarminGateway.login,
    interactive: bool | None = None,
) -> int:
    settings = load_settings(args.config)
    week, workouts, week_no = build(args, settings)
    out(render_week(week, workouts, week_no))
    todo = [w for w in workouts.values() if w]
    if not todo:
        out("\nNothing to upload.")
        return 0

    out("\nConnecting to Garmin Connect (read-only until you confirm)...")
    gw = gateway_factory()
    items = plan_sync(todo, gw)
    out("\n" + render_plan(items))

    actionable = [i for i in items if i.action in (CREATE, SCHEDULE, UPDATE)]
    if args.dry_run:
        out("\nDry run: nothing was created, updated or scheduled.")
        return 0
    if not actionable:
        out("\nNothing to do: everything is already in Garmin Connect.")
        return 0

    if not args.yes:
        counts = ", ".join(f"{sum(i.action == a for i in items)} {a}" for a in (CREATE, SCHEDULE, UPDATE) if any(i.action == a for i in items))
        if ask(f"\nProceed ({counts})? Type 'yes' to continue: ").strip().lower() != "yes":
            out("Cancelled. Nothing was changed.")
            return 1
    allow_update = args.update_changed
    changed = [i for i in items if i.action == UPDATE]
    if changed and not allow_update:
        tty = sys.stdin.isatty() if interactive is None else interactive
        if tty and ask(f"\n{len(changed)} existing workout(s) differ from the sheet. Overwrite them? Type 'yes': ").strip().lower() == "yes":
            allow_update = True

    execute(items, gw, allow_update)
    out("\nResults:")
    for it in items:
        out(f"  {it.workout.name or '<ambiguous>'}: {it.result}")
    problems = verify(items, gw)
    failed = [i for i in items if i.result.startswith("FAILED")]
    for p in problems:
        out(f"  VERIFY: {p}")
    done = sum(i.result in ("created + scheduled", "updated + scheduled", "scheduled") for i in items)
    out(f"\nSummary: {done} changed, {sum(i.action == SKIP for i in items)} unchanged, {len(failed)} failed. Sync your watch to receive them.")
    return 1 if failed or problems else 0


def _managed_lines(items) -> list[str]:
    return [f"  {m.name}  (id {m.workout_id})  scheduled: {', '.join(sorted(m.dates)) or 'not in calendar window'}" for m in items]


def cmd_list(args, out=print, gateway_factory: Callable[[], Gateway] = GarminGateway.login) -> int:
    settings = load_settings(args.config)
    items = find_managed(gateway_factory(), settings.prefix, args.week)
    out(f"Workouts created by garmin-excel ({len(items)}):")
    for line in _managed_lines(items):
        out(line)
    return 0


def cmd_delete(
    args,
    out=print,
    ask: Callable[[str], str] = input,
    gateway_factory: Callable[[], Gateway] = GarminGateway.login,
) -> int:
    """Delete workouts this tool created. Always needs a typed confirmation."""
    if args.week is None and not args.name:
        out("error: give --week N or --name 'exact workout name'")
        return 2
    settings = load_settings(args.config)
    gw = gateway_factory()
    items = find_managed(gw, settings.prefix, args.week, args.name)
    if not items:
        out("No matching workouts created by garmin-excel (hand-made workouts are never touched).")
        return 0
    out("Would delete (workout + its calendar entries):")
    for line in _managed_lines(items):
        out(line)
    if args.dry_run:
        out("\nDry run: nothing was deleted.")
        return 0
    if ask(f"\nDelete {len(items)} workout(s) from Garmin Connect? This cannot be undone. Type 'delete': ").strip() != "delete":
        out("Cancelled. Nothing was deleted.")
        return 1
    delete_managed(items, gw)
    for m in items:
        out(f"  {m.name}: {m.result}")
    return 1 if any(m.result.startswith("FAILED") for m in items) else 0


def cmd_login(args, out=print) -> int:
    GarminGateway.login()
    out("Logged in; tokens stored with owner-only permissions.")
    return 0


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="garmin-excel", description=__doc__)
    sub = p.add_subparsers(dest="cmd", required=True)
    for name in ("preview", "upload"):
        s = sub.add_parser(name)
        s.add_argument("--input", required=True, help="weekly .xlsx plan")
        s.add_argument("--week-number", type=int, help="plan week (overrides config)")
        s.add_argument("--year", type=int, help="year of the file (overrides config)")
        s.add_argument("--config", type=Path)
        s.add_argument("--name-override", action="append", metavar="D06=Controlado", help="force the label for one day")
        if name == "upload":
            s.add_argument("--dry-run", action="store_true", help="log in read-only, show what would change, write nothing")
            s.add_argument("--yes", action="store_true", help="skip the confirmation prompt (never implies --update-changed)")
            s.add_argument("--update-changed", action="store_true", help="overwrite existing workouts whose content differs")
    for name in ("list", "delete"):
        s = sub.add_parser(name, help="workouts created by this tool" + ("; deletes them" if name == "delete" else ""))
        s.add_argument("--week", type=int, help="plan week number, e.g. 5")
        s.add_argument("--config", type=Path)
        if name == "delete":
            s.add_argument("--name", help="exact workout name")
            s.add_argument("--dry-run", action="store_true", help="show what would be deleted")
    sub.add_parser("login")
    return p


def main(argv: list[str] | None = None) -> None:
    args = parser().parse_args(argv)
    try:
        code = {"preview": cmd_preview, "upload": cmd_upload, "list": cmd_list, "delete": cmd_delete, "login": cmd_login}[args.cmd](args)
    except (DateError, FileNotFoundError) as e:
        print(f"error: {e}", file=sys.stderr)
        code = 2
    sys.exit(code)
