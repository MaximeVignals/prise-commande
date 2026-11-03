import os
import unittest
from pathlib import Path
from unittest import mock


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


if __name__ == "__main__":
    unittest.main()
