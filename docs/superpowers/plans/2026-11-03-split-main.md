# Split `src/main.py` Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn the 3163-line `src/main.py` into a thin entry point plus focused modules, with strictly identical behaviour.

**Architecture:** Pure logic (constants, text, storage, catalogue, orders, photos) moves out first as plain functions. Then the 2300-line `main()` closure is split: its shared state and core helpers become an `AppContext` object, and each screen becomes a `view_*.py` module with `install(ctx)` that defines the same inner functions and attaches the ones other modules need onto `ctx`. Cross-module calls go through `ctx.<name>` (looked up at call time), so definition order stops mattering.

**Tech Stack:** Python 3.12+, Flet 1.0.4, flet-camera 1.0.4, openpyxl, unittest.

**Spec:** the user's refactor brief (pasted in the session of 2026-11-03) + the approved audit/structure in that session. The one deviation from the approved tree: `screens/` becomes flat `view_*.py` files in `src/` (see Global Constraints, "Imports").

## Global Constraints

- Zero functional change. Bugs found → `REFACTOR_NOTES.md`, never fixed.
- No new dependencies. No change to `pyproject.toml`, `scripts/`, `.githooks/`, file names/paths the app reads or writes, JSON formats.
- Do not touch `[tool.flet] org` / `product`. No builds in this plan except the final check, run through the `flet-release` skill **without** bumping the version.
- Never open, print or summarise the real catalogue, prices and orders (private, git-ignored). Test only with the sample catalogue.
- Imports: every new module uses the existing dual pattern so `flet run` (script mode, `src` on `sys.path`) and the tests (`from src import main`, package mode) both work:
  ```python
  if __package__:
      from .text import fold, norm_text
  else:
      from text import fold, norm_text
  ```
  A `screens/` sub-package would break this pattern (`from ..` fails in script mode), hence flat `view_*.py` files.
- Dependencies go one way: `main → shell/view_* → context → catalogue/storage/orders/photos → text/config`. `ui.py` may import `text` only. No cycles.
- Code moves verbatim: same names, same French strings and comments, same bodies. Only allowed body edits: a name owned by another view module becomes `ctx.<name>`; a name owned by `AppContext` becomes `ctx.<name>`.
- Targets: `main.py` < 100 lines; modules ideally < 400 lines; flag any function still > 50 lines in the notes (splitting long functions is **not** in this plan, see Task 13).
- One task = one commit, each with all tests passing. Commit message ends with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`. Before every commit: `git status --short` and stop if any `.xlsx`, `.csv`, `.json` (other than tests/fixtures), `.jks` or password file is staged. Never push.

## Verification used by every task ("the checks")

1. `python -m unittest discover -s tests` → `OK`, 86 tests (more after Task 1).
2. Undefined-name check (catches a `ctx.` forgotten during moves). Keep the script in the session scratchpad, not in the repo:
   ```python
   # check_names.py — usage: python -I check_names.py src/*.py
   import builtins, symtable, sys
   for path in sys.argv[1:]:
       top = symtable.symtable(open(path, encoding="utf-8").read(), path, "exec")
       known = {s.get_name() for s in top.get_symbols() if s.is_assigned() or s.is_imported()} | set(dir(builtins))
       def walk(t):
           for s in t.get_symbols():
               if s.is_referenced() and s.is_global() and s.get_name() not in known:
                   print(f"{path}: {t.get_name()} uses undefined {s.get_name()}")
           for c in t.get_children():
               walk(c)
       walk(top)
   ```
   Expected: no output.
3. `flet run --web` from the worktree root starts without a traceback (stop it after the page loads).
4. Tasks 6–12 only: the smoke checklist below via the Playwright MCP, at 390 px and at desktop width.

### Smoke checklist (sample catalogue, fresh storage dir)
- First launch shows the import screen; "essayer le modèle" loads the sample.
- Create an order, rename it, add 3 articles from 2 categories, change a quantity by typing and by +/−, remove a line, total updates.
- Search, category filter, Favoris/Récents modes, filter tags and "reset filters".
- Copy e-mail text (snack appears); notes on the order.
- Duplicate, archive, reactivate (banner), delete an order; drawer lists groups.
- ☰ › catalogue admin: hide an item, change and reset a price, add and delete an article.
- ☰ › catalogues: rename, hide, remove a catalogue; Importer un catalogue (sample again).
- Photos tab: import a photo, label it, delete it; ZIP export.
- ☰ › sauvegarde: export a backup, restore it.
- Resize from 390 px to 1300 px: single pane ↔ dual pane, quick cart button, theme toggle.

## Review Focus

1. Late-bound handlers: a widget built in one `install()` whose `on_click` points to a function from a later module. Expected: same handler runs. Rule: use `async def _fwd(e=None): await ctx.<name>(e)` (or a sync lambda for sync targets) so Flet still sees an async handler when the original was async. Pinned by Task 6 test `test_every_ctx_handler_is_callable_after_install`.
2. Rebound state: code that reassigns a closure variable (`orders = …`, `prefs = …`, `excel_items = …` after a catalogue replace or restore). Expected: every module sees the new object. Rule: these live only as `ctx.orders` etc. and are never copied into a module-level or local alias. Pinned by existing tests that replace the catalogue and restore a backup (`test_app.py`, `test_productivity.py`), which must keep passing unchanged except for imports.
3. Save failure messages: `persist()` must still show "⚠️ Sauvegarde impossible" when `save_orders` raises. Tests patch `storage.save_orders` (was `app.save_orders`); `context.py` must call `storage.save_orders(...)` through the module, not a `from` import, or the patch silently stops applying and the test would fail.
4. Camera absent: `fc = None` path (`flet run` on PC). Tests patch `view_photos.fc` (was `app.fc`). Same module-attribute rule.
5. Relaunch on the same page: `main()` called again after import/restore must not duplicate controls (`reset_page`). Covered by existing tests calling `app.main(page)` twice; keep `reset_page` in `main.py`.

---

### Task 0: Worktree, baseline, notes skeleton

**Files:**
- Create: `REFACTOR_NOTES.md`
- Move in: this plan file (currently untracked on `ui-testing`)

- [ ] **Step 1:** Use the `superpowers:using-git-worktrees` skill to create the worktree at `..\prise-commande-refactor` on new branch `refactor/split-main`, from `ui-testing` HEAD `3a444a0` (the checked-out branch; `main` is behind it — confirm with the user if `main` was meant).
- [ ] **Step 2:** Move `docs/superpowers/plans/2026-11-03-split-main.md` into the worktree.
- [ ] **Step 3:** Run the checks. Expected: 86 tests OK, `flet run --web` starts.
- [ ] **Step 4:** Create `REFACTOR_NOTES.md` with the "before" table (real line counts: `main.py` 3163, `backup.py` 295, `ui.py` 208, tests 1113) and a "Bugs / risks (not fixed)" section seeded with:
  - git-ignored data files (the real catalogue and its settings) present in `src/` would be packaged, since `flet build` packages `src/`, and `construire.ps1` only checks `src\assets`. Check before the next build.
  - `CLAUDE.md` says 1.2.0 / build 3; `pyproject.toml` is 1.5.0 / build 6.
  - `scripts/preview_ui.py`: purpose unclear. A non-versioned `storage/` folder also exists in the main checkout (not in git); check it.
  - No pytest/linter installed; tests run with `python -m unittest discover -s tests`.
- [ ] **Step 5:** Commit `docs: add refactor plan and notes`.

### Task 1: `config.py` + `text.py`

**Files:**
- Create: `src/config.py` — all module constants from `main.py:32-50` (`CATALOGUE_STEM` … `ALL_CATALOGUES`).
- Create: `src/text.py` — `_is_empty`, `norm_text`, `fold`, `_to_price`, `fmt_eur`, `fmt_input`, `matches_search`, `default_order_name`.
- Modify: `src/main.py` — delete those definitions, import them back (dual pattern) so `app.<name>` still works for the tests.
- Test: `tests/test_modules.py` (new)

**Interfaces:** Produces exactly the names above with unchanged signatures.

- [ ] **Step 1: Write the test** — pins that the old access path and the new module are the same objects:
  ```python
  class ModuleSplitTest(unittest.TestCase):
      def test_text_helpers_moved(self):
          from src import main as app, text
          for name in ["fold", "norm_text", "_to_price", "fmt_eur", "fmt_input", "matches_search", "default_order_name"]:
              self.assertIs(getattr(app, name), getattr(text, name))
          self.assertEqual(text.fold("Écran"), "ecran")
  ```
- [ ] **Step 2:** Run it: FAIL, `ImportError: cannot import name 'text'`.
- [ ] **Step 3:** Move the code.
- [ ] **Step 4:** Run the checks: all pass.
- [ ] **Step 5:** Commit `refactor: move constants and text helpers out of main`.

### Task 2: `storage.py`

**Files:**
- Create: `src/storage.py` — `assets_dir`, `storage_dir`, `orders_path`, `prefs_path`, `photos_dir`, `photo_path`, `_set_aside`, `read_json`, `write_json`, `_valid_iso`, `load_orders`, `save_orders`, `migrate_cart_keys`, `load_prefs`, `save_prefs`. Imports `config`, `text` only.
- Modify: `src/main.py` (delete + re-import), `tests/test_modules.py`.

`assets_dir` uses `Path(__file__).parent / "assets"`: still correct because `storage.py` sits in `src/` next to `main.py`.

- [ ] **Step 1:** Add `test_storage_moved`: `assertIs(app.load_orders, storage.load_orders)` for every moved name, and `assertEqual(storage.assets_dir(), Path(app.__file__).parent / "assets")` with `FLET_ASSETS_DIR` unset.
- [ ] **Step 2:** Run: FAIL (no `storage`).
- [ ] **Step 3:** Move the code.
- [ ] **Step 4:** Run the checks.
- [ ] **Step 5:** Commit `refactor: move storage and preferences I/O out of main`.

### Task 3: `catalogue.py`

**Files:**
- Create: `src/catalogue.py` — `CatalogueError`, `catalogue_path`, `sample_catalogue_path`, `split_catalogue_category`, `_read_rows`, `parse_catalogue`, `load_catalogue`, `install_catalogue`, `build_catalogue`, `categories_of`, `catalogues_of`. Imports `config`, `text`, `storage`, `openpyxl`.
- Modify: `src/main.py`, `tests/test_modules.py`.

- [ ] **Step 1:** `test_catalogue_moved`: identity checks, plus `catalogue.parse_catalogue` on `storage.assets_dir() / config.SAMPLE_CATALOGUE_FILENAME` read as bytes returns the same result as `app.parse_catalogue` did before (compare to a value computed in the test from the same call through `app`).
- [ ] **Step 2:** Run: FAIL.
- [ ] **Step 3:** Move the code.
- [ ] **Step 4:** Run the checks.
- [ ] **Step 5:** Commit `refactor: move catalogue parsing and loading out of main`.

### Task 4: `orders.py` + `photos.py` + `get_category_icon`

**Files:**
- Create: `src/orders.py` — `order_total`, `order_count`, `order_email_text`, `duplicate_order`. Imports `text`, `storage`.
- Create: `src/photos.py` — `safe_filename`, `photo_export_names`, `photos_summary`, `build_photos_zip`. Imports `text`, `storage`.
- Modify: `src/ui.py` — add `get_category_icon` (imports `fold` from `text`, dual pattern).
- Modify: `src/main.py`, `tests/test_modules.py`.

- [ ] **Step 1:** `test_orders_and_photos_moved`: identity checks for all moved names, `app.get_category_icon is ui.get_category_icon`.
- [ ] **Step 2:** Run: FAIL.
- [ ] **Step 3:** Move the code.
- [ ] **Step 4:** Run the checks. `main.py` should now be ≈ 2600 lines, with only `pick_catalogue_file` … `reset_page` and `main()` above the `main()` body.
- [ ] **Step 5:** Commit `refactor: move order and photo helpers out of main`.

### Task 5: `import_screen.py`

**Files:**
- Create: `src/import_screen.py` — `pick_catalogue_file`, `skipped_summary`, `request_restore`, `show_import_screen` (`main.py:648-830`). It calls `main()` again after a successful import/restore: import it lazily inside the function body (`from main import main` / `from .main import main`, dual pattern) to avoid a cycle; note this in `REFACTOR_NOTES.md`.
- Modify: `src/main.py`, `tests/test_modules.py`, and any test that patches `app.pick_catalogue_file` → `import_screen.pick_catalogue_file`.

- [ ] **Step 1:** `test_import_screen_moved`: `app.show_import_screen is import_screen.show_import_screen`.
- [ ] **Step 2:** Run: FAIL.
- [ ] **Step 3:** Move the code.
- [ ] **Step 4:** Run the checks + smoke items "first launch" and "Importer un catalogue".
- [ ] **Step 5:** Commit `refactor: move the import screen out of main`.

### Task 6: `context.py` — `AppContext`

**Files:**
- Create: `src/context.py`
- Modify: `src/main.py` — `main()` builds `ctx = AppContext(page, excel_items)` right after the `if not excel_items` early return, and the inner code reads/writes `ctx.<name>` for everything listed below (local aliases removed).
- Modify: `tests/test_productivity.py:174,180` → `patch.object(storage, "save_orders", …)`; `tests/test_app.py:531`, `tests/test_productivity.py:70` → `patch.object(storage, "save_prefs", …)`.

**Interfaces — Produces:**
```python
class AppContext:
    def __init__(self, page: ft.Page, excel_items: list[dict]) -> None
    # attributes (from main.py:847-889, same initial values and order of side effects):
    page, excel_items, clipboard, startup_warnings, orders, state, migrated,
    quantity_drafts, catalogue_grids, catalogue_rows, catalogue_badges,
    favorite_buttons, window, prefs, cat
    # methods (bodies from main.py:855-961, verbatim except self.):
    show_snack(message), refresh(), rebuild_catalogue(), entry_by_key(key),
    visible_entries(), new_order(name=None) -> str, current_order() -> dict,
    cart() -> dict, persist(), persist_prefs(), dialog_width() -> int,
    update_catalogue_selector(dropdown, include_hidden=False),
    entries_in(catalogue) -> list, managed_catalogues() -> list
```
`persist`/`persist_prefs` call `storage.save_orders` / `storage.save_prefs` through the module (Review Focus 3). Every view module adds its shared widgets and functions as plain attributes on the same object (`ctx.render_catalogue = render_catalogue`).

- [ ] **Step 1:** Write `test_context_persist_reports_failure`: build `AppContext(TestPage(), sample_items)`, patch `storage.save_orders` to raise `OSError("x")`, call `ctx.persist()`, assert the page's last dialog is a `SnackBar` whose text starts with "⚠️ Sauvegarde impossible". Also write `test_every_ctx_handler_is_callable_after_install` (placeholder list, filled in Task 12): after `app.main(page)`, every name in `EXPECTED_CTX_FUNCTIONS` is a callable attribute of the context. Reach the context through `page.data["ctx"]`: `main()` sets `page.data = {"ctx": ctx}` **only if `page.data` is unused today** — check with grep first. If it is used, keep a module-level `_last_ctx` in `main.py` for tests and note it.
- [ ] **Step 2:** Run: FAIL.
- [ ] **Step 3:** Implement `AppContext`; rewrite references inside `main()`.
- [ ] **Step 4:** Run the checks + full smoke checklist.
- [ ] **Step 5:** Commit `refactor: gather main() shared state into AppContext`.

### Tasks 7–11: one view module per task

Same five steps each: (1) add the moved function names to `EXPECTED_CTX_FUNCTIONS`; (2) run, FAIL; (3) move the code into `def install(ctx: AppContext) -> None`, calling it from `main()` at the point where that code used to run, and prefix cross-module names with `ctx.`; (4) run the checks + smoke items for that screen; (5) commit `refactor: move <screen> out of main()`.

| Task | File | Moves (from `main()`) | Attaches to `ctx` (used elsewhere) |
|---|---|---|---|
| 7 | `src/view_cart.py` | `change_qty_field`, `update_cart_qty`, `remove_cart_line`, `set_cart_qty`, `clear_cart`, `copy_email_text`, `render_cart`, `update_cart_summary`, cart widgets (`cart_listview`, `total_text`, `cart_info`, basket heading/footer, `content_panier`) | `render_cart`, `update_cart_summary`, `content_panier`, `basket_footer`, `basket_heading`, `cart_listview` |
| 8 | `src/view_catalogue.py` | catalogue widgets and filters (`main.py:963-1011`, filter rows ~2900-2985), `add_to_cart`, `render_catalogue`, `reset_filters`, `toggle_favorite`, `update_catalogue_badges`, `render_filter_tags`, `toggle_filters` | `render_catalogue`, `update_catalogue_badges`, `content_catalogue`, `catalogue_heading`, filter widgets used by `apply_filter_layout` |
| 9 | `src/view_orders.py` | drawer, `open_drawer`, `close_drawer`, `select_order`, `ask_name`, order dialogs, `archive_order`, `show_order_group`, `edit_notes`, `order_handlers`, `render_orders`, `appbar_title`, `order_info` | `render_orders`, `create_order_dialog`, `archive_order`, `open_drawer`, `drawer`, `appbar_title`, `order_info` |
| 10 | `src/view_admin.py` + `src/view_catalogues.py` (two commits) | admin: `main.py:1833-2230`; catalogues: `2232-2445` | `open_admin` targets, `apply_admin_density`, `admin_catalogue`, `admin_category`, `render_catalogues`, `replace_catalogue` |
| 11 | `src/view_photos.py` + `src/view_backup.py` (two commits) | photos + camera `2451-2776` (with `fc` try-import moved here; tests patch `view_photos.fc`); backup `2787-2860` | `render_photos`, `content_photos`, `photo_heading`, `open_backup_view` |

Install order in `main()`: cart, catalogue, orders, admin, catalogues, photos, backup, shell — so widgets exist before the shell lays them out.

### Task 12: `shell.py` and thin `main.py`

**Files:**
- Create: `src/shell.py` — `def install(ctx)` with `go_to_tab`, `render_all`, routes (`route_change`, `view_pop`, `open_admin`, `open_catalogue_manager`), navigation, panes, `apply_filter_layout`, `apply_catalogue_columns`, `layout_workspace`, resize/media handlers, `toggle_theme`, app bar, empty state, `page.add(...)`, first render and the startup saves (`main.py:2862-3163`).
- Modify: `src/main.py` → imports, `reset_page`, `main()` (≈ 20 lines: reset, title, `ui.configure_page`, load catalogue or `show_import_screen`, `AppContext`, the 8 `install` calls) and the existing `__main__`/`ft.run` line. Remove the Task 1–4 re-exports.
- Modify: tests → import from the real modules (`from src import storage, catalogue, …`) instead of `app.<name>`; `app.main` stays.

- [ ] **Step 1:** Fill `EXPECTED_CTX_FUNCTIONS` with the shell names; add `test_main_is_thin`: `len(Path(app.__file__).read_text(encoding="utf-8").splitlines()) < 100`.
- [ ] **Step 2:** Run: FAIL.
- [ ] **Step 3:** Move the code, update test imports, delete re-exports.
- [ ] **Step 4:** Run the checks + full smoke checklist at 390 px and 1300 px.
- [ ] **Step 5:** Commit `refactor: move layout and navigation to shell, slim main.py`.

### Task 13: Evidence-based cleanup

- [ ] **Step 1:** List functions > 50 lines and modules > 400 lines (re-run the AST size script). For each, either split it into named helpers in the same module (verbatim code, no logic change) or record in `REFACTOR_NOTES.md` why cohesion argues against it. One commit per function split, checks after each.
- [ ] **Step 2:** Dead code: names defined but referenced nowhere (grep each `def` name across `src/` and `tests/`). Remove only those with zero references; one commit.
- [ ] **Step 3:** Duplicated literals across modules (e.g. `storage_dir() / "sauvegardes"`, `"avant-restauration-*.zip"`): move to `config.py` only if the value is identical in every place; one commit.

### Task 14: Verify and hand over

- [ ] **Step 1:** Full checks + full smoke checklist.
- [ ] **Step 2:** Build check via the `flet-release` skill, Windows build only, **no version bump, no release copy** — confirm with the user before running it (it takes several minutes). Expected: build succeeds and the .exe opens on the import screen.
- [ ] **Step 3:** Complete `REFACTOR_NOTES.md`: before/after line table, architecture tree with one line per module, bugs/risks, manual checks for the user (Android camera on a real phone, APK install over the existing app), follow-ups to automate (max file/function length check in `.githooks/pre-commit` using the AST size script, the undefined-name check, running unittest in the hook).
- [ ] **Step 4:** `superpowers:requesting-code-review` on the whole branch diff; fix only refactor mistakes it finds, log anything else.
- [ ] **Step 5:** Commit `docs: complete refactor notes`. Do not merge or push; report the branch to the user.
