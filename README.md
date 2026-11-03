# Prise de Commande

A mobile and desktop app for building equipment orders from an Excel price list, written in Python with [Flet](https://flet.dev). One codebase ships as an Android APK and a Windows app.

The interface is in French: it was built for field sales work in France.

## What it does

- **Catalogue from Excel.** Reads a price list (item, new price, used price), groups items into categories and lets you search them in any word order, without worrying about accents.
- **Multiple catalogues.** Use `Catalogue:Category` in the category column (for example, `Tarif matériel:Caméra`) to create named catalogues, then switch catalogues while browsing or managing articles. Unprefixed categories stay in the main catalogue, and orders can combine articles from several catalogues.
- **Catalogue visibility.** Open ☰ › **Gérer les catalogues** to show or hide catalogues while browsing. Choices are saved on the device; articles, individual item settings and existing orders are preserved.
- **Catalogue management.** The **⋮** menu lets you empty the main catalogue, or rename and delete additional catalogues. Emptying and deletion require confirmation and preserve existing orders. Edits are saved locally; a new import uses the names and articles from the imported file again.
- **Orders.** Create named orders, add items and quantities, adjust prices, and see the running total.
- **Photos per order.** Take photos of the equipment to replace with the in-app camera (Android, via `flet-camera`) or import them; label them, share them, or export everything as a ZIP.
- **Email text.** Copy a ready-to-send summary of the order to the clipboard.
- **Manage items.** Hide items, change prices or add your own items without touching the Excel file.
- **Faster browsing.** Star favorite articles, revisit the last 20 distinct articles added, search all visible catalogues, and clear active filters from chips. Cards show quantities already ordered.
- **Order history.** Duplicate orders with independent photos or archive and reactivate them from the order menu.
- **Notes.** Add remarks to an order or individual basket lines; they are included in the accounting text and photo ZIP summary.
- **Complete backups.** Open ☰ › **Sauvegarder / restaurer** to export orders, photos, catalogue and preferences together. Restore validates the archive, preserves existing orders and creates a recovery copy that can also be exported. Catalogue and settings are replaced; colliding order IDs become new copies.

Everything stays on the device: orders, photos and settings are saved in the app's private storage. There is no server and no account.

## Adaptive interface

The Material 3 interface follows the system light/dark theme, with a toolbar theme
switch. Narrow windows use bottom navigation; unfolded and larger windows show
the catalogue or photos beside the live basket. Filters, grids and short landscape
windows adapt to the available space without resetting entered quantities.

For a preview with isolated sample data, run `python scripts/preview_ui.py`.
Add `--capture` to generate the responsive screenshot matrix. Design decisions,
validation and native-device checks are documented in [UI_REDESIGN.md](UI_REDESIGN.md).

## Try it

```powershell
pip install flet==1.0.4 flet-camera==1.0.4 openpyxl
flet run            # desktop window
flet run --web      # in the browser
```

On first launch the app asks for a catalogue file. Pick **Try the sample catalogue** to test with made-up data.

## Catalogue format

The app imports an `.xlsx` or `.csv` file with these headers on row 1: `Catégorie | Article | Prix | Masqué`.
The full spec, templates in `modele/`, and a ready-made prompt to convert an existing price list with an AI assistant are in [FORMAT_CATALOGUE.md](FORMAT_CATALOGUE.md).

To replace the imported catalogues later: ☰ › **Importer un catalogue**. Include all catalogues in one file. Orders are preserved; edited prices and hidden items remain linked to articles whose name and catalogue are unchanged.

## Tests

```powershell
python -m unittest discover -s tests -v
```

The tests use the sample catalogue and isolated temporary storage under `storage/tests/`.
The 95 tests cover catalogue imports and visibility, prices, persistence, migration,
photos, adaptive layouts, favorites/recents, notes, order duplication/archiving,
backup validation and rollback, restore UI flows, web downloads, and the module layout.

## Code layout

`src/main.py` only starts the app. The rest of `src/` is split by job:

- `config.py`, `text.py`: shared constants and text/price helpers.
- `storage.py`, `catalogue.py`, `orders.py`, `photos.py`, `backup.py`: data files, catalogue import, order and photo logic, backups. No UI code.
- `context.py`: `AppContext`, the state the screens share (orders, preferences, catalogue).
- `view_*.py`: one module per screen (catalogue, cart, orders, admin, catalogues, photos, backup), each with an `install(ctx)` function. `shell.py` adds navigation and layout; `import_screen.py` is the first-launch screen; `ui.py` holds the theme and widget helpers.

Dependencies go one way: screens → logic → constants. [REFACTOR_NOTES.md](REFACTOR_NOTES.md) explains the split and lists known risks.

## Build

```powershell
.\scripts\construire.ps1              # APK + Windows
.\scripts\construire.ps1 -Cible apk   # APK only
```

The script expects a private folder layout next to the repo: `..\signature_android\` for the Android key, and `..\releases\` for the outputs.  No catalogue is built in; the script stops if a data file other than the template sits in `src/assets`. Version and build number come from `pyproject.toml`.

A pre-commit hook in `.githooks/` refuses spreadsheets other than the templates, signing keys and password files. Enable it with `git config core.hooksPath .githooks`.

## Stack

Python 3.12+, Flet 1.0, flet-camera, openpyxl.

## License

MIT, © 2026 Maxime Vignals. Contact: contact@maximevignals.fr
