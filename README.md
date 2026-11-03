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

Everything stays on the device: orders, photos and settings are saved in the app's private storage. There is no server and no account.

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
They cover catalogue imports, catalogue switching and visibility, prices, saved orders and preferences, migration, and web photo import/export.

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
