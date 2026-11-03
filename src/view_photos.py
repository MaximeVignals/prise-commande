import asyncio
import os
import shutil
import uuid
from datetime import datetime
from pathlib import Path

import flet as ft

if __package__:
    from . import ui
    from .text import norm_text
    from .storage import photo_path, photos_dir, storage_dir
    from .photos import build_photos_zip, photo_export_names, photos_summary, safe_filename
    from .context import AppContext
else:
    import ui
    from text import norm_text
    from storage import photo_path, photos_dir, storage_dir
    from photos import build_photos_zip, photo_export_names, photos_summary, safe_filename
    from context import AppContext

try:
    # Appareil photo intégré (Android) : extension officielle flet-camera.
    # Absente (ex. « flet run » sur PC sans l'extension) → seul l'import de photos est proposé.
    import flet_camera as fc
except ImportError:
    fc = None


def install(ctx: AppContext) -> None:
    # =====================================================================
    # --- PHOTOS DE LA COMMANDE (matériel à remplacer) ---
    # =====================================================================

    share = ft.Share()
    is_mobile = ctx.page.platform in (ft.PagePlatform.ANDROID, ft.PagePlatform.IOS)
    camera_available = fc is not None and is_mobile and not ctx.page.web
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
        if ctx.page.web:
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
            ctx.page.pop_dialog()
            label = norm_text(label_field.value or "")
            if label and label != photo["label"]:
                photo["label"] = label
                ctx.persist()
            ctx.render_all()
            if on_done:
                on_done()
            ctx.refresh()

        def remove(e):
            ctx.page.pop_dialog()
            if delete_photo(order_id, photo["id"]):
                ctx.persist()
                ctx.render_all()
                ctx.show_snack("🗑️ Photo supprimée.")
            if on_done:
                on_done()
            ctx.refresh()

        label_field.on_submit = save
        added = datetime.fromisoformat(photo["added"]).strftime("%d/%m/%Y à %H:%M")
        ctx.page.show_dialog(ft.AlertDialog(
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
            files = await ctx.file_picker.pick_files(
                dialog_title="Choisir des photos",
                file_type=ft.FilePickerFileType.IMAGE,
                allow_multiple=True,
                with_data=ctx.page.web,
            )
        except Exception as err:  # sélecteur indisponible
            ctx.show_snack(f"Impossible d'ouvrir la galerie : {err}")
            ctx.refresh()
            return
        if not files:
            return  # annulé
        added, failed = 0, 0
        for f in files:
            data = f.bytes if ctx.page.web else None
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
        ctx.render_all()
        ctx.go_to_tab(2)
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
            chosen = await ctx.file_picker.save_file(
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
        if not is_mobile and not ctx.page.web:
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
        await ctx.page.push_route("/photo")  # la caméra démarre dans route_change, une fois l'écran affiché

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
            await ctx.page.push_route("/")
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
        await ctx.page.push_route("/")

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
        expand=True, visible=is_mobile and not ctx.page.web,
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

    ctx.render_photos = render_photos
    ctx.photos_tab = photos_tab
    ctx.content_photos = content_photos
    ctx.photo_heading = photo_heading
    ctx.is_mobile = is_mobile
    ctx.camera_available = camera_available
    ctx.camera_state = camera_state
    ctx.build_camera_view = build_camera_view
    ctx.start_camera = start_camera
