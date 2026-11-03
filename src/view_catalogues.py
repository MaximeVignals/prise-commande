import flet as ft

if __package__:
    from . import ui, storage
    from .config import DEFAULT_CATALOGUE, DEFAULT_CATALOGUE_LABEL
    from .text import fold, norm_text
    from .catalogue import install_catalogue
    from .import_screen import pick_catalogue_file, skipped_summary
    from .context import AppContext
else:
    import ui
    import storage
    from config import DEFAULT_CATALOGUE, DEFAULT_CATALOGUE_LABEL
    from text import fold, norm_text
    from catalogue import install_catalogue
    from import_screen import pick_catalogue_file, skipped_summary
    from context import AppContext


def install(ctx: AppContext) -> None:
    # --- ÉCRAN « GÉRER LES CATALOGUES » ---
    catalogues_listview = ft.ListView(expand=True, spacing=12)
    catalogues_summary = ui.text("", weight=ft.FontWeight.W_600)

    def save_catalogue_changes(updated):
        # Enregistrer avant de modifier l'écran : une erreur disque ne doit pas effacer les données en mémoire.
        try:
            storage.save_prefs(updated)
        except OSError as err:
            ctx.show_snack(f"⚠️ Modification du catalogue impossible : {err}")
            ctx.refresh()
            return False
        ctx.prefs.clear()
        ctx.prefs.update(updated)
        ctx.rebuild_catalogue()
        return True

    def refresh_catalogues():
        ctx.render_catalogue()
        render_catalogues()
        ctx.render_all()
        ctx.refresh()

    def rename_catalogue_dialog(name):
        if name == DEFAULT_CATALOGUE or name not in ctx.managed_catalogues():
            return
        name_field = ui.field(label="Nom du catalogue", value=name, autofocus=True)

        def validate(e=None):
            new_name = norm_text(name_field.value or "")
            reserved = {fold(n) for n in ctx.managed_catalogues() if n != name}
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
                ctx.refresh()
                return
            name_field.error = None
            if new_name != name:
                snapshot = [{**item, "Catalogue": new_name if item["Catalogue"] == name else item["Catalogue"]}
                            for item in ctx.prefs.get("catalogue_items", ctx.excel_items)]
                custom = [{**item, "catalogue": new_name} if item.get("catalogue", DEFAULT_CATALOGUE) == name
                          else dict(item) for item in ctx.prefs["custom"]]
                hidden_catalogues = set(ctx.prefs["hidden_catalogues"])
                was_hidden = name in hidden_catalogues
                hidden_catalogues.discard(name)
                hidden_catalogues.discard(new_name)
                if was_hidden:
                    hidden_catalogues.add(new_name)
                if not save_catalogue_changes({**ctx.prefs, "catalogue_items": snapshot, "custom": custom,
                                               "hidden_catalogues": hidden_catalogues}):
                    return
                for dropdown in (ctx.catalogue_dropdown, ctx.admin_catalogue):
                    if dropdown.value == name:
                        dropdown.value = new_name
            ctx.page.pop_dialog()
            refresh_catalogues()

        name_field.on_submit = validate
        ctx.page.show_dialog(ft.AlertDialog(
            scrollable=True,
            modal=True, title=ui.text("Renommer le catalogue"),
            content=ft.Column([name_field], tight=True, width=ctx.dialog_width()),
            actions=[ft.TextButton(content="Annuler", on_click=lambda e: ctx.page.pop_dialog()),
                     ui.button(content="Renommer", on_click=validate)],
        ))

    def remove_catalogue_dialog(name):
        is_main = name == DEFAULT_CATALOGUE
        label = name or DEFAULT_CATALOGUE_LABEL

        def confirm(e=None):
            keys = {item["Cle"] for item in ctx.entries_in(name)}
            snapshot = [dict(item) for item in ctx.prefs.get("catalogue_items", ctx.excel_items)
                        if item["Catalogue"] != name]
            custom = [dict(item) for item in ctx.prefs["custom"]
                      if item.get("catalogue", DEFAULT_CATALOGUE) != name]
            hidden_catalogues = set(ctx.prefs["hidden_catalogues"])
            if not is_main:
                hidden_catalogues.discard(name)
            if not save_catalogue_changes({**ctx.prefs, "catalogue_items": snapshot, "custom": custom,
                    "hidden_catalogues": hidden_catalogues, "hidden": ctx.prefs["hidden"] - keys,
                    "prices": {key: value for key, value in ctx.prefs["prices"].items() if key not in keys}}):
                return
            ctx.page.pop_dialog()
            refresh_catalogues()

        ctx.page.show_dialog(ft.AlertDialog(
            scrollable=True,
            modal=True,
            title=ui.text("Vider le catalogue principal ?" if is_main else "Supprimer le catalogue ?"),
            content=ui.text(f"Les {len(ctx.entries_in(name))} article(s) de « {label} » seront retirés, "
                            "y compris les articles ajoutés manuellement.\n"
                            "Les commandes existantes sont conservées. Un nouvel import peut rétablir ces articles."),
            actions=[ft.TextButton(content="Annuler", on_click=lambda e: ctx.page.pop_dialog()),
                     ui.button(content="Vider" if is_main else "Supprimer", on_click=confirm,
                               style=ft.ButtonStyle(bgcolor=ft.Colors.ERROR, color=ft.Colors.ON_ERROR))],
        ))

    def set_catalogue_visible(name, visible):
        if visible:
            ctx.prefs["hidden_catalogues"].discard(name)
        else:
            ctx.prefs["hidden_catalogues"].add(name)
        ctx.persist_prefs()
        ctx.render_catalogue()
        render_catalogues()
        ctx.render_orders()
        ctx.refresh()

    def render_catalogues():
        catalogues_listview.controls.clear()
        names = ctx.managed_catalogues()
        n_visible = sum(name not in ctx.prefs["hidden_catalogues"] for name in names)
        catalogues_summary.value = f"{n_visible} catalogue(s) affiché(s) sur {len(names)}"
        for name in names:
            label = name or DEFAULT_CATALOGUE_LABEL
            visible = name not in ctx.prefs["hidden_catalogues"]
            count = len(ctx.entries_in(name))
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

    async def replace_catalogue(e=None):
        """☰ › Importer un catalogue : remplace le catalogue. Paniers, prix modifiés et articles
        masqués sont conservés pour les articles qui gardent le même nom et catalogue."""
        await ctx.close_drawer()
        try:
            picked = await pick_catalogue_file(ctx.file_picker)
            if picked is None:
                return  # annulé
            items, skipped = install_catalogue(*picked)
        except Exception as err:  # fichier invalide, illisible, ou sélecteur indisponible
            ctx.page.show_dialog(ft.AlertDialog(
                scrollable=True,
                title=ui.text("Import impossible"),
                content=ui.text(f"{err}\n\nLe catalogue actuel est conservé.", selectable=True),
                actions=[ft.TextButton(content="OK", on_click=lambda e: ctx.page.pop_dialog())],
            ))
            ctx.refresh()
            return
        old_keys = {it["Cle"] for it in ctx.cat["all"] if not it["Perso"]}
        ctx.prefs.pop("catalogue_items", None)  # le nouveau fichier remplace les modifications locales
        # Nouveaux articles marqués « Masqué » : masqués comme au premier lancement
        ctx.prefs["hidden"] |= {it["Cle"] for it in items if it["Masque"] and it["Cle"] not in old_keys}
        ctx.excel_items[:] = items
        ctx.rebuild_catalogue()
        ctx.persist_prefs()
        ctx.render_catalogue()
        ctx.render_all()
        message = f"✅ Catalogue importé : {len(items)} article(s)."
        if skipped:
            ctx.page.show_dialog(ft.AlertDialog(
                scrollable=True,
                title=ui.text("Catalogue importé"),
                content=ui.text(f"{len(items)} article(s) importé(s).\n\n{skipped_summary(skipped)}",
                                selectable=True),
                actions=[ft.TextButton(content="OK", on_click=lambda e: ctx.page.pop_dialog())],
            ))
        else:
            ctx.show_snack(message)
        ctx.refresh()

    ctx.render_catalogues = render_catalogues
    ctx.replace_catalogue = replace_catalogue
    ctx.catalogues_view = catalogues_view
