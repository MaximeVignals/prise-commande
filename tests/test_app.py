import asyncio
import io
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch
import zipfile

import flet as ft
from openpyxl import Workbook

from src import main as app


class StorageTest(unittest.TestCase):
    def setUp(self):
        # Toutes les données de test restent isolées des commandes réelles.
        root = Path(__file__).resolve().parents[1] / "storage" / "tests"
        root.mkdir(parents=True, exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=root)
        self.addCleanup(self.temp.cleanup)
        self.storage = Path(self.temp.name)
        self.env = patch.dict(os.environ, {"FLET_APP_STORAGE_DATA": str(self.storage)})
        self.env.start()
        self.addCleanup(self.env.stop)


class CatalogueTests(StorageTest):
    def test_sample_xlsx_and_csv(self):
        for path in [app.sample_catalogue_path(), Path("modele/catalogue_modele.csv")]:
            with self.subTest(path=path):
                items, skipped = app.parse_catalogue(path.read_bytes(), path.suffix)
                self.assertTrue(items)
                self.assertEqual(skipped, [])

    def test_prices(self):
        for raw, price in [("4 990,00 €", 4990), ("4990.5", 4990.5),
                           ("1.234,56", 1234.56), ("1.234", 1234), (0, 0)]:
            with self.subTest(raw=raw):
                self.assertEqual(app._to_price(raw), price)

    def test_reject_nonfinite_prices(self):
        for raw in ["NaN", "inf", "-inf", "1e309", float("nan"), float("inf"), 10**400, True]:
            with self.subTest(raw=raw):
                self.assertIsNone(app._to_price(raw))

    def test_csv_encodings_and_delimiters(self):
        for delimiter in [";", ",", "\t"]:
            for encoding in ["utf-8-sig", "cp1252"]:
                with self.subTest(delimiter=delimiter, encoding=encoding):
                    data = delimiter.join(["Catégorie", "Article", "Prix", "Masqué"]) + "\n"
                    data += delimiter.join(["Écrans", "Écran", "149", "oui"])
                    items, skipped = app.parse_catalogue(data.encode(encoding), ".CSV")
                    self.assertEqual(items[0]["Nom_Article"], "Écran")
                    self.assertTrue(items[0]["Masque"])
                    self.assertEqual(skipped, [])

    def test_invalid_encoding_has_user_facing_error(self):
        with self.assertRaises(app.CatalogueError):
            app.parse_catalogue(b"Categorie;Article;Prix\nTest;Article;\x81", ".csv")

    def test_csv_with_leading_blank_line(self):
        items, _ = app.parse_catalogue(b"\nCategorie,Article,Prix\nTest,Exemple,10", ".csv")
        self.assertEqual(items[0]["Prix_Excel"], 10)

    def test_invalid_rows_are_skipped(self):
        data = "Categorie;Article;Prix\nTest;Valide;10\nTest;Infini;inf\nTest;Negatif;-10\n;Sans categorie;2\nTest;;3\n"
        items, skipped = app.parse_catalogue(data.encode(), ".csv")
        self.assertEqual([item["Nom_Article"] for item in items], ["Valide"])
        self.assertEqual(len(skipped), 4)

    def test_invalid_workbook_and_headers(self):
        for data, ext in [(b"invalid", ".xlsx"), (b"A;B;C\n1;2;3", ".csv"), (b"", ".csv")]:
            with self.subTest(ext=ext, data=data), self.assertRaises(app.CatalogueError):
                app.parse_catalogue(data, ext)

    def test_workbook_columns_and_duplicate_names(self):
        wb = Workbook()
        wb.active.append(["Article", "Prix", "Catégorie"])
        for _ in range(2):
            wb.active.append(["Écran", 10, "Test"])
        buffer = io.BytesIO()
        wb.save(buffer)
        wb.close()
        items, _ = app.parse_catalogue(buffer.getvalue(), ".xlsx")
        self.assertEqual(len({item["Cle"] for item in items}), 2)

    def test_named_catalogues_in_csv_and_xlsx(self):
        rows = [["Catégorie", "Article", "Prix"],
                ["Tarif matériel:Caméra", "Caméra démo", 10],
                [" Tarif matériel : Accessoires ", "Câble", 2],
                ["Services:Installation:Sur site", "Pose", 30],
                ["Divers", "Autre", 5]]
        wb = Workbook()
        for row in rows:
            wb.active.append(row)
        buffer = io.BytesIO()
        wb.save(buffer)
        wb.close()
        csv = "\n".join(";".join(map(str, row)) for row in rows).encode()
        for data, ext in [(csv, ".csv"), (buffer.getvalue(), ".xlsx")]:
            with self.subTest(ext=ext):
                items, skipped = app.parse_catalogue(data, ext)
                self.assertEqual(skipped, [])
                self.assertEqual([(it["Catalogue"], it["Categorie"]) for it in items], [
                    ("Tarif matériel", "Caméra"), ("Tarif matériel", "Accessoires"),
                    ("Services", "Installation:Sur site"), ("", "Divers")])
                prefs, _ = app.load_prefs(items)
                self.assertEqual(app.catalogues_of(app.build_catalogue(items, prefs)),
                                 ["Tarif matériel", "Services", ""])

    def test_empty_catalogue_or_category_is_skipped(self):
        items, skipped = app.parse_catalogue(
            b"Categorie;Article;Prix\n:Camera;A;1\nTarif:;B;2\n : ;C;3\nDivers;D;4", ".csv")
        self.assertEqual([it["Nom_Article"] for it in items], ["D"])
        self.assertEqual(len(skipped), 3)

    def test_same_names_in_different_catalogues_keep_stable_keys(self):
        rows = ["Divers;Caméra;5", "Tarif matériel:Caméra;Caméra;10", "Services:Caméra;Caméra;20"]
        def parse(rows):
            return app.parse_catalogue(("Categorie;Article;Prix\n" + "\n".join(rows)).encode(), ".csv")[0]
        items = parse(rows)
        keys = {it["Catalogue"]: it["Cle"] for it in items}
        self.assertEqual(len(set(keys.values())), 3)
        self.assertEqual(keys[""], "XL:Caméra")
        self.assertEqual({it["Catalogue"]: it["Cle"] for it in parse(list(reversed(rows)))}, keys)
        prefs, _ = app.load_prefs(items)
        prefs["prices"][keys["Tarif matériel"]] = 15
        prefs["hidden"].add(keys["Services"])
        app.save_prefs(prefs)
        loaded, _ = app.load_prefs(items)
        entries = app.build_catalogue(parse(list(reversed(rows))), loaded)
        by_catalogue = {it["Catalogue"]: it for it in entries}
        self.assertEqual(by_catalogue["Tarif matériel"]["Prix_Unitaire"], 15)
        self.assertEqual(by_catalogue[""]["Prix_Unitaire"], 5)
        self.assertFalse(by_catalogue["Services"]["Visible"])
        self.assertTrue(by_catalogue["Tarif matériel"]["Visible"])

    def test_failed_import_preserves_catalogue(self):
        data = b"Categorie;Article;Prix\nTest;Exemple;10"
        app.install_catalogue(data, ".csv")
        with self.assertRaises(app.CatalogueError):
            app.install_catalogue(b"invalid", ".xlsx")
        self.assertEqual(app.catalogue_path().read_bytes(), data)

    def test_switch_catalogue_format(self):
        app.install_catalogue(app.sample_catalogue_path().read_bytes(), ".xlsx")
        app.install_catalogue(b"Categorie;Article;Prix\nTest;Exemple;10", ".csv")
        self.assertEqual(app.catalogue_path().suffix, ".csv")
        self.assertFalse((self.storage / "catalogue_importe.xlsx").exists())

    def test_search_without_accents_in_any_order(self):
        self.assertTrue(app.matches_search("Écran 24 DELL", "dell ecran 24"))
        self.assertFalse(app.matches_search("Écran 24 DELL", "dell 27"))


class PersistenceTests(StorageTest):
    def test_local_catalogue_snapshot_roundtrip_and_empty_snapshot(self):
        items, _ = app.parse_catalogue(b"Categorie;Article;Prix\nTarif:Camera;Demo;10", ".csv")
        prefs, _ = app.load_prefs(items)
        for snapshot in [items, []]:
            with self.subTest(snapshot=snapshot):
                prefs["catalogue_items"] = snapshot
                app.save_prefs(prefs)
                loaded, _ = app.load_prefs(items)
                self.assertEqual(loaded["catalogue_items"], snapshot)
                self.assertEqual(len(app.build_catalogue(items, loaded)), len(snapshot))

    def test_malformed_local_snapshot_falls_back_to_imported_items(self):
        items, _ = app.parse_catalogue(b"Categorie;Article;Prix\nTarif:Camera;Demo;10", ".csv")
        for snapshot in [[{}], [None], [items[0], items[0]], [{**items[0], "Prix_Excel": "NaN"}]]:
            with self.subTest(snapshot=snapshot):
                app.write_json(app.prefs_path(), {"catalogue_items": snapshot})
                prefs, _ = app.load_prefs(items)
                self.assertNotIn("catalogue_items", prefs)
                self.assertEqual(len(app.build_catalogue(items, prefs)), 1)

    def test_catalogue_visibility_preferences_roundtrip(self):
        prefs, _ = app.load_prefs([])
        self.assertEqual(prefs["hidden_catalogues"], set())
        prefs["hidden_catalogues"] = {"", "Tarif matériel"}
        prefs["hidden"] = {"XL:Démo"}
        app.save_prefs(prefs)
        loaded, warning = app.load_prefs([])
        self.assertIsNone(warning)
        self.assertEqual(loaded, prefs)

    def test_old_and_malformed_catalogue_visibility_preferences(self):
        for value, expected in [(None, set()), ("Services", set()),
                                (["", "Services", 1, None, {}], {"", "Services"})]:
            with self.subTest(value=value):
                data = {} if value is None else {"hidden_catalogues": value}
                app.write_json(app.prefs_path(), data)
                prefs, _ = app.load_prefs([])
                self.assertEqual(prefs["hidden_catalogues"], expected)

    def test_named_catalogue_cart_keys_are_not_migrated(self):
        key = app.parse_catalogue(b"Categorie;Article;Prix\nTarif:Camera;Demo;10", ".csv")[0][0]["Cle"]
        line = {"Nom": "Demo", "Prix": 10, "quantite": 2}
        orders = {"demo": {"items": {key: line, "ART_1": {**line, "Nom": "Ancien"}}}}
        self.assertTrue(app.migrate_cart_keys(orders))
        self.assertEqual(orders["demo"]["items"][key], line)
        self.assertFalse(app.migrate_cart_keys(orders))

    def test_custom_article_catalogue_survives_reload(self):
        custom = {"key": "PERSO:demo", "name": "Démo", "category": "Caméra", "price": 10,
                  "catalogue": "Tarif matériel"}
        prefs = {"hidden": set(), "prices": {}, "custom": [custom]}
        app.save_prefs(prefs)
        loaded, _ = app.load_prefs([])
        self.assertEqual(loaded["custom"], [custom])
        self.assertEqual(app.build_catalogue([], loaded)[0]["Catalogue"], "Tarif matériel")

    def test_orders_roundtrip(self):
        orders = {"demo": {"name": "Démo", "created": "2026-11-03T12:00",
                           "items": {"XL:Exemple": {"Nom": "Exemple", "Prix": 1.5, "quantite": 2}},
                           "photos": []}}
        app.save_orders(orders, "demo")
        loaded, current, warning = app.load_orders()
        self.assertEqual(loaded, orders)
        self.assertEqual(current, "demo")
        self.assertIsNone(warning)
        self.assertEqual(app.order_total(loaded["demo"]), 3)

    def test_corrupt_json_is_preserved(self):
        app.orders_path().write_text("{invalid", encoding="utf-8")
        orders, current, warning = app.load_orders()
        self.assertEqual(orders, {})
        self.assertIsNone(current)
        self.assertTrue(warning)
        self.assertEqual(next(self.storage.glob("commandes.illisible-*.json")).read_text(), "{invalid")

    def test_malformed_order_lines_do_not_prevent_loading_valid_lines(self):
        valid = {"Nom": "Exemple", "Prix": 10, "quantite": 2}
        items = {"valid": valid, "bad": [], "infinite_qty": {**valid, "quantite": float("inf")},
                 "nan_price": {**valid, "Prix": "NaN"}, "negative": {**valid, "Prix": -1}}
        app.write_json(app.orders_path(), {"orders": {"demo": {"items": items}}})
        orders, _, _ = app.load_orders()
        self.assertEqual(orders["demo"]["items"], {"valid": valid})

    def test_malformed_custom_articles_do_not_prevent_loading(self):
        valid = {"key": "PERSO:demo", "name": "Exemple", "category": "Test", "price": 10}
        app.write_json(app.prefs_path(), {"custom": [[], valid, {**valid, "price": "NaN"},
                                                    {**valid, "price": 10**400}]})
        prefs, _ = app.load_prefs([])
        self.assertEqual(prefs["custom"], [valid])

    def test_invalid_price_overrides_are_ignored(self):
        app.write_json(app.prefs_path(), {"prices": {"good": 10, "nan": "NaN", "negative": -1}})
        prefs, _ = app.load_prefs([])
        self.assertEqual(prefs["prices"], {"good": 10})

    def test_defaults_and_personalisation_survive_reload(self):
        items, _ = app.parse_catalogue(b"Categorie;Article;Prix;Masque\nTest;Exemple;10;oui", ".csv")
        prefs, _ = app.load_prefs(items)
        self.assertEqual(prefs["hidden"], {"XL:Exemple"})
        prefs["prices"]["XL:Exemple"] = 20
        app.save_prefs(prefs)
        loaded, _ = app.load_prefs(items)
        catalogue = app.build_catalogue(items, loaded)
        self.assertEqual(catalogue[0]["Prix_Unitaire"], 20)
        self.assertFalse(catalogue[0]["Visible"])

    def test_migration_keeps_quantities_and_different_prices(self):
        orders = {"demo": {"items": {
            "ART_1": {"Nom": "Exemple", "Prix": 10, "quantite": 2},
            "ART_2": {"Nom": "Exemple", "Prix": 10, "quantite": 3},
            "ART_3": {"Nom": "Exemple", "Prix": 20, "quantite": 1}}}}
        self.assertTrue(app.migrate_cart_keys(orders))
        self.assertEqual(app.order_count(orders["demo"]), 6)
        self.assertEqual(app.order_total(orders["demo"]), 70)
        self.assertFalse(app.migrate_cart_keys(orders))

    def test_photo_zip_contents(self):
        folder = app.photos_dir("demo")
        folder.mkdir(parents=True)
        (folder / "test.jpg").write_bytes(b"fake image")
        order = {"name": "Démo", "items": {}, "photos": [
            {"file": "test.jpg", "label": "Écran / ancien", "added": "2026-11-03T12:00"}]}
        with zipfile.ZipFile(io.BytesIO(app.build_photos_zip("demo", order))) as archive:
            self.assertEqual(archive.read("01 - Écran ancien.jpg"), b"fake image")
            self.assertIn("Écran / ancien", archive.read("photos.txt").decode())


class FilePickerTests(unittest.IsolatedAsyncioTestCase):
    async def test_catalogue_from_bytes_without_local_path(self):
        picker = SimpleNamespace(pick_files=AsyncMock(return_value=[
            SimpleNamespace(bytes=b"example", path=None, name="catalogue.CSV")]))
        self.assertEqual(await app.pick_catalogue_file(picker), (b"example", ".csv"))

    async def test_cancelled_catalogue_picker(self):
        self.assertIsNone(await app.pick_catalogue_file(SimpleNamespace(pick_files=AsyncMock(return_value=[]))))


class TestPage:
    def __init__(self, web=True, platform=ft.PagePlatform.WINDOWS, width=390, height=800):
        self.web = web
        self.platform = platform
        self.width, self.height = width, height
        self.controls = []
        self.overlay = []
        self.dialogs = []
        self.appbar = self.drawer = None
        self.views = [ft.View(route="/")]
        self.route = "/"

    def add(self, control):
        self.controls.append(control)

    def update(self):
        pass

    def show_dialog(self, dialog):
        self.dialogs.append(dialog)

    def pop_dialog(self):
        dialog = self.dialogs.pop()
        if dialog.on_dismiss:
            result = dialog.on_dismiss(SimpleNamespace(control=dialog))
            if asyncio.iscoroutine(result):
                try:
                    loop = asyncio.get_running_loop()
                except RuntimeError:
                    asyncio.run(result)
                else:
                    loop.create_task(result)
        return dialog

    async def close_drawer(self):
        pass

    async def push_route(self, route):
        self.route = route
        await self.on_route_change()

    def select_tab(self, index):
        navigation = self.find(ft.NavigationBar)
        navigation.selected_index = index
        navigation.on_change(SimpleNamespace(control=navigation))

    def find(self, control_type, **attributes):
        pending = [self.controls, self.dialogs, self.appbar, self.drawer, self.views]
        seen = set()
        while pending:
            value = pending.pop()
            if id(value) in seen:
                continue
            seen.add(id(value))
            if isinstance(value, control_type) and all(
                getattr(value, key, None) == expected for key, expected in attributes.items()
            ):
                return value
            if isinstance(value, ft.BaseControl):
                pending.extend(vars(value).values())
            elif isinstance(value, dict):
                pending.extend(value.values())
            elif isinstance(value, (list, tuple)):
                pending.extend(value)
        raise AssertionError(f"Contrôle introuvable : {control_type.__name__} {attributes}")


class CatalogueBrowsingTests(StorageTest):
    def setUp(self):
        super().setUp()
        self.data = ("Categorie;Article;Prix;Masque\nDivers;Commun;5;\n"
                     "Tarif matériel:Caméra;Commun;10;\nTarif matériel:Accessoires;Câble;2;\n"
                     "Services:Maintenance;Intervention;30;\nServices:Caméra;Commun;20;\n"
                     "Réserve:Archive;Ancien;1;oui").encode()
        app.install_catalogue(self.data, ".csv")
        app.save_orders({"demo": {"name": "Démo", "items": {}, "photos": []}}, "demo")
        self.page = TestPage()
        app.main(self.page)
        self.scroll = patch.object(ft.ListView, "scroll_to", new_callable=AsyncMock)
        self.scroll.start()
        self.addCleanup(self.scroll.stop)

    def select_catalogue(self, name):
        dropdown = self.page.find(ft.Dropdown, label="Catalogue")
        dropdown.value = name
        asyncio.run(dropdown.on_select())
        return dropdown

    def open_catalogue_manager(self):
        tile = self.page.find(ft.ListTile, title=self.page.find(ft.Text, value="Gérer les catalogues"))
        asyncio.run(tile.on_click())
        self.assertEqual(self.page.views[-1].route, "/catalogues")

    def set_catalogue_visible(self, name, visible):
        label = name or app.DEFAULT_CATALOGUE_LABEL
        switch = self.page.find(ft.Switch, tooltip=f"Afficher « {label} »")
        switch.value = visible
        switch.on_change(SimpleNamespace(control=switch))

    def catalogue_action(self, name, action):
        menu = self.page.find(ft.PopupMenuButton, tooltip=f"Options « {name or app.DEFAULT_CATALOGUE_LABEL} »")
        item = next(item for item in menu.items if item.content == action)
        item.on_click(None)

    def test_restarting_main_on_same_page_does_not_duplicate_screen(self):
        self.page.views.append(ft.View(route="/catalogues"))
        app.main(self.page)
        self.assertEqual(len(self.page.controls), 1)
        self.assertEqual(len(self.page.views), 1)
        dropdown = self.select_catalogue("Services")
        keys = [option.key for option in dropdown.options]
        self.assertEqual(len(keys), len(set(keys)))
        self.assertEqual(dropdown.value, "Services")

    def test_rename_catalogue_preserves_keys_settings_custom_articles_and_orders(self):
        items = app.load_catalogue()
        prefs, _ = app.load_prefs(items)
        named = [item for item in items if item["Catalogue"] == "Tarif matériel"]
        key = named[0]["Cle"]
        prefs["prices"][key] = 123
        prefs["hidden"].add(named[1]["Cle"])
        prefs["custom"].append({"key": "PERSO:manual", "name": "Manuel", "category": "Caméra",
                                "price": 7, "catalogue": "Tarif matériel"})
        app.save_prefs(prefs)
        self.page = TestPage()
        app.main(self.page)
        self.select_catalogue("Tarif matériel")
        search = self.page.find(ft.TextField, label="Rechercher")
        search.value = "Commun"
        asyncio.run(search.on_change())
        self.page.find(ft.IconButton, icon=ft.Icons.ADD_SHOPPING_CART).on_click(None)
        orders_before = app.load_orders()[0]
        self.open_catalogue_manager()
        self.catalogue_action("Tarif matériel", "Renommer")
        self.page.find(ft.TextField, label="Nom du catalogue").value = "Tarif équipement"
        self.page.find(ft.Button, content="Renommer").on_click(None)
        loaded, _ = app.load_prefs(items)
        entries = app.build_catalogue(items, loaded)
        renamed = [item for item in entries if item["Catalogue"] == "Tarif équipement"]
        self.assertEqual({item["Cle"] for item in renamed}, {it["Cle"] for it in named} | {"PERSO:manual"})
        self.assertEqual(next(it for it in renamed if it["Cle"] == key)["Prix_Unitaire"], 123)
        self.assertEqual(loaded["hidden"], prefs["hidden"])
        self.assertEqual(loaded["custom"][0]["catalogue"], "Tarif équipement")
        self.assertEqual(app.load_orders()[0], orders_before)
        self.assertEqual(app.catalogue_path().read_bytes(), self.data)
        asyncio.run(self.page.push_route("/"))
        self.assertEqual(self.page.find(ft.Dropdown, label="Catalogue").value, "Tarif équipement")
        self.page = TestPage()
        app.main(self.page)
        self.assertIn("Tarif équipement", [opt.key for opt in self.page.find(ft.Dropdown, label="Catalogue").options])

    def test_rename_hidden_catalogue_and_validate_names(self):
        self.open_catalogue_manager()
        self.set_catalogue_visible("Tarif matériel", False)
        self.catalogue_action("Tarif matériel", "Renommer")
        field = self.page.find(ft.TextField, label="Nom du catalogue")
        for invalid in ["", "  ", "Services", "sérvices", "Catalogue principal", "Autre:Test"]:
            field.value = invalid
            self.page.find(ft.Button, content="Renommer").on_click(None)
            self.assertTrue(self.page.dialogs)
            self.assertNotIn("catalogue_items", app.load_prefs([])[0])
        field.value = "  Équipement   démo  "
        self.page.find(ft.Button, content="Renommer").on_click(None)
        self.assertEqual(app.load_prefs([])[0]["hidden_catalogues"], {"Équipement démo"})
        self.page.find(ft.Switch, tooltip="Afficher « Équipement démo »")

    def test_rename_visible_catalogue_does_not_inherit_stale_hidden_preference(self):
        prefs, _ = app.load_prefs([])
        prefs["hidden_catalogues"].add("Ancien nom")
        app.save_prefs(prefs)
        self.page = TestPage()
        app.main(self.page)
        self.open_catalogue_manager()
        self.catalogue_action("Services", "Renommer")
        self.page.find(ft.TextField, label="Nom du catalogue").value = "Ancien nom"
        self.page.find(ft.Button, content="Renommer").on_click(None)
        self.assertNotIn("Ancien nom", app.load_prefs([])[0]["hidden_catalogues"])

    def test_delete_catalogue_removes_its_articles_and_keeps_existing_orders(self):
        items = app.load_catalogue()
        prefs, _ = app.load_prefs(items)
        keys = {it["Cle"] for it in items if it["Catalogue"] == "Services"}
        prefs["prices"] = {key: 99 for key in keys}
        prefs["hidden"] |= keys
        prefs["custom"] = [{"key": "PERSO:delete", "name": "Manuel", "category": "Caméra",
                            "price": 7, "catalogue": "Services"}]
        app.save_prefs(prefs)
        app.save_orders({"demo": {"name": "Démo", "items": {
            next(iter(keys)): {"Nom": "Conservé", "Prix": 30, "quantite": 2}}, "photos": []}}, "demo")
        orders_before = app.load_orders()[0]
        self.page = TestPage()
        app.main(self.page)
        self.open_catalogue_manager()
        self.set_catalogue_visible("Services", False)
        self.catalogue_action("Services", "Supprimer")
        self.page.find(ft.TextButton, content="Annuler").on_click(None)
        self.page.find(ft.Switch, tooltip="Afficher « Services »")
        self.catalogue_action("Services", "Supprimer")
        self.page.find(ft.Button, content="Supprimer").on_click(None)
        with self.assertRaises(AssertionError):
            self.page.find(ft.PopupMenuButton, tooltip="Options « Services »")
        loaded, _ = app.load_prefs(items)
        self.assertFalse(any(it["Catalogue"] == "Services" for it in app.build_catalogue(items, loaded)))
        self.assertEqual(loaded["custom"], [])
        self.assertFalse(keys & loaded["hidden"])
        self.assertFalse(keys & loaded["prices"].keys())
        self.assertNotIn("Services", loaded["hidden_catalogues"])
        self.assertEqual(app.load_orders()[0], orders_before)

    def test_empty_main_and_delete_all_catalogues_survives_restart_and_allows_adding(self):
        self.open_catalogue_manager()
        self.catalogue_action("", "Vider le catalogue principal")
        self.page.find(ft.Button, content="Vider").on_click(None)
        for name in ["Tarif matériel", "Services", "Réserve"]:
            self.catalogue_action(name, "Supprimer")
            self.page.find(ft.Button, content="Supprimer").on_click(None)
        menu = self.page.find(ft.PopupMenuButton, tooltip=f"Options « {app.DEFAULT_CATALOGUE_LABEL} »")
        self.assertEqual([item.content for item in menu.items], ["Vider le catalogue principal"])
        self.assertTrue(menu.items[0].disabled)
        self.page = TestPage()
        app.main(self.page)
        self.assertEqual(app.build_catalogue(app.load_catalogue(), app.load_prefs([])[0]), [])
        asyncio.run(self.page.push_route("/articles"))
        self.page.find(ft.TextButton, content="Ajouter").on_click(None)
        self.page.find(ft.TextField, label="Nom de l'article").value = "Nouveau"
        self.page.find(ft.TextField, label="Nom de la nouvelle catégorie").value = "Divers"
        self.page.find(ft.TextField, label="Prix unitaire").value = "5"
        self.page.find(ft.Button, content="Ajouter").on_click(None)
        entries = app.build_catalogue(app.load_catalogue(), app.load_prefs([])[0])
        self.assertEqual([(it["Nom_Article"], it["Catalogue"]) for it in entries], [("Nouveau", "")])

    def test_edit_save_failure_preserves_catalogue(self):
        self.open_catalogue_manager()
        self.catalogue_action("Services", "Supprimer")
        with patch.object(app, "save_prefs", side_effect=OSError("Test")):
            self.page.find(ft.Button, content="Supprimer").on_click(None)
        self.page.find(ft.Switch, tooltip="Afficher « Services »")
        self.assertNotIn("catalogue_items", app.load_prefs([])[0])

    def test_reimport_restores_removed_and_renamed_imported_catalogues(self):
        self.open_catalogue_manager()
        self.catalogue_action("Tarif matériel", "Renommer")
        self.page.find(ft.TextField, label="Nom du catalogue").value = "Renommé"
        self.page.find(ft.Button, content="Renommer").on_click(None)
        self.catalogue_action("Réserve", "Supprimer")
        self.page.find(ft.Button, content="Supprimer").on_click(None)
        asyncio.run(self.page.push_route("/"))
        picked = SimpleNamespace(name="demo.csv", path=None, bytes=self.data)
        with patch.object(ft.FilePicker, "pick_files", new_callable=AsyncMock, return_value=[picked]):
            tile = self.page.find(ft.ListTile, title=self.page.find(ft.Text, value="Importer un catalogue"))
            asyncio.run(tile.on_click())
        prefs, _ = app.load_prefs([])
        self.assertNotIn("catalogue_items", prefs)
        self.assertEqual(app.catalogues_of(app.build_catalogue(app.load_catalogue(), prefs)),
                         ["", "Tarif matériel", "Services", "Réserve"])
        restored = next(it for it in app.build_catalogue(app.load_catalogue(), prefs) if it["Catalogue"] == "Réserve")
        self.assertFalse(restored["Visible"])

    def test_hide_active_catalogue_and_restore_preserves_article_settings_and_cart(self):
        self.select_catalogue("Tarif matériel")
        category = self.page.find(ft.Dropdown, label="Catégorie")
        category.value = "Caméra"
        asyncio.run(category.on_select())
        self.page.find(ft.IconButton, icon=ft.Icons.ADD_SHOPPING_CART).on_click(None)
        orders_before, _, _ = app.load_orders()
        prefs_before, _ = app.load_prefs([])
        self.open_catalogue_manager()
        self.set_catalogue_visible("Tarif matériel", False)
        self.set_catalogue_visible("Réserve", False)
        asyncio.run(self.page.push_route("/"))
        dropdown = self.page.find(ft.Dropdown, label="Catalogue")
        self.assertNotIn("Tarif matériel", [opt.key for opt in dropdown.options])
        self.assertEqual(dropdown.value, "")
        self.assertEqual(category.value, "Toutes")
        self.assertEqual(app.load_orders()[0], orders_before)
        self.assertEqual(app.load_prefs([])[0]["hidden"], prefs_before["hidden"])
        self.open_catalogue_manager()
        self.set_catalogue_visible("Tarif matériel", True)
        self.set_catalogue_visible("Réserve", True)
        asyncio.run(self.page.push_route("/"))
        self.select_catalogue("Tarif matériel")
        self.page.find(ft.Text, value="Câble")
        self.select_catalogue("Réserve")
        self.page.find(ft.Text, value="Aucun article affiché.\nCochez des articles dans ☰ › Gérer les articles.")

    def test_hide_all_catalogues_and_recover_from_empty_state(self):
        self.open_catalogue_manager()
        for name in ["", "Tarif matériel", "Services", "Réserve"]:
            self.set_catalogue_visible(name, False)
        asyncio.run(self.page.push_route("/"))
        dropdown = self.page.find(ft.Dropdown, label="Catalogue")
        self.assertEqual(dropdown.options, [])
        self.assertIsNone(dropdown.value)
        self.assertTrue(self.page.find(ft.TextField, label="Rechercher").disabled)
        with self.assertRaises(AssertionError):
            self.page.find(ft.IconButton, icon=ft.Icons.ADD_SHOPPING_CART)
        asyncio.run(self.page.find(ft.TextButton, content="Gérer les catalogues").on_click())
        self.set_catalogue_visible("Services", True)
        asyncio.run(self.page.push_route("/"))
        dropdown = self.page.find(ft.Dropdown, label="Catalogue")
        self.assertEqual([opt.key for opt in dropdown.options], ["Services"])
        self.assertEqual(dropdown.value, "Services")
        self.assertFalse(self.page.find(ft.TextField, label="Rechercher").disabled)
        self.page.find(ft.Text, value="Intervention")

    def test_hidden_catalogue_stays_manageable_after_reload_and_reimport(self):
        self.open_catalogue_manager()
        self.set_catalogue_visible("Tarif matériel", False)
        self.page = TestPage()
        app.main(self.page)
        dropdown = self.page.find(ft.Dropdown, label="Catalogue")
        self.assertNotIn("Tarif matériel", [opt.key for opt in dropdown.options])
        picked = SimpleNamespace(name="demo.csv", path=None, bytes=self.data)
        with patch.object(ft.FilePicker, "pick_files", new_callable=AsyncMock, return_value=[picked]):
            tile = self.page.find(ft.ListTile, title=self.page.find(ft.Text, value="Importer un catalogue"))
            asyncio.run(tile.on_click())
        self.assertNotIn("Tarif matériel", [opt.key for opt in dropdown.options])
        asyncio.run(self.page.push_route("/articles"))
        admin_dropdown = self.page.find(ft.Dropdown, label="Catalogue")
        self.assertIn("Tarif matériel", [opt.key for opt in admin_dropdown.options])
        self.select_catalogue("Tarif matériel")
        self.page.find(ft.Text, value="Câble")

    def test_catalogue_manager_available_without_orders(self):
        app.save_orders({}, None)
        self.page = TestPage()
        app.main(self.page)
        self.open_catalogue_manager()
        self.set_catalogue_visible("Services", False)
        self.assertIn("Services", app.load_prefs([])[0]["hidden_catalogues"])

    def test_switching_scopes_categories_and_preserves_mixed_cart(self):
        self.page.find(ft.IconButton, icon=ft.Icons.ADD_SHOPPING_CART).on_click(None)
        dropdown = self.select_catalogue("Tarif matériel")
        self.assertTrue(dropdown.visible)
        category = self.page.find(ft.Dropdown, label="Catégorie")
        self.assertEqual({opt.key for opt in category.options}, {"Toutes", "Caméra", "Accessoires"})
        category.value = "Caméra"
        asyncio.run(category.on_select())
        self.page.find(ft.IconButton, icon=ft.Icons.ADD_SHOPPING_CART).on_click(None)
        self.select_catalogue("Services")
        self.assertEqual(category.value, "Toutes")
        self.assertEqual({opt.key for opt in category.options}, {"Toutes", "Caméra", "Maintenance"})
        orders, _, _ = app.load_orders()
        self.assertEqual(len(orders["demo"]["items"]), 2)
        self.assertEqual(app.order_total(orders["demo"]), 15)
        self.assertFalse(app.migrate_cart_keys(orders))

    def test_hidden_only_catalogue_remains_selectable(self):
        dropdown = self.select_catalogue("Réserve")
        self.assertIn("Réserve", [opt.key for opt in dropdown.options])
        self.page.find(ft.Text, value="Aucun article affiché.\nCochez des articles dans ☰ › Gérer les articles.")

    def test_search_is_scoped_to_selected_catalogue(self):
        search = self.page.find(ft.TextField, label="Rechercher")
        search.value = "Intervention"
        self.select_catalogue("Tarif matériel")
        self.page.find(ft.Text, value="Aucun article ne correspond.")
        self.select_catalogue("Services")
        self.page.find(ft.Text, value="Intervention")

    def test_manage_articles_and_add_to_selected_catalogue(self):
        self.select_catalogue("Tarif matériel")
        asyncio.run(self.page.push_route("/articles"))
        self.assertEqual(self.page.find(ft.Dropdown, label="Catalogue").value, "Tarif matériel")
        self.select_catalogue("Réserve")
        self.assertEqual(self.page.find(ft.SegmentedButton).segments[0].label, "Tous")
        self.page.find(ft.Text, value="0 articles affichés sur 1 · prix enregistrés automatiquement")
        self.page.find(ft.TextButton, content="Ajouter").on_click(None)
        self.page.find(ft.TextField, label="Nom de l'article").value = "Ajouté"
        self.page.find(ft.TextField, label="Prix unitaire").value = "7"
        self.page.find(ft.Button, content="Ajouter").on_click(None)
        prefs, _ = app.load_prefs([])
        self.assertEqual(prefs["custom"][0]["catalogue"], "Réserve")
        self.assertEqual(prefs["custom"][0]["category"], "Archive")

    def test_reimport_removes_stale_catalogue_selection(self):
        self.select_catalogue("Services")
        picked = SimpleNamespace(name="demo.csv", path=None,
                                 bytes=b"Categorie;Article;Prix\nNouveau:Test;Exemple;10")
        with patch.object(ft.FilePicker, "pick_files", new_callable=AsyncMock, return_value=[picked]):
            tile = self.page.find(ft.ListTile, title=self.page.find(ft.Text, value="Importer un catalogue"))
            asyncio.run(tile.on_click())
        dropdown = self.page.find(ft.Dropdown, label="Catalogue")
        self.assertEqual(dropdown.value, "Nouveau")
        self.assertFalse(dropdown.visible)
        self.page.find(ft.Text, value="Exemple")


class AdaptiveWorkspaceTests(StorageTest):
    def setUp(self):
        super().setUp()
        app.install_catalogue(app.sample_catalogue_path().read_bytes(), ".xlsx")
        app.save_orders({"demo": {"name": "Démo", "created": "2026-11-03T12:00",
                                  "items": {}, "photos": []}}, "demo")
        self.page = TestPage()
        app.main(self.page)

    def resize(self, width, height):
        self.page.width, self.page.height = width, height
        asyncio.run(self.page.on_resize())
        body = self.page.controls[0].content
        asyncio.run(body.on_size_change(SimpleNamespace(width=width, height=height - 64)))

    def test_window_classes_and_short_windows(self):
        for width, expected in [(280, "compact"), (599, "compact"), (600, "medium"),
                                (839, "medium"), (840, "expanded"), (1600, "expanded")]:
            self.assertEqual(app.ui.WindowLayout(width, 800).size_class, expected)
        self.assertFalse(app.ui.WindowLayout(900, 440).dual_pane)
        self.assertTrue(app.ui.WindowLayout(900, 800).dual_pane)

    def test_quantity_and_search_survive_repeated_fold_and_resize(self):
        item = app.load_catalogue()[0]
        tooltip = f"Quantité à ajouter : {item['Nom_Article']}"
        quantity = self.page.find(ft.TextField, tooltip=tooltip)
        quantity.value = "7"
        quantity.on_change(SimpleNamespace(control=quantity))
        search = self.page.find(ft.TextField, label="Rechercher")
        search.value = "écran"
        for width, height in [(320, 850), (900, 950), (600, 750), (850, 440), (390, 900)]:
            self.resize(width, height)
            self.assertIs(self.page.find(ft.TextField, tooltip=tooltip), quantity)
            self.assertEqual(quantity.value, "7")
            self.assertIs(self.page.find(ft.TextField, label="Rechercher"), search)
            self.assertEqual(search.value, "écran")
        quantity.on_submit(None)
        self.assertEqual(app.load_orders()[0]["demo"]["items"][item["Cle"]]["quantite"], 7)

    def test_photo_navigation_and_actions_survive_fold(self):
        self.page.select_tab(2)
        navigation = self.page.find(ft.NavigationBar)
        photo_import = self.page.find(ft.OutlinedButton, content="Importer des photos")
        for width in [900, 320, 1200, 390]:
            self.resize(width, 900)
            self.assertEqual(navigation.selected_index, 2)
            self.assertIs(self.page.find(ft.OutlinedButton, content="Importer des photos"), photo_import)
        self.assertEqual(app.load_orders()[0]["demo"]["items"], {})

    def test_basket_edit_and_undo_still_work_after_resize(self):
        item = app.load_catalogue()[0]
        self.page.find(ft.IconButton, tooltip=f"Ajouter au panier : {item['Nom_Article']}").on_click(None)
        self.page.select_tab(1)
        quantity = self.page.find(ft.TextField, tooltip="Quantité")
        quantity.value = "12"
        quantity.on_change(None)
        self.resize(1000, 900)
        self.assertIs(self.page.find(ft.TextField, tooltip="Quantité"), quantity)
        self.assertEqual(app.load_orders()[0]["demo"]["items"][item["Cle"]]["quantite"], 12)
        self.page.find(ft.IconButton, tooltip="Retirer du panier").on_click(None)
        snack = self.page.find(ft.SnackBar, action="Annuler")
        snack.on_action(None)
        self.assertEqual(app.load_orders()[0]["demo"]["items"][item["Cle"]]["quantite"], 12)

    def test_filter_changes_restore_quantity_draft(self):
        item = app.load_catalogue()[0]
        tooltip = f"Quantité à ajouter : {item['Nom_Article']}"
        quantity = self.page.find(ft.TextField, tooltip=tooltip)
        quantity.value = "9"
        quantity.on_change(SimpleNamespace(control=quantity))
        with patch.object(ft.ListView, "scroll_to", new_callable=AsyncMock):
            search = self.page.find(ft.TextField, label="Rechercher")
            search.value = "no matching article"
            asyncio.run(search.on_change())
            search.value = ""
            asyncio.run(search.on_change())
        self.assertEqual(self.page.find(ft.TextField, tooltip=tooltip).value, "9")

    def test_system_theme_and_toggle_preserve_order(self):
        self.assertEqual(self.page.theme_mode, ft.ThemeMode.SYSTEM)
        before = app.load_orders()
        toggle = self.page.find(ft.IconButton, tooltip="Changer le thème clair / sombre")
        toggle.on_click(None)
        self.assertEqual(self.page.theme_mode, ft.ThemeMode.DARK)
        toggle.on_click(None)
        self.assertEqual(self.page.theme_mode, ft.ThemeMode.LIGHT)
        self.assertEqual(app.load_orders(), before)


class WebPhotoTests(StorageTest):
    def setUp(self):
        super().setUp()
        app.install_catalogue(app.sample_catalogue_path().read_bytes(), ".xlsx")
        app.save_orders({"demo": {"name": "Démo", "created": "2026-11-03T12:00",
                                  "items": {}, "photos": []}}, "demo")
        self.page = TestPage()
        app.main(self.page)

    def import_photo(self):
        self.page.select_tab(2)
        picked = SimpleNamespace(name="example.png", path=None, bytes=b"fake image")
        with patch.object(ft.FilePicker, "pick_files", new_callable=AsyncMock, return_value=[picked]) as picker:
            asyncio.run(self.page.find(ft.OutlinedButton, content="Importer des photos").on_click())
            self.assertTrue(picker.call_args.kwargs["with_data"])

    def test_import_and_preview_web_photo_without_local_path(self):
        self.import_photo()
        orders, _, _ = app.load_orders()
        photo = orders["demo"]["photos"][0]
        self.assertEqual(app.photo_path("demo", photo).read_bytes(), b"fake image")
        self.assertEqual(self.page.find(ft.Image).src, b"fake image")

    def test_web_zip_does_not_write_download_filename_on_server(self):
        self.import_photo()
        target = self.storage / "browser-download.zip"
        with patch.object(ft.FilePicker, "save_file", new_callable=AsyncMock, return_value=str(target)) as save:
            asyncio.run(self.page.find(ft.OutlinedButton, content="Enregistrer en ZIP").on_click())
            with zipfile.ZipFile(io.BytesIO(save.call_args.kwargs["src_bytes"])) as archive:
                self.assertIn("01 - Photo 1.png", archive.namelist())
        self.assertFalse(target.exists())

    def test_mobile_browser_uses_photo_import(self):
        page = TestPage(platform=ft.PagePlatform.ANDROID)
        with patch.object(app, "fc", SimpleNamespace()):
            app.main(page)
        page.select_tab(2)
        self.assertFalse(page.find(ft.Button, content="Prendre une photo").visible)
        self.assertFalse(page.find(ft.Button, content="Partager les photos").visible)
        self.assertTrue(page.find(ft.OutlinedButton, content="Importer des photos").visible)


if __name__ == "__main__":
    unittest.main()
