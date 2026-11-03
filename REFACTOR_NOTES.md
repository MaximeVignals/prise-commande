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

## After (Task 13)

| File | Lines |
|---|---|
| `src/main.py` | 65 |
| `src/config.py` | 23 |
| `src/text.py` | 69 |
| `src/storage.py` | 245 |
| `src/catalogue.py` | 217 |
| `src/orders.py` | 60 |
| `src/photos.py` | 64 |
| `src/context.py` | 139 |
| `src/import_screen.py` | 207 |
| `src/shell.py` | 290 |
| `src/view_cart.py` | 239 |
| `src/view_catalogue.py` | 344 |
| `src/view_orders.py` | 408 |
| `src/view_admin.py` | 425 |
| `src/view_catalogues.py` | 224 |
| `src/view_photos.py` | 415 |
| `src/view_backup.py` | 100 |
| `src/backup.py` | 295 |
| `src/ui.py` | 229 |
| `tests/` (all files) | 1396 |

Tests: 95 OK. Three modules stay just over 400 lines (`view_admin`, `view_photos`, `view_orders`): each is one screen, and splitting functions inside a module does not shorten it.

## Long functions (> 50 lines)

Split in Task 13 (verbatim blocks moved into helpers, same call point and order):
- `render_catalogue` 152 → 106 (`filter_catalogue`, `render_catalogue_empty`, `category_header`)
- `render_orders` 139 → 34 (`drawer_header`, `order_tile`)
- `shell.install` 268 → 234 (`install_appbar`, `finish_startup`)
- `load_prefs` 62 → 32 (`_load_custom_articles`, `_load_catalogue_snapshot`)
- `parse_catalogue` 70 → 56 (`_find_columns`)

Kept whole:
- `install()` of every view module and of `shell` (205–405 lines): the old closure body; the widgets and handlers share locals by closure.
- `render_catalogue` (106): what remains is the per-article card loop; its lambdas bind loop variables (`k=draft_key`, `item=current_item`, `q=qty_field`), so it stays inline.
- `render_cart` (58): same reason, per-line loop with lambdas binding `id_art` / `qty_field`.
- `drawer_header` (67): one list literal of fixed drawer entries.
- `add_article_dialog` (64): fields, `validate` closure and dialog form one unit; extracting the fields alone would leave it over 50.
- `ask_photo_label` (55): `save` / `remove` closures share the field and photo with the dialog.
- `parse_catalogue` (56): the per-row loop uses `continue` to build the skipped-line warnings; splitting it would restructure control flow.
- `show_import_screen` (95): a closure-heavy screen builder. Its four handlers share `page`, `file_picker` and `error_text`, and about 45 lines are one `page.add(...)` widget tree that wires up three of those handlers. Follow-up: that tree could become a helper that takes the three handlers and `error_text`. It contains no loops or lambdas that capture loop variables.
- `restore_backup` (65): one transactional sequence. It takes the recovery copy first, then merges, writes the recovery ZIP, stages the files, swaps them in and rolls back on error. `originals`, `touched`, `stage` and `recovery` are used across the `try`/rollback, which spans the second half. Follow-up: the order-merge loop (`mapping`/`updates`/`reserved_ids`) is contiguous and could become `_merge_orders(root, snapshot, merged)`.
- `make_theme` (64): a declarative theme table, a single `ColorScheme` plus a single `Theme(...)` call. It has no logic to separate.
- `request_restore` (61): the error handling spans the whole flow. The pick/inspect `try` returns early, and the nested `confirm` closure shares `snapshot`, `restore_button`, `restore_error` and `dismissed` with the dialog built after it.

## Bugs / risks (not fixed)

- `src/catalogue_importe.xlsx` and `src/catalogue_perso.json` exist in `src/`; they are git-ignored, but `flet build` packages `src/`, and `construire.ps1` only checks `src\assets`. Check before the next build.
- `CLAUDE.md` says version 1.2.0 / build 3; `pyproject.toml` is 1.5.0 / build 6.
- `storage/tests/catalogue_preview.py` and `scripts/preview_ui.py`: purpose unclear.
- No pytest or linter installed; tests run with `python -m unittest discover -s tests`.
- Seen once in the Task 12 web smoke (not reproduced after reload, not investigated against the pre-refactor build): after three quick add-to-cart clicks the cart showed a duplicate row for one article while the totals were right.
- `shell.install` was ~270 lines; Task 13 moved the app bar and the startup tail out (now 234, see "Long functions").
- `backup.py` still spells `"commandes.json"`, `"catalogue_perso.json"` and `"sauvegardes/avant-restauration-…zip"` itself (it is a standalone module with no app imports). `config.py` holds the same values (`ORDERS_FILENAME`, `PREFS_FILENAME`, `BACKUPS_DIRNAME`, `RECOVERY_BACKUP_PATTERN`): change both together.

## Changes required by the move

- Task 12: in `scripts/preview_ui.py`, only the import paths changed (`app.<name>` -> `catalogue`/`storage`/`config`/`backup`/`import_screen`), because main.py no longer re-exports those names.

## Design notes

- `import_screen.py` imports `main` lazily inside `start_app` and `done` (`from .main import main` / `from main import main`) because `main` imports `import_screen`; a top-level import would be a cycle.
- `context.py` / `AppContext` (Task 6) holds the state `main()` used to share through closures (`orders`, `state`, `prefs`, `cat`, `excel_items`, …) and the core helpers (`persist`, `show_snack`, …). Nothing rebinds these: `excel_items` is only mutated in place (`ctx.excel_items[:] = items`), so no alias can go stale. `main()` sets `page.data = {"ctx": ctx}` (`page.data` was unused) so tests can reach the context.
- Every save inside `main()` and `AppContext` goes through the module (`storage.save_orders(...)`), so tests patch `storage.save_orders` / `storage.save_prefs`, not `app.*`.
