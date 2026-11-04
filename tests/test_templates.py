import copy
from datetime import datetime
import json
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from src import catalogue, config, templates


class TemplatesTests(unittest.TestCase):
    def setUp(self):
        # Aucune donnée réelle : stockage temporaire hors du dépôt.
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.storage = Path(temp.name)
        env = patch.dict(os.environ, {"FLET_APP_STORAGE_DATA": temp.name})
        env.start()
        self.addCleanup(env.stop)
        self.entries = self.catalogue("Accessoires;Câble;4\n")
        self.order = {"name": "Commande à ne pas copier", "created": "2020-01-01T12:00",
                      "items": {"XL:Câble": {"Nom": "Ancien nom", "Prix": 1, "quantite": 3,
                                             "note": "Note de ligne privée"}},
                      "photos": [{"file": "photo.jpg"}], "notes": "Note privée", "archived": True}
        self.template = templates.template_from_order(self.order, self.entries, "  Modèle démo  ")

    def catalogue(self, rows, prices=None, hidden=None, custom=None):
        items, skipped = catalogue.parse_catalogue(("Catégorie;Article;Prix\n" + rows).encode(), ".csv")
        self.assertEqual(skipped, [])
        return catalogue.build_catalogue(items, {"prices": prices or {}, "hidden": hidden or set(),
                                                  "custom": custom or []})

    def resolve(self, entries=None, hidden_catalogues=()):
        return templates.resolve_template(self.template, self.entries if entries is None else entries,
                                          hidden_catalogues)[0]

    def test_missing_file_and_roundtrip(self):
        self.assertEqual(templates.templates_path(), self.storage / config.TEMPLATES_FILENAME)
        self.assertEqual(config.TEMPLATES_FILENAME, "modeles.json")
        self.assertEqual(templates.load_templates(), ({}, None))
        data = {"abcd1234": self.template}
        templates.save_templates(data)
        self.assertEqual(templates.load_templates(), (data, None))
        self.assertFalse(templates.templates_path().with_suffix(".tmp").exists())
        templates.save_templates({})
        self.assertEqual(templates.load_templates(), ({}, None))

    def test_corrupt_and_non_dict_files_are_set_aside(self):
        for raw in [b"{invalid", b"[]", b"null", b'"texte"', b"42", b"\xff"]:
            with self.subTest(raw=raw):
                path = templates.templates_path()
                path.write_bytes(raw)
                loaded, warning = templates.load_templates()
                self.assertEqual(loaded, {})
                self.assertTrue(warning)
                self.assertFalse(path.exists())
                backups = list(self.storage.glob("modeles.illisible-*.json"))
                self.assertEqual(len(backups), 1)
                self.assertEqual(backups[0].read_bytes(), raw)
                backups[0].unlink()

    def test_load_drops_malformed_templates_and_entries(self):
        valid = self.template["entries"][0]
        invalid = [None, [], "ligne", {}, {**valid, "name": " "}, {**valid, "key": ""},
                   {**valid, "category": None}, {**valid, "catalogue": 7}]
        invalid += [{**valid, "quantite": value} for value in [0, -1, True, 1.5, "2", None]]
        data = {"valid": {**self.template, "entries": invalid + [{**valid, "Prix": 99, "note": "oubliée"}],
                          "photos": ["oubliée"]},
                "null": None, "list": [], "blank": {**self.template, "name": " "},
                "bad_name": {**self.template, "name": 3}, "absent": {},
                "bad_entries": {**self.template, "entries": {}},
                "empty": {**self.template, "entries": []},
                "invalid_only": {**self.template, "entries": invalid}}
        templates.save_templates(data)
        self.assertEqual(templates.load_templates(), ({"valid": self.template}, None))

    def test_load_repairs_date_like_storage(self):
        templates.save_templates({"id": {**self.template, "created": "invalide"}})
        loaded, warning = templates.load_templates()
        self.assertIsNone(warning)
        datetime.fromisoformat(loaded["id"]["created"])

    def test_new_id_retries_collisions(self):
        with patch.object(templates._uuid, "uuid4", side_effect=[SimpleNamespace(hex="12345678" + "0" * 24),
                                                                SimpleNamespace(hex="abcdef01" + "0" * 24)]):
            self.assertEqual(templates.new_template_id({"12345678": self.template}), "abcdef01")
        self.assertRegex(templates.new_template_id({}), r"^[0-9a-f]{8}$")

    def test_from_order_keeps_only_template_fields(self):
        before = copy.deepcopy((self.order, self.entries))
        start = datetime.now().replace(second=0, microsecond=0)
        result = templates.template_from_order(self.order, self.entries, "  Modèle démo  ")
        self.assertEqual(set(result), {"name", "created", "entries"})
        self.assertEqual(result["name"], "Modèle démo")
        created = datetime.fromisoformat(result["created"])
        self.assertGreaterEqual(created, start)
        self.assertLessEqual(created, datetime.now())
        self.assertEqual(len(result["created"]), 16)
        self.assertEqual(result["entries"], [{"key": "XL:Câble", "catalogue": "", "category": "Accessoires",
                                               "name": "Câble", "quantite": 3}])
        self.assertEqual((self.order, self.entries), before)

    def test_from_order_missing_articles_derive_catalogue(self):
        named = config.KEY_CATALOGUE + json.dumps(["Matériel", "Câble"], ensure_ascii=False)
        keys = ["XL:Câble", named, named + " (2)", "PERSO:abc", "CAT:invalide", "CAT:{}"]
        order = {"items": {key: {"Nom": "Nom conservé", "Prix": 7, "quantite": 2} for key in keys}}
        result = templates.template_from_order(order, [], "Modèle")
        self.assertEqual([entry["key"] for entry in result["entries"]], keys)
        self.assertEqual([entry["catalogue"] for entry in result["entries"]], ["", "Matériel", "Matériel", "", "", ""])
        for entry in result["entries"]:
            self.assertEqual(entry["name"], "Nom conservé")
            self.assertEqual(entry["category"], "")

    def test_from_order_rejects_empty_order_or_name(self):
        for order, name in [({"items": {}}, "Modèle"), ({}, "Modèle"), (self.order, " \n ")]:
            with self.subTest(order=order, name=name), self.assertRaises(ValueError):
                templates.template_from_order(order, self.entries, name)

    def test_current_price_includes_local_override(self):
        entries = self.catalogue("Accessoires;Câble;6\n", prices={"XL:Câble": 9.5})
        line = self.resolve(entries)
        self.assertEqual(line["status"], "ok")
        self.assertIs(line["article"], entries[0])
        self.assertEqual(line["candidates"], entries)
        self.assertEqual(line["article"]["Prix_Excel"], 6)
        self.assertEqual(templates.line_price(line["article"]), 9.5)
        items = templates.build_order_items([(line["article"], line["entry"]["quantite"])])
        self.assertEqual(items["XL:Câble"]["Prix"], 9.5)
        self.assertEqual(templates.items_total(items), 28.5)

    def test_multiple_catalogues_resolve_in_entry_order(self):
        entries = self.catalogue("Matériel:Accessoires;Câble;4\nServices:Accessoires;Câble;8\n")
        order = {"items": {article["Cle"]: {"Nom": "Câble", "quantite": 1} for article in reversed(entries)}}
        template = templates.template_from_order(order, entries, "Deux catalogues")
        lines = templates.resolve_template(template, entries, set())
        self.assertEqual([line["status"] for line in lines], ["ok", "ok"])
        self.assertEqual([line["article"] for line in lines], list(reversed(entries)))

    def test_resolution_normalizes_spaces_but_does_not_match_similar_names(self):
        self.template["entries"][0]["name"] = "  Câble \n USB "
        entries = self.catalogue("Accessoires;Câble USB;4\n")
        self.assertEqual(self.resolve(entries)["status"], "ok")
        for name in ["Câble", "câble USB", "Cable USB", "Câble USB long"]:
            with self.subTest(name=name):
                line = self.resolve([{**entries[0], "Nom_Article": name}])
                self.assertEqual((line["status"], line["article"], line["candidates"]), ("missing", None, []))

    def test_missing_article_including_suffixed_key(self):
        for suffix in ["", " (2)"]:
            self.template["entries"][0]["key"] = "XL:Câble" + suffix
            line = self.resolve([])
            self.assertEqual((line["status"], line["article"], line["candidates"]), ("missing", None, []))

    def test_duplicate_names_are_ambiguous_even_with_exact_key(self):
        entries = self.catalogue("Accessoires;Câble;4\nAutres;Câble;8\n")
        line = self.resolve(entries)
        self.assertEqual(line["status"], "ambiguous")
        self.assertIsNone(line["article"])
        self.assertEqual(line["candidates"], entries)

    def test_suffix_is_ambiguous_even_with_one_candidate(self):
        for suffix in [" (2)", " (3)", " (12)"]:
            with self.subTest(suffix=suffix):
                self.template["entries"][0]["key"] = "XL:Câble" + suffix
                line = self.resolve()
                self.assertEqual(line["status"], "ambiguous")
                self.assertIsNone(line["article"])
                self.assertEqual(line["candidates"], self.entries)

    def test_personal_article_matches_only_stable_key(self):
        custom = {"key": "PERSO:stable (2)", "name": "Nouveau nom", "category": "Divers", "price": 12}
        entries = self.catalogue("Accessoires;Câble;4\n", custom=[custom])
        self.template["entries"][0]["key"] = custom["key"]
        line = self.resolve(entries)
        self.assertEqual(line["status"], "ok")
        self.assertIs(line["article"], entries[1])
        self.assertEqual(self.resolve(entries[:1])["status"], "missing")

    def test_hidden_article_and_hidden_catalogue(self):
        hidden = self.catalogue("Accessoires;Câble;4\n", hidden={"XL:Câble"})
        for entries, hidden_catalogues in [(hidden, set()), (self.entries, {""})]:
            with self.subTest(hidden_catalogues=hidden_catalogues):
                line = self.resolve(entries, hidden_catalogues)
                self.assertEqual(line["status"], "hidden")
                self.assertIs(line["article"], entries[0])

    def test_resolution_does_not_mutate_inputs(self):
        for entries in [self.entries, [], self.entries * 2, [{**self.entries[0], "Visible": False}]]:
            hidden = {"Autre"}
            before = copy.deepcopy((self.template, entries, hidden))
            line = self.resolve(entries, hidden)
            self.assertIs(line["entry"], self.template["entries"][0])
            self.assertEqual((self.template, entries, hidden), before)

    def test_build_items_merges_quantities_and_totals(self):
        entries = self.catalogue("Accessoires;Câble;4\nDivers;Adaptateur;2.5\n")
        before = copy.deepcopy(entries)
        choices = [(entries[0], 2), (entries[1], 0), (entries[1], -3), (entries[1], "4"), (entries[0], 3)]
        items = templates.build_order_items(iter(choices))
        self.assertEqual(items, {"XL:Câble": {"Nom": "Câble", "Prix": 4.0, "quantite": 5},
                                 "XL:Adaptateur": {"Nom": "Adaptateur", "Prix": 2.5, "quantite": 4}})
        self.assertIsInstance(items["XL:Câble"]["Prix"], float)
        self.assertEqual(templates.items_total(items), 30)
        self.assertEqual(templates.build_order_items([]), {})
        self.assertEqual(templates.items_total({}), 0)
        self.assertEqual(entries, before)


if __name__ == "__main__":
    unittest.main()
