import uuid
from datetime import datetime

import flet as ft

if __package__:
    from . import ui, storage
    from .config import ALL_CATALOGUES, DEFAULT_CATALOGUE, DEFAULT_CATALOGUE_LABEL
    from .text import default_order_name
    from .catalogue import build_catalogue, catalogues_of
else:
    import ui
    import storage
    from config import ALL_CATALOGUES, DEFAULT_CATALOGUE, DEFAULT_CATALOGUE_LABEL
    from text import default_order_name
    from catalogue import build_catalogue, catalogues_of


class AppContext:
    """État partagé de l'écran principal et fonctions de base utilisées par tous les écrans.

    Chaque écran ajoute ensuite ses propres widgets et fonctions partagés comme attributs
    (ctx.render_catalogue = render_catalogue). Les sauvegardes passent par le module storage
    (storage.save_orders), pour que les tests puissent le remplacer.
    """

    def __init__(self, page: ft.Page, excel_items: list[dict]) -> None:
        self.page = page
        self.excel_items = excel_items
        self.clipboard = ft.Clipboard()  # service : on garde une référence

        self.startup_warnings = []

        # --- ÉTAT : plusieurs commandes nommées, une seule active à la fois ---
        self.orders, current_id, warning = storage.load_orders()
        if warning:
            self.startup_warnings.append(warning)
        self.migrated = storage.migrate_cart_keys(self.orders)
        self.state = {"current": current_id, "tab": 0, "show_archived": False}
        # Keep presentation state and mounted fields across window/fold transitions.
        self.quantity_drafts = {}
        self.catalogue_grids = []
        self.catalogue_rows = {}
        self.catalogue_cards = {}  # clé d'article → éléments de sa carte (view_catalogue)
        self.favorite_buttons = {}
        self.window = {"layout": ui.WindowLayout(getattr(page, "width", None) or 390,
                                                  getattr(page, "height", None) or 800)}

        # --- RÉGLAGES DU CATALOGUE (articles affichés, prix, articles ajoutés) ---
        self.prefs, warning = storage.load_prefs(excel_items)
        if warning:
            self.startup_warnings.append(warning)
        self.cat = {"all": build_catalogue(excel_items, self.prefs)}

        # Aucune création automatique : s'il n'y a pas encore de commande,
        # l'écran d'aide « Créer une commande » s'affiche à la place du catalogue.
        if self.state["current"] not in self.orders or self.orders[self.state["current"]].get("archived"):
            self.state["current"] = next((k for k in reversed(self.orders) if not self.orders[k].get("archived")), None)

    # Défini en premier : utilisé par les sauvegardes dès le démarrage
    def show_snack(self, message):
        self.page.show_dialog(ft.SnackBar(ui.text(message, color=ft.Colors.ON_INVERSE_SURFACE), duration=ft.Duration(milliseconds=2000)))

    def refresh(self):
        """Envoie toutes les modifications à l'écran.

        Flet 1.0 rafraîchit l'écran tout seul à la fin d'un clic, SAUF si quelque chose a déjà
        été rafraîchi pendant ce clic. Or afficher un message (SnackBar) ou une boîte de dialogue
        le fait : le message apparaissait, mais le panier, le total, le menu… restaient figés.
        On appelle donc refresh() à la fin de chaque action qui affiche un message ou une boîte.
        """
        self.page.update()

    def rebuild_catalogue(self):
        self.cat["all"] = build_catalogue(self.excel_items, self.prefs)

    def entry_by_key(self, key):
        return next((e for e in self.cat["all"] if e["Cle"] == key), None)

    def visible_entries(self):
        return [e for e in self.cat["all"] if e["Visible"] and e["Catalogue"] not in self.prefs["hidden_catalogues"]]

    def new_order(self, name=None):
        order_id = uuid.uuid4().hex[:8]
        self.orders[order_id] = {
            "name": (name or "").strip() or default_order_name(),
            "created": datetime.now().isoformat(timespec="minutes"),
            "items": {},
            "photos": [],
        }
        self.state["current"] = order_id
        return order_id

    def current_order(self):
        return self.orders[self.state["current"]]

    def cart(self):
        return self.current_order()["items"]

    def persist(self):
        try:
            storage.save_orders(self.orders, self.state["current"])
        except OSError as err:
            self.show_snack(f"⚠️ Sauvegarde impossible : {err}")

    def persist_prefs(self):
        try:
            storage.save_prefs(self.prefs)
        except OSError as err:
            self.show_snack(f"⚠️ Sauvegarde des réglages impossible : {err}")

    # --- COMPOSANTS UI ---
    def dialog_width(self):
        return max(160, min(420, (getattr(self.page, "width", None) or 390) - 80))

    def update_catalogue_selector(self, dropdown, include_hidden=False):
        names = catalogues_of(self.cat["all"])
        if include_hidden or not names:
            names = list(dict.fromkeys([DEFAULT_CATALOGUE] + names))
        if not include_hidden:
            names = [name for name in names if name not in self.prefs["hidden_catalogues"]]
        dropdown.options = [ft.DropdownOption(key=name, text=name or DEFAULT_CATALOGUE_LABEL)
                            for name in names]
        choices = names[:]
        if not include_hidden and len(names) > 1:
            choices.append(ALL_CATALOGUES)
            dropdown.options.insert(0, ft.DropdownOption(key=ALL_CATALOGUES, text="Tous les catalogues"))
        if dropdown.value not in choices:
            dropdown.value = names[0] if names else None
        dropdown.visible = len(names) > 1
        dropdown.disabled = not names

    def entries_in(self, catalogue):
        if catalogue == ALL_CATALOGUES:
            return [entry for entry in self.cat["all"] if entry["Catalogue"] not in self.prefs["hidden_catalogues"]]
        return [entry for entry in self.cat["all"] if entry["Catalogue"] == catalogue]

    def managed_catalogues(self):
        return list(dict.fromkeys([DEFAULT_CATALOGUE] + catalogues_of(self.cat["all"])))
