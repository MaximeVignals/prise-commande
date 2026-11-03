# Prise de Commande

A mobile and desktop app for building equipment orders from an Excel price list, written in Python with [Flet](https://flet.dev). One codebase ships as an Android APK and a Windows app.

The interface is in French: it was built for field sales work in France.

## What it does

- **Catalogue from Excel.** Reads a price list (item, new price, used price), groups items into categories and lets you search them in any word order, without worrying about accents.
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

The repo ships with a made-up catalogue (`src/assets/catalogue exemple.xlsx`) and example rules, so the app runs as is.

## Use your own catalogue

**Excel format (first sheet).**

| Column | Content |
|---|---|
| A | Item name. A **bold** row with no price is a category title. |
| B | New price (number, or text such as `1 190,00 €`). A row with a header of `TARIF NEUF` is skipped. |
| C | Used price (optional). |

Non-bold rows without a price (pack details, notes) are ignored.

**Files.** Put your files next to the sample in `src/assets/`:
- `catalogue materiel.xlsx`: used instead of the sample when present.
- `regles_catalogue.json`: optional rules, in the same format as `regles_catalogue.exemple.json`. They cover renamed categories, words kept in capitals, sections to skip and items hidden by default.

Both names are git-ignored.

## Build

```powershell
.\scripts\construire.ps1              # APK + Windows
.\scripts\construire.ps1 -Cible apk   # APK only
```

The script expects a private folder layout next to the repo: `..\prive\` for the catalogue and rules, `..\signature_android\` for the Android key, and `..\releases\` for the outputs. It copies the private files into `src/assets` only for the duration of the build. Version and build number come from `pyproject.toml`.

A pre-commit hook in `.githooks/` refuses spreadsheets other than the sample, signing keys and password files. Enable it with `git config core.hooksPath .githooks`.

## Stack

Python 3.12+, Flet 1.0, flet-camera, openpyxl.

## License

MIT, © 2026 Maxime Vignals. Contact: contact@maximevignals.fr
