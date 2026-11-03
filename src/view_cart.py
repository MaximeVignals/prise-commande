import flet as ft

if __package__:
    from . import ui
    from .text import fmt_eur
    from .orders import order_count, order_email_text, order_total
    from .context import AppContext
else:
    import ui
    from text import fmt_eur
    from orders import order_count, order_email_text, order_total
    from context import AppContext


def install(ctx: AppContext) -> None:
    cart_listview = ft.ListView(expand=True, spacing=6, padding=ft.Padding.only(bottom=12))
    total_text = ui.text(fmt_eur(0), size=26, weight=ft.FontWeight.W_600, color=ui.PRIMARY)
    cart_info = ui.text("", size=12, color=ui.MUTED)

    def change_qty_field(field, delta):
        try:
            current = int(field.value)
        except (TypeError, ValueError):
            current = 1
        field.value = str(max(1, current + delta))

    def update_cart_qty(id_art, delta):
        items = ctx.cart()
        if id_art not in items:
            return
        if items[id_art]["quantite"] + delta <= 0:
            remove_cart_line(id_art)  # « − » sur une quantité de 1 : retire la ligne (annulable)
            return
        items[id_art]["quantite"] += delta
        ctx.persist()
        ctx.render_all()
        ctx.refresh()

    def remove_cart_line(id_art):
        """Retire une ligne du panier, avec « Annuler » dans le message pendant 8 secondes."""
        order_id = ctx.state["current"]
        items = ctx.cart()
        if id_art not in items:
            return
        position = list(items).index(id_art)
        line = items.pop(id_art)
        ctx.persist()
        ctx.render_all()

        def undo(e):
            if order_id not in ctx.orders or id_art in ctx.orders[order_id]["items"]:
                return
            restored = list(ctx.orders[order_id]["items"].items())
            restored.insert(position, (id_art, line))
            ctx.orders[order_id]["items"].clear()
            ctx.orders[order_id]["items"].update(restored)
            ctx.persist()
            ctx.render_all()
            ctx.refresh()

        ctx.page.show_dialog(ft.SnackBar(
            ui.text("🗑️ Ligne retirée du panier.", color=ft.Colors.ON_INVERSE_SURFACE),
            action="Annuler",
            on_action=undo,
            persist=False,
            duration=ft.Duration(seconds=8),  # le temps de toucher « Annuler »
        ))
        ctx.refresh()

    def set_cart_qty(id_art, field, subtotal_text, final):
        """Quantité tapée au clavier. Enregistrée à chaque chiffre ; à la sortie du champ,
        une saisie vide ou à 0 est annulée (pour retirer une ligne : la corbeille)."""
        items = ctx.cart()
        if id_art not in items:
            return
        try:
            qty = int(field.value)
        except (TypeError, ValueError):
            qty = 0
        if qty > 0:
            if qty != items[id_art]["quantite"]:
                items[id_art]["quantite"] = qty
                ctx.persist()
                subtotal_text.value = fmt_eur(items[id_art]["Prix"] * qty)
                update_cart_summary()
                ctx.render_orders()
            if final:
                field.value = str(qty)
        elif final:
            field.value = str(items[id_art]["quantite"])
            ctx.show_snack("Quantité invalide. Pour retirer la ligne, utilisez la corbeille.")
        ctx.refresh()

    def clear_cart(e):
        order = ctx.current_order()
        if not order["items"]:
            ctx.show_snack("Le panier est déjà vide.")
            ctx.refresh()
            return

        def confirm(e):
            ctx.page.pop_dialog()
            if not order["items"]:  # double appui
                return
            order["items"].clear()
            ctx.persist()
            ctx.render_all()
            ctx.show_snack("🗑️ Panier vidé.")
            ctx.refresh()

        ctx.page.show_dialog(ft.AlertDialog(
            scrollable=True,
            modal=True,
            title=ui.text("Vider le panier ?"),
            content=ui.text(
                f"Les {order_count(order)} article(s) de « {order['name']} » "
                f"({fmt_eur(order_total(order))}) seront retirés."
            ),
            actions=[
                ft.TextButton(content="Annuler", on_click=lambda e: ctx.page.pop_dialog()),
                ui.button(content="Vider", on_click=confirm,
                          style=ft.ButtonStyle(bgcolor=ft.Colors.ERROR, color=ft.Colors.ON_ERROR)),
            ],
        ))

    async def copy_email_text(e):
        order = ctx.current_order()
        if not order["items"]:
            ctx.show_snack("Le panier est vide.")
            return

        await ctx.clipboard.set(order_email_text(order))
        ctx.show_snack("📋 Texte copié dans le presse-papiers !")

    # --- RENDU PANIER ---
    def render_cart():
        cart_listview.controls.clear()
        items = ctx.cart()

        if not items:
            cart_listview.controls.append(ui.empty(
                ft.Icons.SHOPPING_BAG_OUTLINED, "Votre panier est prêt",
                "Ajoutez des articles du catalogue pour préparer votre commande.",
                ft.TextButton(content="Parcourir le catalogue", icon=ft.Icons.ARROW_FORWARD,
                              on_click=lambda e: ctx.go_to_tab(0)),
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
                    tooltip=f"Remarque : {item['Nom']}", on_click=lambda e, k=id_art: ctx.edit_notes(key=k))

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
        order = ctx.current_order()
        total_text.value = fmt_eur(order_total(order))
        n = order_count(order)
        ctx.cart_tab.label = f"Panier ({n})" if n else "Panier"
        cart_info.value = f"{n} article(s) · {len(order['items'])} référence(s)"
        ctx.order_info.value = f"{n} article(s) · {fmt_eur(order_total(order))}"
        ctx.compact_cart_btn.content = f"{n} article(s) · {fmt_eur(order_total(order))}"
        notes_preview.value = ctx.current_order().get("notes", "")
        notes_preview.visible = bool(notes_preview.value)
        ctx.archive_banner.visible = bool(order.get("archived"))
        copy_order_btn.disabled = not bool(order["items"])
        clear_order_btn.disabled = not bool(order["items"])
        ctx.update_catalogue_badges()

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
                               on_click=lambda e: ctx.edit_notes(e)))
    content_panier = ft.Column([
        basket_heading, cart_info, notes_preview, cart_listview, basket_footer,
    ], expand=True, spacing=12)

    # Partagé avec main() et les autres écrans
    ctx.change_qty_field = change_qty_field
    ctx.render_cart = render_cart
    ctx.update_cart_summary = update_cart_summary
    ctx.cart_listview = cart_listview
    ctx.basket_heading = basket_heading
    ctx.basket_footer = basket_footer
    ctx.content_panier = content_panier
