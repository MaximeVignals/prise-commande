"""Parcours des modèles de commande dans l'app (données fictives uniquement)."""

import asyncio
import json
import unittest
import unittest.mock

import flet as ft

from test_app import StorageTest, TestPage
from src import main as app
from src import storage
from src import templates
from src import catalogue as catalogue_mod

CSV = ("Categorie;Article;Prix;Masque\n"
       "Divers;Câble;2;\n"
       "Tarif matériel:Caméra;Commun;10;\n"
       "Services:Caméra;Commun;20;\n"
       "Divers;Écran;100;\n"
       "Divers;Ancien;1;oui\n")


def walk(value, seen=None):
    seen = set() if seen is None else seen
    if id(value) in seen:
        return
    seen.add(id(value))
    if isinstance(value, ft.BaseControl):
        yield value
        for child in vars(value).values():
            yield from walk(child, seen)
    elif isinstance(value, (list, tuple)):
        for child in value:
            yield from walk(child, seen)
    elif isinstance(value, dict):
        for child in value.values():
            yield from walk(child, seen)


def buttons(dialog, label):
    return [c for c in walk(dialog.content) if isinstance(c, ft.TextButton) and c.content == label]


class TemplateFlowTests(StorageTest):
    def setUp(self):
        super().setUp()
        catalogue_mod.install_catalogue(CSV.encode(), ".csv")
        self.keys = {(i["Catalogue"], i["Nom_Article"]): i["Cle"]
                     for i in catalogue_mod.load_catalogue()}
        order = {"name": "Client Dupont", "notes": "Sonner deux fois", "photos": [], "items": {
            self.keys[("", "Câble")]: {"Nom": "Câble", "Prix": 1.0, "quantite": 3, "note": "Rouge"},
            self.keys[("Tarif matériel", "Commun")]: {"Nom": "Commun", "Prix": 10.0, "quantite": 1},
            self.keys[("Services", "Commun")]: {"Nom": "Commun", "Prix": 20.0, "quantite": 2},
        }}
        storage.save_orders({"src": order}, "src")
        self.start()

    def start(self):
        self.page = TestPage()
        app.main(self.page)
        self.ctx = self.page.data["ctx"]

    def save_template(self, name="Salle type"):
        asyncio.run(self.ctx.save_template_dialog("src"))
        dialog = self.page.dialogs[-1]
        field = next(c for c in walk(dialog.content) if isinstance(c, ft.TextField))
        field.value = name
        dialog.actions[1].on_click(None)
        data, _ = templates.load_templates()
        return next(iter(data)), data

    def open_review(self, name="Nouvelle"):
        template_id, _ = templates.load_templates()[0].popitem()
        self.created = []
        self.ctx.review_template(template_id, name, self.created.append)
        return self.page.dialogs[-1]

    def test_saved_template_keeps_only_identity_and_quantities(self):
        _, data = self.save_template()
        raw = json.loads(templates.templates_path().read_text(encoding="utf-8"))
        text = json.dumps(raw, ensure_ascii=False)
        for forbidden in ("Prix", "Rouge", "Sonner", "Client Dupont", "photos", "note"):
            self.assertNotIn(forbidden, text)
        entry = next(iter(data.values()))["entries"]
        self.assertEqual({(e["catalogue"], e["name"], e["quantite"]) for e in entry},
                         {("", "Câble", 3), ("Tarif matériel", "Commun", 1), ("Services", "Commun", 2)})

    def test_review_uses_current_prices_and_creates_independent_order(self):
        self.save_template()
        self.ctx.prefs["prices"][self.keys[("", "Câble")]] = 4.5  # prix modifié localement
        self.ctx.rebuild_catalogue()
        dialog = self.open_review()
        self.assertFalse(dialog.actions[1].disabled)
        self.assertIn("4,5", json.dumps([c.value for c in walk(dialog.content) if isinstance(c, ft.Text)],
                                        ensure_ascii=False).replace(".", ","))
        dialog.actions[1].on_click(None)
        self.assertEqual(len(self.created), 1)
        order = storage.load_orders()[0][self.created[0]]
        self.assertEqual(order["items"][self.keys[("", "Câble")]]["Prix"], 4.5)
        self.assertEqual(order["items"][self.keys[("Services", "Commun")]]["quantite"], 2)
        self.assertNotIn("notes", order)
        self.assertEqual(order["photos"], [])
        self.assertTrue(all("note" not in line for line in order["items"].values()))
        self.assertEqual(order["name"], "Nouvelle")

    def test_cancel_writes_nothing(self):
        self.save_template()
        before = storage.orders_path().read_text(encoding="utf-8")
        dialog = self.open_review()
        dialog.actions[0].on_click(None)
        self.assertEqual(storage.orders_path().read_text(encoding="utf-8"), before)
        self.assertEqual(list(self.ctx.orders), ["src"])
        self.assertEqual(self.created, [])

    def test_missing_ambiguous_and_hidden_need_a_choice(self):
        tid, data = self.save_template()
        data[tid]["entries"] += [
            {"key": "XL:Disparu", "catalogue": "", "category": "Divers", "name": "Disparu", "quantite": 1},
            {"key": "XL:Ancien", "catalogue": "", "category": "Divers", "name": "Ancien", "quantite": 1},
            {"key": "XL:Câble (2)", "catalogue": "", "category": "Divers", "name": "Câble", "quantite": 1},
        ]
        templates.save_templates(data)
        hidden_before = set(self.ctx.prefs["hidden"])
        dialog = self.open_review()
        create = dialog.actions[1]
        self.assertTrue(create.disabled)
        # Masqué : inclusion explicite, sans changer la visibilité globale
        buttons(dialog, "Inclure quand même")[0].on_click(None)
        self.assertTrue(create.disabled)
        # Introuvable : retiré explicitement
        removes = buttons(dialog, "Retirer")
        removes[3].on_click(None)
        self.assertTrue(create.disabled)
        # Ambigu : remplacé par un article choisi
        choice = next(b for b in walk(dialog.content) if isinstance(b, ft.TextButton)
                      and str(b.content).startswith("Câble ·"))
        choice.on_click(None)
        self.assertFalse(create.disabled)
        create.on_click(None)
        order = storage.load_orders()[0][self.created[0]]
        self.assertIn("XL:Ancien", order["items"])
        self.assertNotIn("XL:Disparu", order["items"])
        self.assertEqual(order["items"][self.keys[("", "Câble")]]["quantite"], 4)  # 3 + 1 regroupés
        self.assertEqual(self.ctx.prefs["hidden"], hidden_before)
        self.assertEqual(storage.load_prefs([])[0]["hidden"], hidden_before)
        self.assertEqual(templates.load_templates()[0][tid], data[tid])  # modèle inchangé

    def test_catalogue_change_flags_missing_articles(self):
        self.save_template()
        catalogue_mod.install_catalogue("Categorie;Article;Prix\nDivers;Câble;3;\n".encode(), ".csv")
        self.start()
        lines = templates.resolve_template(next(iter(templates.load_templates()[0].values())),
                                           self.ctx.cat["all"], self.ctx.prefs["hidden_catalogues"])
        self.assertEqual([l["status"] for l in lines], ["ok", "missing", "missing"])
        self.assertEqual(lines[0]["article"]["Prix_Unitaire"], 3)

    def test_never_substitutes_custom_or_moved_articles(self):
        entry = {"key": "XL:Câble", "catalogue": "", "category": "Divers", "name": "Câble", "quantite": 1}
        perso = {"Cle": "PERSO:x", "Nom_Article": "Câble", "Catalogue": "", "Categorie": "Divers",
                 "Prix_Unitaire": 1, "Prix_Excel": None, "Perso": True, "Visible": True}
        line = templates.resolve_template({"entries": [entry]}, [perso], set())[0]
        self.assertEqual(line["status"], "missing")
        moved = {**perso, "Cle": "XL:Câble", "Perso": False, "Categorie": "Autre"}
        line = templates.resolve_template({"entries": [entry]}, [moved], set())[0]
        self.assertEqual(line["status"], "ambiguous")
        self.assertIsNone(line["article"])

    def test_all_ambiguous_candidates_are_listed_with_category(self):
        tid, data = self.save_template()
        data[tid]["entries"] = [{"key": "XL:Câble (2)", "catalogue": "", "category": "Divers",
                                 "name": "Câble", "quantite": 1}]
        templates.save_templates(data)
        many = [{"Cle": f"XL:Câble ({n})", "Nom_Article": "Câble", "Catalogue": "", "Categorie": f"Cat {n}",
                 "Prix_Unitaire": 2, "Prix_Excel": 2, "Perso": False, "Visible": True} for n in range(2, 12)]
        self.ctx.cat["all"] += many
        dialog = self.open_review()
        labels = [b.content for b in walk(dialog.content) if isinstance(b, ft.TextButton)
                  and str(b.content).startswith("Câble ·")]
        self.assertEqual(len(labels), 11)
        self.assertEqual(len(set(labels)), 11)

    def test_double_tap_creates_one_order_and_one_template(self):
        asyncio.run(self.ctx.save_template_dialog("src"))
        save = self.page.dialogs[-1].actions[1]
        save.on_click(None)
        save.on_click(None)
        self.assertEqual(len(templates.load_templates()[0]), 1)
        self.page.dialogs.clear()
        create = self.open_review().actions[1]
        create.on_click(None)
        create.on_click(None)
        self.assertEqual(len(self.created), 1)
        self.assertEqual(len(storage.load_orders()[0]), 2)

    def test_failed_delete_keeps_error_visible_and_closes_confirmation(self):
        self.save_template()
        self.page.dialogs.clear()
        asyncio.run(self.ctx.open_template_manager())
        [c for c in walk(self.page.dialogs[-1].content) if isinstance(c, ft.IconButton)][1].on_click(None)
        with unittest.mock.patch.object(templates, "save_templates", side_effect=OSError("disque plein")):
            self.page.dialogs[-1].actions[1].on_click(None)
        kinds = [type(d).__name__ for d in self.page.dialogs]
        self.assertEqual(kinds, ["AlertDialog", "SnackBar"])  # liste des modèles + message, plus de confirmation
        self.assertEqual(self.page.dialogs[0].title.value, "Modèles de commande")
        self.assertEqual(len(templates.load_templates()[0]), 1)

    def test_name_ending_with_number_in_brackets_is_not_ambiguous(self):
        entry = {"key": "XL:Pack (2)", "catalogue": "", "category": "Divers", "name": "Pack (2)", "quantite": 1}
        article = {"Cle": "XL:Pack (2)", "Nom_Article": "Pack (2)", "Catalogue": "", "Categorie": "Divers",
                   "Prix_Unitaire": 5, "Prix_Excel": 5, "Perso": False, "Visible": True}
        self.assertEqual(templates.resolve_template({"entries": [entry]}, [article], set())[0]["status"], "ok")
        duplicate = {**entry, "key": "XL:Câble (2)", "name": "Câble"}
        cable = {**article, "Cle": "XL:Câble", "Nom_Article": "Câble"}
        self.assertEqual(templates.resolve_template({"entries": [duplicate]}, [cable], set())[0]["status"], "ambiguous")

    def test_new_order_dialog_offers_templates_or_hint(self):
        asyncio.run(self.ctx.create_order_dialog())
        hint = [c for c in walk(self.page.dialogs[-1].content) if isinstance(c, ft.Text) and "modèle" in str(c.value)]
        self.assertTrue(hint)
        self.page.dialogs.pop()
        tid, _ = self.save_template()
        asyncio.run(self.ctx.create_order_dialog())
        dialog = self.page.dialogs[-1]
        start = next(c for c in walk(dialog.content) if isinstance(c, ft.Dropdown))
        self.assertEqual(start.value, "__vide__")
        start.value = tid
        dialog.actions[1].on_click(None)
        self.assertIn("Modèle", self.page.dialogs[-1].title.value)
        self.assertEqual(list(self.ctx.orders), ["src"])  # rien de créé avant validation

    def test_empty_start_still_creates_immediately(self):
        self.save_template()
        asyncio.run(self.ctx.create_order_dialog())
        self.page.dialogs[-1].actions[1].on_click(None)
        self.assertEqual(len(self.ctx.orders), 2)

    def test_rename_and_delete_with_confirmation(self):
        tid, _ = self.save_template()
        asyncio.run(self.ctx.open_template_manager())
        manager = self.page.dialogs[-1]
        edit, delete = [c for c in walk(manager.content) if isinstance(c, ft.IconButton)]
        edit.on_click(None)
        rename = self.page.dialogs[-1]
        next(c for c in walk(rename.content) if isinstance(c, ft.TextField)).value = "Bureau"
        rename.actions[1].on_click(None)
        self.assertEqual(templates.load_templates()[0][tid]["name"], "Bureau")
        manager = self.page.dialogs[-1]
        [c for c in walk(manager.content) if isinstance(c, ft.IconButton)][1].on_click(None)
        self.assertIn(tid, templates.load_templates()[0])  # pas encore confirmé
        self.page.dialogs[-1].actions[1].on_click(None)
        self.assertNotIn(tid, templates.load_templates()[0])


if __name__ == "__main__":
    unittest.main()
