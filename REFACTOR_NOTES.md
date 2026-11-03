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
- Seen once in the Task 12 web smoke (not reproduced after reload, not investigated against the pre-refactor build): after three quick add-to-cart clicks the cart showed a duplicate row for one article while the totals were right.
- `shell.install` is ~270 lines (layout, routes, resize handlers, app bar in one function); splitting is Task 13.

## Design notes

- `import_screen.py` imports `main` lazily inside `start_app` and `done` (`from .main import main` / `from main import main`) because `main` imports `import_screen`; a top-level import would be a cycle.
- `context.py` / `AppContext` (Task 6) holds the state `main()` used to share through closures (`orders`, `state`, `prefs`, `cat`, `excel_items`, …) and the core helpers (`persist`, `show_snack`, …). Nothing rebinds these: `excel_items` is only mutated in place (`ctx.excel_items[:] = items`), so no alias can go stale. `main()` sets `page.data = {"ctx": ctx}` (`page.data` was unused) so tests can reach the context.
- Every save inside `main()` and `AppContext` goes through the module (`storage.save_orders(...)`), so tests patch `storage.save_orders` / `storage.save_prefs`, not `app.*`.
