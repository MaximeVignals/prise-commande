import unittest


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


if __name__ == "__main__":
    unittest.main()
