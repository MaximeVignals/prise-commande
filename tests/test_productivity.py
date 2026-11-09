import asyncio
import copy
import hashlib
import io
import json
import os
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch
import zipfile

import flet as ft

from src import main as app
from src import storage
from src import catalogue as catalogue_mod
from src import config as config_mod
from src import orders as orders_mod
from src import text as text_mod
from src import backup
from test_app import StorageTest, TestPage


class ProductivityTests(StorageTest):
    def setUp(self):
        super().setUp()
        self.catalogue = ("Categorie;Article;Prix\nÉcrans;Écran principal;10\n"
                          "Matériel:Écrans;Écran démo;20\nServices:Pose;Installation;30\n"
                          "Réserve:Écrans;Écran caché;40").encode()
        catalogue_mod.install_catalogue(self.catalogue, ".csv")
        prefs, _ = storage.load_prefs(catalogue_mod.load_catalogue())
        prefs["hidden_catalogues"].add("Réserve")
        storage.save_prefs(prefs)
        storage.save_orders({"demo": {"name": "Démo", "created": "2026-11-03T12:00", "items": {}, "photos": []}}, "demo")
        self.start()
        self.scroll = patch.object(ft.ListView, "scroll_to", new_callable=AsyncMock)
        self.scroll.start()
        self.addCleanup(self.scroll.stop)

    def start(self):
        self.page = TestPage()
        app.main(self.page)

    def add(self, name="Écran principal"):
        self.page.find(ft.IconButton, tooltip=f"Ajouter au panier : {name}").on_click(None)

    def choose(self, catalogue):
        control = self.page.find(ft.Dropdown, label="Catalogue")
        control.value = catalogue
        asyncio.run(control.on_select())

    def mode(self, value):
        control = self.page.find(ft.SegmentedButton)
        control.selected = [value]
        asyncio.run(control.on_change())

    def menu(self, action):
        menu = self.page.find(ft.PopupMenuButton, tooltip="Options")
        return next(item for item in menu.items if item.content == action)

    def test_favorites_persist_and_empty_filter_can_be_reset(self):
        favorite = self.page.find(ft.IconButton, tooltip="Favori : Écran principal")
        favorite.on_click(None)
        self.assertEqual(storage.load_prefs([])[0]["favorites"], {"XL:Écran principal"})
        self.start()
        self.assertEqual(self.page.find(ft.IconButton, tooltip="Favori : Écran principal").icon, ft.Icons.STAR)
        self.mode("favorites")
        self.page.find(ft.IconButton, tooltip="Favori : Écran principal").on_click(None)
        self.page.find(ft.TextButton, content="Réinitialiser les filtres").on_click(None)
        self.page.find(ft.IconButton, tooltip="Ajouter au panier : Écran principal")

    def test_failed_favorite_save_does_not_change_star_or_disk(self):
        star = self.page.find(ft.IconButton, tooltip="Favori : Écran principal")
        with patch.object(storage, "save_prefs", side_effect=OSError("test")):
            star.on_click(None)
        self.assertEqual(star.icon, ft.Icons.STAR_BORDER)
        self.assertEqual(storage.load_prefs([])[0]["favorites"], set())

    def test_global_search_excludes_hidden_catalogues_and_shows_origins(self):
        self.choose(config_mod.ALL_CATALOGUES)
        search = self.page.find(ft.TextField, label="Rechercher")
        search.value = "ecran"
        asyncio.run(search.on_change())
        self.page.find(ft.IconButton, tooltip="Ajouter au panier : Écran principal")
        self.page.find(ft.IconButton, tooltip="Ajouter au panier : Écran démo")
        self.page.find(ft.Text, value="Matériel", visible=True)
        with self.assertRaises(AssertionError):
            self.page.find(ft.IconButton, tooltip="Ajouter au panier : Écran caché")
        tag = self.page.find(ft.Chip, delete_icon_tooltip="Effacer la recherche")
        tag.on_delete(None)
        self.assertEqual(search.value, "")

    def test_recents_are_persistent_unique_and_scoped_to_visible_catalogues(self):
        self.add()
        self.choose("Matériel")
        self.add("Écran démo")
        self.page.find(ft.SnackBar, action="Annuler").on_action(None)  # annule l'ajout
        self.add("Écran démo")  # le bouton d'ajout est revenu : on ajoute à nouveau
        prefs, _ = storage.load_prefs([])
        self.assertEqual(len(prefs["recent"]), 2)
        self.assertEqual(prefs["recent"][1], "XL:Écran principal")
        self.start()
        self.choose(config_mod.ALL_CATALOGUES)
        self.mode("recent")
        self.page.find(ft.Text, value="Articles récents")
        self.page.find(ft.TextField, tooltip="Quantité dans la commande : Écran démo")
        with self.assertRaises(AssertionError):
            self.page.find(ft.IconButton, tooltip="Ajouter au panier : Installation")

    def test_quantity_badge_and_compact_total_follow_basket_edits_and_undo(self):
        self.add()
        self.page.find(ft.Text, value="Dans la commande", visible=True)
        in_order = self.page.find(ft.TextField, tooltip="Quantité dans la commande : Écran principal")
        self.assertEqual(in_order.value, "1")
        self.page.find(ft.TextButton, tooltip="Voir le panier").on_click(None)
        quantity = self.page.find(ft.TextField, tooltip="Quantité")
        quantity.value = "4"
        quantity.on_change(None)
        self.page.select_tab(0)
        self.assertEqual(in_order.value, "4")
        self.page.select_tab(1)
        self.page.find(ft.IconButton, tooltip="Retirer du panier").on_click(None)
        self.page.find(ft.SnackBar, action="Annuler").on_action(None)
        self.page.select_tab(0)
        self.assertEqual(in_order.value, "4")
        self.page.find(ft.Text, value="Dans la commande", visible=True)

    def test_add_resets_quantity_and_can_be_undone(self):
        field = self.page.find(ft.TextField, tooltip="Quantité à ajouter : Écran principal")
        field.value = "5"
        field.on_change(SimpleNamespace(control=field))
        self.add()
        self.assertEqual(field.value, "1")  # le prochain ajout ne reprend pas 5
        self.assertEqual(storage.load_orders()[0]["demo"]["items"]["XL:Écran principal"]["quantite"], 5)
        self.page.find(ft.SnackBar, action="Annuler").on_action(None)
        self.assertNotIn("XL:Écran principal", storage.load_orders()[0]["demo"]["items"])
        self.page.find(ft.IconButton, tooltip="Ajouter au panier : Écran principal")  # bouton d'ajout revenu

    def test_in_order_stepper_edits_the_order_line(self):
        self.add()
        key = "XL:Écran principal"
        self.page.find(ft.IconButton, tooltip="Ajouter un : Écran principal").on_click(None)
        self.assertEqual(storage.load_orders()[0]["demo"]["items"][key]["quantite"], 2)
        field = self.page.find(ft.TextField, tooltip="Quantité dans la commande : Écran principal")
        self.assertEqual(field.value, "2")
        field.value = "6"
        field.on_change(None)
        self.assertEqual(storage.load_orders()[0]["demo"]["items"][key]["quantite"], 6)
        field.value = ""
        field.on_blur(None)  # saisie vide : quantité précédente remise
        self.assertEqual(field.value, "6")
        self.page.select_tab(1)
        self.assertEqual(self.page.find(ft.TextField, tooltip="Quantité").value, "6")  # panier à jour
        self.page.select_tab(0)
        field.value = "1"
        field.on_change(None)
        self.page.find(ft.IconButton, tooltip="Retirer un : Écran principal").on_click(None)
        self.assertNotIn(key, storage.load_orders()[0]["demo"]["items"])  # − à 1 : ligne retirée
        self.page.find(ft.SnackBar, action="Annuler").on_action(None)
        self.assertEqual(storage.load_orders()[0]["demo"]["items"][key]["quantite"], 1)

    def test_search_hides_cards_without_rebuilding_and_matches_category(self):
        self.choose(config_mod.ALL_CATALOGUES)
        card_field = self.page.find(ft.TextField, tooltip="Quantité à ajouter : Installation")
        search = self.page.find(ft.TextField, label="Rechercher")
        search.value = "pose"  # catégorie « Pose » de « Installation »
        asyncio.run(search.on_change())
        self.assertIs(self.page.find(ft.TextField, tooltip="Quantité à ajouter : Installation"), card_field)
        ctx = self.page.data["ctx"]
        visible = [part["item"]["Nom_Article"] for part in ctx.catalogue_cards.values() if part["card"].visible]
        self.assertEqual(visible, ["Installation"])
        self.page.find(ft.Text, value="1 article(s) · 1 catégorie(s)")
        search.value = "introuvable"
        asyncio.run(search.on_change())
        self.assertFalse(any(part["card"].visible for part in ctx.catalogue_cards.values()))
        self.page.find(ft.Text, value="Aucun article ne correspond.")

    def test_only_the_last_search_keystroke_filters(self):
        ctx = self.page.data["ctx"]
        search = self.page.find(ft.TextField, label="Rechercher")
        scroll = ft.ListView.scroll_to  # AsyncMock posé dans setUp
        scroll.reset_mock()

        async def type_quickly():
            letters = []
            for value in ["e", "ec", "ecr"]:
                search.value = value
                letters.append(asyncio.create_task(search.on_change()))
                await asyncio.sleep(0)
            await asyncio.gather(*letters)

        asyncio.run(type_quickly())
        self.assertEqual(scroll.await_count, 1)  # un seul filtrage, après la dernière lettre
        visible = {part["item"]["Nom_Article"] for part in ctx.catalogue_cards.values() if part["card"].visible}
        self.assertEqual(visible, {"Écran principal"})

    def test_order_and_item_notes_persist_and_are_in_clipboard_text(self):
        self.add()
        self.page.select_tab(1)
        self.page.find(ft.TextButton, tooltip="Remarques de la commande").on_click(None)
        self.page.find(ft.TextField, label="Remarques").value = "Livraison groupée\nSalle 2"
        self.page.find(ft.Button, content="Enregistrer").on_click(None)
        self.page.find(ft.IconButton, tooltip="Remarque : Écran principal").on_click(None)
        self.page.find(ft.TextField, label="Remarques").value = "Vérifier HDMI"
        self.page.find(ft.Button, content="Enregistrer").on_click(None)
        loaded = storage.load_orders()[0]["demo"]
        self.assertEqual(loaded["notes"], "Livraison groupée\nSalle 2")
        self.assertEqual(loaded["items"]["XL:Écran principal"]["note"], "Vérifier HDMI")
        with patch.object(ft.Clipboard, "set", new_callable=AsyncMock) as clipboard:
            asyncio.run(self.page.find(ft.Button, content="Copier pour la Compta").on_click(None))
        message = clipboard.call_args.args[0]
        self.assertIn("Livraison groupée\nSalle 2", message)
        self.assertIn("Vérifier HDMI", message)
        self.assertIn(f"TOTAL : {text_mod.fmt_eur(10)}", message)

    def test_duplicate_and_archive_are_available_and_persist(self):
        self.add()
        asyncio.run(self.menu("Dupliquer").on_click(None))
        self.page.find(ft.TextField, label="Nom de la commande").value = "Deuxième salle"
        self.page.find(ft.Button, content="Valider").on_click(None)
        orders, selected, _ = storage.load_orders()
        self.assertNotEqual(selected, "demo")
        self.assertEqual(orders[selected]["name"], "Deuxième salle")
        self.assertEqual(orders[selected]["items"], orders["demo"]["items"])
        # Target the active order's menu by its tile title, independently of traversal order.
        tile = self.page.find(ft.ListTile, title=self.page.find(ft.Text, value="Deuxième salle"))
        archive = next(item for item in tile.trailing.items if item.content == "Archiver")
        asyncio.run(archive.on_click(None))
        self.assertTrue(storage.load_orders()[0][selected]["archived"])
        self.assertEqual(storage.load_orders()[1], "demo")
        self.start()
        self.page.find(ft.TextButton, content="Archives (1)").on_click(None)
        asyncio.run(self.menu("Réactiver").on_click(None))
        self.assertNotIn("archived", storage.load_orders()[0][selected])
        self.assertEqual(storage.load_orders()[1], selected)

    def test_quantity_drafts_are_separate_for_each_order(self):
        field = self.page.find(ft.TextField, tooltip="Quantité à ajouter : Écran principal")
        field.value = "7"
        field.on_change(SimpleNamespace(control=field))
        asyncio.run(self.page.find(ft.IconButton, tooltip="Nouvelle commande").on_click())
        self.page.find(ft.Button, content="Valider").on_click(None)
        self.assertEqual(self.page.find(ft.TextField, tooltip="Quantité à ajouter : Écran principal").value, "1")

    def test_note_save_failure_keeps_previous_data_and_dialog_open(self):
        self.add()
        self.page.select_tab(1)
        self.page.find(ft.TextButton, tooltip="Remarques de la commande").on_click(None)
        field = self.page.find(ft.TextField, label="Remarques")
        field.value = "À ne pas enregistrer"
        with patch.object(storage, "save_orders", side_effect=OSError("test")):
            self.page.find(ft.Button, content="Enregistrer").on_click(None)
        self.assertIn("Enregistrement impossible", field.error)
        self.assertNotIn("notes", storage.load_orders()[0]["demo"])

    def test_archive_save_failure_keeps_active_order(self):
        with patch.object(storage, "save_orders", side_effect=OSError("test")):
            asyncio.run(self.menu("Archiver").on_click(None))
        self.assertNotIn("archived", storage.load_orders()[0]["demo"])
        self.assertEqual(storage.load_orders()[1], "demo")
        self.menu("Archiver")

    def drawer_texts(self):
        """Textes du menu dans l'ordre d'affichage (titres et libellés)."""
        texts, pending = [], list(reversed(self.page.drawer.controls))
        while pending:
            value = pending.pop()
            if isinstance(value, ft.Text):
                texts.append(value.value)
                continue
            children = []
            for name in ("content", "leading", "title", "controls"):
                child = getattr(value, name, None)
                children.extend(child if isinstance(child, list) else [child] if child is not None else [])
            pending.extend(reversed([c for c in children if isinstance(c, ft.BaseControl)]))
        return texts

    def test_menu_lists_orders_before_settings(self):
        texts = self.drawer_texts()
        self.assertLess(texts.index("Démo"), texts.index("Réglages"))
        self.assertLess(texts.index("Réglages"), texts.index("Gérer les catalogues"))
        self.assertIn("Sauvegarder / restaurer", texts[texts.index("Réglages"):])

    def test_order_search_appears_for_long_lists_and_finds_archived_orders(self):
        search = self.page.find(ft.TextField, label="Rechercher une commande")
        self.assertFalse(self.page.data["ctx"].drawer.controls[2].visible)  # 1 commande : pas de recherche
        orders = {f"o{i}": {"name": f"Salle {i}", "created": "2026-11-03T12:00", "items": {}, "photos": []}
                  for i in range(6)}
        orders["o0"]["name"] = "Cabinet Dupont"
        orders["o0"]["archived"] = True
        storage.save_orders(orders, "o5")
        self.start()
        search = self.page.find(ft.TextField, label="Rechercher une commande")
        self.assertTrue(self.page.drawer.controls[2].visible)
        search.value = "dupont"
        asyncio.run(search.on_change())
        self.assertIn("Cabinet Dupont", self.drawer_texts())
        self.assertNotIn("Salle 3", self.drawer_texts())
        self.page.find(ft.Text, value="03/11 · 0 art. · 0,00 € · archivée")
        search.value = "rien"
        asyncio.run(search.on_change())
        self.assertIn("Aucune commande ne correspond.", self.drawer_texts())

    def test_delete_dialog_offers_archive_instead(self):
        asyncio.run(self.menu("Supprimer").on_click(None))
        asyncio.run(self.page.find(ft.TextButton, content="Archiver plutôt").on_click(None))
        orders, _, _ = storage.load_orders()
        self.assertTrue(orders["demo"]["archived"])  # gardée, seulement archivée

    def open_backup(self):
        tile = self.page.find(ft.ListTile, title=self.page.find(ft.Text, value="Sauvegarder / restaurer"))
        asyncio.run(tile.on_click())

    def test_web_backup_export_uses_download_bytes_without_server_path_write(self):
        self.add()
        self.open_backup()
        target = self.storage / "browser-download.zip"
        with patch.object(ft.FilePicker, "save_file", new_callable=AsyncMock, return_value=str(target)) as save:
            asyncio.run(self.page.find(ft.Button, content="Créer une sauvegarde").on_click())
        snapshot = backup.inspect_backup(save.call_args.kwargs["src_bytes"], catalogue_mod.parse_catalogue)
        self.assertEqual(len(snapshot.orders["orders"]["demo"]["items"]), 1)
        self.assertFalse(target.exists())

    def test_restore_preview_can_be_cancelled_without_changes(self):
        data = backup.create_backup(self.storage)
        before = storage.load_orders()
        self.open_backup()
        picked = SimpleNamespace(bytes=data, path=None, name="backup.zip")
        with patch.object(ft.FilePicker, "pick_files", new_callable=AsyncMock, return_value=[picked]) as picker:
            asyncio.run(self.page.find(ft.OutlinedButton, content="Restaurer une sauvegarde").on_click())
        self.assertTrue(picker.call_args.kwargs["with_data"])
        self.page.find(ft.TextButton, content="Annuler").on_click(None)
        self.assertEqual(storage.load_orders(), before)
        self.assertFalse((self.storage / "sauvegardes").exists())

    def test_restore_confirm_merges_and_reloads_application(self):
        self.add()
        data = backup.create_backup(self.storage)
        storage.save_orders({"local": {"name": "Local", "created": "2026-11-03T12:00", "items": {}, "photos": []}}, "local")
        self.start()
        self.open_backup()
        picked = SimpleNamespace(bytes=data, path=None, name="backup.zip")
        with patch.object(ft.FilePicker, "pick_files", new_callable=AsyncMock, return_value=[picked]):
            asyncio.run(self.page.find(ft.OutlinedButton, content="Restaurer une sauvegarde").on_click())
        asyncio.run(self.page.find(ft.Button, content="Restaurer").on_click())
        orders, current, _ = storage.load_orders()
        self.assertEqual(set(orders), {"demo", "local"})
        self.assertEqual(current, "local")
        self.page.find(ft.NavigationBar)
        self.page.find(ft.Text, value="Local")

    def test_restore_available_before_first_catalogue_import(self):
        data = backup.create_backup(self.storage)
        catalogue_mod.catalogue_path().unlink()
        self.start()
        picked = SimpleNamespace(bytes=data, path=None, name="backup.zip")
        with patch.object(ft.FilePicker, "pick_files", new_callable=AsyncMock, return_value=[picked]):
            asyncio.run(self.page.find(ft.TextButton, content="Restaurer une sauvegarde").on_click())
        asyncio.run(self.page.find(ft.Button, content="Restaurer").on_click())
        self.assertTrue(catalogue_mod.load_catalogue())
        self.page.find(ft.NavigationBar)

    def test_archive_last_order_survives_restart_and_remains_accessible(self):
        asyncio.run(self.menu("Archiver").on_click(None))
        self.assertIsNone(storage.load_orders()[1])
        self.start()
        self.page.find(ft.TextButton, content="Archives (1)").on_click(None)
        asyncio.run(self.menu("Réactiver").on_click(None))
        self.assertEqual(storage.load_orders()[1], "demo")
        self.page.find(ft.NavigationBar)

    def test_note_draft_survives_fold_and_window_resize(self):
        self.page.select_tab(1)
        self.page.find(ft.TextButton, tooltip="Remarques de la commande").on_click(None)
        field = self.page.find(ft.TextField, label="Remarques")
        field.value = "Brouillon conservé\nDeuxième ligne"
        for width, height in [(320, 800), (900, 900), (600, 480)]:
            self.page.width, self.page.height = width, height
            asyncio.run(self.page.on_resize())
            self.assertIs(self.page.find(ft.TextField, label="Remarques"), field)
            self.assertEqual(field.value, "Brouillon conservé\nDeuxième ligne")
        self.page.find(ft.Button, content="Enregistrer").on_click(None)
        self.assertEqual(storage.load_orders()[0]["demo"]["notes"], field.value)

    def test_export_recovery_uses_pre_restore_snapshot(self):
        self.add()
        data = backup.create_backup(self.storage)
        storage.save_orders({"local": {"name": "Local", "created": "2026-11-03T12:00", "items": {}, "photos": []}}, "local")
        recovery = backup.restore_backup(self.storage, backup.inspect_backup(data, catalogue_mod.parse_catalogue))
        self.start()
        self.open_backup()
        with patch.object(ft.FilePicker, "save_file", new_callable=AsyncMock, return_value="recovery.zip") as save:
            asyncio.run(self.page.find(ft.TextButton, content="Exporter la dernière copie de secours").on_click())
        self.assertEqual(save.call_args.kwargs["src_bytes"], recovery.read_bytes())
        snapshot = backup.inspect_backup(save.call_args.kwargs["src_bytes"], catalogue_mod.parse_catalogue)
        self.assertEqual(set(snapshot.orders["orders"]), {"local"})

    def test_legacy_migration_does_not_merge_different_item_notes(self):
        order = {"items": {"ART_1": {"Nom": "Écran", "Prix": 10, "quantite": 1, "note": "Salle 1"},
                           "ART_2": {"Nom": "Écran", "Prix": 10, "quantite": 1, "note": "Salle 2"}}}
        self.assertTrue(storage.migrate_cart_keys({"legacy": order}))
        self.assertEqual(len(order["items"]), 2)
        self.assertEqual({line["note"] for line in order["items"].values()}, {"Salle 1", "Salle 2"})

    def test_email_without_notes_keeps_original_format(self):
        order = {"name": "Démo", "items": {"a": {"Nom": "Écran", "Prix": 10, "quantite": 2}}}
        self.assertEqual(orders_mod.order_email_text(order),
            f"Bonjour,\n\nVoici le détail de la commande « Démo » :\n\n"
            f"- 2x Écran ({text_mod.fmt_eur(10)}/u) = {text_mod.fmt_eur(20)}\n\nTOTAL : {text_mod.fmt_eur(20)}\n\nMerci.")


class BackupTests(StorageTest):
    def setUp(self):
        super().setUp()
        catalogue_mod.install_catalogue(catalogue_mod.sample_catalogue_path().read_bytes(), ".xlsx")
        prefs, _ = storage.load_prefs(catalogue_mod.load_catalogue())
        prefs.update(favorites={"XL:Exemple"}, recent=["XL:Exemple"])
        storage.save_prefs(prefs)
        folder = storage.photos_dir("demo")
        folder.mkdir(parents=True)
        (folder / "p.jpg").write_bytes(b"sample photo")
        self.order = {"name": "Démo", "created": "2026-11-03T12:00", "notes": "Commande notée", "archived": True,
                      "items": {"XL:Exemple": {"Nom": "Exemple", "Prix": 10, "quantite": 2, "note": "HDMI"}},
                      "photos": [{"id": "p", "file": "p.jpg", "label": "Étiquette", "added": "2026-11-03T12:00"}]}
        storage.save_orders({"demo": self.order}, "demo")
        self.data = backup.create_backup(self.storage)
        self.destination = self.storage / "target"

    def inspect(self, data=None):
        return backup.inspect_backup(data or self.data, catalogue_mod.parse_catalogue)

    def rewrite(self, change):
        with zipfile.ZipFile(io.BytesIO(self.data)) as archive:
            files = {name: archive.read(name) for name in archive.namelist()}
        change(files)
        result = io.BytesIO()
        with zipfile.ZipFile(result, "w", zipfile.ZIP_DEFLATED) as archive:
            for name, data in files.items():
                archive.writestr(name, data)
        return result.getvalue()

    def replace_file(self, files, name, payload):
        files[name] = payload
        manifest = json.loads(files["manifest.json"])
        manifest["files"][name] = {"size": len(payload), "sha256": hashlib.sha256(payload).hexdigest()}
        files["manifest.json"] = json.dumps(manifest).encode()

    def test_full_restore_to_empty_storage_includes_photos_settings_and_notes(self):
        snapshot = self.inspect()
        self.assertEqual(snapshot.photo_count, 1)
        recovery = backup.restore_backup(self.destination, snapshot)
        self.assertTrue(recovery.exists())
        with patch.dict(os.environ, {"FLET_APP_STORAGE_DATA": str(self.destination)}):
            self.assertEqual(storage.load_orders()[0]["demo"], self.order)
            self.assertEqual(storage.photo_path("demo", self.order["photos"][0]).read_bytes(), b"sample photo")
            prefs, _ = storage.load_prefs(catalogue_mod.load_catalogue())
            self.assertEqual(prefs["favorites"], {"XL:Exemple"})
            self.assertEqual(prefs["recent"], ["XL:Exemple"])
        empty = backup.inspect_backup(recovery.read_bytes(), catalogue_mod.parse_catalogue)
        self.assertEqual(empty.orders["orders"], {})

    def test_collision_keeps_existing_order_and_photo_intact(self):
        snapshot = self.inspect()
        existing = copy.deepcopy(self.order)
        existing["name"] = "À conserver"
        (self.destination / "photos" / "demo").mkdir(parents=True)
        (self.destination / "photos" / "demo" / "p.jpg").write_bytes(b"existing photo")
        (self.destination / backup.ORDERS).write_text(json.dumps({"orders": {"demo": existing}, "current": "demo"}))
        backup.restore_backup(self.destination, snapshot)
        restored = json.loads((self.destination / backup.ORDERS).read_text(encoding="utf-8"))
        self.assertEqual(restored["orders"]["demo"], existing)
        self.assertEqual(restored["current"], "demo")
        imported = next(key for key in restored["orders"] if key != "demo")
        self.assertEqual((self.destination / "photos" / "demo" / "p.jpg").read_bytes(), b"existing photo")
        self.assertEqual((self.destination / "photos" / imported / "p.jpg").read_bytes(), b"sample photo")

    def test_failed_write_rolls_back_catalogue_settings_and_orders(self):
        self.destination.mkdir()
        original = {backup.ORDERS: b'{"orders":{},"current":null}', backup.PREFS: b'{"favorites":["local"]}',
                    "catalogue_importe.csv": b"Categorie;Article;Prix\nLocal;Local;1"}
        for name, data in original.items():
            (self.destination / name).write_bytes(data)
        replace = os.replace
        failed = False
        def fail_once(source, target):
            nonlocal failed
            if Path(target).name == backup.ORDERS and not failed:
                failed = True
                raise OSError("test write failure")
            return replace(source, target)
        with patch.object(backup.os, "replace", side_effect=fail_once), self.assertRaises(OSError):
            backup.restore_backup(self.destination, self.inspect())
        for name, data in original.items():
            self.assertEqual((self.destination / name).read_bytes(), data)
        self.assertFalse((self.destination / "catalogue_importe.xlsx").exists())
        self.assertFalse((self.destination / "photos" / "demo" / "p.jpg").exists())
        self.assertEqual(len(list((self.destination / "sauvegardes").glob("*.zip"))), 1)

    def test_restore_remaps_case_insensitive_order_id_collisions(self):
        self.destination.mkdir()
        local = {"name": "Local", "created": "2026-11-03T12:00", "items": {}, "photos": []}
        (self.destination / backup.ORDERS).write_text(json.dumps({"orders": {"DEMO": local}, "current": "DEMO"}))
        backup.restore_backup(self.destination, self.inspect())
        data = json.loads((self.destination / backup.ORDERS).read_text(encoding="utf-8"))
        self.assertEqual(data["orders"]["DEMO"], local)
        imported = next(key for key in data["orders"] if key != "DEMO")
        self.assertNotEqual(imported.casefold(), "demo")

    def test_hash_mismatch_rejected(self):
        data = self.rewrite(lambda files: files.__setitem__(backup.PREFS, b"{}"))
        with self.assertRaises(ValueError):
            self.inspect(data)

    def test_missing_photo_rejected_before_any_restore(self):
        data = self.rewrite(lambda files: files.pop("photos/demo/p.jpg"))
        with self.assertRaises(ValueError):
            self.inspect(data)
        self.assertFalse(self.destination.exists())

    def test_path_traversal_rejected_even_with_a_valid_hash(self):
        data = self.rewrite(lambda files: self.replace_file(files, "photos/../outside.jpg", b"test"))
        with self.assertRaises(ValueError):
            self.inspect(data)

    def test_invalid_catalogue_rejected_even_with_valid_hash(self):
        data = self.rewrite(lambda files: self.replace_file(files, "catalogue_importe.xlsx", b"invalid workbook"))
        with self.assertRaises(ValueError):
            self.inspect(data)

    def test_unknown_version_and_size_limit_rejected(self):
        def change(files):
            manifest = json.loads(files["manifest.json"])
            manifest["version"] = 99
            files["manifest.json"] = json.dumps(manifest).encode()
        with self.assertRaises(ValueError):
            self.inspect(self.rewrite(change))
        with patch.object(backup, "MAX_BYTES", 100), self.assertRaises(ValueError):
            self.inspect()

    def test_duplicate_photos_and_notes_are_independent(self):
        key, duplicate = orders_mod.duplicate_order("demo", self.order, existing_ids={"demo"})
        self.assertNotIn("archived", duplicate)
        self.assertEqual(duplicate["notes"], self.order["notes"])
        duplicate["items"]["XL:Exemple"]["note"] = "Différent"
        self.assertEqual(self.order["items"]["XL:Exemple"]["note"], "HDMI")
        copied = storage.photo_path(key, duplicate["photos"][0])
        self.assertEqual(copied.read_bytes(), b"sample photo")
        copied.unlink()
        self.assertTrue(storage.photo_path("demo", self.order["photos"][0]).exists())


if __name__ == "__main__":
    unittest.main()
