import asyncio
from datetime import datetime
from pathlib import Path

import logging
import flet as ft

if __package__:
    from . import ui, backup, storage
    from .text import describe_error
    from .storage import storage_dir
    from .config import BACKUPS_DIRNAME, RECOVERY_BACKUP_PATTERN
    from .import_screen import request_restore
    from .context import AppContext
else:
    import ui
    import backup
    import storage
    from storage import storage_dir
    from config import BACKUPS_DIRNAME, RECOVERY_BACKUP_PATTERN
    from import_screen import request_restore
    from context import AppContext
    from text import describe_error

log = logging.getLogger("prise_commande")


def install(ctx: AppContext) -> None:
    backup_status = ui.text("", color=ui.MUTED, selectable=True)
    backup_progress = ft.ProgressRing(visible=False, width=24, height=24)

    async def export_backup(e=None, recovery=False):
        export_backup_btn.disabled = restore_backup_btn.disabled = recovery_backup_btn.disabled = True
        backup_progress.visible = True
        backup_status.value = "Préparation de la sauvegarde…"
        ctx.refresh()
        try:
            if recovery:
                path = max((storage_dir() / BACKUPS_DIRNAME).glob(RECOVERY_BACKUP_PATTERN),
                           key=lambda path: path.stat().st_mtime_ns)
                if not path.resolve().is_relative_to(storage_dir().resolve()):
                    raise ValueError("La copie de secours est située hors du stockage de l'application.")
                data = await asyncio.to_thread(path.read_bytes)
            else:
                storage.save_orders(ctx.orders, ctx.state["current"])
                storage.save_prefs(ctx.prefs)
                data = await asyncio.to_thread(backup.create_backup, storage_dir())
            chosen = await ctx.file_picker.save_file(dialog_title="Enregistrer la sauvegarde complète",
                file_name=path.name if recovery else f"Prise de Commande - {datetime.now():%Y-%m-%d-%H%M}.zip",
                file_type=ft.FilePickerFileType.CUSTOM, allowed_extensions=["zip"], src_bytes=data)
            if chosen and not ctx.is_mobile and not ctx.page.web:
                target = Path(chosen)
                if target.suffix.lower() != ".zip":
                    target = target.with_suffix(".zip")
                await asyncio.to_thread(target.write_bytes, data)
            backup_status.value = "Sauvegarde enregistrée." if chosen else "Enregistrement annulé."
        except Exception as err:
            log.exception("Erreur affichée à l'utilisateur")
            backup_status.value = f"Sauvegarde impossible : {describe_error(err)}"
        finally:
            export_backup_btn.disabled = restore_backup_btn.disabled = False
            recovery_backup_btn.disabled = not any((storage_dir() / BACKUPS_DIRNAME).glob(RECOVERY_BACKUP_PATTERN))
            backup_progress.visible = False
            ctx.refresh()

    async def export_journal(e=None):
        export_journal_btn.disabled = True
        backup_status.value = "Préparation du journal…"
        ctx.refresh()
        try:
            def read_journal():
                current = storage_dir() / "journal.log"
                parts = [path.read_bytes() for path in (current.with_name("journal.log.1"), current) if path.exists()]
                return b"".join(parts)
            data = await asyncio.to_thread(read_journal)
            if not data.strip():
                backup_status.value = "Le journal est vide."
                return
            chosen = await ctx.file_picker.save_file(dialog_title="Enregistrer le journal",
                file_name="journal-prise-commande.txt",
                file_type=ft.FilePickerFileType.CUSTOM, allowed_extensions=["txt"], src_bytes=data)
            if chosen and not ctx.is_mobile and not ctx.page.web:
                target = Path(chosen)
                if target.suffix.lower() != ".txt":
                    target = target.with_suffix(".txt")
                await asyncio.to_thread(target.write_bytes, data)
            backup_status.value = "Journal enregistré." if chosen else "Enregistrement annulé."
        except Exception as err:
            log.exception("Export du journal impossible")
            backup_status.value = f"Export du journal impossible : {describe_error(err)}"
        finally:
            export_journal_btn.disabled = False
            ctx.refresh()

    async def restore_from_view(e=None):
        async def done():
            await ctx.page.push_route("/")
            ctx.page.controls.clear()
            ctx.main(ctx.page)
        await request_restore(ctx.page, ctx.file_picker, done)

    async def export_recovery(e=None):
        await export_backup(recovery=True)

    export_backup_btn = ui.button(content="Créer une sauvegarde", icon=ft.Icons.SAVE_ALT, on_click=export_backup)
    restore_backup_btn = ft.OutlinedButton(content="Restaurer une sauvegarde", icon=ft.Icons.RESTORE,
                                            on_click=restore_from_view)
    recovery_backup_btn = ft.TextButton(content="Exporter la dernière copie de secours", icon=ft.Icons.HISTORY,
        on_click=export_recovery, disabled=not any((storage_dir() / BACKUPS_DIRNAME).glob(RECOVERY_BACKUP_PATTERN)))
    export_journal_btn = ft.OutlinedButton(content="Exporter le journal", icon=ft.Icons.DESCRIPTION_OUTLINED,
                                           on_click=export_journal)
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
            ui.card(ft.Column([
                ui.heading("En cas de problème", "Un fichier texte à transmettre pour comprendre une erreur",
                           ft.Icons.BUG_REPORT_OUTLINED),
                ui.text("Le journal contient des messages techniques. Il peut citer des noms de fichiers ou d'articles : "
                        "vérifiez-le avant de l'envoyer.",
                        color=ui.MUTED),
                export_journal_btn,
            ], spacing=16, tight=True)),
            backup_progress, backup_status,
        ]))])

    async def open_backup_view(e=None):
        await ctx.close_drawer()
        await ctx.page.push_route("/sauvegarde")

    ctx.open_backup_view = open_backup_view
    ctx.backup_view = backup_view
