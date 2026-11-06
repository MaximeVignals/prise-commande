import flet as ft

if __package__:
    from . import ui
    from .storage import prefs_path
    from .orders import order_count
    from .context import AppContext
else:
    import ui
    from storage import prefs_path
    from orders import order_count
    from context import AppContext


def install(ctx: AppContext) -> None:
    # --- LOGIQUE ---

    def go_to_tab(index):
        ctx.state["tab"] = index
        navigation.selected_index = index
        ctx.set_header_collapsed(False)
        layout_workspace()
    ctx.go_to_tab = go_to_tab  # partagé avec view_cart

    def render_all():
        if ctx.state.get("catalogue_order", object()) != ctx.state["current"]:
            ctx.render_catalogue()
        if ctx.state["current"] is None:
            # Pas de commande : écran d'aide à la place du catalogue / panier
            ctx.appbar_title.value = "Prise de Commande"
            ctx.order_info.value = ""
            body.content = empty_state
        else:
            ctx.appbar_title.value = ctx.current_order()["name"]
            body.content = workspace
            ctx.render_cart()  # met aussi à jour les badges du catalogue
            ctx.render_photos()
            layout_workspace()
        if ctx.state["current"] is None:
            ctx.update_catalogue_badges()
        ctx.render_orders()
    ctx.render_all = render_all  # partagé avec view_cart

    def refresh_cart_state():
        """Après un changement du panier seulement (ajout, quantité, retrait) : le panier, ses
        résumés, les badges du catalogue et la ligne de la commande dans le menu.
        Les photos, le menu complet et la mise en page du catalogue ne changent pas."""
        ctx.render_cart()
        place_basket_footer()  # render_cart() vide la liste, qui peut contenir le total
        update_quick_cart()
    ctx.refresh_cart_state = refresh_cart_state  # partagé avec view_cart et view_catalogue

    file_picker = ft.FilePicker()  # services : on garde une référence
    ctx.file_picker = file_picker  # partagé avec view_catalogues

    async def open_admin(e=None):
        await ctx.close_drawer()
        await ctx.page.push_route("/articles")
    ctx.open_admin = open_admin  # partagé avec view_orders

    async def open_catalogue_manager(e=None):
        await ctx.close_drawer()
        await ctx.page.push_route("/catalogues")
    ctx.open_catalogue_manager = open_catalogue_manager  # partagé avec view_catalogue

    async def route_change(e=None):
        if ctx.page.route == "/sauvegarde":
            if len(ctx.page.views) == 1:
                ctx.page.views.append(ctx.backup_view)
        elif ctx.page.route == "/articles":
            if len(ctx.page.views) == 1:
                ctx.admin_catalogue.value = ctx.catalogue_dropdown.value
                ctx.render_admin()
                ctx.page.views.append(ctx.admin_view)
        elif ctx.page.route == "/catalogues":
            if len(ctx.page.views) == 1:
                ctx.render_catalogues()
                ctx.page.views.append(ctx.catalogues_view)
        elif ctx.page.route == "/photo":
            if len(ctx.page.views) == 1 and ctx.camera_available and ctx.state["current"] is not None:
                ctx.page.views.append(ctx.build_camera_view())
                ctx.refresh()
                await ctx.start_camera()
                return
        else:
            # Retour à l'écran principal : le catalogue reflète les changements
            while len(ctx.page.views) > 1:
                ctx.page.views.pop()
            ctx.camera_state["cam"] = None
            ctx.render_catalogue()
            render_all()
            if ctx.state.pop("back_to_photos", False) and ctx.state["current"] is not None:
                go_to_tab(2)  # retour de l'appareil photo : on montre les photos
        ctx.refresh()

    async def view_pop(e):
        # Flèche ← de la barre du haut, ou bouton « retour » d'Android
        await ctx.page.push_route("/")

    ctx.page.on_route_change = route_change
    ctx.page.on_view_pop = view_pop

    # --- ADAPTIVE WORKSPACE: keep controls alive while changing their parents ---
    ctx.state["filters_open"] = False

    cart_tab = ft.NavigationBarDestination(
        label="Panier", icon=ft.Icons.SHOPPING_BAG_OUTLINED, selected_icon=ft.Icons.SHOPPING_BAG,
    )
    ctx.cart_tab = cart_tab  # partagé avec view_cart
    navigation = ft.NavigationBar(
        destinations=[
            ft.NavigationBarDestination(label="Catalogue", icon=ft.Icons.INVENTORY_2_OUTLINED,
                                        selected_icon=ft.Icons.INVENTORY_2),
            cart_tab, ctx.photos_tab,
        ],
        selected_index=0, on_change=lambda e: go_to_tab(e.control.selected_index),
    )
    # Les trois écrans restent attachés ; changer d'onglet ne fait que les afficher ou les
    # masquer. Les retirer puis les remettre obligeait Flet à renvoyer tout le catalogue
    # (≈ 6 500 contrôles avec 400 articles) à chaque retour sur « Catalogue ».
    tabs_column = ft.Column([ctx.content_catalogue, ctx.content_panier, ctx.content_photos],
                            expand=True, spacing=0)
    main_host = ft.Container(content=tabs_column, expand=True)
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
    ctx.compact_cart_btn = compact_cart_btn  # partagé avec view_cart
    quick_cart = ft.Container(content=ft.Row([compact_cart_btn]),
        padding=ft.Padding.only(left=12, right=12, bottom=8), visible=False)

    async def restore_current_order(e=None):
        await ctx.archive_order(ctx.state["current"])

    archive_banner = ft.Container(content=ft.Row([
        ui.text("Commande archivée", expand=True),
        ft.TextButton(content="Réactiver", on_click=restore_current_order),
    ]), padding=8, bgcolor=ft.Colors.PRIMARY_CONTAINER, visible=False)
    ctx.archive_banner = archive_banner  # partagé avec view_cart
    workspace = ft.Column([archive_banner, pane_area, quick_cart, navigation], spacing=0, expand=True)

    def apply_filter_layout():
        layout = ctx.window["layout"]
        narrow = layout.width < 600 or layout.dual_pane
        ctx.filter_details.visible = ctx.state["filters_open"] if narrow or layout.short else True
        ctx.filter_button.visible = narrow or layout.short
        ctx.browse_row.visible = not layout.short or ctx.state["filters_open"]
        ctx.catalogue_info.visible = not layout.short
        ctx.filter_button.bgcolor = ft.Colors.PRIMARY_CONTAINER if ctx.state["filters_open"] else None
        ctx.catalogue_dropdown.col = ctx.category_dropdown.col = 12 if narrow else 6
        for heading in [ctx.catalogue_heading, ctx.basket_heading, ctx.photo_heading]:
            heading.visible = not layout.short
    ctx.apply_filter_layout = apply_filter_layout  # partagé avec view_catalogue

    def apply_catalogue_columns():
        layout = ctx.window["layout"]
        available = min(1440 if layout.dual_pane else 780, layout.width - 2 * layout.margin)
        pane_width = ((available - 24) * (0.5 if layout.width < 1200 else 6 / 11)
                      if layout.dual_pane else available)
        # Flet ResponsiveRow breakpoints use the view width, so use explicit
        # spans based on this pane's width for master/detail catalogue cards.
        for grid in ctx.catalogue_grids:
            columns = 2 if pane_width >= 680 else 1
            for i, card in enumerate(grid.controls):
                # Give an odd final article the full row instead of leaving
                # half a grid row empty. Its controls then fit on one line.
                full_width = columns == 1 or (len(grid.controls) % 2 and i == len(grid.controls) - 1)
                card.col = 12 if full_width else 6
                card_width = pane_width if full_width else (pane_width - 8) / 2
                compact, wide = ctx.catalogue_rows[id(card)]
                card.content = wide if card_width >= 380 else compact
    ctx.apply_catalogue_columns = apply_catalogue_columns  # partagé avec view_catalogue

    def place_basket_footer():
        # In a short landscape/keyboard window, let the summary scroll with
        # the lines instead of consuming all of the basket's usable height.
        if ctx.window["layout"].short:
            if ctx.basket_footer in ctx.content_panier.controls:
                ctx.content_panier.controls.remove(ctx.basket_footer)
            if ctx.basket_footer not in ctx.cart_listview.controls:
                ctx.cart_listview.controls.append(ctx.basket_footer)
        else:
            if ctx.basket_footer in ctx.cart_listview.controls:
                ctx.cart_listview.controls.remove(ctx.basket_footer)
            if ctx.basket_footer not in ctx.content_panier.controls:
                ctx.content_panier.controls.append(ctx.basket_footer)

    def update_quick_cart():
        layout = ctx.window["layout"]
        quick_cart.visible = bool(ctx.state["current"] and order_count(ctx.current_order())
                                  and not layout.dual_pane and not layout.short and ctx.state["tab"] == 0)

    def place_cart_pane(dual):
        # Le panier ne peut avoir qu'un parent : à droite en double volet, sinon avec les
        # onglets. On ne le déplace qu'au passage simple ↔ double volet (pliage,
        # redimensionnement), jamais en changeant d'onglet.
        if ctx.state.get("cart_in_detail") == dual:
            return
        if dual:
            if ctx.content_panier in tabs_column.controls:
                tabs_column.controls.remove(ctx.content_panier)
            detail_host.content = ctx.content_panier
        else:
            detail_host.content = None
            if ctx.content_panier not in tabs_column.controls:
                tabs_column.controls.insert(1, ctx.content_panier)
        detail_host.visible = dual
        ctx.state["cart_in_detail"] = dual

    def layout_workspace():
        layout = ctx.window["layout"]
        apply_filter_layout()
        apply_catalogue_columns()
        place_basket_footer()
        index = ctx.state["tab"]
        dual = layout.dual_pane
        place_cart_pane(dual)
        # Double volet : catalogue (ou photos) à gauche, panier toujours visible à droite.
        ctx.content_photos.visible = index == 2
        ctx.content_catalogue.visible = index == 0 or (dual and index == 1)
        ctx.content_panier.visible = dual or index == 1
        pane_area.padding = layout.margin
        pane_frame.width = min(1440 if dual else 780, max(0, layout.width - 2 * layout.margin))
        ctx.drawer.width = min(360, max(240, layout.width - 24))
        # Limit line lengths on large desktops; balanced panes on inner displays.
        main_host.expand = (1 if layout.width < 1200 else 6) if dual else True
        detail_host.expand = 1 if layout.width < 1200 else 5
        navigation.visible = not (layout.short and ctx.state.get("keyboard_open", False))
        update_quick_cart()

    async def on_workspace_size(e):
        ctx.window["layout"] = ui.WindowLayout(e.width, e.height)
        layout_workspace()
        ctx.refresh()

    async def on_window_resize(e=None):
        # SafeArea's measured workspace is the source of truth. This fallback
        # updates immediately when the host reports a new window size.
        ctx.window["layout"] = ui.WindowLayout(
            getattr(ctx.page, "width", None) or ctx.window["layout"].width,
            max(0, (getattr(ctx.page, "height", None) or ctx.window["layout"].height) - 64),
        )
        layout_workspace()
        ctx.apply_admin_density()
        admin_narrow = ctx.window["layout"].width < 600
        ctx.admin_catalogue.col = ctx.admin_category.col = 12 if admin_narrow else 6
        ctx.refresh()

    async def on_media_change(e=None):
        media = getattr(ctx.page, "media", None)
        ctx.state["keyboard_open"] = bool(media and (media.view_insets.bottom or 0) > 0)
        layout_workspace()
        ctx.refresh()

    ctx.page.on_resize = on_window_resize
    ctx.page.on_media_change = on_media_change

    install_appbar(ctx)
    ctx.page.drawer = ctx.drawer

    empty_state = ft.ListView(expand=True, controls=[ui.empty(
        ft.Icons.RECEIPT_LONG, "Votre prochaine commande commence ici",
        "Un client, une salle, un projet. Créez une commande, choisissez votre matériel "
        "et retrouvez tous vos éléments au même endroit.",
        ui.button(content="Créer une commande", icon=ft.Icons.ADD, on_click=ctx.create_order_dialog),
    )], padding=24)
    body = ft.Container(expand=True, content=workspace, on_size_change=on_workspace_size,
                        size_change_interval=100)
    ctx.page.add(ft.SafeArea(expand=True, content=body, maintain_bottom_view_padding=True))
    ctx.render_catalogue()
    render_all()

    finish_startup(ctx)


def install_appbar(ctx: AppContext) -> None:
    def toggle_theme(e=None):
        dark = ctx.page.theme_mode == ft.ThemeMode.DARK or (
            ctx.page.theme_mode == ft.ThemeMode.SYSTEM
            and getattr(ctx.page, "platform_brightness", None) == ft.Brightness.DARK
        )
        ctx.page.theme_mode = ft.ThemeMode.LIGHT if dark else ft.ThemeMode.DARK
        theme_button.icon = ft.Icons.DARK_MODE_OUTLINED if dark else ft.Icons.LIGHT_MODE_OUTLINED

    theme_button = ft.IconButton(
        icon=ft.Icons.CONTRAST, tooltip="Changer le thème clair / sombre",
        width=48, height=48, on_click=toggle_theme,
    )
    ctx.page.appbar = ft.AppBar(
        leading=ft.IconButton(icon=ft.Icons.MENU, tooltip="Commandes", on_click=ctx.open_drawer,
                              width=48, height=48),
        title=ft.Column([ctx.appbar_title, ctx.order_info], spacing=2, tight=True),
        actions=[theme_button, ft.IconButton(
            icon=ft.Icons.ADD, tooltip="Nouvelle commande", width=48, height=48,
            on_click=ctx.create_order_dialog,
        )],
    )


def finish_startup(ctx: AppContext) -> None:
    # Sauvegardes de démarrage : seulement si quelque chose a été converti ou créé
    if ctx.migrated:
        ctx.persist()
    if not prefs_path().exists():
        ctx.persist_prefs()  # garde les réglages par défaut (articles masqués par défaut)
    ctx.refresh()  # page.add() a déjà rafraîchi l'écran : on envoie le catalogue et le menu remplis ensuite

    if ctx.startup_warnings:
        ctx.page.show_dialog(ft.AlertDialog(
            scrollable=True,
            modal=True,
            title=ui.text("Attention"),
            content=ui.text("\n\n".join(ctx.startup_warnings)),
            actions=[ui.button(content="OK", on_click=lambda e: ctx.page.pop_dialog())],
        ))
