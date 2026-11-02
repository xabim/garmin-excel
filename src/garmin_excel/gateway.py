"""Thin wrapper over python-garminconnect: auth + the few calls we need.

Credentials: GARMIN_EMAIL / GARMIN_PASSWORD env vars, or an interactive prompt.
Only OAuth tokens are stored, under ~/.config/garmin-excel (0700 dir, 0600 files).
Nothing here ever prints or logs credentials or tokens.
"""

from __future__ import annotations

import getpass
import os
import stat
from pathlib import Path
from typing import Any, Protocol

TOKEN_DIR = Path(os.environ.get("GARMIN_EXCEL_TOKENS", "~/.config/garmin-excel/tokens")).expanduser()


class Gateway(Protocol):
    def list_workouts(self) -> list[dict[str, Any]]: ...
    def get_workout(self, workout_id: int) -> dict[str, Any]: ...
    def scheduled(self, year: int, month: int) -> list[dict[str, Any]]: ...
    def create(self, payload: dict[str, Any]) -> int: ...
    def update(self, workout_id: int, payload: dict[str, Any]) -> None: ...
    def schedule(self, workout_id: int, day: str) -> None: ...
    def unschedule(self, scheduled_id: int) -> None: ...
    def delete(self, workout_id: int) -> None: ...


def _lock_down(path: Path) -> None:
    path.chmod(stat.S_IRWXU)
    for p in path.rglob("*"):
        p.chmod(stat.S_IRWXU if p.is_dir() else stat.S_IRUSR | stat.S_IWUSR)


class GarminGateway:
    def __init__(self, api: Any):
        self.api = api

    @classmethod
    def login(cls, token_dir: Path = TOKEN_DIR) -> "GarminGateway":
        from garminconnect import Garmin

        token_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        token_dir.chmod(stat.S_IRWXU)
        email = os.environ.get("GARMIN_EMAIL")
        password = os.environ.get("GARMIN_PASSWORD")
        api = Garmin(prompt_mfa=lambda: input("Garmin MFA code: ").strip())
        try:
            api.login(str(token_dir))  # reuses saved tokens
        except Exception:
            api = Garmin(
                email or input("Garmin email: ").strip(),
                password or getpass.getpass("Garmin password: "),
                prompt_mfa=lambda: input("Garmin MFA code: ").strip(),
            )
            api.login(str(token_dir))
        _lock_down(token_dir)
        return cls(api)

    def list_workouts(self) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        start = 0
        while True:
            page = self.api.get_workouts(start, 100) or []
            out += page
            if len(page) < 100:
                return out
            start += 100

    def get_workout(self, workout_id: int) -> dict[str, Any]:
        return self.api.get_workout_by_id(workout_id)

    def scheduled(self, year: int, month: int) -> list[dict[str, Any]]:
        data = self.api.get_scheduled_workouts(year, month) or {}
        return [i for i in data.get("calendarItems", []) if i.get("itemType") == "workout"]

    def create(self, payload: dict[str, Any]) -> int:
        return int(self.api.upload_workout(payload)["workoutId"])

    def update(self, workout_id: int, payload: dict[str, Any]) -> None:
        self.api.update_workout(workout_id, payload)

    def schedule(self, workout_id: int, day: str) -> None:
        self.api.schedule_workout(workout_id, day)

    def unschedule(self, scheduled_id: int) -> None:
        self.api.unschedule_workout(scheduled_id)

    def delete(self, workout_id: int) -> None:
        self.api.delete_workout(workout_id)
