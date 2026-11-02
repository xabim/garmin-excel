"""Settings loaded from garmin-excel.yaml (all optional)."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

import yaml


@dataclass
class Settings:
    prefix: str = "RUN"
    week_digits: int = 2
    day_digits: int = 2
    plan_start: date | None = None
    week_number: int | None = None
    year: int | None = None
    pace_tolerance_s: int = 10
    hr_tolerance_bpm: int = 5
    names: dict[str, str] = field(default_factory=dict)  # block kind -> label override


def load_settings(path: Path | None) -> Settings:
    s = Settings()
    if path is None:
        default = Path("garmin-excel.yaml")
        if not default.exists():
            return s
        path = default
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    naming, plan = raw.get("naming") or {}, raw.get("plan") or {}
    s.prefix = naming.get("prefix", s.prefix)
    s.week_digits = int(naming.get("week_number_digits", s.week_digits))
    s.day_digits = int(naming.get("day_number_digits", s.day_digits))
    start = plan.get("start_date")
    if start is not None:
        s.plan_start = start if isinstance(start, date) else date.fromisoformat(str(start))
    s.week_number = plan.get("week_number_override")
    s.year = plan.get("year")
    s.pace_tolerance_s = int((raw.get("pace") or {}).get("tolerance_seconds_per_km", s.pace_tolerance_s))
    s.hr_tolerance_bpm = int((raw.get("heart_rate") or {}).get("tolerance_bpm", s.hr_tolerance_bpm))
    s.names = {str(k).lower(): str(v) for k, v in (raw.get("names") or {}).items()}
    return s
