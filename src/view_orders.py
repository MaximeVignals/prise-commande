import copy
import shutil
from datetime import datetime

import logging
import flet as ft

if __package__:
    from . import ui, storage
    from .text import default_order_name, fmt_eur, matches_search, describe_error
    from .storage import photos_dir
    from .orders import duplicate_order, order_count, order_total
    from .context import AppContext
else:
    import ui
    import storage
    from text import default_order_name, fmt_eur, matches_search, describe_error
    from storage import photos_dir
    from orders import duplicate_order, order_count, order_total
    from context import AppContext

log = logging.getLogger("prise_commande")


EMPTY_START = "__vide__"
ORDER_SEARCH_MIN = 6  # nombre de commandes à partir duquel le menu propose une recherche


def install(ctx: AppContext) -> None:
    order_info = ui.text("", size=12, color=ui.MUTED)

    # Titre de la barre du haut = nom de la commande active
    appbar_title = ui.text("", max_lines=1, overflow=ft.TextOverflow.ELLIPSIS,
                           weight=ft.FontWeight.W_600)
    # Menu latéral (comme la liste des conversations de Claude) : rempli par render_orders()
    drawer = ft.NavigationDrawer(controls=[], selected_index=-1, bgcolor=ui.PANEL)

    # --- GESTION DES COMMANDES ---

    async def open_drawer(e=None):
        await ctx.page.show_drawer()

    async def close_drawer():
        await ctx.page.close_drawer()

    async def select_order(order_id):
        if order_id not in ctx.orders:
            return
        ctx.state["current"] = order_id
        ctx.persist()
        ctx.render_all()
        await close_drawer()
        ctx.show_snack(f"Commande active : {ctx.orders[order_id]['name']}")
        ctx.refresh()

    def ask_name(title, initial, on_ok, extra=()):
        """Petite boîte de dialogue avec un champ texte (création / renommage).
        extra : contrôles affichés sous le champ (choix du modèle à la création)."""
        name_field = ui.field(
            value=initial,
            label="Nom de la commande",
            hint_text="ex. Cabinet Dupont – salle 2",
            autofocus=True,
            capitalization=ft.TextCapitalization.SENTENCES,
        )

        def validate(e=None):
            ctx.page.pop_dialog()
            on_ok(name_field.value)
            ctx.refresh()

        name_field.on_submit = validate
        ctx.page.show_dialog(ft.AlertDialog(
            scrollable=True,
            modal=True,
            title=ui.text(title),
            content=ft.Container(width=ctx.dialog_width(), content=ft.Column(
                [name_field, *extra], tight=True, spacing=12)) if extra else name_field,
            actions=[
                ft.TextButton(content="Annuler", on_click=lambda e: ctx.page.pop_dialog()),
                ui.button(content="Valider", on_click=validate),
            ],
        ))

    async def create_order_dialog(e=None):
        await close_drawer()
        saved = ctx.load_templates()
        start = ui.dropdown(label="Départ", value=EMPTY_START, options=[
            ft.DropdownOption(key=EMPTY_START, text="Commande vide"),
            *[ft.DropdownOption(key=tid, text=f"Modèle : {t['name']}") for tid, t in saved.items()]])
        extra = [start] if saved else [ui.text(
            "Astuce : une commande peut être enregistrée comme modèle (menu ⋮ › Enregistrer comme modèle) "
            "pour repartir de ses articles.", size=12, color=ui.MUTED)]

        def created(order_id):
            ctx.state["show_archived"] = False
            ctx.render_all()
            ctx.go_to_tab(0)  # retour au catalogue pour remplir la nouvelle commande
            ctx.show_snack(f"🆕 Nouvelle commande : {ctx.current_order()['name']}")

        def done(name):
            if saved and start.value and start.value != EMPTY_START:
                # Rien n'est créé tant que la vérification n'est pas validée
                ctx.review_template(start.value, name, created)
                return
            ctx.new_order(name)
            ctx.persist()
            created(ctx.state["current"])

        ask_name("Nouvelle commande", default_order_name(), done, extra)

    async def rename_order_dialog(order_id):
        await close_drawer()

        def done(name):
            name = name.strip()
            if name and order_id in ctx.orders:
                ctx.orders[order_id]["name"] = name
                ctx.persist()
                ctx.render_all()

        ask_name("Renommer la commande", ctx.orders[order_id]["name"], done)

    async def duplicate_order_dialog(order_id):
        await close_drawer()

        def done(name):
            new_id = None
            try:
                new_id, duplicate = duplicate_order(order_id, ctx.orders[order_id], name, ctx.orders)
                storage.save_orders({**ctx.orders, new_id: duplicate}, new_id)
            except OSError as err:
                log.exception("Erreur affichée à l'utilisateur")
                if new_id:
                    folder = photos_dir(new_id)
                    for path in folder.glob("*"):
                        path.unlink()
                    if folder.exists():
                        folder.rmdir()
                ctx.show_snack(f"Duplication impossible : {describe_error(err)}")
                return
            ctx.orders[new_id] = duplicate
            ctx.state.update(current=new_id, show_archived=False)
            ctx.render_all()
            ctx.go_to_tab(0)
            ctx.show_snack("Commande dupliquée, avec ses remarques et photos.")

        ask_name("Dupliquer la commande", f"{ctx.orders[order_id]['name']} — copie", done)

    async def archive_order(order_id):
        await close_drawer()
        updated = copy.deepcopy(ctx.orders)
        archived = not updated[order_id].get("archived", False)
        if archived:
            updated[order_id]["archived"] = True
        else:
            updated[order_id].pop("archived", None)
        selected = ctx.state["current"]
        if archived and selected == order_id:
            selected = next((k for k in reversed(updated) if not updated[k].get("archived")), None)
        elif not archived:
            selected = order_id
        try:
            storage.save_orders(updated, selected)
        except OSError as err:
            log.exception("Erreur affichée à l'utilisateur")
            ctx.show_snack(f"Archivage impossible : {describe_error(err)}")
            ctx.refresh()
            return
        ctx.orders.clear()
        ctx.orders.update(updated)
        ctx.state["current"] = selected
        ctx.state["show_archived"] = archived
        ctx.render_all()
        ctx.show_snack("Commande archivée." if archived else "Commande réactivée.")
        ctx.refresh()

    def show_order_group(e=None):
        ctx.state["show_archived"] = not ctx.state["show_archived"]
        render_orders()

    def edit_notes(e=None, key=None):
        order = ctx.current_order()
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
                storage.save_orders(ctx.orders, ctx.state["current"])
            except OSError as err:
                log.exception("Erreur affichée à l'utilisateur")
                if previous is None:
                    target.pop(attribute, None)
                else:
                    target[attribute] = previous
                field.error = f"Enregistrement impossible : {describe_error(err)}"
                ctx.refresh()
                return
            ctx.page.pop_dialog()
            ctx.render_all()
            ctx.refresh()

        ctx.page.show_dialog(ft.AlertDialog(scrollable=True, title=ui.text(
            "Remarques de la commande" if key is None else target["Nom"]),
            content=ft.Container(content=field, width=ctx.dialog_width()),
            actions=[ft.TextButton(content="Annuler", on_click=lambda e: ctx.page.pop_dialog()),
                     ui.button(content="Enregistrer", on_click=save)]))

    async def delete_order_dialog(order_id):
        await close_drawer()
        order = ctx.orders[order_id]

        def confirm(e):
            ctx.page.pop_dialog()
            if order_id not in ctx.orders:  # double appui sur « Supprimer »
                return
            del ctx.orders[order_id]
            shutil.rmtree(photos_dir(order_id), ignore_errors=True)  # ses photos aussi
            if ctx.state["current"] == order_id:
                # la plus récente restante, ou aucune → écran d'aide
                ctx.state["current"] = next((k for k in reversed(ctx.orders) if not ctx.orders[k].get("archived")), None)
            ctx.persist()
            ctx.render_all()
            ctx.show_snack(f"🗑️ « {order['name']} » supprimée.")
            ctx.refresh()

        async def archive_instead(e):
            ctx.page.pop_dialog()
            if order_id in ctx.orders:
                await archive_order(order_id)

        can_archive = not order.get("archived")
        ctx.page.show_dialog(ft.AlertDialog(
            scrollable=True,
            modal=True,
            title=ui.text("Supprimer la commande ?"),
            content=ui.text(
                f"« {order['name']} » ({order_count(order)} article(s), "
                f"{fmt_eur(order_total(order))}) sera définitivement supprimée."
                + (f"\nSes {len(order.get('photos', []))} photo(s) aussi."
                   if order.get("photos") else "")
                + ("\n\nPour la retirer de la liste sans la perdre, archivez-la plutôt."
                   if can_archive else "")
            ),
            actions=[
                ft.TextButton(content="Annuler", on_click=lambda e: ctx.page.pop_dialog()),
                *([ft.TextButton(content="Archiver plutôt", icon=ft.Icons.ARCHIVE_OUTLINED,
                                 on_click=archive_instead)] if can_archive else []),
                ui.button(
                    content="Supprimer",
                    on_click=confirm,
                    style=ft.ButtonStyle(bgcolor=ft.Colors.ERROR, color=ft.Colors.ON_ERROR),
                ),
            ],
        ))


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

        async def on_template(e):
            await ctx.save_template_dialog(order_id)

        async def on_notes(e):
            await select_order(order_id)
            edit_notes()

        return on_select, on_rename, on_delete, on_duplicate, on_archive, on_notes, on_template

    # --- MENU LATÉRAL : commandes d'abord, réglages en bas ---
    def is_dark():
        return ctx.page.theme_mode == ft.ThemeMode.DARK or (
            ctx.page.theme_mode == ft.ThemeMode.SYSTEM
            and getattr(ctx.page, "platform_brightness", None) == ft.Brightness.DARK
        )

    theme_title = ui.text("", weight=ft.FontWeight.W_500)
    theme_icon = ft.Icon(ft.Icons.DARK_MODE_OUTLINED, color=ft.Colors.PRIMARY)

    def update_theme_tile():
        theme_title.value = "Passer en thème clair" if is_dark() else "Passer en thème sombre"
        theme_icon.icon = ft.Icons.LIGHT_MODE_OUTLINED if is_dark() else ft.Icons.DARK_MODE_OUTLINED

    def toggle_theme(e=None):
        ctx.page.theme_mode = ft.ThemeMode.LIGHT if is_dark() else ft.ThemeMode.DARK
        update_theme_tile()

    async def on_order_search(e=None):
        render_order_tiles()

    # Champs gardés d'un rendu à l'autre : la saisie et le clavier restent en place.
    order_search = ui.field(
        label="Rechercher une commande", hint_text="Nom, date (ex. 03/11)…",
        prefix_icon=ft.Icons.SEARCH, dense=True, on_change=on_order_search,
    )
    order_search_box = ft.Container(content=order_search, visible=False,
                                    padding=ft.Padding.symmetric(horizontal=12, vertical=4))
    orders_label = ui.text("Commandes", size=12, weight=ft.FontWeight.W_600,
                           color=ft.Colors.ON_SURFACE_VARIANT, expand=True)
    archive_toggle = ft.TextButton(icon=ft.Icons.ARCHIVE_OUTLINED, on_click=lambda e: show_order_group(e))
    orders_column = ft.Column(spacing=0, tight=True)

    def settings_tile(icon, title, subtitle, on_click, leading=None):
        return ft.Container(
            padding=ft.Padding.symmetric(horizontal=8),
            content=ft.ListTile(
                dense=True,
                shape=ft.RoundedRectangleBorder(radius=10),
                leading=leading or ft.Icon(icon, color=ft.Colors.PRIMARY),
                title=title if isinstance(title, ft.Text) else ui.text(title, weight=ft.FontWeight.W_500),
                subtitle=ui.text(subtitle, size=12) if subtitle else None,
                on_click=on_click,
            ),
        )

    def drawer_header():
        return [
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
            order_search_box,
            ft.Container(
                padding=ft.Padding.only(left=16, right=8, top=8),
                content=ft.Row([orders_label, archive_toggle]),
            ),
            orders_column,
        ]

    def drawer_settings():
        n_total = len(ctx.cat["all"])
        n_visible = len(ctx.visible_entries())
        names = ctx.managed_catalogues()
        n_catalogues_visible = sum(name not in ctx.prefs["hidden_catalogues"] for name in names)
        update_theme_tile()
        return [
            ft.Divider(height=1),
            ft.Container(
                padding=ft.Padding.only(left=16, top=12, bottom=4),
                content=ui.text("Réglages", size=12, weight=ft.FontWeight.W_600,
                                color=ft.Colors.ON_SURFACE_VARIANT),
            ),
            settings_tile(ft.Icons.FOLDER_OUTLINED, "Gérer les catalogues",
                          f"{n_catalogues_visible} affichés sur {len(names)}", ctx.open_catalogue_manager),
            settings_tile(ft.Icons.TUNE, "Gérer les articles",
                          f"{n_visible} affichés sur {n_total}", ctx.open_admin),
            settings_tile(ft.Icons.UPLOAD_FILE, "Importer un catalogue",
                          "Remplace le catalogue actuel (.xlsx ou .csv)", ctx.replace_catalogue),
            settings_tile(ft.Icons.BOOKMARKS_OUTLINED, "Modèles de commande",
                          "Renommer ou supprimer", ctx.open_template_manager),
            settings_tile(ft.Icons.BACKUP_OUTLINED, "Sauvegarder / restaurer", None, ctx.open_backup_view),
            settings_tile(None, theme_title, None, toggle_theme, leading=theme_icon),
            ft.Container(height=12),
        ]

    # Ligne « date · articles · total » de chaque commande du menu, pour la mettre à jour
    # seule après un changement du panier (sans reconstruire tout le menu).
    order_summaries = {}

    def order_summary_text(order):
        created = datetime.fromisoformat(order["created"]).strftime("%d/%m")
        return (f"{created} · {order_count(order)} art. · {fmt_eur(order_total(order))}"
                + (f" · 📷 {len(order['photos'])}" if order.get("photos") else ""))

    def update_order_summary(order_id=None):
        order_id = order_id or ctx.state["current"]
        text = order_summaries.get(order_id)
        if text is not None and order_id in ctx.orders:
            text.value = order_summary_text(ctx.orders[order_id])

    def order_tile(order_id, order, show_archived_mark=False):
        is_active = order_id == ctx.state["current"]
        on_select, on_rename, on_delete, on_duplicate, on_archive, on_notes, on_template = order_handlers(order_id)
        summary = ui.text(order_summary_text(order) + (" · archivée" if show_archived_mark else ""), size=12)
        order_summaries[order_id] = summary

        return ft.Container(
            padding=ft.Padding.symmetric(horizontal=8),
            content=ft.ListTile(
                dense=True,
                shape=ft.RoundedRectangleBorder(radius=10),
                title=ui.text(
                    order["name"], max_lines=1, overflow=ft.TextOverflow.ELLIPSIS,
                    weight=ft.FontWeight.BOLD if is_active else ft.FontWeight.NORMAL,
                ),
                subtitle=summary,
                trailing=ft.PopupMenuButton(
                    icon=ft.Icons.MORE_VERT,
                    tooltip="Options",
                    items=[
                        ft.PopupMenuItem(content="Remarques", icon=ft.Icons.NOTES, on_click=on_notes),
                        ft.PopupMenuItem(content="Dupliquer", icon=ft.Icons.CONTENT_COPY,
                            on_click=on_duplicate),
                        ft.PopupMenuItem(content="Enregistrer comme modèle", icon=ft.Icons.BOOKMARK_ADD_OUTLINED,
                            on_click=on_template),
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

    def order_matches(order, query):
        created = datetime.fromisoformat(order["created"]).strftime("%d/%m/%Y") if order.get("created") else ""
        return matches_search(f"{order['name']} {created}", query)

    def drawer_note(message):
        return ft.Container(padding=ft.Padding.symmetric(horizontal=16, vertical=8), content=ui.text(
            message, size=13, italic=True, color=ft.Colors.ON_SURFACE_VARIANT))

    def render_order_tiles():
        """Liste des commandes seule : la recherche la refait sans toucher au reste du menu."""
        order_summaries.clear()
        query = (order_search.value or "").strip() if order_search_box.visible else ""
        archives = sum(bool(order.get("archived")) for order in ctx.orders.values())
        archive_toggle.content = "Commandes actives" if ctx.state["show_archived"] else f"Archives ({archives})"
        archive_toggle.visible = not query  # la recherche couvre actives et archivées
        orders_label.value = "Résultats" if query else (
            "Commandes archivées" if ctx.state["show_archived"] else "Commandes")

        tiles = []
        # Les plus récentes en premier (le dict garde l'ordre de création)
        for order_id in reversed(list(ctx.orders)):
            order = ctx.orders[order_id]
            archived = bool(order.get("archived"))
            if query:
                if order_matches(order, query):
                    tiles.append(order_tile(order_id, order, show_archived_mark=archived))
            elif archived == ctx.state["show_archived"]:
                tiles.append(order_tile(order_id, order))

        if not ctx.orders:
            tiles.append(drawer_note("Aucune commande pour l'instant.\n"
                                     "Appuyez sur « Nouvelle commande » pour commencer."))
        elif not tiles:
            tiles.append(drawer_note(
                "Aucune commande ne correspond." if query
                else "Aucune commande archivée." if ctx.state["show_archived"] else "Aucune commande active."))
        orders_column.controls = tiles

    def render_orders():
        # La recherche n'apparaît que quand la liste devient longue.
        order_search_box.visible = len(ctx.orders) >= ORDER_SEARCH_MIN
        render_order_tiles()
        drawer.controls = drawer_header() + drawer_settings()

    ctx.render_orders = render_orders
    ctx.update_order_summary = update_order_summary  # partagé avec view_cart
    ctx.create_order_dialog = create_order_dialog
    ctx.archive_order = archive_order
    ctx.open_drawer = open_drawer
    ctx.close_drawer = close_drawer
    ctx.edit_notes = edit_notes
    ctx.drawer = drawer
    ctx.appbar_title = appbar_title
    ctx.order_info = order_info
