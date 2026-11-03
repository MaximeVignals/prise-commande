import copy
import shutil
from datetime import datetime

import flet as ft

if __package__:
    from . import ui, storage
    from .text import default_order_name, fmt_eur
    from .storage import photos_dir
    from .orders import duplicate_order, order_count, order_total
    from .context import AppContext
else:
    import ui
    import storage
    from text import default_order_name, fmt_eur
    from storage import photos_dir
    from orders import duplicate_order, order_count, order_total
    from context import AppContext


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
            ctx.page.pop_dialog()
            on_ok(name_field.value)
            ctx.refresh()

        name_field.on_submit = validate
        ctx.page.show_dialog(ft.AlertDialog(
            scrollable=True,
            modal=True,
            title=ui.text(title),
            content=name_field,
            actions=[
                ft.TextButton(content="Annuler", on_click=lambda e: ctx.page.pop_dialog()),
                ui.button(content="Valider", on_click=validate),
            ],
        ))

    async def create_order_dialog(e=None):
        await close_drawer()

        def done(name):
            ctx.new_order(name)
            ctx.state["show_archived"] = False
            ctx.persist()
            ctx.render_all()
            ctx.go_to_tab(0)  # retour au catalogue pour remplir la nouvelle commande
            ctx.show_snack(f"🆕 Nouvelle commande : {ctx.current_order()['name']}")

        ask_name("Nouvelle commande", default_order_name(), done)

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
                if new_id:
                    folder = photos_dir(new_id)
                    for path in folder.glob("*"):
                        path.unlink()
                    if folder.exists():
                        folder.rmdir()
                ctx.show_snack(f"Duplication impossible : {err}")
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
            ctx.show_snack(f"Archivage impossible : {err}")
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
                if previous is None:
                    target.pop(attribute, None)
                else:
                    target[attribute] = previous
                field.error = f"Enregistrement impossible : {err}"
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

        ctx.page.show_dialog(ft.AlertDialog(
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
                ft.TextButton(content="Annuler", on_click=lambda e: ctx.page.pop_dialog()),
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

        async def on_notes(e):
            await select_order(order_id)
            edit_notes()

        return on_select, on_rename, on_delete, on_duplicate, on_archive, on_notes

    def render_orders():
        n_total = len(ctx.cat["all"])
        n_visible = len(ctx.visible_entries())
        names = ctx.managed_catalogues()
        n_catalogues_visible = sum(name not in ctx.prefs["hidden_catalogues"] for name in names)
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
                    on_click=ctx.open_catalogue_manager,
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
                    on_click=ctx.open_admin,
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
                    on_click=ctx.replace_catalogue,
                ),
            ),
            ft.Divider(height=1),
            ft.Container(
                padding=ft.Padding.only(left=16, top=12, bottom=4),
                content=ui.text("Commandes", size=12, weight=ft.FontWeight.W_600,
                                color=ft.Colors.ON_SURFACE_VARIANT),
            ),
        ]

        if not ctx.orders:
            controls.append(ft.Container(
                padding=ft.Padding.symmetric(horizontal=16, vertical=8),
                content=ui.text(
                    "Aucune commande pour l'instant.\n"
                    "Appuyez sur « Nouvelle commande » pour commencer.",
                    size=13, italic=True, color=ft.Colors.ON_SURFACE_VARIANT,
                ),
            ))

        # Les plus récentes en premier (le dict garde l'ordre de création)
        for order_id in reversed(list(ctx.orders)):
            order = ctx.orders[order_id]
            if bool(order.get("archived")) != ctx.state["show_archived"]:
                continue
            is_active = order_id == ctx.state["current"]
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

        archives = sum(bool(order.get("archived")) for order in ctx.orders.values())
        controls.insert(6, ft.Container(padding=8, content=ft.Row([
            ft.TextButton(content="Commandes actives" if ctx.state["show_archived"] else f"Archives ({archives})",
                icon=ft.Icons.ARCHIVE_OUTLINED, on_click=show_order_group, expand=True),
        ])))
        controls.extend([
            ft.Divider(),
            ft.ListTile(title=ui.text("Sauvegarder / restaurer"), leading=ft.Icon(ft.Icons.BACKUP_OUTLINED),
                        on_click=ctx.open_backup_view),
        ])
        if not any(bool(order.get("archived")) == ctx.state["show_archived"] for order in ctx.orders.values()):
            controls.append(ft.Container(padding=16, content=ui.text(
                "Aucune commande archivée." if ctx.state["show_archived"] else "Aucune commande active.", color=ui.MUTED)))
        drawer.controls = controls

    ctx.render_orders = render_orders
    ctx.create_order_dialog = create_order_dialog
    ctx.archive_order = archive_order
    ctx.open_drawer = open_drawer
    ctx.close_drawer = close_drawer
    ctx.edit_notes = edit_notes
    ctx.drawer = drawer
    ctx.appbar_title = appbar_title
    ctx.order_info = order_info
