import uuid

import flet as ft

if __package__:
    from . import ui
    from .ui import get_category_icon
    from .config import KEY_PERSO
    from .text import _to_price, fmt_eur, fmt_input, matches_search, norm_text
    from .catalogue import categories_of
    from .context import AppContext
else:
    import ui
    from ui import get_category_icon
    from config import KEY_PERSO
    from text import _to_price, fmt_eur, fmt_input, matches_search, norm_text
    from catalogue import categories_of
    from context import AppContext


def install(ctx: AppContext) -> None:
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
            e for e in ctx.entries_in(admin_catalogue.value)
            if matches_search(e["Nom_Article"], search_val)
            and (cat_val == "Toutes" or e["Categorie"] == cat_val)
            and (visibility == "tous" or e["Visible"] == (visibility == "affiches"))
        ]

    async def on_admin_filter(e=None):
        render_admin()
        ctx.refresh()
        await admin_listview.scroll_to(offset=0)  # résultats affichés depuis le début

    async def on_admin_catalogue_select(e=None):
        admin_category.value = "Toutes"
        await on_admin_filter()

    admin_catalogue.on_select = on_admin_catalogue_select
    admin_search.on_change = on_admin_filter
    admin_category.on_select = on_admin_filter
    admin_visibility.on_change = on_admin_filter

    def refresh_admin_info():
        entries = ctx.entries_in(admin_catalogue.value)
        n_visible = sum(entry["Visible"] for entry in entries)
        n_total = len(entries)
        labels = {"tous": "Tous", "affiches": "Affichés", "masques": "Masqués"}
        for segment in admin_visibility.segments:
            segment.label = labels[segment.value]
        admin_info.value = f"{n_visible} articles affichés sur {n_total} · prix enregistrés automatiquement"

    def refresh_admin_row(key):
        refs = admin_rows.get(key)
        entry = ctx.entry_by_key(key)
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
        entries = [ctx.entry_by_key(k) for k in keys]
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
                ctx.prefs["hidden"].discard(key)
            else:
                ctx.prefs["hidden"].add(key)
        ctx.persist_prefs()
        ctx.rebuild_catalogue()
        for key in keys:
            refresh_admin_row(key)
        for categorie in {ctx.entry_by_key(k)["Categorie"] for k in keys if ctx.entry_by_key(k)}:
            refresh_admin_header(categorie)
        refresh_admin_info()
        ctx.refresh()

    def toggle_category(categorie):
        # Tout est coché → on décoche tout ; sinon on coche tout (articles affichés par le filtre)
        keys = admin_headers[categorie][2]
        all_visible = all(ctx.entry_by_key(k)["Visible"] for k in keys)
        set_visible(keys, not all_visible)

    def commit_price(key, field, final):
        """Enregistre le prix saisi. final=True (sortie du champ / Entrée) : remet le champ au propre."""
        entry = ctx.entry_by_key(key)
        if not entry:
            return
        price = _to_price(field.value)
        if price is None or price < 0:
            if final:
                field.value = fmt_input(entry['Prix_Unitaire'])
                ctx.show_snack("Prix invalide : saisissez un nombre, ex. 1190 ou 79,50.")
                ctx.refresh()
            return
        price = round(price, 2)
        if entry["Perso"]:
            for c in ctx.prefs["custom"]:
                if c["key"] == key:
                    c["price"] = price
        elif abs(price - entry["Prix_Excel"]) < 0.005:
            ctx.prefs["prices"].pop(key, None)  # retour au prix de l'Excel
        else:
            ctx.prefs["prices"][key] = price
        if abs(price - entry["Prix_Unitaire"]) >= 0.005:
            ctx.persist_prefs()
            ctx.rebuild_catalogue()
            refresh_admin_row(key)
        if final:
            field.value = fmt_input(price)

    def reset_price(key, field):
        ctx.prefs["prices"].pop(key, None)
        ctx.persist_prefs()
        ctx.rebuild_catalogue()
        entry = ctx.entry_by_key(key)
        field.value = fmt_input(entry['Prix_Unitaire'])
        refresh_admin_row(key)
        ctx.show_snack(f"Prix Excel rétabli : {fmt_eur(entry['Prix_Unitaire'])}")
        ctx.refresh()

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
        width = ctx.window["layout"].width
        columns = 3 if width >= 1100 else 2 if width >= 680 else 1
        card_width = (width - 32 - (columns - 1) * 8) / columns
        for refs in admin_rows.values():
            refs["card"].content = refs["wide"] if card_width >= 340 else refs["compact"]

    def render_admin():
        admin_listview.controls.clear()
        admin_rows.clear()
        admin_headers.clear()

        ctx.update_catalogue_selector(admin_catalogue, include_hidden=True)
        categories = categories_of(ctx.entries_in(admin_catalogue.value))
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
        categories = categories_of(ctx.entries_in(catalogue))
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
            width=ctx.dialog_width(),
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
            ctx.page.pop_dialog()
            ctx.prefs["custom"].append({
                "key": KEY_PERSO + uuid.uuid4().hex[:8],
                "name": name,
                "category": category,
                "catalogue": catalogue,
                "price": round(price, 2),
            })
            ctx.persist_prefs()
            ctx.rebuild_catalogue()
            render_admin()
            ctx.show_snack(f"➕ « {name} » ajouté dans « {category} »")
            ctx.refresh()

        name_field.on_submit = validate
        price_field.on_submit = validate
        ctx.page.show_dialog(ft.AlertDialog(
            scrollable=True,
            modal=True,
            title=ui.text("Ajouter un article"),
            content=ft.Column([name_field, cat_field, new_cat_field, price_field],
                              tight=True, spacing=12, width=ctx.dialog_width()),
            actions=[
                ft.TextButton(content="Annuler", on_click=lambda e: ctx.page.pop_dialog()),
                ui.button(content="Ajouter", on_click=validate),
            ],
        ))

    def delete_article_dialog(key):
        entry = ctx.entry_by_key(key)
        if not entry:
            return

        def confirm(e):
            ctx.page.pop_dialog()
            if not any(c["key"] == key for c in ctx.prefs["custom"]):  # double appui
                return
            ctx.prefs["custom"] = [c for c in ctx.prefs["custom"] if c["key"] != key]
            ctx.prefs["hidden"].discard(key)
            ctx.persist_prefs()
            ctx.rebuild_catalogue()
            render_admin()
            ctx.show_snack(f"🗑️ « {entry['Nom_Article']} » supprimé du catalogue.")
            ctx.refresh()

        ctx.page.show_dialog(ft.AlertDialog(
            scrollable=True,
            modal=True,
            title=ui.text("Supprimer l'article ?"),
            content=ui.text(f"« {entry['Nom_Article']} » sera retiré du catalogue.\n"
                            "Les commandes qui le contiennent déjà ne changent pas."),
            actions=[
                ft.TextButton(content="Annuler", on_click=lambda e: ctx.page.pop_dialog()),
                ui.button(content="Supprimer", on_click=confirm,
                          style=ft.ButtonStyle(bgcolor=ft.Colors.ERROR, color=ft.Colors.ON_ERROR)),
            ],
        ))

    admin_info = ui.text("", size=12, color=ui.MUTED)
    admin_listview.spacing = 6
    admin_search.expand = True
    admin_catalogue.col = admin_category.col = 12
    admin_filter_details = ft.ResponsiveRow([admin_catalogue, admin_category], spacing=12, run_spacing=12)
    admin_filter_details.visible = ctx.window["layout"].width >= 600 and not ctx.window["layout"].short

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

    ctx.apply_admin_density = apply_admin_density
    ctx.render_admin = render_admin
    ctx.admin_catalogue = admin_catalogue
    ctx.admin_category = admin_category
    ctx.admin_view = admin_view
