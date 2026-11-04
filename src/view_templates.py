# Modèles de commande : enregistrer une commande comme modèle, partir d'un modèle (avec vérification),
# renommer / supprimer les modèles. Rien n'est envoyé ailleurs : tout reste dans le stockage de l'app.

import flet as ft

if __package__:
    from . import ui, templates, storage
    from .config import DEFAULT_CATALOGUE_LABEL
    from .text import fmt_eur, matches_search
    from .context import AppContext
else:
    import ui
    import templates
    import storage
    from config import DEFAULT_CATALOGUE_LABEL
    from text import fmt_eur, matches_search
    from context import AppContext

STATUS_LABELS = {
    "missing": "Introuvable dans le catalogue actuel",
    "ambiguous": "Plusieurs articles correspondent",
    "hidden": "Article masqué",
}


def install(ctx: AppContext) -> None:

    def load():
        data, warning = templates.load_templates()
        if warning:
            ctx.show_snack(warning)
        return data

    def article_label(article):
        catalogue = article["Catalogue"] or DEFAULT_CATALOGUE_LABEL
        hidden = (not article["Visible"]) or article["Catalogue"] in ctx.prefs["hidden_catalogues"]
        origin = "article ajouté" if article.get("Perso") else article["Categorie"]
        return f"{article['Nom_Article']} · {catalogue} › {origin} · {fmt_eur(article['Prix_Unitaire'])}" + (" · masqué" if hidden else "")

    # --- ENREGISTRER UNE COMMANDE COMME MODÈLE ---

    async def save_template_dialog(order_id):
        await ctx.close_drawer()
        order = ctx.orders[order_id]
        if not order["items"]:
            ctx.show_snack("Commande vide : ajoutez des articles avant d'en faire un modèle.")
            ctx.refresh()
            return
        field = ui.field(label="Nom du modèle", value=order["name"], autofocus=True,
                         capitalization=ft.TextCapitalization.SENTENCES)

        saved = {"done": False}  # double appui / Entrée puis clic : un seul modèle

        def save(e=None):
            if saved["done"]:
                return
            name = (field.value or "").strip()
            if not name:
                field.error = "Donnez un nom au modèle."
                ctx.refresh()
                return
            data, warning = templates.load_templates()
            data[templates.new_template_id(data)] = templates.template_from_order(order, ctx.cat["all"], name)
            try:
                templates.save_templates(data)
            except OSError as err:
                field.error = f"Enregistrement impossible : {err}"
                ctx.refresh()
                return
            saved["done"] = True
            ctx.page.pop_dialog()
            if warning:
                ctx.show_snack(warning)
            ctx.show_snack(f"Modèle « {name} » enregistré (articles et quantités, sans remarques ni photos).")
            ctx.refresh()

        field.on_submit = save
        ctx.page.show_dialog(ft.AlertDialog(
            modal=True, scrollable=True, title=ui.text("Enregistrer comme modèle"),
            content=ft.Container(width=ctx.dialog_width(), content=ft.Column(tight=True, controls=[
                field,
                ui.text("Seuls les articles et les quantités sont conservés. Les prix seront ceux "
                        "du catalogue au moment de l'utilisation.", size=12, color=ui.MUTED),
            ])),
            actions=[ft.TextButton(content="Annuler", on_click=lambda e: ctx.page.pop_dialog()),
                     ui.button(content="Enregistrer", on_click=save)]))
        ctx.refresh()

    # --- VÉRIFICATION AVANT DE CRÉER UNE COMMANDE À PARTIR D'UN MODÈLE ---

    def review_template(template_id, order_name, on_created):
        data = load()
        template = data.get(template_id)
        if template is None:
            ctx.show_snack("Ce modèle n'existe plus.")
            return
        lines = []
        for resolved in templates.resolve_template(template, ctx.cat["all"], ctx.prefs["hidden_catalogues"]):
            lines.append({
                "resolved": resolved,
                "qty": resolved["entry"]["quantite"],
                "article": resolved["article"] if resolved["status"] == "ok" else None,
                # None = choix à faire ; "include" / "omit"
                "decision": "include" if resolved["status"] == "ok" else None,
                "picking": resolved["status"] == "ambiguous",
                "query": "",
            })

        body = ft.Column(tight=True, spacing=8, horizontal_alignment=ft.CrossAxisAlignment.STRETCH)
        total_text = ui.text("", weight=ft.FontWeight.BOLD)
        pending_text = ui.text("", size=12, color=ft.Colors.ERROR)
        create_button = ui.button(content="Créer la commande")

        def included():
            return [l for l in lines if l["decision"] == "include" and l["article"] is not None and l["qty"] > 0]

        def line_controls(line):
            entry, status = line["resolved"]["entry"], line["resolved"]["status"]
            article = line["article"]
            title = article["Nom_Article"] if article else entry["name"]
            sub = [entry["catalogue"] or DEFAULT_CATALOGUE_LABEL]
            if article:
                sub.append(f"{fmt_eur(article['Prix_Unitaire'])}/u")
            controls = [ui.text(title, weight=ft.FontWeight.W_600,
                                color=ui.MUTED if line["decision"] == "omit" else None),
                        ui.text(" · ".join(sub), size=12, color=ui.MUTED)]
            if status != "ok" and line["decision"] is None:
                controls.append(ui.text("⚠️ " + STATUS_LABELS[status] + " : choisissez.", size=12, color=ft.Colors.ERROR))
            elif status != "ok" and line["decision"] == "include":
                controls.append(ui.text("Remplacé / inclus à votre demande." if status != "hidden" or article is not line["resolved"]["article"]
                                        else "Article masqué, inclus à votre demande.", size=12, color=ui.MUTED))
            if line["decision"] == "omit":
                controls.append(ui.text("Laissé de côté.", size=12, color=ui.MUTED))

            buttons = []
            if line["decision"] == "include":
                buttons += [
                    ft.IconButton(ft.Icons.REMOVE, tooltip="Moins", on_click=lambda e, l=line: change_qty(l, -1)),
                    ui.text(str(line["qty"]), weight=ft.FontWeight.BOLD),
                    ft.IconButton(ft.Icons.ADD, tooltip="Plus", on_click=lambda e, l=line: change_qty(l, 1)),
                ]
            if status == "hidden" and line["decision"] is None:
                buttons.append(ft.TextButton(content="Inclure quand même", on_click=lambda e, l=line: include_hidden(l)))
            if status != "ok":
                buttons.append(ft.TextButton(content="Remplacer…", on_click=lambda e, l=line: toggle_picker(l)))
            if line["decision"] != "omit":
                buttons.append(ft.TextButton(content="Retirer", on_click=lambda e, l=line: set_omit(l)))
            else:
                buttons.append(ft.TextButton(content="Annuler le retrait", on_click=lambda e, l=line: undo_omit(l)))
            controls.append(ft.Row(buttons, wrap=True, spacing=0,
                                   vertical_alignment=ft.CrossAxisAlignment.CENTER))
            if line["picking"]:
                controls.append(picker(line))
            return ui.card(ft.Column(controls, tight=True, spacing=2), padding=10)

        def picker(line):
            status = line["resolved"]["status"]
            search = ui.field(label="Rechercher un article", value=line["query"])
            results = ft.Column(tight=True, spacing=0)

            def fill():
                if status == "ambiguous" and not line["query"]:
                    found = line["resolved"]["candidates"]
                else:
                    found = [a for a in ctx.cat["all"] if line["query"] and matches_search(a["Nom_Article"], line["query"])]
                # Les candidats d'un article ambigu sont tous affichés ; une recherche libre est limitée à 20.
                shown = found if found is line["resolved"]["candidates"] else found[:20]
                results.controls = [ft.TextButton(content=article_label(a), on_click=lambda e, a=a: choose(line, a))
                                    for a in shown]
                if len(found) > len(shown):
                    results.controls.append(ui.text(f"{len(found) - len(shown)} autre(s) : précisez la recherche.",
                                                    size=12, color=ui.MUTED))
                if not results.controls:
                    results.controls = [ui.text("Tapez un nom pour chercher." if not line["query"] else "Aucun article trouvé.",
                                                size=12, color=ui.MUTED)]

            def on_change(e):
                line["query"] = search.value or ""
                fill()
                results.update()

            search.on_change = on_change
            fill()
            return ft.Column([search, results], tight=True, spacing=4)

        def render():
            body.controls = [line_controls(l) for l in lines]
            total = templates.items_total(templates.build_order_items((l["article"], l["qty"]) for l in included()))
            total_text.value = f"Total : {fmt_eur(total)}"
            pending = sum(l["decision"] is None for l in lines)
            pending_text.value = f"{pending} article(s) à vérifier avant de créer la commande." if pending else ""
            create_button.disabled = bool(pending) or not included()

        def refresh():
            render()
            ctx.refresh()

        def change_qty(line, delta):
            line["qty"] = max(1, line["qty"] + delta)
            refresh()

        def include_hidden(line):
            line.update(article=line["resolved"]["article"], decision="include", picking=False)
            refresh()

        def toggle_picker(line):
            line["picking"] = not line["picking"]
            refresh()

        def choose(line, article):
            line.update(article=article, decision="include", picking=False)
            refresh()

        def set_omit(line):
            line.update(decision="omit", picking=False)
            refresh()

        def undo_omit(line):
            status = line["resolved"]["status"]
            line["decision"] = "include" if status == "ok" or line["article"] is not None else None
            refresh()

        created = {"done": False}  # double appui : une seule commande

        def create(e=None):
            if created["done"]:
                return
            items = templates.build_order_items((l["article"], l["qty"]) for l in included())
            if not items:
                return
            previous = ctx.state["current"]
            order_id = ctx.new_order(order_name)
            ctx.orders[order_id]["items"] = items
            try:
                # Enregistrement direct (pas ctx.persist) pour pouvoir annuler en cas d'erreur.
                storage.save_orders(ctx.orders, order_id)
            except OSError as err:
                del ctx.orders[order_id]
                ctx.state["current"] = previous
                pending_text.value = f"Enregistrement impossible : {err}"
                ctx.refresh()
                return
            created["done"] = True
            create_button.disabled = True
            ctx.page.pop_dialog()
            on_created(order_id)
            ctx.refresh()  # le message affiché bloque le rafraîchissement automatique (voir ctx.refresh)

        create_button.on_click = create
        render()
        ctx.page.show_dialog(ft.AlertDialog(
            modal=True, scrollable=True,
            title=ui.text(f"Modèle « {template['name']} »"),
            content=ft.Container(width=ctx.dialog_width(), content=ft.Column(
                tight=True, controls=[ui.text("Vérifiez les articles. Les prix sont ceux du catalogue actuel.",
                                              size=12, color=ui.MUTED), body, total_text, pending_text])),
            actions=[ft.TextButton(content="Annuler", on_click=lambda e: ctx.page.pop_dialog()), create_button]))
        ctx.refresh()

    # --- GESTION DES MODÈLES ---

    async def open_template_manager(e=None):
        await ctx.close_drawer()
        show_manager()

    def show_manager():
        data = load()
        if data:
            rows = [ft.ListTile(
                dense=True, title=ui.text(t["name"], max_lines=1, overflow=ft.TextOverflow.ELLIPSIS),
                subtitle=ui.text(f"{len(t['entries'])} article(s)", size=12),
                trailing=ft.Row(tight=True, spacing=0, controls=[
                    ft.IconButton(ft.Icons.EDIT_OUTLINED, tooltip="Renommer", on_click=lambda e, i=tid: rename(i)),
                    ft.IconButton(ft.Icons.DELETE_OUTLINE, tooltip="Supprimer", on_click=lambda e, i=tid: delete(i)),
                ])) for tid, t in data.items()]
        else:
            rows = [ui.text("Aucun modèle. Ouvrez le menu ⋮ d'une commande puis « Enregistrer comme modèle ».",
                            color=ui.MUTED)]
        ctx.page.show_dialog(ft.AlertDialog(
            scrollable=True, title=ui.text("Modèles de commande"),
            content=ft.Container(width=ctx.dialog_width(), content=ft.Column(rows, tight=True)),
            actions=[ft.TextButton(content="Fermer", on_click=lambda e: ctx.page.pop_dialog())]))
        ctx.refresh()

    def rename(template_id):
        ctx.page.pop_dialog()  # la liste des modèles ; avant load(), qui peut afficher un message
        data = load()
        if template_id not in data:
            show_manager()
            return
        field = ui.field(label="Nom du modèle", value=data[template_id]["name"], autofocus=True)

        def save(e=None):
            name = (field.value or "").strip()
            if not name:
                field.error = "Donnez un nom au modèle."
                ctx.refresh()
                return
            data[template_id]["name"] = name
            try:
                templates.save_templates(data)
            except OSError as err:
                field.error = f"Enregistrement impossible : {err}"
                ctx.refresh()
                return
            ctx.page.pop_dialog()
            show_manager()

        field.on_submit = save
        ctx.page.show_dialog(ft.AlertDialog(
            modal=True, scrollable=True, title=ui.text("Renommer le modèle"),
            content=ft.Container(width=ctx.dialog_width(), content=field),
            actions=[ft.TextButton(content="Annuler", on_click=lambda e: (ctx.page.pop_dialog(), show_manager())),
                     ui.button(content="Valider", on_click=save)]))
        ctx.refresh()

    def delete(template_id):
        ctx.page.pop_dialog()  # la liste des modèles ; avant load(), qui peut afficher un message
        data = load()
        if template_id not in data:
            show_manager()
            return
        confirmed = {"done": False}

        def confirm(e):
            if confirmed["done"]:
                return
            confirmed["done"] = True
            data.pop(template_id, None)
            ctx.page.pop_dialog()  # la confirmation, avant le message d'erreur éventuel
            try:
                templates.save_templates(data)
            except OSError as err:
                show_manager()
                ctx.show_snack(f"Suppression impossible : {err}")
                ctx.refresh()
                return
            show_manager()

        ctx.page.show_dialog(ft.AlertDialog(
            modal=True, scrollable=True, title=ui.text("Supprimer le modèle ?"),
            content=ui.text(f"« {data[template_id]['name']} » sera définitivement supprimé. "
                            "Les commandes déjà créées ne changent pas."),
            actions=[ft.TextButton(content="Annuler", on_click=lambda e: (ctx.page.pop_dialog(), show_manager())),
                     ui.button(content="Supprimer", on_click=confirm,
                               style=ft.ButtonStyle(bgcolor=ft.Colors.ERROR, color=ft.Colors.ON_ERROR))]))
        ctx.refresh()

    ctx.save_template_dialog = save_template_dialog
    ctx.review_template = review_template
    ctx.open_template_manager = open_template_manager
    ctx.load_templates = load
