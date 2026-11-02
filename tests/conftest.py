import datetime as dt

import openpyxl
import pytest

from garmin_excel.config import Settings

BLOCKS = [5, 8, 11, 14, 17, 20]
DEFAULT_TITLES = ["Calentamiento y Soltar", "Entrenamiento Largo", "Rodaje", "Controlado", "Series largas", "Series 2x(4x500)"]
SHEETS = ["lunes", "martes", "miercoles", "jueves", "viernes", "Sábado ", "domingo"]


def mmss(m, s=0):
    return dt.time(m, s)  # typed style: 7:10 typed in an h:mm cell is stored as 07:10:00


def day_sheet(wb, title, *, rest=False, note=None, blocks=None, realizado=None):
    """blocks: {block_index: dict(title=, pace=, hr=, rows=[(series, rec, orden, km), ...])}"""
    ws = wb.create_sheet(title)
    if rest:
        ws["A3"] = "Descanso"
    if note:
        ws["A2"] = note
    ws["B3"], ws["H3"] = "Programado", "Realizado"
    ws.merge_cells("B3:G3"), ws.merge_cells("H3:L3")
    for col, h in zip("BCDEFG", ["series", "rec (´)", "orden", "km", "Ritmo", "HR"]):
        ws[f"{col}4"] = h
    for col, h in zip("HIJKLMN", ["series", "rec (´)", "orden", "tiempo(´)", "HR", "Ritmo", "Kms"]):
        ws[f"{col}4"] = h
    for i, r in enumerate(BLOCKS):
        ws[f"A{r}"] = DEFAULT_TITLES[i]
        for rng in ("A", "F", "G", "L", "M"):
            ws.merge_cells(f"{rng}{r}:{rng}{r + 2}")
        for k in range(3):
            for col in "CBDE":
                ws[f"{col}{r + k}"] = "-"
    for idx, spec in (blocks or {}).items():
        r = BLOCKS[idx]
        if "title" in spec:
            ws[f"A{r}"] = spec["title"]
        if "pace" in spec:
            ws[f"F{r}"] = spec["pace"]
        if "hr" in spec:
            ws[f"G{r}"] = spec["hr"]
        for k, (series, rec, orden, km) in enumerate(spec["rows"]):
            for col, v in zip("BCDE", (series, rec, orden, km)):
                ws[f"{col}{r + k}"] = "-" if v is None else v
    ws["A23"], ws["E23"] = "km día", "=SUM(E5:E22)"
    for cell, v in (realizado or {}).items():
        ws[cell] = v
    return ws


@pytest.fixture
def make_week(tmp_path):
    def _make(name="Test 19_25 oct.xlsx", days=None):
        wb = openpyxl.Workbook()
        wb.remove(wb.active)
        for t in SHEETS:
            key = t.strip().casefold().replace("é", "e").replace("á", "a")
            day_sheet(wb, t, **(days or {}).get(key, {"rest": True}))
        wb.create_sheet("Other")["A1"] = "irrelevant"
        path = tmp_path / name
        wb.save(path)
        return path
    return _make


@pytest.fixture
def settings():
    return Settings(year=2026)




@pytest.fixture(autouse=True)
def _isolated_cwd(tmp_path_factory, monkeypatch):
    """Never pick up a developer's local garmin-excel.yaml."""
    monkeypatch.chdir(tmp_path_factory.mktemp("cwd"))
