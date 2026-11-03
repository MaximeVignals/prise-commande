import flet as ft

if __package__:
    from . import ui, storage
    from .ui import get_category_icon
    from .config import ALL_CATALOGUES
    from .text import fmt_eur, matches_search
    from .catalogue import categories_of
    from .context import AppContext
else:
    import ui
    import storage
    from ui import get_category_icon
    from config import ALL_CATALOGUES
    from text import fmt_eur, matches_search
    from catalogue import categories_of
    from context import AppContext


def install(ctx: AppContext) -> None:
    async def on_catalogue_filter(e=None):
        render_catalogue()
        ctx.refresh()
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
    catalogue_info = ui.text("", size=12, color=ui.MUTED)

    def add_to_cart(item, qty):
        try:
            qty = int(qty)
        except (TypeError, ValueError):
            ctx.show_snack("Quantité invalide.")
            return
        if qty <= 0:
            ctx.show_snack("Quantité invalide.")
            return

        items = ctx.cart()
        if item["Cle"] in items:
            items[item["Cle"]]["quantite"] += qty
        else:
            items[item["Cle"]] = {
                "Nom": item["Nom_Article"],
                "Prix": item["Prix_Unitaire"],
                "quantite": qty,
            }
        ctx.persist()
        ctx.prefs["recent"] = [item["Cle"]] + [key for key in ctx.prefs["recent"] if key != item["Cle"]][:19]
        ctx.persist_prefs()
        if browse_mode.selected == ["recent"]:
            render_catalogue()
        ctx.render_all()
        ctx.show_snack(f"✅ Ajouté au panier (x{qty})")
        ctx.refresh()

    # --- RENDU CATALOGUE ---
    def render_catalogue():
        catalogue_listview.controls.clear()
        ctx.catalogue_grids.clear()
        ctx.catalogue_rows.clear()
        ctx.catalogue_badges.clear()
        ctx.favorite_buttons.clear()
        previous_catalogue = catalogue_dropdown.value
        ctx.update_catalogue_selector(catalogue_dropdown)
        if catalogue_dropdown.value != previous_catalogue:
            category_dropdown.value = "Toutes"
        has_catalogue = catalogue_dropdown.value is not None
        search_input.disabled = not has_catalogue
        category_dropdown.disabled = not has_catalogue
        shown = [entry for entry in ctx.entries_in(catalogue_dropdown.value) if entry["Visible"]]
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
            filtered = [it for it in filtered if it["Cle"] in ctx.prefs["favorites"]]
        elif mode == "recent":
            filtered = sorted((it for it in filtered if it["Cle"] in ctx.prefs["recent"]),
                              key=lambda it: ctx.prefs["recent"].index(it["Cle"]))
        # Recents keep chronological order instead of being regrouped by category.
        groups = [("Articles récents", filtered)] if mode == "recent" else [
            (category, [it for it in filtered if it["Categorie"] == category]) for category in categories]
        catalogue_info.value = f"{len(filtered)} article(s) · {len(categories_of(filtered))} catégorie(s)"
        render_filter_tags()

        if not has_catalogue:
            catalogue_listview.controls.extend([
                ui.text("Aucun catalogue affiché. Activez un catalogue pour parcourir ses articles.",
                        italic=True, color=ft.Colors.ON_SURFACE_VARIANT),
                ft.TextButton(content="Gérer les catalogues", on_click=ctx.open_catalogue_manager),
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
                draft_key = (ctx.state["current"], current_item["Cle"])
                qty_field = ui.field(
                    value=ctx.quantity_drafts.get(draft_key, "1"), width=64, text_align=ft.TextAlign.CENTER,
                    keyboard_type=ft.KeyboardType.NUMBER,
                    input_filter=ft.NumbersOnlyInputFilter(),
                    dense=True, tooltip=f"Quantité à ajouter : {current_item['Nom_Article']}",
                    on_change=lambda e, k=draft_key: ctx.quantity_drafts.__setitem__(k, e.control.value),
                )
                def adjust(e, q=qty_field, k=draft_key, delta=1):
                    ctx.change_qty_field(q, delta)
                    ctx.quantity_drafts[k] = q.value

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
                    icon=ft.Icons.STAR if current_item["Cle"] in ctx.prefs["favorites"] else ft.Icons.STAR_BORDER,
                    icon_color=ui.PRIMARY, width=48, height=48,
                    tooltip=f"Favori : {current_item['Nom_Article']}",
                    on_click=lambda e, k=current_item["Cle"]: toggle_favorite(k),
                )
                ctx.favorite_buttons[current_item["Cle"]] = favorite
                badge = ui.text("", size=12, color=ui.PRIMARY, visible=False)
                ctx.catalogue_badges[current_item["Cle"]] = badge
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
                ctx.catalogue_rows[id(card)] = (compact, wide)
                group_cards.append(card)
            grid = ft.ResponsiveRow(group_cards, spacing=8, run_spacing=8)
            ctx.catalogue_grids.append(grid)
            catalogue_listview.controls.append(grid)
        ctx.apply_catalogue_columns()
        update_catalogue_badges()
        ctx.state["catalogue_order"] = ctx.state["current"]
        # Plus besoin de page.update() : Flet 1.0 met à jour automatiquement
        # après chaque gestionnaire d'événement et après main().

    def reset_filters(e=None):
        search_input.value = ""
        category_dropdown.value = "Toutes"
        browse_mode.selected = ["all"]
        render_catalogue()
        ctx.refresh()

    def toggle_favorite(key):
        previous = set(ctx.prefs["favorites"])
        if key in ctx.prefs["favorites"]:
            ctx.prefs["favorites"].remove(key)
        else:
            ctx.prefs["favorites"].add(key)
        try:
            storage.save_prefs(ctx.prefs)
        except OSError as err:
            ctx.prefs["favorites"] = previous
            ctx.show_snack(f"Favori non enregistré : {err}")
            ctx.refresh()
            return
        if browse_mode.selected == ["favorites"]:
            render_catalogue()
        else:
            ctx.favorite_buttons[key].icon = ft.Icons.STAR if key in ctx.prefs["favorites"] else ft.Icons.STAR_BORDER
        ctx.refresh()

    def update_catalogue_badges():
        items = ctx.cart() if ctx.state["current"] else {}
        for key, badge in ctx.catalogue_badges.items():
            quantity = items.get(key, {}).get("quantite", 0)
            badge.value = f"Déjà {quantity} dans la commande" if quantity else ""
            badge.visible = quantity > 0

    def render_filter_tags():
        tags = []
        def clear(attribute, value):
            setattr(attribute, "value", value)
            render_catalogue()
            ctx.refresh()
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

    def toggle_filters(e=None):
        ctx.state["filters_open"] = not ctx.state["filters_open"]
        ctx.apply_filter_layout()

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

    ctx.render_catalogue = render_catalogue
    ctx.update_catalogue_badges = update_catalogue_badges
    ctx.content_catalogue = content_catalogue
    ctx.catalogue_heading = catalogue_heading
    ctx.catalogue_dropdown = catalogue_dropdown
    ctx.category_dropdown = category_dropdown
    ctx.catalogue_info = catalogue_info
    ctx.browse_row = browse_row
    ctx.filter_button = filter_button
    ctx.filter_details = filter_details
