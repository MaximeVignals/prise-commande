"""Preview with fictitious data only: python scripts/preview_ui.py [--capture].

The screenshot matrix uses the installed Flet desktop client and writes under
storage/ui-preview. It never reads the application's existing storage.
"""

import asyncio
import os
from pathlib import Path
import sys
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ["FLET_APP_STORAGE_DATA"] = str(ROOT / "storage" / "ui-preview" / "data")
os.environ["FLET_ASSETS_DIR"] = str(ROOT / "src" / "assets")

import flet as ft
from src import main as app
from src import backup, catalogue, config, import_screen, storage


def walk(value):
    pending, seen = [value], set()
    while pending:
        item = pending.pop()
        if id(item) in seen:
            continue
        seen.add(id(item))
        if isinstance(item, ft.BaseControl):
            yield item
            pending.extend(vars(item).values())
        elif isinstance(item, dict):
            pending.extend(item.values())
        elif isinstance(item, (list, tuple)):
            pending.extend(item)


async def preview(page):
    catalogue.install_catalogue(catalogue.sample_catalogue_path().read_bytes(), ".xlsx")
    entries = catalogue.load_catalogue()
    prefs, _ = storage.load_prefs(entries)
    prefs["favorites"] = {entries[0]["Cle"]}
    prefs["recent"] = [entry["Cle"] for entry in entries[:3]]
    prefs["catalogue_items"] = entries + [{"Cle": "CAT:preview-service", "Nom_Article": "Installation de démonstration",
        "Catalogue": "Prestations démo", "Categorie": "Installation", "Prix_Excel": 90, "Masque": False}]
    storage.save_prefs(prefs)
    items = {entry["Cle"]: {"Nom": entry["Nom_Article"], "Prix": entry["Prix_Excel"], "quantite": i}
             for i, entry in enumerate(entries[:2], 1)}
    next(iter(items.values()))["note"] = "Vérifier HDMI"
    storage.save_orders({"preview": {"name": "Cabinet Horizon · Salle 2", "created": "2026-11-03T12:00",
                                 "notes": "Livraison groupée · Salle 2", "items": items, "photos": []},
                     "archive-preview": {"name": "Ancien projet démo", "created": "2026-10-01T12:00",
                                         "archived": True, "items": {}, "photos": []}}, "preview")
    page.window.width, page.window.height = 412, 900
    page.enable_screenshots = True
    app.main(page)
    if "--capture" not in sys.argv:
        return
    output = ROOT / "storage" / "ui-preview" / "screenshots"
    output.mkdir(parents=True, exist_ok=True)
    # Keep the user's resting mouse position from adding tooltips to captures.
    for theme in (page.theme, page.dark_theme):
        theme.tooltip_theme = ft.TooltipTheme(wait_duration=ft.Duration(seconds=60))
    await asyncio.sleep(1)
    navigation = next(c for c in walk(page.views) if isinstance(c, ft.NavigationBar))
    for name, width, height, tab, dark in [
        ("folded-320", 320, 850, 0, False),
        ("phone-390", 390, 900, 0, False),
        ("phone-basket", 390, 900, 1, False),
        ("inner-900", 900, 950, 0, False),
        ("inner-dark", 900, 950, 0, True),
        ("inner-photos", 900, 950, 2, False),
        ("split-600", 600, 750, 0, False),
        ("landscape", 850, 440, 0, False),
        ("landscape-basket", 850, 440, 1, False),
        ("landscape-photos", 850, 440, 2, False),
        ("desktop", 1440, 960, 0, False),
    ]:
        page.window.width, page.window.height = width, height
        page.theme_mode = ft.ThemeMode.DARK if dark else ft.ThemeMode.LIGHT
        navigation.selected_index = tab
        navigation.on_change(SimpleNamespace(control=navigation))
        page.update()
        await asyncio.sleep(0.8)
        (output / f"{name}.png").write_bytes(await page.take_screenshot(pixel_ratio=1))
        print(f"Captured {name}", flush=True)

    async def capture(name):
        page.update()
        await asyncio.sleep(0.5)
        (output / f"{name}.png").write_bytes(await page.take_screenshot(pixel_ratio=1))
        print(f"Captured {name}", flush=True)

    # Review the management screens and a dialog constrained by a narrow window.
    page.window.width, page.window.height = 390, 900
    await page.push_route("/articles")
    await capture("phone-articles")
    add = next(c for c in walk(page.views[-1]) if isinstance(c, ft.TextButton) and c.content == "Ajouter")
    add.on_click(None)
    await capture("phone-add-article")
    page.pop_dialog()
    await page.push_route("/")
    await page.push_route("/catalogues")
    await capture("phone-catalogues")
    await page.push_route("/")
    mode = next(c for c in walk(page.views) if isinstance(c, ft.SegmentedButton))
    for value, name in [("favorites", "phone-favorites"), ("recent", "phone-recents"), ("all", "phone-all")]:
        mode.selected = [value]
        await mode.on_change()
        await capture(name)
    selector = next(c for c in walk(page.views) if isinstance(c, ft.Dropdown) and c.label == "Catalogue")
    selector.value = config.ALL_CATALOGUES
    await selector.on_select()
    await capture("phone-all-catalogues")
    selector.value = ""
    await selector.on_select()
    navigation.selected_index = 1
    navigation.on_change(SimpleNamespace(control=navigation))
    notes = next(c for c in walk(page.views) if isinstance(c, ft.IconButton) and c.tooltip == "Remarques de la commande")
    notes.on_click(None)
    await capture("phone-order-notes")
    closed = page.pop_dialog()
    page.update()
    await asyncio.sleep(0.4)  # Let the native dialog route finish dismissing before navigating.
    print(f"Notes dialog closed: {closed is not None and not closed.open}", flush=True)
    await page.push_route("/sauvegarde")
    await capture("phone-backup")
    await page.push_route("/")
    await page.show_drawer()
    await capture("phone-orders")
    archives = next(c for c in walk(page.drawer) if isinstance(c, ft.TextButton) and c.content == "Archives (1)")
    archives.on_click(None)
    await capture("phone-archives")
    await page.close_drawer()
    navigation.selected_index = 0
    navigation.on_change(SimpleNamespace(control=navigation))
    filters = next(c for c in walk(page.views) if isinstance(c, ft.IconButton)
                   and c.tooltip == "Afficher ou masquer les filtres")
    filters.on_click(None)
    await capture("phone-filters")
    filters.on_click(None)

    # Simulate a short IME viewport without changing the user's OS settings.
    page.window.width, page.window.height = 390, 480
    navigation.selected_index = 1
    navigation.on_change(SimpleNamespace(control=navigation))
    await capture("keyboard-height-basket")

    # Typography stress test, not a substitute for Android's actual font scaler.
    page.window.width, page.window.height = 390, 900
    navigation.selected_index = 0
    navigation.on_change(SimpleNamespace(control=navigation))
    changed = []
    for control in walk(page.views):
        if isinstance(control, ft.Text):
            changed.append((control, "size", control.size))
            control.size = (control.size or 14) * 1.5
        elif isinstance(control, (ft.TextField, ft.Dropdown)):
            changed.append((control, "text_size", control.text_size))
            control.text_size = (control.text_size or 16) * 1.5
    await capture("phone-large-type")
    page.window.width, page.window.height = 900, 950
    await capture("inner-large-type")
    workspace = page.controls[0].content.content
    assert not workspace.controls[2].visible, "The compact basket bar must hide beside the live basket."
    for control, attribute, value in changed:
        setattr(control, attribute, value)
    page.window.width, page.window.height = 390, 900

    # Native restore smoke test: fake picker + the real confirmation/dismissal
    # flow. All source, destination and recovery data remain in ui-preview.
    await page.push_route("/sauvegarde")
    data = backup.create_backup(storage.storage_dir())
    async def pick_backup(**kwargs):
        return [SimpleNamespace(bytes=data, path=None, name="demo-backup.zip")]
    async def restored():
        await page.push_route("/")
        page.controls.clear()
        app.main(page)
    await import_screen.request_restore(page, SimpleNamespace(pick_files=pick_backup), restored)
    await capture("phone-restore-confirm")
    confirm = next(c for c in walk(page._dialogs) if isinstance(c, ft.Button) and c.content == "Restaurer")
    await confirm.on_click(None)
    await capture("phone-restored")
    # The success snackbar is dismissed before the onboarding capture.
    page.pop_dialog()
    await asyncio.sleep(0.3)

    # First-run screen uses the same design system and remains scrollable.
    page.controls.clear()
    page.appbar = None
    import_screen.show_import_screen(page)
    await capture("phone-onboarding")
    page.controls.clear()
    app.main(page)
    page.window.width, page.window.height = 900, 950
    page.update()
    print(f"Screenshots: {output}", flush=True)


if __name__ == "__main__":
    ft.run(preview, assets_dir=str(ROOT / "src" / "assets"))
