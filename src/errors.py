# Filet de sécurité : journal fichier + écran d'erreur en français quand une exception échappe à l'app.

import logging
import sys
from logging.handlers import RotatingFileHandler

import flet as ft

if __package__:
    from . import storage
else:
    import storage

JOURNAL_NAME = "journal.log"
log = logging.getLogger("prise_commande")
_LOGGER_NAMES = ("prise_commande", "flet")
_FORMAT = "%(asctime)s %(levelname)s %(name)s: %(message)s"
_original_error = None
_handling = False
_dialog = None


class _JournalHandler(RotatingFileHandler):
    """Rouvre le fichier à chaque message puis le ferme : rien ne reste verrouillé (Windows, tests, restauration)."""

    def emit(self, record):
        super().emit(record)
        self.close()

    def handleError(self, record):
        pass  # un journal inaccessible ne doit jamais gêner l'app


def log_path():
    return storage.storage_dir() / JOURNAL_NAME


def setup_logging():
    """Journal tournant (512 Ko + 1 copie) dans le dossier de l'app. Idempotent, ne lève jamais."""
    try:
        path = str(log_path())
        for name in _LOGGER_NAMES:
            logger = logging.getLogger(name)
            if name == "prise_commande":
                logger.setLevel(logging.INFO)  # le niveau de « flet » reste réglé par FLET_LOG_LEVEL
            if any(getattr(h, "_pc_journal", None) == path for h in logger.handlers):
                continue
            for h in [h for h in logger.handlers if getattr(h, "_pc_journal", None)]:
                logger.removeHandler(h)  # le dossier de stockage a changé : on repart sur le bon fichier
                h.close()
            try:
                handler = _JournalHandler(path, maxBytes=512 * 1024, backupCount=1, encoding="utf-8", delay=True)
            except Exception:
                handler = logging.StreamHandler(sys.stderr)
            handler.setFormatter(logging.Formatter(_FORMAT))
            handler._pc_journal = path
            logger.addHandler(handler)
        if not logging.getLogger().handlers and not any(
                getattr(h, "_pc_stderr", False) for h in logging.getLogger("flet").handlers):
            console = logging.StreamHandler(sys.stderr)  # sans ça, notre handler désactive logging.lastResort
            console.setLevel(logging.WARNING)
            console.setFormatter(logging.Formatter(_FORMAT))
            console._pc_stderr = True
            logging.getLogger("flet").addHandler(console)
    except Exception:
        pass


def reset_for_tests():
    """Retire nos handlers et remet Session.error d'origine (isolation entre tests)."""
    global _dialog
    _dialog = None
    uninstall()
    for name in _LOGGER_NAMES:
        logger = logging.getLogger(name)
        for h in list(logger.handlers):
            if getattr(h, "_pc_journal", None) or getattr(h, "_pc_stderr", False):
                logger.removeHandler(h)
                h.close()


def _show_error_dialog(page):
    global _dialog
    if _dialog is not None and _dialog.open:
        # Fermée en touchant à côté : Flet la retire de la page sans forcément remettre open à False.
        shown = getattr(getattr(page, "_dialogs", None), "controls", None)
        if shown is None or _dialog in shown:
            return  # déjà affichée : on n'empile pas
    _dialog = ft.AlertDialog(
        title=ft.Text("Une erreur est survenue"),
        content=ft.Text("Cette action n'a pas abouti. Réessayez ; si le problème continue, "
                        "exportez le journal depuis Sauvegarder / restaurer."),
        actions=[ft.TextButton(content="Fermer", on_click=lambda e: page.pop_dialog())],
    )
    page.show_dialog(_dialog)
    page.update()


def _usable_page(session):
    """Page utilisable = l'app a créé son contexte (page.data["ctx"]) ou un écran (import, démarrage) est affiché."""
    page = getattr(session, "page", None)
    data = getattr(page, "data", None)
    if isinstance(data, dict) and "ctx" in data:
        return page
    return page if page is not None and getattr(page, "controls", None) else None


def _patched_error(self, message):
    global _handling
    text = str(message)
    # Flet journalise déjà la trace complète (session.py, app.py) sauf pour les effets.
    first_line = text.splitlines()[0] if text else ""
    log.error("Erreur non gérée : %s", text if text.startswith("Exception in effect") else first_line)
    log.debug("Détail : %s", text)
    if _handling:
        return _original_error(self, message)
    _handling = True
    try:
        page = _usable_page(self)
        if page is None:
            return _original_error(self, message)
        try:
            _show_error_dialog(page)
        except Exception:
            log.exception("Impossible d'afficher la boîte d'erreur")
            return _original_error(self, message)
    finally:
        _handling = False


def install():
    """Remplace Session.error (une seule fois par processus) : l'app reste ouverte au lieu de planter."""
    global _original_error
    try:
        from flet.messaging.session import Session
        if getattr(ft, "__version__", None) != "1.0.4":
            log.warning("Version de Flet non prévue : filet de sécurité désactivé")
            return
        if Session.error is _patched_error:
            return
        _original_error = Session.error
        Session.error = _patched_error
    except Exception:
        log.exception("Filet de sécurité non installé")


def uninstall():
    """Pour les tests : remet Session.error d'origine."""
    global _original_error
    if _original_error is not None:
        from flet.messaging.session import Session
        Session.error = _original_error
        _original_error = None
