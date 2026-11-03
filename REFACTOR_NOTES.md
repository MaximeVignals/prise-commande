# Refactor notes: split `src/main.py`

Branch `refactor/split-main`, from `ui-testing` (3a444a0). Plan: `docs/superpowers/plans/2026-11-03-split-main.md`.
Goal: split `main.py` into focused modules, zero behaviour change.

## Before

| File | Lines |
|---|---|
| `src/main.py` | 3163 |
| `src/backup.py` | 295 |
| `src/ui.py` | 208 |
| `tests/` (all files) | 1113 |

Baseline: 86 tests OK (`python -m unittest discover -s tests`).

## Bugs / risks (not fixed)

- `src/catalogue_importe.xlsx` and `src/catalogue_perso.json` exist in `src/`; they are git-ignored, but `flet build` packages `src/`, and `construire.ps1` only checks `src\assets`. Check before the next build.
- `CLAUDE.md` says version 1.2.0 / build 3; `pyproject.toml` is 1.5.0 / build 6.
- `storage/tests/catalogue_preview.py` and `scripts/preview_ui.py`: purpose unclear.
- No pytest or linter installed; tests run with `python -m unittest discover -s tests`.
