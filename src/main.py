import asyncio
import copy
import os
import shutil
import uuid
from datetime import datetime
from pathlib import Path

import flet as ft

if __package__:
    from . import ui, backup, storage
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
    from .context import AppContext
    from . import view_cart, view_catalogue, view_orders, view_admin, view_catalogues
else:
    import ui
    import backup
    import storage
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
    from context import AppContext
    import view_cart
    import view_catalogue
    import view_orders
    import view_admin
    import view_catalogues

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

    if not excel_items:
        show_import_screen(page)
        return

    ctx = AppContext(page, excel_items)
    page.data = {"ctx": ctx}  # les tests retrouvent le contexte via page.data["ctx"]

    view_cart.install(ctx)
    view_catalogue.install(ctx)
    view_orders.install(ctx)

    # --- LOGIQUE ---

    def go_to_tab(index):
        ctx.state["tab"] = index
        navigation.selected_index = index
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
            ctx.render_cart()
            render_photos()
            layout_workspace()
        ctx.update_catalogue_badges()
        ctx.render_orders()
    ctx.render_all = render_all  # partagé avec view_cart

    view_admin.install(ctx)

    view_catalogues.install(ctx)

    # =====================================================================
    # --- PHOTOS DE LA COMMANDE (matériel à remplacer) ---
    # =====================================================================

    file_picker = ft.FilePicker()  # services : on garde une référence
    ctx.file_picker = file_picker  # partagé avec view_catalogues
    share = ft.Share()
    is_mobile = page.platform in (ft.PagePlatform.ANDROID, ft.PagePlatform.IOS)
    camera_available = fc is not None and is_mobile and not page.web
    camera_state = {"cam": None}


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
        return (order or ctx.current_order()).setdefault("photos", [])

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
        photos = ctx.orders[order_id].setdefault("photos", [])
        entry = {"id": photo_id, "file": filename, "label": f"Photo {len(photos) + 1}",
                 "added": datetime.now().isoformat(timespec="minutes")}
        photos.append(entry)
        return entry

    def delete_photo(order_id, photo_id):
        photos = ctx.orders[order_id].get("photos", [])
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
        order_id = ctx.state["current"]
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
                            cache_width=ctx.dialog_width(),  # vignette : évite de décoder l'image en pleine taille
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
                ctx.persist()
            render_all()
            if on_done:
                on_done()
            ctx.refresh()

        def remove(e):
            page.pop_dialog()
            if delete_photo(order_id, photo["id"]):
                ctx.persist()
                render_all()
                ctx.show_snack("🗑️ Photo supprimée.")
            if on_done:
                on_done()
            ctx.refresh()

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
                tight=True, spacing=10, width=ctx.dialog_width(),
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
        order_id = ctx.state["current"]
        photo = next((p for p in order_photos() if p["id"] == photo_id), None)
        if photo is None:
            return
        ask_photo_label(order_id, photo, "Photo", modal=False)
        ctx.refresh()

    async def import_photos(e=None):
        """Galerie du téléphone, ou fichiers sur PC (plusieurs à la fois)."""
        order_id = ctx.state["current"]
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
            ctx.show_snack(f"Impossible d'ouvrir la galerie : {err}")
            ctx.refresh()
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
        ctx.persist()
        render_all()
        go_to_tab(2)
        message = f"📷 {added} photo(s) ajoutée(s) — touchez une photo pour la nommer."
        if failed:
            message += f" {failed} n'ont pas pu être copiée(s)."
        ctx.show_snack(message)
        ctx.refresh()

    async def share_photos(e=None):
        """Feuille de partage du téléphone (mail, WhatsApp, Drive…) : photos nommées + liste."""
        order_id, order = ctx.state["current"], ctx.current_order()
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
            ctx.show_snack(f"Partage impossible : {err}")
            ctx.refresh()

    async def save_photos_zip(e=None):
        """Un fichier .zip : photos nommées par leur libellé + photos.txt (liste et articles)."""
        order_id, order = ctx.state["current"], ctx.current_order()
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
            ctx.show_snack(f"Enregistrement impossible : {err}")
            ctx.refresh()
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
                ctx.show_snack(f"Enregistrement impossible : {err}")
                ctx.refresh()
                return
            chosen = str(target)
        ctx.show_snack(f"💾 Photos enregistrées : {Path(chosen).name}")
        ctx.refresh()

    # --- Appareil photo intégré (Android) ---
    camera_count = ui.text("", color=ft.Colors.WHITE, size=13, width=90)

    def update_camera_count():
        n = len(order_photos()) if ctx.state["current"] else 0
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
                title=ui.text(ctx.current_order()["name"], max_lines=1, overflow=ft.TextOverflow.ELLIPSIS),
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
        if not camera_available or ctx.state["current"] is None:
            await import_photos()
            return
        ctx.state["back_to_photos"] = True
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
            ctx.show_snack(f"Appareil photo indisponible ({err}). Utilisez « Importer ».")
            ctx.refresh()

    async def take_photo(e=None):
        cam, order_id = camera_state["cam"], ctx.state["current"]
        if cam is None or order_id is None:
            return
        try:
            data = await cam.take_picture()
        except Exception as err:
            ctx.show_snack(f"Photo impossible : {err}")
            ctx.refresh()
            return
        photo = add_photo_file(order_id, data=data, ext=".jpg")
        ctx.persist()
        update_camera_count()
        # On nomme la photo tout de suite, puis on reste dans l'appareil photo pour la suivante
        ask_photo_label(order_id, photo, "Nommer la photo", on_done=update_camera_count)
        ctx.refresh()

    async def close_camera(e=None):
        await page.push_route("/")

    async def open_admin(e=None):
        await ctx.close_drawer()
        await page.push_route("/articles")
    ctx.open_admin = open_admin  # partagé avec view_orders

    async def open_catalogue_manager(e=None):
        await ctx.close_drawer()
        await page.push_route("/catalogues")
    ctx.open_catalogue_manager = open_catalogue_manager  # partagé avec view_catalogue

    backup_status = ui.text("", color=ui.MUTED, selectable=True)
    backup_progress = ft.ProgressRing(visible=False, width=24, height=24)

    async def export_backup(e=None, recovery=False):
        export_backup_btn.disabled = restore_backup_btn.disabled = recovery_backup_btn.disabled = True
        backup_progress.visible = True
        backup_status.value = "Préparation de la sauvegarde…"
        ctx.refresh()
        try:
            if recovery:
                path = max((storage_dir() / "sauvegardes").glob("avant-restauration-*.zip"),
                           key=lambda path: path.stat().st_mtime_ns)
                if not path.resolve().is_relative_to(storage_dir().resolve()):
                    raise ValueError("La copie de secours est située hors du stockage de l'application.")
                data = await asyncio.to_thread(path.read_bytes)
            else:
                storage.save_orders(ctx.orders, ctx.state["current"])
                storage.save_prefs(ctx.prefs)
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
            ctx.refresh()

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
        await ctx.close_drawer()
        await page.push_route("/sauvegarde")
    ctx.open_backup_view = open_backup_view  # partagé avec view_orders

    async def route_change(e=None):
        if page.route == "/sauvegarde":
            if len(page.views) == 1:
                page.views.append(backup_view)
        elif page.route == "/articles":
            if len(page.views) == 1:
                ctx.admin_catalogue.value = ctx.catalogue_dropdown.value
                ctx.render_admin()
                page.views.append(ctx.admin_view)
        elif page.route == "/catalogues":
            if len(page.views) == 1:
                ctx.render_catalogues()
                page.views.append(ctx.catalogues_view)
        elif page.route == "/photo":
            if len(page.views) == 1 and camera_available and ctx.state["current"] is not None:
                page.views.append(build_camera_view())
                ctx.refresh()
                await start_camera()
                return
        else:
            # Retour à l'écran principal : le catalogue reflète les changements
            while len(page.views) > 1:
                page.views.pop()
            camera_state["cam"] = None
            ctx.render_catalogue()
            render_all()
            if ctx.state.pop("back_to_photos", False) and ctx.state["current"] is not None:
                go_to_tab(2)  # retour de l'appareil photo : on montre les photos
        ctx.refresh()

    async def view_pop(e):
        # Flèche ← de la barre du haut, ou bouton « retour » d'Android
        await page.push_route("/")

    page.on_route_change = route_change
    page.on_view_pop = view_pop

    # --- ADAPTIVE WORKSPACE: keep controls alive while changing their parents ---
    ctx.state["filters_open"] = False


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
    ctx.cart_tab = cart_tab  # partagé avec view_cart
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
        for heading in [ctx.catalogue_heading, ctx.basket_heading, photo_heading]:
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

    def layout_workspace():
        layout = ctx.window["layout"]
        apply_filter_layout()
        apply_catalogue_columns()
        # In a short landscape/keyboard window, let the summary scroll with
        # the lines instead of consuming all of the basket's usable height.
        if layout.short:
            if ctx.basket_footer in ctx.content_panier.controls:
                ctx.content_panier.controls.remove(ctx.basket_footer)
            if ctx.basket_footer not in ctx.cart_listview.controls:
                ctx.cart_listview.controls.append(ctx.basket_footer)
        else:
            if ctx.basket_footer in ctx.cart_listview.controls:
                ctx.cart_listview.controls.remove(ctx.basket_footer)
            if ctx.basket_footer not in ctx.content_panier.controls:
                ctx.content_panier.controls.append(ctx.basket_footer)
        index = ctx.state["tab"]
        dual = layout.dual_pane
        # Reparent only at a layout/navigation boundary, never on every resize pixel.
        signature = (dual, index)
        if ctx.state.get("layout_signature") != signature:
            main_host.content = None
            detail_host.content = None
            main_host.content = content_photos if index == 2 else ctx.content_catalogue if dual or index == 0 else ctx.content_panier
            if dual:
                detail_host.content = ctx.content_panier
            detail_host.visible = dual
            ctx.state["layout_signature"] = signature
        pane_area.padding = layout.margin
        pane_frame.width = min(1440 if dual else 780, max(0, layout.width - 2 * layout.margin))
        ctx.drawer.width = min(360, max(240, layout.width - 24))
        # Limit line lengths on large desktops; balanced panes on inner displays.
        main_host.expand = (1 if layout.width < 1200 else 6) if dual else True
        detail_host.expand = 1 if layout.width < 1200 else 5
        navigation.visible = not (layout.short and ctx.state.get("keyboard_open", False))
        quick_cart.visible = bool(ctx.state["current"] and order_count(ctx.current_order()) and not dual
                                  and not layout.short and ctx.state["tab"] == 0)

    async def on_workspace_size(e):
        ctx.window["layout"] = ui.WindowLayout(e.width, e.height)
        layout_workspace()
        ctx.refresh()

    async def on_window_resize(e=None):
        # SafeArea's measured workspace is the source of truth. This fallback
        # updates immediately when the host reports a new window size.
        ctx.window["layout"] = ui.WindowLayout(
            getattr(page, "width", None) or ctx.window["layout"].width,
            max(0, (getattr(page, "height", None) or ctx.window["layout"].height) - 64),
        )
        layout_workspace()
        ctx.apply_admin_density()
        admin_narrow = ctx.window["layout"].width < 600
        ctx.admin_catalogue.col = ctx.admin_category.col = 12 if admin_narrow else 6
        ctx.refresh()

    async def on_media_change(e=None):
        media = getattr(page, "media", None)
        ctx.state["keyboard_open"] = bool(media and (media.view_insets.bottom or 0) > 0)
        layout_workspace()
        ctx.refresh()

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
        leading=ft.IconButton(icon=ft.Icons.MENU, tooltip="Commandes", on_click=ctx.open_drawer,
                              width=48, height=48),
        title=ft.Column([ctx.appbar_title, ctx.order_info], spacing=2, tight=True),
        actions=[theme_button, ft.IconButton(
            icon=ft.Icons.ADD, tooltip="Nouvelle commande", width=48, height=48,
            on_click=ctx.create_order_dialog,
        )],
    )
    page.drawer = ctx.drawer

    empty_state = ft.ListView(expand=True, controls=[ui.empty(
        ft.Icons.RECEIPT_LONG, "Votre prochaine commande commence ici",
        "Un client, une salle, un projet. Créez une commande, choisissez votre matériel "
        "et retrouvez tous vos éléments au même endroit.",
        ui.button(content="Créer une commande", icon=ft.Icons.ADD, on_click=ctx.create_order_dialog),
    )], padding=24)
    body = ft.Container(expand=True, content=workspace, on_size_change=on_workspace_size,
                        size_change_interval=100)
    page.add(ft.SafeArea(expand=True, content=body, maintain_bottom_view_padding=True))
    ctx.render_catalogue()
    render_all()

    # Sauvegardes de démarrage : seulement si quelque chose a été converti ou créé
    if ctx.migrated:
        ctx.persist()
    if not prefs_path().exists():
        ctx.persist_prefs()  # garde les réglages par défaut (articles masqués par défaut)
    ctx.refresh()  # page.add() a déjà rafraîchi l'écran : on envoie le catalogue et le menu remplis ensuite

    if ctx.startup_warnings:
        page.show_dialog(ft.AlertDialog(
            scrollable=True,
            modal=True,
            title=ui.text("Attention"),
            content=ui.text("\n\n".join(ctx.startup_warnings)),
            actions=[ui.button(content="OK", on_click=lambda e: page.pop_dialog())],
        ))


# Démarrage de l'application
if __name__ == "__main__":
    ft.run(main)
