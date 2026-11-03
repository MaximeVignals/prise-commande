import asyncio
import copy
import os
import shutil
import uuid
from datetime import datetime
from pathlib import Path

import flet as ft

if __package__:
    from . import ui, backup
    from .ui import get_category_icon
    from .config import (ALL_CATALOGUES, CATALOGUE_COLUMNS, CATALOGUE_EXTENSIONS, CATALOGUE_STEM, DEFAULT_CATALOGUE,
                         DEFAULT_CATALOGUE_LABEL, KEY_CATALOGUE, KEY_EXCEL, KEY_PERSO, ORDERS_FILENAME, PREFS_FILENAME,
                         REQUIRED_COLUMNS, SAMPLE_CATALOGUE_FILENAME, YES_VALUES)
    from .text import (_is_empty, _to_price, default_order_name, fmt_eur, fmt_input, fold, matches_search,
                       norm_text)
    from .storage import (_set_aside, _valid_iso, assets_dir, load_orders, load_prefs, migrate_cart_keys, orders_path,
                          photo_path, photos_dir, prefs_path, read_json, save_orders, save_prefs, storage_dir,
                          write_json)
    from .orders import duplicate_order, order_count, order_email_text, order_total
    from .photos import build_photos_zip, photo_export_names, photos_summary, safe_filename
    from .catalogue import (CatalogueError, _read_rows, build_catalogue, catalogue_path, catalogues_of, categories_of,
                            install_catalogue, load_catalogue, parse_catalogue, sample_catalogue_path,
                            split_catalogue_category)
    from .import_screen import pick_catalogue_file, request_restore, show_import_screen, skipped_summary
else:
    import ui
    import backup
    from ui import get_category_icon
    from config import (ALL_CATALOGUES, CATALOGUE_COLUMNS, CATALOGUE_EXTENSIONS, CATALOGUE_STEM, DEFAULT_CATALOGUE,
                        DEFAULT_CATALOGUE_LABEL, KEY_CATALOGUE, KEY_EXCEL, KEY_PERSO, ORDERS_FILENAME, PREFS_FILENAME,
                        REQUIRED_COLUMNS, SAMPLE_CATALOGUE_FILENAME, YES_VALUES)
    from text import (_is_empty, _to_price, default_order_name, fmt_eur, fmt_input, fold, matches_search,
                      norm_text)
    from storage import (_set_aside, _valid_iso, assets_dir, load_orders, load_prefs, migrate_cart_keys, orders_path,
                         photo_path, photos_dir, prefs_path, read_json, save_orders, save_prefs, storage_dir,
                         write_json)
    from orders import duplicate_order, order_count, order_email_text, order_total
    from photos import build_photos_zip, photo_export_names, photos_summary, safe_filename
    from catalogue import (CatalogueError, _read_rows, build_catalogue, catalogue_path, catalogues_of, categories_of,
                           install_catalogue, load_catalogue, parse_catalogue, sample_catalogue_path,
                           split_catalogue_category)
    from import_screen import pick_catalogue_file, request_restore, show_import_screen, skipped_summary

try:
    # Appareil photo intégré (Android) : extension officielle flet-camera.
    # Absente (ex. « flet run » sur PC sans l'extension) → seul l'import de photos est proposé.
    import flet_camera as fc
except ImportError:
    fc = None

# --- FONCTIONS DE NETTOYAGE ET UTILITAIRES ---


# --- APPLICATION PRINCIPALE FLET ---


def reset_page(page):
    """Repart d'un écran vide : main() peut être relancé sur la même page (import au premier
    lancement, restauration, reprise Android). Sans ça, l'ancien écran reste et tout apparaît en double."""
    while len(page.views) > 1:
        page.views.pop()
    page.controls.clear()
    page.overlay.clear()
    page.appbar = page.drawer = None


def main(page: ft.Page):
    reset_page(page)
    page.title = "Prise de Commande"
    ui.configure_page(page)

    excel_items = load_catalogue()
    clipboard = ft.Clipboard()  # service : on garde une référence

    if not excel_items:
        show_import_screen(page)
        return

    # Défini en premier : utilisé par les sauvegardes dès le démarrage
    def show_snack(message):
        page.show_dialog(ft.SnackBar(ui.text(message, color=ft.Colors.ON_INVERSE_SURFACE), duration=ft.Duration(milliseconds=2000)))

    def refresh():
        """Envoie toutes les modifications à l'écran.

        Flet 1.0 rafraîchit l'écran tout seul à la fin d'un clic, SAUF si quelque chose a déjà
        été rafraîchi pendant ce clic. Or afficher un message (SnackBar) ou une boîte de dialogue
        le fait : le message apparaissait, mais le panier, le total, le menu… restaient figés.
        On appelle donc refresh() à la fin de chaque action qui affiche un message ou une boîte.
        """
        page.update()

    startup_warnings = []

    # --- ÉTAT : plusieurs commandes nommées, une seule active à la fois ---
    orders, current_id, warning = load_orders()
    if warning:
        startup_warnings.append(warning)
    migrated = migrate_cart_keys(orders)
    state = {"current": current_id, "tab": 0, "show_archived": False}
    # Keep presentation state and mounted fields across window/fold transitions.
    quantity_drafts = {}
    catalogue_grids = []
    catalogue_rows = {}
    catalogue_badges = {}
    favorite_buttons = {}
    window = {"layout": ui.WindowLayout(getattr(page, "width", None) or 390,
                                         getattr(page, "height", None) or 800)}

    # --- RÉGLAGES DU CATALOGUE (articles affichés, prix, articles ajoutés) ---
    prefs, warning = load_prefs(excel_items)
    if warning:
        startup_warnings.append(warning)
    cat = {"all": build_catalogue(excel_items, prefs)}

    def rebuild_catalogue():
        cat["all"] = build_catalogue(excel_items, prefs)

    def entry_by_key(key):
        return next((e for e in cat["all"] if e["Cle"] == key), None)

    def visible_entries():
        return [e for e in cat["all"] if e["Visible"] and e["Catalogue"] not in prefs["hidden_catalogues"]]

    def new_order(name=None):
        order_id = uuid.uuid4().hex[:8]
        orders[order_id] = {
            "name": (name or "").strip() or default_order_name(),
            "created": datetime.now().isoformat(timespec="minutes"),
            "items": {},
            "photos": [],
        }
        state["current"] = order_id
        return order_id

    # Aucune création automatique : s'il n'y a pas encore de commande,
    # l'écran d'aide « Créer une commande » s'affiche à la place du catalogue.
    if state["current"] not in orders or orders[state["current"]].get("archived"):
        state["current"] = next((k for k in reversed(orders) if not orders[k].get("archived")), None)

    def current_order():
        return orders[state["current"]]

    def cart():
        return current_order()["items"]

    def persist():
        try:
            save_orders(orders, state["current"])
        except OSError as err:
            show_snack(f"⚠️ Sauvegarde impossible : {err}")

    def persist_prefs():
        try:
            save_prefs(prefs)
        except OSError as err:
            show_snack(f"⚠️ Sauvegarde des réglages impossible : {err}")

    # --- COMPOSANTS UI ---
    def dialog_width():
        return max(160, min(420, (getattr(page, "width", None) or 390) - 80))

    def update_catalogue_selector(dropdown, include_hidden=False):
        names = catalogues_of(cat["all"])
        if include_hidden or not names:
            names = list(dict.fromkeys([DEFAULT_CATALOGUE] + names))
        if not include_hidden:
            names = [name for name in names if name not in prefs["hidden_catalogues"]]
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

    def entries_in(catalogue):
        if catalogue == ALL_CATALOGUES:
            return [entry for entry in cat["all"] if entry["Catalogue"] not in prefs["hidden_catalogues"]]
        return [entry for entry in cat["all"] if entry["Catalogue"] == catalogue]

    def managed_catalogues():
        return list(dict.fromkeys([DEFAULT_CATALOGUE] + catalogues_of(cat["all"])))

    async def on_catalogue_filter(e=None):
        render_catalogue()
        refresh()
        await catalogue_listview.scroll_to(offset=0)  # résultats affichés depuis le début

    async def on_catalogue_select(e=None):
        category_dropdown.value = "Toutes"
        await on_catalogue_filter()

    catalogue_dropdown = ui.dropdown(
        label="Catalogue", options=[], on_select=on_catalogue_select, expand=True,
    )

    search_input = ui.field(
        label="Rechercher",
        hint_text="Un article, une référence…",
        prefix_icon=ft.Icons.SEARCH,
        on_change=on_catalogue_filter,
        expand=3,
    )

    category_dropdown = ui.dropdown(
        label="Catégorie",
        options=[],
        value="Toutes",
        on_select=on_catalogue_filter,
        expand=2,
    )
    browse_mode = ft.SegmentedButton(
        segments=[ft.Segment(value="all", label="Tous"),
                  ft.Segment(value="favorites", label="Favoris"),
                  ft.Segment(value="recent", label="Récents")],
        selected=["all"], allow_empty_selection=False, show_selected_icon=False,
        on_change=on_catalogue_filter, expand=True,
    )
    filter_tags = ft.Row([], spacing=6, scroll=ft.ScrollMode.AUTO, visible=False)

    catalogue_listview = ft.ListView(expand=True, spacing=6, padding=ft.Padding.only(bottom=12))
    cart_listview = ft.ListView(expand=True, spacing=6, padding=ft.Padding.only(bottom=12))
    catalogue_info = ui.text("", size=12, color=ui.MUTED)
    total_text = ui.text(fmt_eur(0), size=26, weight=ft.FontWeight.W_600, color=ui.PRIMARY)
    cart_info = ui.text("", size=12, color=ui.MUTED)
    order_info = ui.text("", size=12, color=ui.MUTED)

    # Titre de la barre du haut = nom de la commande active
    appbar_title = ui.text("", max_lines=1, overflow=ft.TextOverflow.ELLIPSIS,
                           weight=ft.FontWeight.W_600)
    # Menu latéral (comme la liste des conversations de Claude) : rempli par render_orders()
    drawer = ft.NavigationDrawer(controls=[], selected_index=-1, bgcolor=ui.PANEL)

    # --- LOGIQUE ---

    def go_to_tab(index):
        state["tab"] = index
        navigation.selected_index = index
        layout_workspace()

    def add_to_cart(item, qty):
        try:
            qty = int(qty)
        except (TypeError, ValueError):
            show_snack("Quantité invalide.")
            return
        if qty <= 0:
            show_snack("Quantité invalide.")
            return

        items = cart()
        if item["Cle"] in items:
            items[item["Cle"]]["quantite"] += qty
        else:
            items[item["Cle"]] = {
                "Nom": item["Nom_Article"],
                "Prix": item["Prix_Unitaire"],
                "quantite": qty,
            }
        persist()
        prefs["recent"] = [item["Cle"]] + [key for key in prefs["recent"] if key != item["Cle"]][:19]
        persist_prefs()
        if browse_mode.selected == ["recent"]:
            render_catalogue()
        render_all()
        show_snack(f"✅ Ajouté au panier (x{qty})")
        refresh()

    def change_qty_field(field, delta):
        try:
            current = int(field.value)
        except (TypeError, ValueError):
            current = 1
        field.value = str(max(1, current + delta))

    def update_cart_qty(id_art, delta):
        items = cart()
        if id_art not in items:
            return
        if items[id_art]["quantite"] + delta <= 0:
            remove_cart_line(id_art)  # « − » sur une quantité de 1 : retire la ligne (annulable)
            return
        items[id_art]["quantite"] += delta
        persist()
        render_all()
        refresh()

    def remove_cart_line(id_art):
        """Retire une ligne du panier, avec « Annuler » dans le message pendant 8 secondes."""
        order_id = state["current"]
        items = cart()
        if id_art not in items:
            return
        position = list(items).index(id_art)
        line = items.pop(id_art)
        persist()
        render_all()

        def undo(e):
            if order_id not in orders or id_art in orders[order_id]["items"]:
                return
            restored = list(orders[order_id]["items"].items())
            restored.insert(position, (id_art, line))
            orders[order_id]["items"].clear()
            orders[order_id]["items"].update(restored)
            persist()
            render_all()
            refresh()

        page.show_dialog(ft.SnackBar(
            ui.text("🗑️ Ligne retirée du panier.", color=ft.Colors.ON_INVERSE_SURFACE),
            action="Annuler",
            on_action=undo,
            persist=False,
            duration=ft.Duration(seconds=8),  # le temps de toucher « Annuler »
        ))
        refresh()

    def set_cart_qty(id_art, field, subtotal_text, final):
        """Quantité tapée au clavier. Enregistrée à chaque chiffre ; à la sortie du champ,
        une saisie vide ou à 0 est annulée (pour retirer une ligne : la corbeille)."""
        items = cart()
        if id_art not in items:
            return
        try:
            qty = int(field.value)
        except (TypeError, ValueError):
            qty = 0
        if qty > 0:
            if qty != items[id_art]["quantite"]:
                items[id_art]["quantite"] = qty
                persist()
                subtotal_text.value = fmt_eur(items[id_art]["Prix"] * qty)
                update_cart_summary()
                render_orders()
            if final:
                field.value = str(qty)
        elif final:
            field.value = str(items[id_art]["quantite"])
            show_snack("Quantité invalide. Pour retirer la ligne, utilisez la corbeille.")
        refresh()

    def clear_cart(e):
        order = current_order()
        if not order["items"]:
            show_snack("Le panier est déjà vide.")
            refresh()
            return

        def confirm(e):
            page.pop_dialog()
            if not order["items"]:  # double appui
                return
            order["items"].clear()
            persist()
            render_all()
            show_snack("🗑️ Panier vidé.")
            refresh()

        page.show_dialog(ft.AlertDialog(
            scrollable=True,
            modal=True,
            title=ui.text("Vider le panier ?"),
            content=ui.text(
                f"Les {order_count(order)} article(s) de « {order['name']} » "
                f"({fmt_eur(order_total(order))}) seront retirés."
            ),
            actions=[
                ft.TextButton(content="Annuler", on_click=lambda e: page.pop_dialog()),
                ui.button(content="Vider", on_click=confirm,
                          style=ft.ButtonStyle(bgcolor=ft.Colors.ERROR, color=ft.Colors.ON_ERROR)),
            ],
        ))

    async def copy_email_text(e):
        order = current_order()
        if not order["items"]:
            show_snack("Le panier est vide.")
            return

        await clipboard.set(order_email_text(order))
        show_snack("📋 Texte copié dans le presse-papiers !")

    # --- GESTION DES COMMANDES ---

    async def open_drawer(e=None):
        await page.show_drawer()

    async def close_drawer():
        await page.close_drawer()

    async def select_order(order_id):
        if order_id not in orders:
            return
        state["current"] = order_id
        persist()
        render_all()
        await close_drawer()
        show_snack(f"Commande active : {orders[order_id]['name']}")
        refresh()

    def ask_name(title, initial, on_ok):
        """Petite boîte de dialogue avec un champ texte (création / renommage)."""
        name_field = ui.field(
            value=initial,
            label="Nom de la commande",
            hint_text="ex. Cabinet Dupont – salle 2",
            autofocus=True,
            capitalization=ft.TextCapitalization.SENTENCES,
        )

        def validate(e=None):
            page.pop_dialog()
            on_ok(name_field.value)
            refresh()

        name_field.on_submit = validate
        page.show_dialog(ft.AlertDialog(
            scrollable=True,
            modal=True,
            title=ui.text(title),
            content=name_field,
            actions=[
                ft.TextButton(content="Annuler", on_click=lambda e: page.pop_dialog()),
                ui.button(content="Valider", on_click=validate),
            ],
        ))

    async def create_order_dialog(e=None):
        await close_drawer()

        def done(name):
            new_order(name)
            state["show_archived"] = False
            persist()
            render_all()
            go_to_tab(0)  # retour au catalogue pour remplir la nouvelle commande
            show_snack(f"🆕 Nouvelle commande : {current_order()['name']}")

        ask_name("Nouvelle commande", default_order_name(), done)

    async def rename_order_dialog(order_id):
        await close_drawer()

        def done(name):
            name = name.strip()
            if name and order_id in orders:
                orders[order_id]["name"] = name
                persist()
                render_all()

        ask_name("Renommer la commande", orders[order_id]["name"], done)

    async def duplicate_order_dialog(order_id):
        await close_drawer()

        def done(name):
            new_id = None
            try:
                new_id, duplicate = duplicate_order(order_id, orders[order_id], name, orders)
                save_orders({**orders, new_id: duplicate}, new_id)
            except OSError as err:
                if new_id:
                    folder = photos_dir(new_id)
                    for path in folder.glob("*"):
                        path.unlink()
                    if folder.exists():
                        folder.rmdir()
                show_snack(f"Duplication impossible : {err}")
                return
            orders[new_id] = duplicate
            state.update(current=new_id, show_archived=False)
            render_all()
            go_to_tab(0)
            show_snack("Commande dupliquée, avec ses remarques et photos.")

        ask_name("Dupliquer la commande", f"{orders[order_id]['name']} — copie", done)

    async def archive_order(order_id):
        await close_drawer()
        updated = copy.deepcopy(orders)
        archived = not updated[order_id].get("archived", False)
        if archived:
            updated[order_id]["archived"] = True
        else:
            updated[order_id].pop("archived", None)
        selected = state["current"]
        if archived and selected == order_id:
            selected = next((k for k in reversed(updated) if not updated[k].get("archived")), None)
        elif not archived:
            selected = order_id
        try:
            save_orders(updated, selected)
        except OSError as err:
            show_snack(f"Archivage impossible : {err}")
            refresh()
            return
        orders.clear()
        orders.update(updated)
        state["current"] = selected
        state["show_archived"] = archived
        render_all()
        show_snack("Commande archivée." if archived else "Commande réactivée.")
        refresh()

    def show_order_group(e=None):
        state["show_archived"] = not state["show_archived"]
        render_orders()

    def edit_notes(e=None, key=None):
        order = current_order()
        target = order if key is None else order["items"][key]
        attribute = "notes" if key is None else "note"
        field = ui.field(label="Remarques", value=target.get(attribute, ""),
            hint_text="Livraison, installation, matériel à remplacer…", multiline=True,
            min_lines=3, max_lines=6, autofocus=True, capitalization=ft.TextCapitalization.SENTENCES)

        def save(e=None):
            value = (field.value or "").strip()
            previous = target.get(attribute)
            if value:
                target[attribute] = value
            else:
                target.pop(attribute, None)
            try:
                save_orders(orders, state["current"])
            except OSError as err:
                if previous is None:
                    target.pop(attribute, None)
                else:
                    target[attribute] = previous
                field.error = f"Enregistrement impossible : {err}"
                refresh()
                return
            page.pop_dialog()
            render_all()
            refresh()

        page.show_dialog(ft.AlertDialog(scrollable=True, title=ui.text(
            "Remarques de la commande" if key is None else target["Nom"]),
            content=ft.Container(content=field, width=dialog_width()),
            actions=[ft.TextButton(content="Annuler", on_click=lambda e: page.pop_dialog()),
                     ui.button(content="Enregistrer", on_click=save)]))

    async def delete_order_dialog(order_id):
        await close_drawer()
        order = orders[order_id]

        def confirm(e):
            page.pop_dialog()
            if order_id not in orders:  # double appui sur « Supprimer »
                return
            del orders[order_id]
            shutil.rmtree(photos_dir(order_id), ignore_errors=True)  # ses photos aussi
            if state["current"] == order_id:
                # la plus récente restante, ou aucune → écran d'aide
                state["current"] = next((k for k in reversed(orders) if not orders[k].get("archived")), None)
            persist()
            render_all()
            show_snack(f"🗑️ « {order['name']} » supprimée.")
            refresh()

        page.show_dialog(ft.AlertDialog(
            scrollable=True,
            modal=True,
            title=ui.text("Supprimer la commande ?"),
            content=ui.text(
                f"« {order['name']} » ({order_count(order)} article(s), "
                f"{fmt_eur(order_total(order))}) sera définitivement supprimée."
                + (f"\nSes {len(order.get('photos', []))} photo(s) aussi."
                   if order.get("photos") else "")
            ),
            actions=[
                ft.TextButton(content="Annuler", on_click=lambda e: page.pop_dialog()),
                ui.button(
                    content="Supprimer",
                    on_click=confirm,
                    style=ft.ButtonStyle(bgcolor=ft.Colors.ERROR, color=ft.Colors.ON_ERROR),
                ),
            ],
        ))

    # --- RENDU CATALOGUE ---
    def render_catalogue():
        catalogue_listview.controls.clear()
        catalogue_grids.clear()
        catalogue_rows.clear()
        catalogue_badges.clear()
        favorite_buttons.clear()
        previous_catalogue = catalogue_dropdown.value
        update_catalogue_selector(catalogue_dropdown)
        if catalogue_dropdown.value != previous_catalogue:
            category_dropdown.value = "Toutes"
        has_catalogue = catalogue_dropdown.value is not None
        search_input.disabled = not has_catalogue
        category_dropdown.disabled = not has_catalogue
        shown = [entry for entry in entries_in(catalogue_dropdown.value) if entry["Visible"]]
        categories = categories_of(shown)

        # Filtre : seules les catégories qui ont au moins un article affiché
        category_dropdown.options = [ft.DropdownOption(key=c, text=c) for c in ["Toutes"] + sorted(categories)]
        if category_dropdown.value not in categories:
            category_dropdown.value = "Toutes"

        search_val = search_input.value or ""
        cat_val = category_dropdown.value

        filtered = [
            it for it in shown
            if matches_search(it["Nom_Article"], search_val)
            and (cat_val == "Toutes" or it["Categorie"] == cat_val)
        ]
        mode = (browse_mode.selected or ["all"])[0]
        if mode == "favorites":
            filtered = [it for it in filtered if it["Cle"] in prefs["favorites"]]
        elif mode == "recent":
            filtered = sorted((it for it in filtered if it["Cle"] in prefs["recent"]),
                              key=lambda it: prefs["recent"].index(it["Cle"]))
        # Recents keep chronological order instead of being regrouped by category.
        groups = [("Articles récents", filtered)] if mode == "recent" else [
            (category, [it for it in filtered if it["Categorie"] == category]) for category in categories]
        catalogue_info.value = f"{len(filtered)} article(s) · {len(categories_of(filtered))} catégorie(s)"
        render_filter_tags()

        if not has_catalogue:
            catalogue_listview.controls.extend([
                ui.text("Aucun catalogue affiché. Activez un catalogue pour parcourir ses articles.",
                        italic=True, color=ft.Colors.ON_SURFACE_VARIANT),
                ft.TextButton(content="Gérer les catalogues", on_click=open_catalogue_manager),
            ])
        elif not shown:
            catalogue_listview.controls.append(ui.text(
                "Aucun article affiché.\nCochez des articles dans ☰ › Gérer les articles.",
                italic=True, color=ft.Colors.ON_SURFACE_VARIANT,
            ))
        elif not filtered:
            title, description = "Aucun article ne correspond.", "Essayez un autre mot ou réinitialisez les filtres."
            if mode == "favorites":
                title, description = "Aucun favori dans cette sélection", "Touchez l'étoile d'un article pour le retrouver ici."
            elif mode == "recent":
                title, description = "Aucun article récent dans cette sélection", "Les derniers articles ajoutés au panier apparaîtront ici."
            catalogue_listview.controls.append(ui.empty(
                ft.Icons.SEARCH_OFF, title, description,
                ft.TextButton(content="Réinitialiser les filtres", on_click=reset_filters),
            ))

        for categorie, group in groups:
            if not group:
                continue

            # En-tête de catégorie
            catalogue_listview.controls.append(
                ft.Container(
                    content=ft.Row([
                        ft.Icon(get_category_icon(categorie), size=20, color=ui.PRIMARY),
                        ui.text(categorie, size=16, weight=ft.FontWeight.W_600, expand=True),
                        ui.text(str(len(group)), size=12, color=ui.MUTED),
                    ], spacing=10),
                    padding=ft.Padding.symmetric(vertical=4, horizontal=4),
                    margin=ft.Margin.only(top=2),
                )
            )

            # The grid responds to the pane width, including resized windows.
            group_cards = []
            for current_item in group:
                draft_key = (state["current"], current_item["Cle"])
                qty_field = ui.field(
                    value=quantity_drafts.get(draft_key, "1"), width=64, text_align=ft.TextAlign.CENTER,
                    keyboard_type=ft.KeyboardType.NUMBER,
                    input_filter=ft.NumbersOnlyInputFilter(),
                    dense=True, tooltip=f"Quantité à ajouter : {current_item['Nom_Article']}",
                    on_change=lambda e, k=draft_key: quantity_drafts.__setitem__(k, e.control.value),
                )
                def adjust(e, q=qty_field, k=draft_key, delta=1):
                    change_qty_field(q, delta)
                    quantity_drafts[k] = q.value

                # Flèches ▼ / ▲ pour ajuster la quantité à ajouter (minimum 1)
                btn_down = ft.IconButton(
                    icon=ft.Icons.REMOVE,
                    tooltip="Diminuer",
                    width=48, height=48,
                    on_click=lambda e, fn=adjust: fn(e, delta=-1),
                )
                btn_up = ft.IconButton(
                    icon=ft.Icons.ADD,
                    tooltip="Augmenter",
                    width=48, height=48, on_click=adjust,
                )

                add_btn = ft.IconButton(
                    icon=ft.Icons.ADD_SHOPPING_CART,
                    icon_color=ft.Colors.ON_PRIMARY,
                    bgcolor=ui.PRIMARY, width=48, height=48,
                    tooltip=f"Ajouter au panier : {current_item['Nom_Article']}",
                    on_click=lambda e, item=current_item, q=qty_field: add_to_cart(item, q.value),
                )
                qty_field.on_submit = add_btn.on_click

                name = ui.text(current_item["Nom_Article"], size=15, weight=ft.FontWeight.W_600)
                favorite = ft.IconButton(
                    icon=ft.Icons.STAR if current_item["Cle"] in prefs["favorites"] else ft.Icons.STAR_BORDER,
                    icon_color=ui.PRIMARY, width=48, height=48,
                    tooltip=f"Favori : {current_item['Nom_Article']}",
                    on_click=lambda e, k=current_item["Cle"]: toggle_favorite(k),
                )
                favorite_buttons[current_item["Cle"]] = favorite
                badge = ui.text("", size=12, color=ui.PRIMARY, visible=False)
                catalogue_badges[current_item["Cle"]] = badge
                origin = ui.text(current_item["Catalogue"] or "Catalogue principal", size=11, color=ui.MUTED,
                                 visible=catalogue_dropdown.value == ALL_CATALOGUES)
                description = ft.Column([name, origin, badge], spacing=2, tight=True)
                price = ui.text(fmt_eur(current_item['Prix_Unitaire']), color=ui.PRIMARY,
                                size=16, weight=ft.FontWeight.W_600)
                actions = ft.Row([btn_down, qty_field, btn_up, add_btn], spacing=0, tight=True)
                compact = ft.Column([
                    ft.Row([ft.Container(content=description, expand=True), favorite], spacing=4),
                    ft.Row([price, actions], alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                           wrap=True, spacing=8, run_spacing=4),
                ], spacing=4, tight=True)
                wide = ft.Row([
                    ft.Column([description, ft.Row([price, favorite], spacing=4, wrap=True)],
                              spacing=2, tight=True, expand=True),
                    actions,
                ], spacing=12)
                card = ui.item_card(compact)
                catalogue_rows[id(card)] = (compact, wide)
                group_cards.append(card)
            grid = ft.ResponsiveRow(group_cards, spacing=8, run_spacing=8)
            catalogue_grids.append(grid)
            catalogue_listview.controls.append(grid)
        apply_catalogue_columns()
        update_catalogue_badges()
        state["catalogue_order"] = state["current"]
        # Plus besoin de page.update() : Flet 1.0 met à jour automatiquement
        # après chaque gestionnaire d'événement et après main().

    def reset_filters(e=None):
        search_input.value = ""
        category_dropdown.value = "Toutes"
        browse_mode.selected = ["all"]
        render_catalogue()
        refresh()

    def toggle_favorite(key):
        previous = set(prefs["favorites"])
        if key in prefs["favorites"]:
            prefs["favorites"].remove(key)
        else:
            prefs["favorites"].add(key)
        try:
            save_prefs(prefs)
        except OSError as err:
            prefs["favorites"] = previous
            show_snack(f"Favori non enregistré : {err}")
            refresh()
            return
        if browse_mode.selected == ["favorites"]:
            render_catalogue()
        else:
            favorite_buttons[key].icon = ft.Icons.STAR if key in prefs["favorites"] else ft.Icons.STAR_BORDER
        refresh()

    def update_catalogue_badges():
        items = cart() if state["current"] else {}
        for key, badge in catalogue_badges.items():
            quantity = items.get(key, {}).get("quantite", 0)
            badge.value = f"Déjà {quantity} dans la commande" if quantity else ""
            badge.visible = quantity > 0

    def render_filter_tags():
        tags = []
        def clear(attribute, value):
            setattr(attribute, "value", value)
            render_catalogue()
            refresh()
        if catalogue_dropdown.visible:
            value = catalogue_dropdown.value
            tags.append(ft.Chip(label=(value or "Catalogue principal") if value != ALL_CATALOGUES else "Tous les catalogues",
                on_click=lambda e: toggle_filters(),
                on_delete=(lambda e: clear(catalogue_dropdown, ALL_CATALOGUES)) if value != ALL_CATALOGUES else None,
                delete_icon_tooltip="Rechercher dans tous les catalogues"))
        if category_dropdown.value != "Toutes":
            tags.append(ft.Chip(label=category_dropdown.value, on_delete=lambda e: clear(category_dropdown, "Toutes"),
                                delete_icon_tooltip="Retirer le filtre de catégorie"))
        if search_input.value:
            tags.append(ft.Chip(label=f"Recherche : {search_input.value[:40]}",
                on_delete=lambda e: clear(search_input, ""), delete_icon_tooltip="Effacer la recherche"))
        filter_tags.controls = tags
        filter_tags.visible = bool(tags)

    # --- RENDU PANIER ---
    def render_cart():
        cart_listview.controls.clear()
        items = cart()

        if not items:
            cart_listview.controls.append(ui.empty(
                ft.Icons.SHOPPING_BAG_OUTLINED, "Votre panier est prêt",
                "Ajoutez des articles du catalogue pour préparer votre commande.",
                ft.TextButton(content="Parcourir le catalogue", icon=ft.Icons.ARROW_FORWARD,
                              on_click=lambda e: go_to_tab(0)),
            ))
        else:
            for id_art, item in items.items():
                sous_total = item["Prix"] * item["quantite"]
                subtotal_text = ui.text(fmt_eur(sous_total), weight=ft.FontWeight.BOLD,
                                        color=ui.PRIMARY)

                # Quantité modifiable au clavier, ou avec − / +
                qty_field = ui.field(
                    value=str(item["quantite"]), width=64, dense=True,
                    text_align=ft.TextAlign.CENTER,
                    keyboard_type=ft.KeyboardType.NUMBER,
                    input_filter=ft.NumbersOnlyInputFilter(),
                    tooltip="Quantité",
                )
                qty_field.on_change = lambda e, i=id_art, f=qty_field, t=subtotal_text: set_cart_qty(i, f, t, False)
                qty_field.on_blur = lambda e, i=id_art, f=qty_field, t=subtotal_text: set_cart_qty(i, f, t, True)
                qty_field.on_submit = lambda e, i=id_art, f=qty_field, t=subtotal_text: set_cart_qty(i, f, t, True)

                btn_minus = ft.IconButton(icon=ft.Icons.REMOVE, tooltip="Diminuer", width=48, height=48,
                                          on_click=lambda e, i=id_art: update_cart_qty(i, -1))
                btn_plus = ft.IconButton(icon=ft.Icons.ADD, tooltip="Augmenter", width=48, height=48,
                                         on_click=lambda e, i=id_art: update_cart_qty(i, 1))
                btn_delete = ft.IconButton(icon=ft.Icons.DELETE_OUTLINE, icon_color=ft.Colors.ERROR,
                                           tooltip="Retirer du panier",
                                           width=48, height=48,
                                           on_click=lambda e, i=id_art: remove_cart_line(i))
                btn_note = ft.IconButton(icon=ft.Icons.NOTES, width=48, height=48,
                    icon_color=ui.PRIMARY if item.get("note") else ui.MUTED,
                    tooltip=f"Remarque : {item['Nom']}", on_click=lambda e, k=id_art: edit_notes(key=k))

                cart_listview.controls.append(
                    ui.item_card(
                        content=ft.Column([
                            ft.Row([
                                ui.text(item["Nom"], weight=ft.FontWeight.W_500, expand=True),
                                subtotal_text,
                            ], vertical_alignment=ft.CrossAxisAlignment.START),
                            ui.text(item.get("note", ""), size=12, color=ui.MUTED, visible=bool(item.get("note"))),
                            ft.Row([
                                ui.text(f"{fmt_eur(item['Prix'])} / unité", size=12, color=ui.MUTED),
                                ft.Row([btn_minus, qty_field, btn_plus, btn_note, btn_delete], spacing=0, tight=True),
                            ], alignment=ft.MainAxisAlignment.SPACE_BETWEEN, wrap=True, spacing=8, run_spacing=4),
                        ], spacing=4, tight=True),
                    )
                )

        update_cart_summary()

    def update_cart_summary():
        """Total en bas du panier et nombre d'articles dans l'onglet « Panier »."""
        order = current_order()
        total_text.value = fmt_eur(order_total(order))
        n = order_count(order)
        cart_tab.label = f"Panier ({n})" if n else "Panier"
        cart_info.value = f"{n} article(s) · {len(order['items'])} référence(s)"
        order_info.value = f"{n} article(s) · {fmt_eur(order_total(order))}"
        compact_cart_btn.content = f"{n} article(s) · {fmt_eur(order_total(order))}"
        notes_preview.value = current_order().get("notes", "")
        notes_preview.visible = bool(notes_preview.value)
        archive_banner.visible = bool(order.get("archived"))
        copy_order_btn.disabled = not bool(order["items"])
        clear_order_btn.disabled = not bool(order["items"])
        update_catalogue_badges()

    # --- RENDU DU MENU LATÉRAL (liste des commandes) ---
    def order_handlers(order_id):
        """Crée les actions d'une ligne de commande (sélection, renommer, supprimer)."""
        async def on_select(e):
            await select_order(order_id)

        async def on_rename(e):
            await rename_order_dialog(order_id)

        async def on_delete(e):
            await delete_order_dialog(order_id)

        async def on_duplicate(e):
            await duplicate_order_dialog(order_id)

        async def on_archive(e):
            await archive_order(order_id)

        async def on_notes(e):
            await select_order(order_id)
            edit_notes()

        return on_select, on_rename, on_delete, on_duplicate, on_archive, on_notes

    def render_orders():
        n_total = len(cat["all"])
        n_visible = len(visible_entries())
        names = managed_catalogues()
        n_catalogues_visible = sum(name not in prefs["hidden_catalogues"] for name in names)
        controls = [
            ft.Container(
                padding=ft.Padding.only(left=16, right=16, top=16, bottom=8),
                content=ft.Row([
                    ft.Icon(ft.Icons.RECEIPT_LONG, color=ft.Colors.PRIMARY),
                    ui.text("Prise de Commande", size=18, weight=ft.FontWeight.BOLD,
                            color=ft.Colors.PRIMARY),
                ]),
            ),
            ft.Container(
                padding=ft.Padding.symmetric(horizontal=12, vertical=4),
                content=ft.Row([
                    ui.button(
                        content="Nouvelle commande",
                        icon=ft.Icons.EDIT_SQUARE,
                        on_click=create_order_dialog,
                        style=ft.ButtonStyle(bgcolor=ft.Colors.PRIMARY, color=ft.Colors.ON_PRIMARY),
                        expand=True,
                    ),
                ]),
            ),
            ft.Container(
                padding=ft.Padding.symmetric(horizontal=8),
                content=ft.ListTile(
                    dense=True,
                    shape=ft.RoundedRectangleBorder(radius=10),
                    leading=ft.Icon(ft.Icons.FOLDER_OUTLINED, color=ft.Colors.PRIMARY),
                    title=ui.text("Gérer les catalogues", weight=ft.FontWeight.W_500),
                    subtitle=ui.text(f"{n_catalogues_visible} affichés sur {len(names)}", size=12),
                    on_click=open_catalogue_manager,
                ),
            ),
            ft.Container(
                padding=ft.Padding.symmetric(horizontal=8),
                content=ft.ListTile(
                    dense=True,
                    shape=ft.RoundedRectangleBorder(radius=10),
                    leading=ft.Icon(ft.Icons.TUNE, color=ft.Colors.PRIMARY),
                    title=ui.text("Gérer les articles", weight=ft.FontWeight.W_500),
                    subtitle=ui.text(f"{n_visible} affichés sur {n_total}", size=12),
                    on_click=open_admin,
                ),
            ),
            ft.Container(
                padding=ft.Padding.symmetric(horizontal=8),
                content=ft.ListTile(
                    dense=True,
                    shape=ft.RoundedRectangleBorder(radius=10),
                    leading=ft.Icon(ft.Icons.UPLOAD_FILE, color=ft.Colors.PRIMARY),
                    title=ui.text("Importer un catalogue", weight=ft.FontWeight.W_500),
                    subtitle=ui.text("Remplace le catalogue actuel (.xlsx ou .csv)", size=12),
                    on_click=replace_catalogue,
                ),
            ),
            ft.Divider(height=1),
            ft.Container(
                padding=ft.Padding.only(left=16, top=12, bottom=4),
                content=ui.text("Commandes", size=12, weight=ft.FontWeight.W_600,
                                color=ft.Colors.ON_SURFACE_VARIANT),
            ),
        ]

        if not orders:
            controls.append(ft.Container(
                padding=ft.Padding.symmetric(horizontal=16, vertical=8),
                content=ui.text(
                    "Aucune commande pour l'instant.\n"
                    "Appuyez sur « Nouvelle commande » pour commencer.",
                    size=13, italic=True, color=ft.Colors.ON_SURFACE_VARIANT,
                ),
            ))

        # Les plus récentes en premier (le dict garde l'ordre de création)
        for order_id in reversed(list(orders)):
            order = orders[order_id]
            if bool(order.get("archived")) != state["show_archived"]:
                continue
            is_active = order_id == state["current"]
            created = datetime.fromisoformat(order["created"]).strftime("%d/%m")
            on_select, on_rename, on_delete, on_duplicate, on_archive, on_notes = order_handlers(order_id)

            controls.append(
                ft.Container(
                    padding=ft.Padding.symmetric(horizontal=8),
                    content=ft.ListTile(
                        dense=True,
                        shape=ft.RoundedRectangleBorder(radius=10),
                        title=ui.text(
                            order["name"], max_lines=1, overflow=ft.TextOverflow.ELLIPSIS,
                            weight=ft.FontWeight.BOLD if is_active else ft.FontWeight.NORMAL,
                        ),
                        subtitle=ui.text(
                            f"{created} · {order_count(order)} art. · {fmt_eur(order_total(order))}"
                            + (f" · 📷 {len(order['photos'])}" if order.get("photos") else ""),
                            size=12,
                        ),
                        trailing=ft.PopupMenuButton(
                            icon=ft.Icons.MORE_VERT,
                            tooltip="Options",
                            items=[
                                ft.PopupMenuItem(content="Remarques", icon=ft.Icons.NOTES, on_click=on_notes),
                                ft.PopupMenuItem(content="Dupliquer", icon=ft.Icons.CONTENT_COPY,
                                    on_click=on_duplicate),
                                ft.PopupMenuItem(content="Réactiver" if order.get("archived") else "Archiver",
                                    icon=ft.Icons.UNARCHIVE_OUTLINED if order.get("archived") else ft.Icons.ARCHIVE_OUTLINED,
                                    on_click=on_archive),
                                ft.PopupMenuItem(content="Renommer", icon=ft.Icons.EDIT_OUTLINED,
                                                 on_click=on_rename),
                                ft.PopupMenuItem(content="Supprimer", icon=ft.Icons.DELETE_OUTLINE,
                                                 on_click=on_delete),
                            ],
                        ),
                        selected=is_active,
                        selected_color=ft.Colors.PRIMARY,
                        selected_tile_color=ft.Colors.PRIMARY_CONTAINER,
                        on_click=on_select,
                    ),
                )
            )

        archives = sum(bool(order.get("archived")) for order in orders.values())
        controls.insert(6, ft.Container(padding=8, content=ft.Row([
            ft.TextButton(content="Commandes actives" if state["show_archived"] else f"Archives ({archives})",
                icon=ft.Icons.ARCHIVE_OUTLINED, on_click=show_order_group, expand=True),
        ])))
        controls.extend([
            ft.Divider(),
            ft.ListTile(title=ui.text("Sauvegarder / restaurer"), leading=ft.Icon(ft.Icons.BACKUP_OUTLINED),
                        on_click=open_backup_view),
        ])
        if not any(bool(order.get("archived")) == state["show_archived"] for order in orders.values()):
            controls.append(ft.Container(padding=16, content=ui.text(
                "Aucune commande archivée." if state["show_archived"] else "Aucune commande active.", color=ui.MUTED)))
        drawer.controls = controls

    def render_all():
        if state.get("catalogue_order", object()) != state["current"]:
            render_catalogue()
        if state["current"] is None:
            # Pas de commande : écran d'aide à la place du catalogue / panier
            appbar_title.value = "Prise de Commande"
            order_info.value = ""
            body.content = empty_state
        else:
            appbar_title.value = current_order()["name"]
            body.content = workspace
            render_cart()
            render_photos()
            layout_workspace()
        update_catalogue_badges()
        render_orders()

    # =====================================================================
    # --- ÉCRAN « GÉRER LES ARTICLES » : affichage, prix, articles ajoutés ---
    # =====================================================================

    admin_search = ui.field(
        label="Rechercher",
        prefix_icon=ft.Icons.SEARCH,
        expand=3,
    )
    admin_category = ui.dropdown(
        label="Catégorie",
        options=[],
        value="Toutes",
        expand=2,
    )
    admin_catalogue = ui.dropdown(label="Catalogue", options=[], expand=True)
    # Filtre Tous / Affichés / Masqués (les nombres sont mis à jour par refresh_admin_info)
    admin_visibility = ft.SegmentedButton(
        segments=[
            ft.Segment(value="tous", label="Tous"),
            ft.Segment(value="affiches", label="Affichés"),
            ft.Segment(value="masques", label="Masqués"),
        ],
        selected=["tous"],
        allow_empty_selection=False,
        allow_multiple_selection=False,
        show_selected_icon=False,
        style=ft.ButtonStyle(padding=ft.Padding.symmetric(horizontal=10, vertical=14)),
        expand=True,
    )
    admin_listview = ft.ListView(expand=True, spacing=0, padding=ft.Padding.only(bottom=24))

    # Références vers les contrôles affichés, pour les mettre à jour sans tout redessiner
    admin_rows = {}     # clé article → contrôles de la ligne
    admin_headers = {}  # catégorie → (case à cocher, compteur, clés des articles affichés)

    def admin_filtered():
        search_val = admin_search.value or ""
        cat_val = admin_category.value
        visibility = (admin_visibility.selected or ["tous"])[0]
        return [
            e for e in entries_in(admin_catalogue.value)
            if matches_search(e["Nom_Article"], search_val)
            and (cat_val == "Toutes" or e["Categorie"] == cat_val)
            and (visibility == "tous" or e["Visible"] == (visibility == "affiches"))
        ]

    async def on_admin_filter(e=None):
        render_admin()
        refresh()
        await admin_listview.scroll_to(offset=0)  # résultats affichés depuis le début

    async def on_admin_catalogue_select(e=None):
        admin_category.value = "Toutes"
        await on_admin_filter()

    admin_catalogue.on_select = on_admin_catalogue_select
    admin_search.on_change = on_admin_filter
    admin_category.on_select = on_admin_filter
    admin_visibility.on_change = on_admin_filter

    def refresh_admin_info():
        entries = entries_in(admin_catalogue.value)
        n_visible = sum(entry["Visible"] for entry in entries)
        n_total = len(entries)
        labels = {"tous": "Tous", "affiches": "Affichés", "masques": "Masqués"}
        for segment in admin_visibility.segments:
            segment.label = labels[segment.value]
        admin_info.value = f"{n_visible} articles affichés sur {n_total} · prix enregistrés automatiquement"

    def refresh_admin_row(key):
        refs = admin_rows.get(key)
        entry = entry_by_key(key)
        if not refs or not entry:
            return
        refs["checkbox"].value = entry["Visible"]
        refs["name"].color = None if entry["Visible"] else ft.Colors.ON_SURFACE_VARIANT
        modified = not entry["Perso"] and abs(entry["Prix_Unitaire"] - entry["Prix_Excel"]) >= 0.005
        if entry["Perso"]:
            refs["detail"].value = "Article ajouté"
        elif modified:
            refs["detail"].value = f"Prix modifié (Excel : {fmt_eur(entry['Prix_Excel'])})"
        else:
            refs["detail"].value = ""
        refs["detail"].visible = bool(refs["detail"].value)
        if "reset" in refs:
            refs["reset"].visible = modified

    def refresh_admin_header(categorie):
        if categorie not in admin_headers:
            return
        checkbox, counter, keys = admin_headers[categorie]
        entries = [entry_by_key(k) for k in keys]
        n_visible = sum(1 for e in entries if e and e["Visible"])
        # Case « mixte » (−) seulement quand une partie est cochée. Une case à 3 états à False
        # s'affiche « − » dans Flet : on ne garde le 3e état que lorsqu'il sert.
        mixed = 0 < n_visible < len(entries)
        checkbox.tristate = mixed
        checkbox.value = None if mixed else n_visible == len(entries)
        counter.value = f"{n_visible}/{len(entries)}"

    def set_visible(keys, visible):
        for key in keys:
            if visible:
                prefs["hidden"].discard(key)
            else:
                prefs["hidden"].add(key)
        persist_prefs()
        rebuild_catalogue()
        for key in keys:
            refresh_admin_row(key)
        for categorie in {entry_by_key(k)["Categorie"] for k in keys if entry_by_key(k)}:
            refresh_admin_header(categorie)
        refresh_admin_info()
        refresh()

    def toggle_category(categorie):
        # Tout est coché → on décoche tout ; sinon on coche tout (articles affichés par le filtre)
        keys = admin_headers[categorie][2]
        all_visible = all(entry_by_key(k)["Visible"] for k in keys)
        set_visible(keys, not all_visible)

    def commit_price(key, field, final):
        """Enregistre le prix saisi. final=True (sortie du champ / Entrée) : remet le champ au propre."""
        entry = entry_by_key(key)
        if not entry:
            return
        price = _to_price(field.value)
        if price is None or price < 0:
            if final:
                field.value = fmt_input(entry['Prix_Unitaire'])
                show_snack("Prix invalide : saisissez un nombre, ex. 1190 ou 79,50.")
                refresh()
            return
        price = round(price, 2)
        if entry["Perso"]:
            for c in prefs["custom"]:
                if c["key"] == key:
                    c["price"] = price
        elif abs(price - entry["Prix_Excel"]) < 0.005:
            prefs["prices"].pop(key, None)  # retour au prix de l'Excel
        else:
            prefs["prices"][key] = price
        if abs(price - entry["Prix_Unitaire"]) >= 0.005:
            persist_prefs()
            rebuild_catalogue()
            refresh_admin_row(key)
        if final:
            field.value = fmt_input(price)

    def reset_price(key, field):
        prefs["prices"].pop(key, None)
        persist_prefs()
        rebuild_catalogue()
        entry = entry_by_key(key)
        field.value = fmt_input(entry['Prix_Unitaire'])
        refresh_admin_row(key)
        show_snack(f"Prix Excel rétabli : {fmt_eur(entry['Prix_Unitaire'])}")
        refresh()

    def admin_row(entry):
        key = entry["Cle"]
        checkbox = ft.Checkbox(
            value=entry["Visible"],
            tooltip="Afficher dans le catalogue",
            on_change=lambda e, k=key: set_visible([k], bool(e.control.value)),
        )
        name = ui.text(entry["Nom_Article"], weight=ft.FontWeight.W_500, size=14)
        detail = ui.text("", size=11, color=ft.Colors.ON_SURFACE_VARIANT, italic=True)
        price_field = ui.field(
            value=fmt_input(entry['Prix_Unitaire']),
            width=118,  # assez large pour « 1350,00 € »
            dense=True,
            text_align=ft.TextAlign.RIGHT,
            suffix="€",
            keyboard_type=ft.KeyboardType.NUMBER,
            tooltip="Prix unitaire",
        )
        price_field.on_change = lambda e, k=key, f=price_field: commit_price(k, f, final=False)
        price_field.on_blur = lambda e, k=key, f=price_field: commit_price(k, f, final=True)
        price_field.on_submit = lambda e, k=key, f=price_field: commit_price(k, f, final=True)

        refs = {"checkbox": checkbox, "name": name, "detail": detail}
        if entry["Perso"]:
            extra = ft.IconButton(
                icon=ft.Icons.DELETE_OUTLINE, icon_color=ft.Colors.ERROR,
                tooltip="Supprimer cet article",
                width=48, height=48,
                on_click=lambda e, k=key: delete_article_dialog(k),
            )
        else:
            extra = ft.IconButton(
                icon=ft.Icons.RESTART_ALT,
                tooltip="Revenir au prix de l'Excel",
                width=48, height=48,
                on_click=lambda e, k=key, f=price_field: reset_price(k, f),
            )
            refs["reset"] = extra
        admin_rows[key] = refs
        refresh_admin_row(key)

        description = ft.Column([name, detail], spacing=2, expand=True, tight=True)
        compact = ft.Column([
            ft.Row([checkbox, description], spacing=4),
            ft.Row([price_field, extra], alignment=ft.MainAxisAlignment.END, spacing=4),
        ], spacing=4, tight=True)
        wide = ft.Row([checkbox, description, price_field, extra], spacing=4)
        card = ui.item_card(compact)
        refs.update(card=card, compact=compact, wide=wide)
        return card

    def apply_admin_density():
        width = window["layout"].width
        columns = 3 if width >= 1100 else 2 if width >= 680 else 1
        card_width = (width - 32 - (columns - 1) * 8) / columns
        for refs in admin_rows.values():
            refs["card"].content = refs["wide"] if card_width >= 340 else refs["compact"]

    def render_admin():
        admin_listview.controls.clear()
        admin_rows.clear()
        admin_headers.clear()

        update_catalogue_selector(admin_catalogue, include_hidden=True)
        categories = categories_of(entries_in(admin_catalogue.value))
        admin_category.options = [ft.DropdownOption(key=c, text=c) for c in ["Toutes"] + sorted(categories)]
        if admin_category.value not in categories:
            admin_category.value = "Toutes"

        filtered = admin_filtered()
        if not filtered:
            admin_listview.controls.append(ft.Container(
                padding=16, content=ui.text("Aucun article ne correspond.", italic=True)))

        for categorie in categories:
            group = [e for e in filtered if e["Categorie"] == categorie]
            if not group:
                continue
            header_checkbox = ft.Checkbox(
                tooltip="Tout cocher / tout décocher",
                on_change=lambda e, c=categorie: toggle_category(c),
            )
            counter = ui.text("", size=12, color=ft.Colors.ON_SURFACE_VARIANT)
            admin_headers[categorie] = (header_checkbox, counter, [e["Cle"] for e in group])
            admin_listview.controls.append(ft.Container(
                bgcolor=ft.Colors.SURFACE_CONTAINER,
                border_radius=14,
                margin=ft.Margin.only(top=4),
                padding=ft.Padding.only(left=0, right=12, top=2, bottom=2),
                content=ft.Row([
                    header_checkbox,
                    ft.Icon(get_category_icon(categorie), size=20, color=ui.PRIMARY),
                    ui.text(categorie, size=16,
                            weight=ft.FontWeight.BOLD, expand=True),
                    counter,
                ]),
            ))
            refresh_admin_header(categorie)
            cards = [admin_row(entry) for entry in group]
            for card in cards:
                card.col = {"xs": 12, "md": 6, "lg": 4}
            admin_listview.controls.append(ft.ResponsiveRow(
                cards, spacing=8, run_spacing=8, breakpoints={"xs": 0, "md": 680, "lg": 1100},
            ))
        apply_admin_density()
        refresh_admin_info()

    def add_article_dialog(e=None):
        catalogue = admin_catalogue.value
        categories = categories_of(entries_in(catalogue))
        new_cat_key = "__nouvelle__"
        initial_cat = admin_category.value if admin_category.value in categories else (
            categories[0] if categories else new_cat_key)

        name_field = ui.field(label="Nom de l'article", autofocus=True,
                                  capitalization=ft.TextCapitalization.SENTENCES)
        new_cat_field = ui.field(label="Nom de la nouvelle catégorie",
                                     capitalization=ft.TextCapitalization.SENTENCES,
                                     visible=initial_cat == new_cat_key)
        cat_field = ui.dropdown(
            label="Catégorie",
            options=[ft.DropdownOption(key=c, text=c) for c in categories]
                    + [ft.DropdownOption(key=new_cat_key, text="➕ Nouvelle catégorie…")],
            value=initial_cat,
            width=dialog_width(),
        )
        cat_field.on_select = lambda e: setattr(new_cat_field, "visible", cat_field.value == new_cat_key)
        price_field = ui.field(label="Prix unitaire", suffix="€", keyboard_type=ft.KeyboardType.NUMBER)
        def fail(field, message):
            field.error = message
            field.error_max_lines = 3

        def validate(e=None):
            for field in (name_field, new_cat_field, price_field):
                field.error = None
            name = norm_text(name_field.value or "")
            category = norm_text(new_cat_field.value or "") if cat_field.value == new_cat_key else cat_field.value
            price = _to_price(price_field.value)
            if not name:
                return fail(name_field, "Indiquez le nom de l'article.")
            if not category:
                return fail(new_cat_field, "Indiquez le nom de la nouvelle catégorie.")
            if price is None or price < 0:
                return fail(price_field, "Prix invalide : saisissez un nombre, ex. 1190 ou 79,50.")
            page.pop_dialog()
            prefs["custom"].append({
                "key": KEY_PERSO + uuid.uuid4().hex[:8],
                "name": name,
                "category": category,
                "catalogue": catalogue,
                "price": round(price, 2),
            })
            persist_prefs()
            rebuild_catalogue()
            render_admin()
            show_snack(f"➕ « {name} » ajouté dans « {category} »")
            refresh()

        name_field.on_submit = validate
        price_field.on_submit = validate
        page.show_dialog(ft.AlertDialog(
            scrollable=True,
            modal=True,
            title=ui.text("Ajouter un article"),
            content=ft.Column([name_field, cat_field, new_cat_field, price_field],
                              tight=True, spacing=12, width=dialog_width()),
            actions=[
                ft.TextButton(content="Annuler", on_click=lambda e: page.pop_dialog()),
                ui.button(content="Ajouter", on_click=validate),
            ],
        ))

    def delete_article_dialog(key):
        entry = entry_by_key(key)
        if not entry:
            return

        def confirm(e):
            page.pop_dialog()
            if not any(c["key"] == key for c in prefs["custom"]):  # double appui
                return
            prefs["custom"] = [c for c in prefs["custom"] if c["key"] != key]
            prefs["hidden"].discard(key)
            persist_prefs()
            rebuild_catalogue()
            render_admin()
            show_snack(f"🗑️ « {entry['Nom_Article']} » supprimé du catalogue.")
            refresh()

        page.show_dialog(ft.AlertDialog(
            scrollable=True,
            modal=True,
            title=ui.text("Supprimer l'article ?"),
            content=ui.text(f"« {entry['Nom_Article']} » sera retiré du catalogue.\n"
                            "Les commandes qui le contiennent déjà ne changent pas."),
            actions=[
                ft.TextButton(content="Annuler", on_click=lambda e: page.pop_dialog()),
                ui.button(content="Supprimer", on_click=confirm,
                          style=ft.ButtonStyle(bgcolor=ft.Colors.ERROR, color=ft.Colors.ON_ERROR)),
            ],
        ))

    admin_info = ui.text("", size=12, color=ui.MUTED)
    admin_listview.spacing = 6
    admin_search.expand = True
    admin_catalogue.col = admin_category.col = 12
    admin_filter_details = ft.ResponsiveRow([admin_catalogue, admin_category], spacing=12, run_spacing=12)
    admin_filter_details.visible = window["layout"].width >= 600 and not window["layout"].short

    def toggle_admin_filters(e=None):
        admin_filter_details.visible = not admin_filter_details.visible

    admin_filter_button = ft.IconButton(icon=ft.Icons.TUNE, width=48, height=48,
        tooltip="Afficher ou masquer les filtres des articles", on_click=toggle_admin_filters)
    admin_view = ft.View(
        route="/articles",
        padding=16,
        appbar=ft.AppBar(
            title=ui.text("Gérer les articles", weight=ft.FontWeight.W_600),
            bgcolor=ft.Colors.SURFACE_CONTAINER,
            actions=[
                ft.TextButton(content="Ajouter", icon=ft.Icons.ADD, tooltip="Ajouter un article",
                              on_click=add_article_dialog),
            ],
        ),
        controls=[
            ft.SafeArea(expand=True, content=ft.Column(
                [
                    ft.Row([admin_search, admin_filter_button], spacing=8),
                    admin_filter_details,
                    ft.Row([admin_visibility]),
                    admin_info,
                    admin_listview,
                ],
                expand=True, spacing=12,
            )),
        ],
    )

    # --- ÉCRAN « GÉRER LES CATALOGUES » ---
    catalogues_listview = ft.ListView(expand=True, spacing=12)
    catalogues_summary = ui.text("", weight=ft.FontWeight.W_600)

    def save_catalogue_changes(updated):
        # Enregistrer avant de modifier l'écran : une erreur disque ne doit pas effacer les données en mémoire.
        try:
            save_prefs(updated)
        except OSError as err:
            show_snack(f"⚠️ Modification du catalogue impossible : {err}")
            refresh()
            return False
        prefs.clear()
        prefs.update(updated)
        rebuild_catalogue()
        return True

    def refresh_catalogues():
        render_catalogue()
        render_catalogues()
        render_all()
        refresh()

    def rename_catalogue_dialog(name):
        if name == DEFAULT_CATALOGUE or name not in managed_catalogues():
            return
        name_field = ui.field(label="Nom du catalogue", value=name, autofocus=True)

        def validate(e=None):
            new_name = norm_text(name_field.value or "")
            reserved = {fold(n) for n in managed_catalogues() if n != name}
            reserved.update({fold(DEFAULT_CATALOGUE_LABEL), fold("Catalogue principal")})
            if not new_name:
                message = "Indiquez un nom de catalogue."
            elif ":" in new_name:
                message = "Le nom du catalogue ne peut pas contenir de deux-points."
            elif fold(new_name) in reserved:
                message = "Ce nom de catalogue est déjà utilisé."
            else:
                message = None
            if message:
                name_field.error, name_field.error_max_lines = message, 3
                refresh()
                return
            name_field.error = None
            if new_name != name:
                snapshot = [{**item, "Catalogue": new_name if item["Catalogue"] == name else item["Catalogue"]}
                            for item in prefs.get("catalogue_items", excel_items)]
                custom = [{**item, "catalogue": new_name} if item.get("catalogue", DEFAULT_CATALOGUE) == name
                          else dict(item) for item in prefs["custom"]]
                hidden_catalogues = set(prefs["hidden_catalogues"])
                was_hidden = name in hidden_catalogues
                hidden_catalogues.discard(name)
                hidden_catalogues.discard(new_name)
                if was_hidden:
                    hidden_catalogues.add(new_name)
                if not save_catalogue_changes({**prefs, "catalogue_items": snapshot, "custom": custom,
                                               "hidden_catalogues": hidden_catalogues}):
                    return
                for dropdown in (catalogue_dropdown, admin_catalogue):
                    if dropdown.value == name:
                        dropdown.value = new_name
            page.pop_dialog()
            refresh_catalogues()

        name_field.on_submit = validate
        page.show_dialog(ft.AlertDialog(
            scrollable=True,
            modal=True, title=ui.text("Renommer le catalogue"),
            content=ft.Column([name_field], tight=True, width=dialog_width()),
            actions=[ft.TextButton(content="Annuler", on_click=lambda e: page.pop_dialog()),
                     ui.button(content="Renommer", on_click=validate)],
        ))

    def remove_catalogue_dialog(name):
        is_main = name == DEFAULT_CATALOGUE
        label = name or DEFAULT_CATALOGUE_LABEL

        def confirm(e=None):
            keys = {item["Cle"] for item in entries_in(name)}
            snapshot = [dict(item) for item in prefs.get("catalogue_items", excel_items)
                        if item["Catalogue"] != name]
            custom = [dict(item) for item in prefs["custom"]
                      if item.get("catalogue", DEFAULT_CATALOGUE) != name]
            hidden_catalogues = set(prefs["hidden_catalogues"])
            if not is_main:
                hidden_catalogues.discard(name)
            if not save_catalogue_changes({**prefs, "catalogue_items": snapshot, "custom": custom,
                    "hidden_catalogues": hidden_catalogues, "hidden": prefs["hidden"] - keys,
                    "prices": {key: value for key, value in prefs["prices"].items() if key not in keys}}):
                return
            page.pop_dialog()
            refresh_catalogues()

        page.show_dialog(ft.AlertDialog(
            scrollable=True,
            modal=True,
            title=ui.text("Vider le catalogue principal ?" if is_main else "Supprimer le catalogue ?"),
            content=ui.text(f"Les {len(entries_in(name))} article(s) de « {label} » seront retirés, "
                            "y compris les articles ajoutés manuellement.\n"
                            "Les commandes existantes sont conservées. Un nouvel import peut rétablir ces articles."),
            actions=[ft.TextButton(content="Annuler", on_click=lambda e: page.pop_dialog()),
                     ui.button(content="Vider" if is_main else "Supprimer", on_click=confirm,
                               style=ft.ButtonStyle(bgcolor=ft.Colors.ERROR, color=ft.Colors.ON_ERROR))],
        ))

    def set_catalogue_visible(name, visible):
        if visible:
            prefs["hidden_catalogues"].discard(name)
        else:
            prefs["hidden_catalogues"].add(name)
        persist_prefs()
        render_catalogue()
        render_catalogues()
        render_orders()
        refresh()

    def render_catalogues():
        catalogues_listview.controls.clear()
        names = managed_catalogues()
        n_visible = sum(name not in prefs["hidden_catalogues"] for name in names)
        catalogues_summary.value = f"{n_visible} catalogue(s) affiché(s) sur {len(names)}"
        for name in names:
            label = name or DEFAULT_CATALOGUE_LABEL
            visible = name not in prefs["hidden_catalogues"]
            count = len(entries_in(name))
            actions = ([ft.PopupMenuItem(content="Vider le catalogue principal", icon=ft.Icons.DELETE_OUTLINE,
                                         disabled=count == 0, on_click=lambda e: remove_catalogue_dialog(DEFAULT_CATALOGUE))]
                       if name == DEFAULT_CATALOGUE else [
                           ft.PopupMenuItem(content="Renommer", icon=ft.Icons.EDIT_OUTLINED,
                                            on_click=lambda e, n=name: rename_catalogue_dialog(n)),
                           ft.PopupMenuItem(content="Supprimer", icon=ft.Icons.DELETE_OUTLINE,
                                            on_click=lambda e, n=name: remove_catalogue_dialog(n)),
                       ])
            catalogues_listview.controls.append(ui.card(ft.Column([
                ft.Row([
                    ft.Icon(ft.Icons.FOLDER_OUTLINED, color=ui.PRIMARY),
                    ui.text(label, weight=ft.FontWeight.W_600, expand=True),
                ]),
                ft.Row([
                    ui.text(f"{'Affiché' if visible else 'Masqué'} · {count} article(s)",
                            size=12, color=ui.MUTED, expand=True),
                    ft.Switch(value=visible, tooltip=f"Afficher « {label} »",
                              on_change=lambda e, n=name: set_catalogue_visible(n, e.control.value)),
                    ft.PopupMenuButton(icon=ft.Icons.MORE_VERT, tooltip=f"Options « {label} »", items=actions),
                ], spacing=0),
            ], spacing=8)))

    catalogues_view = ft.View(
        route="/catalogues",
        padding=16,
        appbar=ft.AppBar(title=ui.text("Gérer les catalogues", weight=ft.FontWeight.W_600),
                        bgcolor=ft.Colors.SURFACE_CONTAINER),
        controls=[ft.SafeArea(expand=True, content=ft.Column([
            ui.text("Affichez ou masquez les catalogues. Le menu ⋮ permet de les gérer. "
                    "Les commandes existantes sont conservées.", color=ft.Colors.ON_SURFACE_VARIANT),
            catalogues_summary,
            catalogues_listview,
        ], expand=True, spacing=16))],
    )

    # =====================================================================
    # --- PHOTOS DE LA COMMANDE (matériel à remplacer) ---
    # =====================================================================

    file_picker = ft.FilePicker()  # services : on garde une référence
    share = ft.Share()
    is_mobile = page.platform in (ft.PagePlatform.ANDROID, ft.PagePlatform.IOS)
    camera_available = fc is not None and is_mobile and not page.web
    camera_state = {"cam": None}

    async def replace_catalogue(e=None):
        """☰ › Importer un catalogue : remplace le catalogue. Paniers, prix modifiés et articles
        masqués sont conservés pour les articles qui gardent le même nom et catalogue."""
        await close_drawer()
        try:
            picked = await pick_catalogue_file(file_picker)
            if picked is None:
                return  # annulé
            items, skipped = install_catalogue(*picked)
        except Exception as err:  # fichier invalide, illisible, ou sélecteur indisponible
            page.show_dialog(ft.AlertDialog(
                scrollable=True,
                title=ui.text("Import impossible"),
                content=ui.text(f"{err}\n\nLe catalogue actuel est conservé.", selectable=True),
                actions=[ft.TextButton(content="OK", on_click=lambda e: page.pop_dialog())],
            ))
            refresh()
            return
        old_keys = {it["Cle"] for it in cat["all"] if not it["Perso"]}
        prefs.pop("catalogue_items", None)  # le nouveau fichier remplace les modifications locales
        # Nouveaux articles marqués « Masqué » : masqués comme au premier lancement
        prefs["hidden"] |= {it["Cle"] for it in items if it["Masque"] and it["Cle"] not in old_keys}
        excel_items[:] = items
        rebuild_catalogue()
        persist_prefs()
        render_catalogue()
        render_all()
        message = f"✅ Catalogue importé : {len(items)} article(s)."
        if skipped:
            page.show_dialog(ft.AlertDialog(
                scrollable=True,
                title=ui.text("Catalogue importé"),
                content=ui.text(f"{len(items)} article(s) importé(s).\n\n{skipped_summary(skipped)}",
                                selectable=True),
                actions=[ft.TextButton(content="OK", on_click=lambda e: page.pop_dialog())],
            ))
        else:
            show_snack(message)
        refresh()

    photos_tab = ft.NavigationBarDestination(label="Photos", icon=ft.Icons.PHOTO_LIBRARY_OUTLINED,
                                             selected_icon=ft.Icons.PHOTO_LIBRARY)
    photos_grid = ft.GridView(
        expand=True, max_extent=260, child_aspect_ratio=0.8,
        spacing=12, run_spacing=12, padding=ft.Padding.only(top=4, bottom=12),
    )
    photos_empty = ft.ListView(expand=True, controls=[ui.empty(
        ft.Icons.PHOTO_CAMERA_OUTLINED, "Aucune photo pour cette commande",
        "Photographiez les étiquettes, numéros de série ou branchements du matériel à remplacer. "
        "Donnez ensuite un nom à chaque photo.",
    )])

    def order_photos(order=None):
        return (order or current_order()).setdefault("photos", [])

    def add_photo_file(order_id, source_path=None, data=None, ext=".jpg"):
        """Range une photo (copie d'un fichier, ou octets de l'appareil photo) dans la commande."""
        folder = photos_dir(order_id)
        folder.mkdir(parents=True, exist_ok=True)
        photo_id = uuid.uuid4().hex[:8]
        filename = photo_id + (ext if ext.startswith(".") else "." + ext)
        if data is not None:
            (folder / filename).write_bytes(data)
        else:
            shutil.copyfile(source_path, folder / filename)
        photos = orders[order_id].setdefault("photos", [])
        entry = {"id": photo_id, "file": filename, "label": f"Photo {len(photos) + 1}",
                 "added": datetime.now().isoformat(timespec="minutes")}
        photos.append(entry)
        return entry

    def delete_photo(order_id, photo_id):
        photos = orders[order_id].get("photos", [])
        photo = next((p for p in photos if p["id"] == photo_id), None)
        if photo is None:
            return None
        photos.remove(photo)
        try:
            photo_path(order_id, photo).unlink()
        except OSError:
            pass
        return photo

    def photo_src(order_id, photo):
        path = photo_path(order_id, photo)
        # Le navigateur ne peut pas ouvrir un chemin local du serveur Python.
        if page.web:
            try:
                return path.read_bytes()
            except OSError:
                return b""
        return str(path)

    def render_photos():
        order_id = state["current"]
        photos = order_photos()
        photos_grid.controls.clear()
        for i, photo in enumerate(photos, 1):
            photos_grid.controls.append(ft.Container(
                bgcolor=ft.Colors.SURFACE_CONTAINER,
                border_radius=10,
                padding=6,
                ink=True,
                tooltip="Renommer ou supprimer",
                on_click=lambda e, pid=photo["id"]: open_photo_dialog(pid),
                content=ft.Column(
                    [
                        ft.Image(
                            src=photo_src(order_id, photo),
                            fit=ft.BoxFit.COVER,
                            expand=True,
                            cache_width=dialog_width(),  # vignette : évite de décoder l'image en pleine taille
                            border_radius=8,
                            error_content=ft.Icon(ft.Icons.BROKEN_IMAGE_OUTLINED, color=ft.Colors.ON_SURFACE_VARIANT),
                        ),
                        ui.text(f"{i}. {photo['label']}", size=12, weight=ft.FontWeight.W_500,
                                max_lines=2, overflow=ft.TextOverflow.ELLIPSIS),
                    ],
                    spacing=6,
                    horizontal_alignment=ft.CrossAxisAlignment.STRETCH,
                ),
            ))
        has_photos = bool(photos)
        photos_grid.visible = has_photos
        photos_empty.visible = not has_photos
        share_photos_btn.disabled = not has_photos
        zip_photos_btn.disabled = not has_photos
        photos_tab.label = f"Photos ({len(photos)})" if has_photos else "Photos"

    def ask_photo_label(order_id, photo, title, on_done=None, image_src=None, modal=True):
        """Boîte « nommer la photo » : aperçu, libellé, Supprimer / Enregistrer.
        modal=False : un appui à côté ferme la boîte (simple consultation)."""
        label_field = ui.field(
            value=photo["label"],
            label="Nom de la photo",
            hint_text="ex. Ancien serveur – étiquette",
            capitalization=ft.TextCapitalization.SENTENCES,
            autofocus=True,
        )

        def save(e=None):
            page.pop_dialog()
            label = norm_text(label_field.value or "")
            if label and label != photo["label"]:
                photo["label"] = label
                persist()
            render_all()
            if on_done:
                on_done()
            refresh()

        def remove(e):
            page.pop_dialog()
            if delete_photo(order_id, photo["id"]):
                persist()
                render_all()
                show_snack("🗑️ Photo supprimée.")
            if on_done:
                on_done()
            refresh()

        label_field.on_submit = save
        added = datetime.fromisoformat(photo["added"]).strftime("%d/%m/%Y à %H:%M")
        page.show_dialog(ft.AlertDialog(
            scrollable=True,
            modal=modal,
            title=ui.text(title),
            content=ft.Column(
                [
                    ft.Image(src=image_src or photo_src(order_id, photo), fit=ft.BoxFit.CONTAIN,
                             height=260, cache_width=1080, border_radius=8),
                    label_field,
                    ui.text(f"Prise le {added}", size=11, color=ft.Colors.ON_SURFACE_VARIANT),
                ],
                tight=True, spacing=10, width=dialog_width(),
                horizontal_alignment=ft.CrossAxisAlignment.STRETCH,
            ),
            actions_alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
            actions=[
                ft.TextButton(content="Supprimer", icon=ft.Icons.DELETE_OUTLINE, on_click=remove,
                              style=ft.ButtonStyle(color=ft.Colors.ERROR)),
                ui.button(content="Enregistrer", on_click=save),
            ],
        ))

    def open_photo_dialog(photo_id):
        order_id = state["current"]
        photo = next((p for p in order_photos() if p["id"] == photo_id), None)
        if photo is None:
            return
        ask_photo_label(order_id, photo, "Photo", modal=False)
        refresh()

    async def import_photos(e=None):
        """Galerie du téléphone, ou fichiers sur PC (plusieurs à la fois)."""
        order_id = state["current"]
        if order_id is None:
            return
        try:
            files = await file_picker.pick_files(
                dialog_title="Choisir des photos",
                file_type=ft.FilePickerFileType.IMAGE,
                allow_multiple=True,
                with_data=page.web,
            )
        except Exception as err:  # sélecteur indisponible
            show_snack(f"Impossible d'ouvrir la galerie : {err}")
            refresh()
            return
        if not files:
            return  # annulé
        added, failed = 0, 0
        for f in files:
            data = f.bytes if page.web else None
            if data is None and not f.path:
                failed += 1
                continue
            ext = os.path.splitext(f.name or f.path or "")[1].lower() or ".jpg"
            try:
                add_photo_file(order_id, source_path=f.path, data=data, ext=ext)
                added += 1
            except OSError:
                failed += 1
        persist()
        render_all()
        go_to_tab(2)
        message = f"📷 {added} photo(s) ajoutée(s) — touchez une photo pour la nommer."
        if failed:
            message += f" {failed} n'ont pas pu être copiée(s)."
        show_snack(message)
        refresh()

    async def share_photos(e=None):
        """Feuille de partage du téléphone (mail, WhatsApp, Drive…) : photos nommées + liste."""
        order_id, order = state["current"], current_order()
        if not order.get("photos"):
            return
        names = photo_export_names(order)
        # Copies portant le libellé comme nom de fichier (le destinataire voit « 01 - Ancien serveur.jpg »)
        export_dir = storage_dir() / "export" / order_id
        shutil.rmtree(export_dir, ignore_errors=True)
        export_dir.mkdir(parents=True, exist_ok=True)
        files = []
        for photo, name in zip(order["photos"], names):
            target = export_dir / name
            shutil.copyfile(photo_path(order_id, photo), target)
            files.append(ft.ShareFile.from_path(str(target), name=name))
        try:
            await share.share_files(
                files,
                subject=f"Photos – {order['name']}",
                text="\n".join(photos_summary(order, names)),
            )
        except Exception as err:
            show_snack(f"Partage impossible : {err}")
            refresh()

    async def save_photos_zip(e=None):
        """Un fichier .zip : photos nommées par leur libellé + photos.txt (liste et articles)."""
        order_id, order = state["current"], current_order()
        if not order.get("photos"):
            return
        data = build_photos_zip(order_id, order)
        file_name = f"{safe_filename(order['name'], 'commande')} - photos.zip"
        try:
            chosen = await file_picker.save_file(
                dialog_title="Enregistrer les photos",
                file_name=file_name,
                file_type=ft.FilePickerFileType.CUSTOM,
                allowed_extensions=["zip"],
                src_bytes=data,
            )
        except Exception as err:
            show_snack(f"Enregistrement impossible : {err}")
            refresh()
            return
        if not chosen:
            return  # annulé
        if not is_mobile and not page.web:
            # Sur PC, le sélecteur renvoie l'emplacement choisi : c'est l'app qui écrit le fichier
            target = Path(chosen)
            if target.suffix.lower() != ".zip":
                target = target.with_suffix(".zip")
            try:
                target.write_bytes(data)
            except OSError as err:
                show_snack(f"Enregistrement impossible : {err}")
                refresh()
                return
            chosen = str(target)
        show_snack(f"💾 Photos enregistrées : {Path(chosen).name}")
        refresh()

    # --- Appareil photo intégré (Android) ---
    camera_count = ui.text("", color=ft.Colors.WHITE, size=13, width=90)

    def update_camera_count():
        n = len(order_photos()) if state["current"] else 0
        camera_count.value = f"{n} photo(s)" if n else ""

    def build_camera_view():
        cam = fc.Camera(expand=True)
        camera_state["cam"] = cam
        update_camera_count()
        return ft.View(
            route="/photo",
            bgcolor=ft.Colors.BLACK,
            padding=0,
            appbar=ft.AppBar(
                title=ui.text(current_order()["name"], max_lines=1, overflow=ft.TextOverflow.ELLIPSIS),
                bgcolor=ft.Colors.BLACK,
                color=ft.Colors.WHITE,
                actions=[ft.TextButton(content="Terminé", on_click=close_camera,
                                       style=ft.ButtonStyle(color=ft.Colors.WHITE))],
            ),
            controls=[ft.SafeArea(expand=True, content=ft.Column(
                [
                    cam,
                    ft.Container(
                        padding=ft.Padding.symmetric(horizontal=20, vertical=14),
                        content=ft.Row(
                            [
                                camera_count,
                                ft.IconButton(
                                    icon=ft.Icons.CAMERA, icon_size=40, icon_color=ft.Colors.WHITE,
                                    bgcolor=ft.Colors.PRIMARY, width=76, height=76,
                                    tooltip="Prendre la photo", on_click=take_photo,
                                ),
                                ft.Container(width=90),
                            ],
                            alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                        ),
                    ),
                ],
                expand=True, spacing=0,
            ))],
        )

    async def open_camera(e=None):
        if not camera_available or state["current"] is None:
            await import_photos()
            return
        state["back_to_photos"] = True
        await page.push_route("/photo")  # la caméra démarre dans route_change, une fois l'écran affiché

    async def start_camera():
        cam = camera_state["cam"]
        await asyncio.sleep(0.4)  # le temps que l'aperçu soit créé à l'écran
        try:
            cameras = await cam.get_available_cameras()
            if not cameras:
                raise RuntimeError("aucun appareil photo trouvé")
            back = next((c for c in cameras if c.lens_direction == fc.CameraLensDirection.BACK), cameras[0])
            await cam.initialize(back, fc.ResolutionPreset.HIGH, enable_audio=False)
        except Exception as err:
            camera_state["cam"] = None
            await page.push_route("/")
            show_snack(f"Appareil photo indisponible ({err}). Utilisez « Importer ».")
            refresh()

    async def take_photo(e=None):
        cam, order_id = camera_state["cam"], state["current"]
        if cam is None or order_id is None:
            return
        try:
            data = await cam.take_picture()
        except Exception as err:
            show_snack(f"Photo impossible : {err}")
            refresh()
            return
        photo = add_photo_file(order_id, data=data, ext=".jpg")
        persist()
        update_camera_count()
        # On nomme la photo tout de suite, puis on reste dans l'appareil photo pour la suivante
        ask_photo_label(order_id, photo, "Nommer la photo", on_done=update_camera_count)
        refresh()

    async def close_camera(e=None):
        await page.push_route("/")

    async def open_admin(e=None):
        await close_drawer()
        await page.push_route("/articles")

    async def open_catalogue_manager(e=None):
        await close_drawer()
        await page.push_route("/catalogues")

    backup_status = ui.text("", color=ui.MUTED, selectable=True)
    backup_progress = ft.ProgressRing(visible=False, width=24, height=24)

    async def export_backup(e=None, recovery=False):
        export_backup_btn.disabled = restore_backup_btn.disabled = recovery_backup_btn.disabled = True
        backup_progress.visible = True
        backup_status.value = "Préparation de la sauvegarde…"
        refresh()
        try:
            if recovery:
                path = max((storage_dir() / "sauvegardes").glob("avant-restauration-*.zip"),
                           key=lambda path: path.stat().st_mtime_ns)
                if not path.resolve().is_relative_to(storage_dir().resolve()):
                    raise ValueError("La copie de secours est située hors du stockage de l'application.")
                data = await asyncio.to_thread(path.read_bytes)
            else:
                save_orders(orders, state["current"])
                save_prefs(prefs)
                data = await asyncio.to_thread(backup.create_backup, storage_dir())
            chosen = await file_picker.save_file(dialog_title="Enregistrer la sauvegarde complète",
                file_name=path.name if recovery else f"Prise de Commande - {datetime.now():%Y-%m-%d-%H%M}.zip",
                file_type=ft.FilePickerFileType.CUSTOM, allowed_extensions=["zip"], src_bytes=data)
            if chosen and not is_mobile and not page.web:
                target = Path(chosen)
                if target.suffix.lower() != ".zip":
                    target = target.with_suffix(".zip")
                await asyncio.to_thread(target.write_bytes, data)
            backup_status.value = "Sauvegarde enregistrée." if chosen else "Enregistrement annulé."
        except Exception as err:
            backup_status.value = f"Sauvegarde impossible : {err}"
        finally:
            export_backup_btn.disabled = restore_backup_btn.disabled = False
            recovery_backup_btn.disabled = not any((storage_dir() / "sauvegardes").glob("avant-restauration-*.zip"))
            backup_progress.visible = False
            refresh()

    async def restore_from_view(e=None):
        async def done():
            await page.push_route("/")
            page.controls.clear()
            main(page)
        await request_restore(page, file_picker, done)

    async def export_recovery(e=None):
        await export_backup(recovery=True)

    export_backup_btn = ui.button(content="Créer une sauvegarde", icon=ft.Icons.SAVE_ALT, on_click=export_backup)
    restore_backup_btn = ft.OutlinedButton(content="Restaurer une sauvegarde", icon=ft.Icons.RESTORE,
                                            on_click=restore_from_view)
    recovery_backup_btn = ft.TextButton(content="Exporter la dernière copie de secours", icon=ft.Icons.HISTORY,
        on_click=export_recovery, disabled=not any((storage_dir() / "sauvegardes").glob("avant-restauration-*.zip")))
    backup_view = ft.View(route="/sauvegarde", padding=16,
        appbar=ft.AppBar(title=ui.text("Sauvegarde et restauration")),
        controls=[ft.SafeArea(expand=True, content=ft.ListView(spacing=16, controls=[
            ui.card(ft.Column([
                ui.heading("Tout conserver", "Un fichier ZIP à garder à l'endroit de votre choix", ft.Icons.BACKUP_OUTLINED),
                ui.text("Commandes actives et archives, photos, remarques, catalogue, prix, favoris et réglages. "
                        "Aucun envoi automatique : vous choisissez où enregistrer le fichier.", color=ui.MUTED),
                export_backup_btn,
            ], spacing=16, tight=True)),
            ui.card(ft.Column([
                ui.heading("Retrouver vos données", icon=ft.Icons.RESTORE),
                ui.text("La restauration ajoute les commandes et remplace le catalogue et les réglages. "
                        "Les commandes déjà présentes sont conservées. Une copie locale de secours est créée "
                        "dans le dossier « sauvegardes » de l'application.", color=ui.MUTED),
                restore_backup_btn,
                recovery_backup_btn,
            ], spacing=16, tight=True)),
            backup_progress, backup_status,
        ]))])

    async def open_backup_view(e=None):
        await close_drawer()
        await page.push_route("/sauvegarde")

    async def route_change(e=None):
        if page.route == "/sauvegarde":
            if len(page.views) == 1:
                page.views.append(backup_view)
        elif page.route == "/articles":
            if len(page.views) == 1:
                admin_catalogue.value = catalogue_dropdown.value
                render_admin()
                page.views.append(admin_view)
        elif page.route == "/catalogues":
            if len(page.views) == 1:
                render_catalogues()
                page.views.append(catalogues_view)
        elif page.route == "/photo":
            if len(page.views) == 1 and camera_available and state["current"] is not None:
                page.views.append(build_camera_view())
                refresh()
                await start_camera()
                return
        else:
            # Retour à l'écran principal : le catalogue reflète les changements
            while len(page.views) > 1:
                page.views.pop()
            camera_state["cam"] = None
            render_catalogue()
            render_all()
            if state.pop("back_to_photos", False) and state["current"] is not None:
                go_to_tab(2)  # retour de l'appareil photo : on montre les photos
        refresh()

    async def view_pop(e):
        # Flèche ← de la barre du haut, ou bouton « retour » d'Android
        await page.push_route("/")

    page.on_route_change = route_change
    page.on_view_pop = view_pop

    # --- ADAPTIVE WORKSPACE: keep controls alive while changing their parents ---
    state["filters_open"] = False

    def toggle_filters(e=None):
        state["filters_open"] = not state["filters_open"]
        apply_filter_layout()

    filter_button = ft.IconButton(
        icon=ft.Icons.TUNE, tooltip="Afficher ou masquer les filtres",
        width=48, height=48, on_click=toggle_filters,
    )
    filter_details = ft.ResponsiveRow(
        [catalogue_dropdown, category_dropdown], spacing=12, run_spacing=12,
        breakpoints={"xs": 0, "sm": 600},
    )
    catalogue_dropdown.col = 12
    category_dropdown.col = 12
    search_input.expand = True
    filter_search_row = ft.Row([search_input, filter_button], spacing=8)
    catalogue_heading = ui.heading("Catalogue", "Trouvez le bon matériel", ft.Icons.INVENTORY_2_OUTLINED)
    browse_row = ft.Row([browse_mode])
    content_catalogue = ft.Column([
        catalogue_heading,
        filter_search_row,
        browse_row,
        filter_details,
        filter_tags,
        catalogue_info,
        catalogue_listview,
    ], expand=True, spacing=8)

    copy_order_btn = ui.button(
        content="Copier pour la Compta", icon=ft.Icons.COPY,
        on_click=copy_email_text, expand=True,
    )
    clear_order_btn = ft.IconButton(
        icon=ft.Icons.DELETE_OUTLINE, tooltip="Vider le panier", width=48, height=48,
        on_click=clear_cart, icon_color=ft.Colors.ERROR,
    )
    basket_footer = ui.card(ft.Column([
        ui.text("Total de la commande", size=13, color=ui.MUTED),
        total_text,
        ft.Row([copy_order_btn, clear_order_btn], spacing=8),
    ], spacing=12))
    notes_preview = ui.text("", size=12, color=ui.MUTED, max_lines=2, overflow=ft.TextOverflow.ELLIPSIS, visible=False)
    basket_heading = ui.heading("Votre panier", icon=ft.Icons.SHOPPING_BAG_OUTLINED,
        trailing=ft.IconButton(icon=ft.Icons.NOTES, tooltip="Remarques de la commande", width=48, height=48,
                               on_click=edit_notes))
    content_panier = ft.Column([
        basket_heading, cart_info, notes_preview, cart_listview, basket_footer,
    ], expand=True, spacing=12)

    take_photo_btn = ui.button(
        content="Prendre une photo", icon=ft.Icons.PHOTO_CAMERA, on_click=open_camera,
        expand=True, visible=camera_available,
    )
    import_photos_btn = ft.OutlinedButton(
        content="Importer" if camera_available else "Importer des photos",
        icon=ft.Icons.PHOTO_LIBRARY_OUTLINED, on_click=import_photos, expand=True,
    )
    share_photos_btn = ui.button(
        content="Partager les photos", icon=ft.Icons.SHARE, on_click=share_photos,
        expand=True, visible=is_mobile and not page.web,
    )
    zip_photos_btn = ft.OutlinedButton(
        content="Enregistrer en ZIP", icon=ft.Icons.FOLDER_ZIP_OUTLINED, on_click=save_photos_zip,
        expand=True,
    )
    photo_actions = ft.Column([
        ft.Row([take_photo_btn]), ft.Row([import_photos_btn]),
    ], spacing=8)
    photo_heading = ui.heading("Photos", "Documentez le matériel à remplacer", ft.Icons.PHOTO_LIBRARY_OUTLINED)
    content_photos = ft.Column([
        photo_heading, photo_actions, photos_empty, photos_grid,
        ft.Row([share_photos_btn]), ft.Row([zip_photos_btn]),
    ], expand=True, spacing=12)

    cart_tab = ft.NavigationBarDestination(
        label="Panier", icon=ft.Icons.SHOPPING_BAG_OUTLINED, selected_icon=ft.Icons.SHOPPING_BAG,
    )
    navigation = ft.NavigationBar(
        destinations=[
            ft.NavigationBarDestination(label="Catalogue", icon=ft.Icons.INVENTORY_2_OUTLINED,
                                        selected_icon=ft.Icons.INVENTORY_2),
            cart_tab, photos_tab,
        ],
        selected_index=0, on_change=lambda e: go_to_tab(e.control.selected_index),
    )
    main_host = ft.Container(expand=True)
    detail_host = ft.Container(expand=True, visible=False)
    # The central gutter keeps controls away from the typical inner display crease.
    # Flet 1.0.4 does not expose Android display-feature / hinge geometry.
    pane_row = ft.Row([main_host, detail_host], expand=True, spacing=24,
                      vertical_alignment=ft.CrossAxisAlignment.STRETCH)
    pane_frame = ft.Container(content=pane_row, width=1440)
    pane_area = ft.Container(content=ft.Row([pane_frame], expand=True,
        alignment=ft.MainAxisAlignment.CENTER, vertical_alignment=ft.CrossAxisAlignment.STRETCH),
        expand=True, padding=12)
    compact_cart_btn = ft.TextButton(content="Voir le panier", icon=ft.Icons.SHOPPING_BAG_OUTLINED,
        tooltip="Voir le panier",
        on_click=lambda e: go_to_tab(1), expand=True,
        style=ft.ButtonStyle(bgcolor=ft.Colors.PRIMARY_CONTAINER, color=ft.Colors.ON_PRIMARY_CONTAINER,
                             padding=ft.Padding.symmetric(horizontal=12, vertical=14)))
    quick_cart = ft.Container(content=ft.Row([compact_cart_btn]),
        padding=ft.Padding.only(left=12, right=12, bottom=8), visible=False)

    async def restore_current_order(e=None):
        await archive_order(state["current"])

    archive_banner = ft.Container(content=ft.Row([
        ui.text("Commande archivée", expand=True),
        ft.TextButton(content="Réactiver", on_click=restore_current_order),
    ]), padding=8, bgcolor=ft.Colors.PRIMARY_CONTAINER, visible=False)
    workspace = ft.Column([archive_banner, pane_area, quick_cart, navigation], spacing=0, expand=True)

    def apply_filter_layout():
        layout = window["layout"]
        narrow = layout.width < 600 or layout.dual_pane
        filter_details.visible = state["filters_open"] if narrow or layout.short else True
        filter_button.visible = narrow or layout.short
        browse_row.visible = not layout.short or state["filters_open"]
        catalogue_info.visible = not layout.short
        filter_button.bgcolor = ft.Colors.PRIMARY_CONTAINER if state["filters_open"] else None
        catalogue_dropdown.col = category_dropdown.col = 12 if narrow else 6
        for heading in [catalogue_heading, basket_heading, photo_heading]:
            heading.visible = not layout.short

    def apply_catalogue_columns():
        layout = window["layout"]
        available = min(1440 if layout.dual_pane else 780, layout.width - 2 * layout.margin)
        pane_width = ((available - 24) * (0.5 if layout.width < 1200 else 6 / 11)
                      if layout.dual_pane else available)
        # Flet ResponsiveRow breakpoints use the view width, so use explicit
        # spans based on this pane's width for master/detail catalogue cards.
        for grid in catalogue_grids:
            columns = 2 if pane_width >= 680 else 1
            for i, card in enumerate(grid.controls):
                # Give an odd final article the full row instead of leaving
                # half a grid row empty. Its controls then fit on one line.
                full_width = columns == 1 or (len(grid.controls) % 2 and i == len(grid.controls) - 1)
                card.col = 12 if full_width else 6
                card_width = pane_width if full_width else (pane_width - 8) / 2
                compact, wide = catalogue_rows[id(card)]
                card.content = wide if card_width >= 380 else compact

    def layout_workspace():
        layout = window["layout"]
        apply_filter_layout()
        apply_catalogue_columns()
        # In a short landscape/keyboard window, let the summary scroll with
        # the lines instead of consuming all of the basket's usable height.
        if layout.short:
            if basket_footer in content_panier.controls:
                content_panier.controls.remove(basket_footer)
            if basket_footer not in cart_listview.controls:
                cart_listview.controls.append(basket_footer)
        else:
            if basket_footer in cart_listview.controls:
                cart_listview.controls.remove(basket_footer)
            if basket_footer not in content_panier.controls:
                content_panier.controls.append(basket_footer)
        index = state["tab"]
        dual = layout.dual_pane
        # Reparent only at a layout/navigation boundary, never on every resize pixel.
        signature = (dual, index)
        if state.get("layout_signature") != signature:
            main_host.content = None
            detail_host.content = None
            main_host.content = content_photos if index == 2 else content_catalogue if dual or index == 0 else content_panier
            if dual:
                detail_host.content = content_panier
            detail_host.visible = dual
            state["layout_signature"] = signature
        pane_area.padding = layout.margin
        pane_frame.width = min(1440 if dual else 780, max(0, layout.width - 2 * layout.margin))
        drawer.width = min(360, max(240, layout.width - 24))
        # Limit line lengths on large desktops; balanced panes on inner displays.
        main_host.expand = (1 if layout.width < 1200 else 6) if dual else True
        detail_host.expand = 1 if layout.width < 1200 else 5
        navigation.visible = not (layout.short and state.get("keyboard_open", False))
        quick_cart.visible = bool(state["current"] and order_count(current_order()) and not dual
                                  and not layout.short and state["tab"] == 0)

    async def on_workspace_size(e):
        window["layout"] = ui.WindowLayout(e.width, e.height)
        layout_workspace()
        refresh()

    async def on_window_resize(e=None):
        # SafeArea's measured workspace is the source of truth. This fallback
        # updates immediately when the host reports a new window size.
        window["layout"] = ui.WindowLayout(
            getattr(page, "width", None) or window["layout"].width,
            max(0, (getattr(page, "height", None) or window["layout"].height) - 64),
        )
        layout_workspace()
        apply_admin_density()
        admin_narrow = window["layout"].width < 600
        admin_catalogue.col = admin_category.col = 12 if admin_narrow else 6
        refresh()

    async def on_media_change(e=None):
        media = getattr(page, "media", None)
        state["keyboard_open"] = bool(media and (media.view_insets.bottom or 0) > 0)
        layout_workspace()
        refresh()

    page.on_resize = on_window_resize
    page.on_media_change = on_media_change

    def toggle_theme(e=None):
        dark = page.theme_mode == ft.ThemeMode.DARK or (
            page.theme_mode == ft.ThemeMode.SYSTEM
            and getattr(page, "platform_brightness", None) == ft.Brightness.DARK
        )
        page.theme_mode = ft.ThemeMode.LIGHT if dark else ft.ThemeMode.DARK
        theme_button.icon = ft.Icons.DARK_MODE_OUTLINED if dark else ft.Icons.LIGHT_MODE_OUTLINED

    theme_button = ft.IconButton(
        icon=ft.Icons.CONTRAST, tooltip="Changer le thème clair / sombre",
        width=48, height=48, on_click=toggle_theme,
    )
    page.appbar = ft.AppBar(
        leading=ft.IconButton(icon=ft.Icons.MENU, tooltip="Commandes", on_click=open_drawer,
                              width=48, height=48),
        title=ft.Column([appbar_title, order_info], spacing=2, tight=True),
        actions=[theme_button, ft.IconButton(
            icon=ft.Icons.ADD, tooltip="Nouvelle commande", width=48, height=48,
            on_click=create_order_dialog,
        )],
    )
    page.drawer = drawer

    empty_state = ft.ListView(expand=True, controls=[ui.empty(
        ft.Icons.RECEIPT_LONG, "Votre prochaine commande commence ici",
        "Un client, une salle, un projet. Créez une commande, choisissez votre matériel "
        "et retrouvez tous vos éléments au même endroit.",
        ui.button(content="Créer une commande", icon=ft.Icons.ADD, on_click=create_order_dialog),
    )], padding=24)
    body = ft.Container(expand=True, content=workspace, on_size_change=on_workspace_size,
                        size_change_interval=100)
    page.add(ft.SafeArea(expand=True, content=body, maintain_bottom_view_padding=True))
    render_catalogue()
    render_all()

    # Sauvegardes de démarrage : seulement si quelque chose a été converti ou créé
    if migrated:
        persist()
    if not prefs_path().exists():
        persist_prefs()  # garde les réglages par défaut (articles masqués par défaut)
    refresh()  # page.add() a déjà rafraîchi l'écran : on envoie le catalogue et le menu remplis ensuite

    if startup_warnings:
        page.show_dialog(ft.AlertDialog(
            scrollable=True,
            modal=True,
            title=ui.text("Attention"),
            content=ui.text("\n\n".join(startup_warnings)),
            actions=[ui.button(content="OK", on_click=lambda e: page.pop_dialog())],
        ))


# Démarrage de l'application
if __name__ == "__main__":
    ft.run(main)
