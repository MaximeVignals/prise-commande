import asyncio
import os
from datetime import datetime
from pathlib import Path

import logging
import flet as ft

if __package__:
    from . import ui, backup
    from .text import describe_error
    from .config import CATALOGUE_COLUMNS
    from .storage import storage_dir
    from .catalogue import CatalogueError, install_catalogue, parse_catalogue, sample_catalogue_path
else:
    import ui
    import backup
    from config import CATALOGUE_COLUMNS
    from storage import storage_dir
    from catalogue import CatalogueError, install_catalogue, parse_catalogue, sample_catalogue_path
    from text import describe_error

log = logging.getLogger("prise_commande")


async def pick_catalogue_file(file_picker):
    """Sélecteur de fichier .xlsx / .csv. Retourne (octets, extension), ou None si annulé.
    with_data : le contenu est lu par le sélecteur (fonctionne aussi en web, où il n'y a pas de chemin)."""
    files = await file_picker.pick_files(
        dialog_title="Choisir le catalogue (.xlsx ou .csv)",
        file_type=ft.FilePickerFileType.CUSTOM,
        allowed_extensions=["xlsx", "csv"],
        with_data=True,
    )
    if not files:
        return None
    f = files[0]
    data = f.bytes
    if data is None and f.path:
        data = Path(f.path).read_bytes()
    if data is None:
        raise CatalogueError("Le fichier choisi n'a pas pu être lu.")
    return data, os.path.splitext(f.name or f.path or "")[1].lower()


def skipped_summary(skipped):
    """Texte court listant les lignes ignorées à l'import."""
    if not skipped:
        return ""
    lines = "\n".join(f"• {s}" for s in skipped[:8])
    more = f"\n… et {len(skipped) - 8} autre(s)." if len(skipped) > 8 else ""
    return f"{len(skipped)} ligne(s) ignorée(s) :\n{lines}{more}"


async def request_restore(page, picker, on_done):
    """Shared restore flow, also available before a catalogue is installed."""
    def report(message):
        page.show_dialog(ft.SnackBar(ui.text(message, color=ft.Colors.ON_INVERSE_SURFACE)))
        page.update()

    try:
        files = await picker.pick_files(dialog_title="Restaurer une sauvegarde",
            file_type=ft.FilePickerFileType.CUSTOM, allowed_extensions=["zip"], with_data=True)
        if not files:
            return
        file = files[0]
        data = file.bytes if file.bytes is not None else Path(file.path).read_bytes()
        snapshot = await asyncio.to_thread(backup.inspect_backup, data, parse_catalogue)
    except Exception as err:
        log.exception("Erreur affichée à l'utilisateur")
        report(f"Restauration impossible : {describe_error(err)}")
        return

    async def confirm(e=None):
        restore_button.disabled = True
        restore_button.content = "Restauration…"
        restore_error.visible = False
        page.update()
        try:
            recovery = await asyncio.to_thread(backup.restore_backup, storage_dir(), snapshot)
        except (OSError, ValueError) as err:
            restore_button.disabled = False
            restore_button.content = "Restaurer"
            restore_error.value, restore_error.visible = str(err), True
            page.update()
            return
        page.pop_dialog()
        # Flet dismisses the native route asynchronously. Navigating/rebuilding
        # the app before that route has closed can leave its modal visible.
        try:
            await asyncio.wait_for(dismissed.wait(), timeout=1)
        except TimeoutError:
            pass  # Older clients may not acknowledge dismissal; allow it time to finish.
        await on_done()
        report(f"Restauration terminée. Copie de secours : {recovery.name}")

    restore_button = ui.button(content="Restaurer", on_click=confirm)
    restore_error = ui.text("", color=ft.Colors.ERROR, visible=False)
    dismissed = asyncio.Event()

    async def on_dismiss(e):
        dismissed.set()

    page.show_dialog(ft.AlertDialog(scrollable=True, modal=True,
        on_dismiss=on_dismiss,
        title=ui.text("Restaurer cette sauvegarde ?"),
        content=ft.Column([
            ui.text(f"Sauvegarde du {datetime.fromisoformat(snapshot.created):%d/%m/%Y à %H:%M}"),
            ui.text(f"{len(snapshot.orders['orders'])} commande(s) · {snapshot.photo_count} photo(s)"),
            ui.text("Les commandes seront ajoutées. Vos commandes actuelles seront conservées, "
                    "y compris en cas de noms identiques. Le catalogue et les réglages seront remplacés. "
                    "Une copie locale de secours sera créée avant toute modification.", color=ui.MUTED),
            restore_error,
        ], spacing=12, tight=True, width=max(160, min(420, (getattr(page, "width", None) or 390) - 80))),
        actions=[ft.TextButton(content="Annuler", on_click=lambda e: page.pop_dialog()), restore_button]))
    page.update()


def show_import_screen(page):
    """Premier lancement (aucun catalogue) : importer un fichier, ou essayer le catalogue d'exemple."""
    file_picker = ft.FilePicker()  # service : on garde une référence
    error_text = ui.text("", color=ft.Colors.ERROR, text_align=ft.TextAlign.CENTER, selectable=True)

    def start_app(skipped):
        if __package__:
            from .main import main
        else:
            from main import main
        page.controls.clear()
        main(page)
        if skipped:
            page.show_dialog(ft.AlertDialog(
                scrollable=True,
                title=ui.text("Catalogue importé"),
                content=ui.text(skipped_summary(skipped), selectable=True),
                actions=[ft.TextButton(content="OK", on_click=lambda e: page.pop_dialog())],
            ))
            page.update()

    async def import_file(e=None):
        try:
            picked = await pick_catalogue_file(file_picker)
            if picked is None:
                return  # annulé
            _, skipped = install_catalogue(*picked)
        except (CatalogueError, OSError) as err:
            log.exception("Erreur affichée à l'utilisateur")
            error_text.value = f"Import impossible : {describe_error(err)}"
            page.update()
            return
        except Exception as err:  # sélecteur indisponible
            log.exception("Erreur affichée à l'utilisateur")
            error_text.value = "Impossible d'ouvrir le sélecteur de fichiers."
            page.update()
            return
        start_app(skipped)

    def use_sample(e=None):
        path = sample_catalogue_path()
        try:
            _, skipped = install_catalogue(path.read_bytes(), path.suffix)
        except (CatalogueError, OSError) as err:
            log.exception("Erreur affichée à l'utilisateur")
            error_text.value = f"Catalogue d'exemple illisible : {describe_error(err)}"
            page.update()
            return
        start_app(skipped)

    async def restore(e=None):
        async def done():
            if __package__:
                from .main import main
            else:
                from main import main
            page.controls.clear()
            main(page)
        await request_restore(page, file_picker, done)

    page.add(ft.SafeArea(expand=True, content=ft.Container(
        expand=True,
        alignment=ft.Alignment.CENTER,
        padding=16,
        content=ft.Column(controls=[ui.card(ft.Column(
            [
                ft.Container(content=ft.Icon(ft.Icons.UPLOAD_FILE, size=36, color=ui.PRIMARY),
                             padding=20, bgcolor=ft.Colors.PRIMARY_CONTAINER, border_radius=24),
                ui.text("Tout commence par votre catalogue", size=26, weight=ft.FontWeight.W_600,
                        text_align=ft.TextAlign.CENTER),
                ui.text(
                    "Importez votre catalogue : un fichier .xlsx ou .csv dont la 1re ligne contient "
                    "les colonnes « " + " | ".join(CATALOGUE_COLUMNS.values()) + " ».",
                    text_align=ft.TextAlign.CENTER, color=ft.Colors.ON_SURFACE_VARIANT,
                ),
                ft.Container(height=8),
                ui.button(
                    content="Importer un catalogue",
                    icon=ft.Icons.FOLDER_OPEN,
                    on_click=import_file,
                    style=ft.ButtonStyle(
                        bgcolor=ft.Colors.PRIMARY, color=ft.Colors.ON_PRIMARY,
                        padding=ft.Padding.symmetric(horizontal=24, vertical=16),
                    ),
                ),
                ft.TextButton(content="Essayer avec le catalogue d'exemple", on_click=use_sample),
                ft.TextButton(content="Restaurer une sauvegarde", icon=ft.Icons.RESTORE, on_click=restore),
                ft.Row([ft.Icon(ft.Icons.LOCK_OUTLINE, size=16, color=ui.MUTED),
                        ui.text("Vos données restent sur cet appareil", size=12, color=ui.MUTED, expand=True)],
                       spacing=8),
                error_text,
            ],
            horizontal_alignment=ft.CrossAxisAlignment.CENTER,
            alignment=ft.MainAxisAlignment.CENTER,
            spacing=20,
            tight=True,
        ))], width=520, tight=True, scroll=ft.ScrollMode.AUTO),
    )))
