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


if __name__ == "__main__":
    unittest.main()
