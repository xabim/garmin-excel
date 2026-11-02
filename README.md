# garmin-excel

Imports a weekly Excel running plan (the `Programado` section only) into the Garmin Connect calendar as
structured running workouts named `RUN - S04D06 - Controlado` (prefix configurable).

It targets one specific, Spanish-language workbook layout (one sheet per weekday, `Programado` / `Realizado`
blocks; described below). It is not a general Excel importer, and it ships no sample workbook.

```
Excel -> parser.py -> model.py (normalized Workout) -> payload.py -> gateway.py (python-garminconnect) -> Garmin
```

## Install and use

```bash
uv sync
uv run garmin-excel preview --input plan.xlsx --week-number 4          # offline, touches nothing
uv run garmin-excel upload  --input plan.xlsx --week-number 4 --dry-run # logs in, shows create/skip/update, writes nothing
uv run garmin-excel upload  --input plan.xlsx --week-number 4          # preview + status + typed "yes" confirmation
```

Manage what the tool created (only workouts tagged by this tool; hand-made ones are never touched):

```bash
uv run garmin-excel list [--week 5]
uv run garmin-excel delete --week 5 --dry-run   # show what would go
uv run garmin-excel delete --week 5             # asks you to type 'delete'; also removes their calendar entries
uv run garmin-excel delete --name "RUN - S05D02 - Caminar"
```

Flags: `--year` (file names carry no year), `--name-override D06=Controlado` (fix an ambiguous day),
`--yes` (skip the prompt; never overwrites), `--update-changed` (overwrite existing workouts whose content differs),
`--config file.yaml`. Copy `garmin-excel.example.yaml` to `garmin-excel.yaml` (git-ignored) for prefix, plan start / week override,
year, pace and HR tolerance, and a name map.

Credentials: `GARMIN_EMAIL` / `GARMIN_PASSWORD` or an interactive prompt (MFA supported). Only OAuth tokens are
kept, in `~/.config/garmin-excel/tokens` (override with `GARMIN_EXCEL_TOKENS`), dir `0700`, files `0600`. Nothing is printed or logged.
Optional: `docker build -t garmin-excel .` (see the Dockerfile header).

Tests: `uv run pytest` (Garmin is faked; workbooks are generated synthetically).

## Built on

[python-garminconnect](https://github.com/cyberjunky/python-garminconnect) does the Garmin side (auth, upload, update, schedule, list).
Only the Excel -> normalized model -> Garmin JSON layer lives here.

## How the workbook is read

* Sheets `lunes..domingo` (accent/space/case-insensitive) are day sheets; other sheets are ignored. Columns are found by
  header text under `Programado`; everything from `Realizado` onwards is never read.
* Blocks are the titles in column A until `km día`. Merged `Ritmo`/`HR` cells resolve to their top-left value.
* Steps are ordered by `orden`. In the `Calentamiento y Soltar` block, a row before every main step is the **warm-up**,
  after all of them the **cooldown**.
* `Descanso` in A2/A3 = rest day. Dates come from the file name (`19_25 oct`, `26 oct_1 nov`, New Year spans); the year is
  `--year`/config, otherwise inferred from workbook metadata **with a warning** and only if the week then starts on a Monday.
* Paces typed `7:10` are stored by Excel as 07:10:00 (h:mm) and read as 7 min 10 s per km.

## Assumptions (shown as warnings in the preview)

1. **Intervals:** `series` / `rec` rows are read as N repetitions of `km` each with `rec` minutes of recovery between, no recovery after the last,
   uploaded as a real Garmin repeat group. Nested repeats (e.g. `2x(4x500)`) are not supported.
2. **Single pace -> range:** a single pace becomes `pace ± tolerance` (default 10 s/km, labelled as derived in the preview). Ranges in the sheet are kept as-is.
3. **Block label = workout name** (`Tirada larga`, `Rodaje`, `Controlado`, `Series`, `Caminar`, ...). Several different main blocks in one day are named `Progresivo`
   only if paces get steadily faster; otherwise the day is flagged ambiguous and **blocked** until `--name-override`.
4. **Caminar** is uploaded as a running workout (Garmin has no walking workout type).
5. Days with only a free-text note and no planned steps import nothing.
6. The plan week number is not in the file; pass it or set `plan.start_date`.

## Duplicates and safety

* Each workout embeds `[garmin-excel:<hash>]` (hash of name + steps) in its Garmin description. Per workout the tool decides:
  create / skip (same hash, already on that date) / schedule-only / update / blocked. Workouts are matched by exact name.
* Updates need `--update-changed` or an interactive "yes"; nothing is ever deleted. A failure mid-way is safe to rerun.
* **Unofficial API:** python-garminconnect uses Garmin's private endpoints and login flow. Garmin can change them or rate-limit logins at any time,
  and automated access may violate Garmin's terms. Use at your own risk, for personal use.
* The spreadsheet is parsed locally; only the resulting workout structure is sent to Garmin.

## License

MIT
