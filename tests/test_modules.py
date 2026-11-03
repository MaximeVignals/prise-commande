import os
import unittest
from pathlib import Path
from unittest import mock

import flet as ft

from test_app import StorageTest, TestPage


class ModuleSplitTest(unittest.TestCase):
    def test_text_helpers_moved(self):
        from src import main as app, text
        for name in ["fold", "norm_text", "_to_price", "fmt_eur", "fmt_input", "matches_search", "default_order_name"]:
            self.assertIs(getattr(app, name), getattr(text, name))
        self.assertEqual(text.fold("Écran"), "ecran")

    def test_config_constants_moved(self):
        from src import main as app, config
        for name in ["CATALOGUE_STEM", "CATALOGUE_EXTENSIONS", "SAMPLE_CATALOGUE_FILENAME", "ORDERS_FILENAME",
                     "PREFS_FILENAME", "CATALOGUE_COLUMNS", "REQUIRED_COLUMNS", "YES_VALUES", "KEY_EXCEL",
                     "KEY_CATALOGUE", "KEY_PERSO", "DEFAULT_CATALOGUE", "DEFAULT_CATALOGUE_LABEL", "ALL_CATALOGUES"]:
            self.assertEqual(getattr(app, name), getattr(config, name))

    def test_storage_moved(self):
        from src import main as app, storage
        for name in ["assets_dir", "storage_dir", "orders_path", "prefs_path", "photos_dir", "photo_path",
                     "_set_aside", "read_json", "write_json", "_valid_iso", "load_orders", "save_orders",
                     "migrate_cart_keys", "load_prefs", "save_prefs"]:
            self.assertIs(getattr(app, name), getattr(storage, name))
        with mock.patch.dict(os.environ):
            os.environ.pop("FLET_ASSETS_DIR", None)
            self.assertEqual(storage.assets_dir(), Path(app.__file__).parent / "assets")

    def test_catalogue_moved(self):
        from src import main as app, catalogue, config, storage
        for name in ["CatalogueError", "catalogue_path", "sample_catalogue_path", "split_catalogue_category",
                     "_read_rows", "parse_catalogue", "load_catalogue", "install_catalogue", "build_catalogue",
                     "categories_of", "catalogues_of"]:
            self.assertIs(getattr(app, name), getattr(catalogue, name))
        data = (storage.assets_dir() / config.SAMPLE_CATALOGUE_FILENAME).read_bytes()
        result = catalogue.parse_catalogue(data, ".xlsx")
        items, skipped = result
        self.assertTrue(items)
        self.assertIsInstance(skipped, list)
        for item in items:
            for key in ["Cle", "Nom_Article", "Catalogue", "Categorie", "Prix_Excel", "Masque"]:
                self.assertIn(key, item)

    def test_orders_and_photos_moved(self):
        from src import main as app, orders, photos, ui
        for name in ["order_total", "order_count", "order_email_text", "duplicate_order"]:
            self.assertIs(getattr(app, name), getattr(orders, name))
        for name in ["safe_filename", "photo_export_names", "photos_summary", "build_photos_zip"]:
            self.assertIs(getattr(app, name), getattr(photos, name))
        self.assertIs(app.get_category_icon, ui.get_category_icon)

    def test_import_screen_moved(self):
        from src import main as app, import_screen
        for name in ["pick_catalogue_file", "skipped_summary", "request_restore", "show_import_screen"]:
            self.assertIs(getattr(app, name), getattr(import_screen, name))


# Fonctions partagées que chaque écran doit trouver sur le contexte après main().
# Task 6 : les méthodes d'AppContext ; les tâches suivantes ajoutent les fonctions des écrans.
EXPECTED_CTX_FUNCTIONS = [
    "show_snack", "refresh", "rebuild_catalogue", "entry_by_key", "visible_entries", "new_order",
    "current_order", "cart", "persist", "persist_prefs", "dialog_width", "update_catalogue_selector",
    "entries_in", "managed_catalogues",
    # Task 7 : écran panier (view_cart) et fonctions de main() qu'il utilise
    "render_cart", "update_cart_summary", "change_qty_field",
    "go_to_tab", "render_all", "render_orders", "edit_notes", "update_catalogue_badges",
    # Task 8 : écran catalogue (view_catalogue) et fonctions de main() qu'il utilise
    "render_catalogue", "apply_catalogue_columns", "apply_filter_layout", "open_catalogue_manager",
    # Task 9 : écran commandes (view_orders) et fonctions de main() qu'il utilise
    "create_order_dialog", "archive_order", "open_drawer", "close_drawer",
    "open_admin", "replace_catalogue", "open_backup_view",
    # Task 10 : écran des articles (view_admin)
    "apply_admin_density", "render_admin",
    # Task 10 : écran des catalogues (view_catalogues)
    "render_catalogues",
    # Task 11 : écran photos (view_photos)
    "render_photos", "build_camera_view", "start_camera",
    # Task 11 : écran sauvegarde (view_backup) et main() qu'il relance après restauration
    "main",
]

# Widgets partagés (vérifiés avec assertIsNotNone).
EXPECTED_CTX_WIDGETS = [
    "content_panier", "basket_footer", "basket_heading", "cart_listview",
    "cart_tab", "compact_cart_btn", "order_info", "archive_banner",
    "content_catalogue", "catalogue_heading", "catalogue_dropdown", "category_dropdown", "catalogue_info",
    "browse_row", "filter_button", "filter_details",
    "drawer", "appbar_title",
    "admin_catalogue", "admin_category", "admin_view", "catalogues_view", "file_picker",
    "photos_tab", "content_photos", "photo_heading", "is_mobile", "camera_available", "camera_state",
    "backup_view",
]


class AppContextTest(StorageTest):
    def install_sample(self):
        from src import main as app
        app.install_catalogue(app.sample_catalogue_path().read_bytes(), ".xlsx")
        return app

    def test_context_persist_reports_failure(self):
        from src import context, storage
        app = self.install_sample()
        page = TestPage()
        ctx = context.AppContext(page, app.load_catalogue())
        with mock.patch.object(storage, "save_orders", side_effect=OSError("x")):
            ctx.persist()
        self.assertIsInstance(page.dialogs[-1], ft.SnackBar)
        self.assertTrue(page.dialogs[-1].content.value.startswith("⚠️ Sauvegarde impossible"))

    def test_every_ctx_handler_is_callable_after_install(self):
        app = self.install_sample()
        page = TestPage()
        app.main(page)
        ctx = page.data["ctx"]
        for name in EXPECTED_CTX_FUNCTIONS:
            with self.subTest(name=name):
                self.assertTrue(callable(getattr(ctx, name, None)))
        for name in EXPECTED_CTX_WIDGETS:
            with self.subTest(widget=name):
                self.assertIsNotNone(getattr(ctx, name, None))


if __name__ == "__main__":
    unittest.main()
