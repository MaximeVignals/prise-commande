# Refactor notes: split `src/main.py`

Branch `refactor/split-main`, from `ui-testing` (3a444a0). Plan: `docs/superpowers/plans/2026-11-03-split-main.md`.
Goal: split `main.py` into focused modules, zero behaviour change.
Tests: 86 before, 95 after (`python -m unittest discover -s tests`, all OK).

## Line counts before / after

Before = commit 3a444a0, after = this branch (`wc -l`).

| File | Before | After |
|---|---:|---:|
| `src/main.py` | 3163 | 65 |
| `src/config.py` | - | 23 |
| `src/text.py` | - | 69 |
| `src/storage.py` | - | 245 |
| `src/catalogue.py` | - | 217 |
| `src/orders.py` | - | 60 |
| `src/photos.py` | - | 64 |
| `src/context.py` | - | 139 |
| `src/import_screen.py` | - | 207 |
| `src/shell.py` | - | 290 |
| `src/view_cart.py` | - | 239 |
| `src/view_catalogue.py` | - | 344 |
| `src/view_orders.py` | - | 408 |
| `src/view_admin.py` | - | 425 |
| `src/view_catalogues.py` | - | 224 |
| `src/view_photos.py` | - | 415 |
| `src/view_backup.py` | - | 100 |
| `src/backup.py` | 295 | 295 |
| `src/ui.py` | 208 | 229 |
| **src total** | **3666** | **4058** |
| `tests/test_app.py` | 818 | 827 |
| `tests/test_productivity.py` | 429 | 434 |
| `tests/test_modules.py` | - | 135 |
| **tests total** | **1247** | **1396** |

The first notes quoted 1113 lines for the old tests; counting the two files at 3a444a0 gives 818 + 429 = 1247.
Three modules stay just over 400 lines (`view_admin`, `view_photos`, `view_orders`): each is one screen, and splitting functions inside a module does not shorten it.

### Long functions (> 50 lines)

Split in Task 13 (verbatim blocks moved into helpers, same call point and order):
- `render_catalogue` 152 -> 106 (`filter_catalogue`, `render_catalogue_empty`, `category_header`)
- `render_orders` 139 -> 34 (`drawer_header`, `order_tile`)
- `shell.install` 268 -> 234 (`install_appbar`, `finish_startup`)
- `load_prefs` 62 -> 32 (`_load_custom_articles`, `_load_catalogue_snapshot`)
- `parse_catalogue` 70 -> 56 (`_find_columns`)

Kept whole:
- `install()` of every view module and of `shell` (205-405 lines): the old closure body; the widgets and handlers share locals by closure.
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

## Architecture

```
src/
  main.py            entry point: builds AppContext, installs the modules, shows the import screen when no catalogue
  config.py          constants: file names, catalogue keys and columns, default catalogue label
  text.py            pure text/number helpers: fold, norm_text, fmt_eur, price parsing, search matching
  storage.py         file locations (storage dir, photos), load/save of orders and prefs, normalisation on load
  catalogue.py       catalogue parsing (.xlsx/.csv), install, build/merge catalogues, sample catalogue path
  orders.py          order-level helpers: totals, counts, e-mail text, duplicate
  photos.py          photo helpers: ZIP export, export names, summary, safe file names
  context.py         AppContext: shared state (orders, prefs, catalogue, ...) and core helpers (persist, snack, ...)
  import_screen.py   first-launch screen, catalogue file picking, restore-from-backup flow
  shell.py           page chrome: app bar, drawer host, navigation, layout (single/dual pane), startup tail
  view_cart.py       cart tab
  view_catalogue.py  catalogue tab (search, filters, favourites/recents)
  view_orders.py     orders drawer, order dialogs (new, rename, duplicate, archive, delete, notes)
  view_admin.py      "Gérer les articles" screen
  view_catalogues.py "Gérer les catalogues" screen and catalogue import from the menu
  view_photos.py     photos tab (import, label, delete, ZIP export, camera)
  view_backup.py     backup / restore screen
  backup.py          standalone backup ZIP create / inspect / restore logic (no app imports)
  ui.py              theme, window layout, icons (imports text only)
```

Dependency direction (verified by grepping the imports):

```
main -> shell, view_*, context, import_screen, catalogue
shell, view_* -> context -> catalogue / storage / orders / photos / import_screen -> text / config
ui and backup are leaf helpers (ui imports text only; backup imports nothing from the app)
```

Edges found beyond the plain downward chain (none creates a hard cycle):
- `import_screen -> main`: lazy import inside `start_app` and `done` (upward edge, see Design notes). It is the only edge that breaks the direction.
- `main` wires `shell` and every `view_*` directly; `shell` does not import the views.
- `view_backup` and `view_catalogues` import helpers from `import_screen` (`request_restore`, `pick_catalogue_file`, `skipped_summary`); `import_screen` imports no view or context.
- `view_*`, `shell` and `context` import some lower modules directly (`catalogue`, `config`, `storage`, `orders`, `photos`, `text`, `ui`, `backup`) instead of going through `context`; all of these point downward.
- Lower layers: `catalogue -> storage, config, text`; `orders -> storage, text`; `photos -> orders, storage, text`; `storage -> config, text`.
- No `view_*` imports another `view_*`; cross-view calls go through `ctx.<name>`.

## Changes required by the move

- Tests now import from the real modules (`catalogue`, `storage`, `orders`, `photos`, `context`, ...) instead of everything through `main`; `main.py` no longer re-exports them.
- Patch targets moved: `storage.save_orders` / `storage.save_prefs` (were `app.save_orders` / `app.save_prefs`) and `view_photos.fc` (was `app.fc`). Callers use `storage.<fn>(...)` through the module so the patches apply.
- The `AppContext` is exposed as `page.data["ctx"]` (`page.data` was unused) so tests can reach it.
- Task 12: in `scripts/preview_ui.py`, only the import paths changed (`app.<name>` -> `catalogue`/`storage`/`config`/`backup`/`import_screen`), because `main.py` no longer re-exports those names.
- The restore relaunch calls `ctx.main` (set by `main()`), not a module-level `main`.

## Bugs / risks (not fixed)

- `src/catalogue_importe.xlsx` and `src/catalogue_perso.json` exist in `src/`; they are git-ignored, but `flet build` packages `src/`, and `construire.ps1` only checks `src\assets`. Check before the next build.
- Web backup export shows "Enregistrement annulé." although the file does download. Pre-existing: confirmed byte-identical behaviour in the old code (3a444a0).
- `CLAUDE.md` says version 1.2.0 / build 3; `pyproject.toml` is 1.5.0 / build 6.
- `storage/tests/catalogue_preview.py` and `scripts/preview_ui.py`: purpose unclear.
- No pytest or linter installed; tests run with `python -m unittest discover -s tests`.
- Seen once in the Task 12 web smoke (not reproduced after reload, not investigated against the pre-refactor build): after three quick add-to-cart clicks the cart showed a duplicate row for one article while the totals were right.
- Restoring a backup adds its orders even when same-named orders already exist (by design, stated in the restore dialog), so restoring on the same storage twice duplicates the orders.
- `backup.py` still spells `"commandes.json"`, `"catalogue_perso.json"` and `"sauvegardes/avant-restauration-…zip"` itself (it is a standalone module with no app imports). `config.py` holds the same values (`ORDERS_FILENAME`, `PREFS_FILENAME`, `BACKUPS_DIRNAME`, `RECOVERY_BACKUP_PATTERN`): change both together.
- Leftovers: unused imports in `tests/test_productivity.py` (lines 20, 22, 24); `page.data["ctx"]` keeps the previous context after a relaunch into the import screen (tests only); `test_every_ctx_handler_is_callable_after_install` is a weak pin; the identity tests became existence checks once the re-exports went away.

## Design notes

- `import_screen.py` imports `main` lazily inside `start_app` and `done` (`from .main import main` / `from main import main`) because `main` imports `import_screen`; a top-level import would be a cycle. In script mode (`flet run`, `main.py` runs as `__main__`) the lazy `from main import main` loads a second copy of `main.py`. That is harmless while `main.py` holds no shared mutable module state: keep it that way.
- `context.py` / `AppContext` holds the state `main()` used to share through closures (`orders`, `state`, `prefs`, `cat`, `excel_items`, ...) and the core helpers (`persist`, `show_snack`, ...). Nothing rebinds these: `excel_items` is only mutated in place (`ctx.excel_items[:] = items`), so no alias can go stale.
- Every save inside `main()` and `AppContext` goes through the module (`storage.save_orders(...)`), so tests patch `storage.save_orders` / `storage.save_prefs`, not `app.*`.
- `ft.Clipboard()` is no longer constructed on the first-launch import-screen path. Flet registers services when they are constructed, and nothing uses the clipboard there; it is still created on the normal path.
- Service registration order changed: `Share` is now created (in `view_photos`) before `FilePicker` (in `shell`). No behaviour effect.
- Restore relaunch uses `ctx.main`; `reset_page` stays in `main.py`, so calling `main(page)` twice does not duplicate controls.
- Splitting stopped at module level on purpose: the long `install()` closures were moved whole (see "Long functions").

## Check manually

Not covered by the unit tests or the web smoke:
- Android camera on a real phone (`flet_camera`, fallback to photo import).
- APK install over the existing app (same package id; `[tool.flet] org` / `product` untouched).
- Windows .exe: first launch, then import of a real catalogue.
- Restore of a real backup, on a test copy of the data.
- The transient duplicate cart row seen once in the Task 12 smoke (see Bugs / risks). Not reproduced in Task 14 (add-to-cart x3, quantity by typing, +/-, remove).
- Live window resize between phone and desktop width in the web build: it switched layout on most runs; once right after a restore the page stayed in the old layout for a few seconds in the headless browser. Not reproduced; the old code switched in the same test.

## Follow-ups worth automating

Project rule: builds and checks run on this PC only, no cloud CI.
- Size check in `.githooks/pre-commit`: a short AST script that fails when a `src/*.py` file is over about 450 lines or a function over about 60 lines, with an allowlist for the `install()` closures listed above.
- Undefined-name check: for each `src/*.py`, build a `symtable` of the module, collect names that are assigned or imported at module level plus builtins, then report every global name referenced inside any scope that is not in that set. It catches a `ctx.` forgotten during a move. Known false positive: `__file__` in `storage.assets_dir`.
- Run `python -m unittest discover -s tests` in the pre-commit hook (about 3 s).
- A local `scripts/check.ps1` that runs the three checks above plus a `flet run --web` launch check, so one command verifies a change before a build.
