# Releases

## 1.5.1 — 2026-11-04 (build 7)

- Split the 3,163-line `src/main.py` into focused modules: logic (`storage`, `catalogue`, `orders`, `photos`), shared state (`context`) and one module per screen (`view_*`, `shell`). `main.py` is now 68 lines.
- No change in behaviour: same screens, file formats and storage paths. Details, known risks and manual checks are in `REFACTOR_NOTES.md`.
- Tests now import from the new modules; `scripts/preview_ui.py` uses the new import paths.

Validation: 95 automated tests pass; the full manual checklist was run in the browser at 390 px and 1300 px and compared with the previous build.

## 1.3.0 — 2026-11-03 (build 4)

- Import multiple catalogues from category names such as `Tarif matériel:Caméra`.
- Switch catalogues while browsing and managing articles; combine them in one order.
- Show or hide catalogues with saved visibility preferences.
- Empty the main catalogue, or rename and delete additional catalogues, while preserving existing orders.
- Keep article prices and visibility settings when renaming a catalogue.
- Improve catalogue and price validation, and browser photo import, preview and ZIP export.
- Document the import format and catalogue management behavior.

Validation: 50 automated tests pass; catalogue selectors, management controls and the rename dialog checked at 390 px width.

- 2026-11-03 — 1.5.0 (build 6), APK only, branch ui-testing: modernized adaptive UI and order productivity tools.

- 2026-11-04 — 1.6.0 (build 8), APK only, branch ui-testing: catalogue header slides away while scrolling; back-to-top button.
