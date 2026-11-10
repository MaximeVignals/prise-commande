import asyncio
import errno
import json
import logging
import unittest
from types import SimpleNamespace
from unittest import mock

import flet as ft
from flet.messaging.session import Session

from test_app import StorageTest, TestPage
from src import catalogue as catalogue_mod
from src import errors
from src import main as app
from src import text as text_mod


class DescribeErrorTests(unittest.TestCase):
    def test_oserror_codes(self):
        for code, expected in [(errno.ENOSPC, "Espace de stockage insuffisant"), (errno.EACCES, "Accès refusé"),
                               (errno.EPERM, "Accès refusé"), (errno.ENOENT, "Fichier introuvable"),
                               (errno.EROFS, "Stockage en lecture seule")]:
            with self.subTest(code=code):
                self.assertEqual(text_mod.describe_error(OSError(code, "détail technique")), expected)

    def test_generic(self):
        self.assertEqual(text_mod.describe_error(OSError("autre")), "Erreur d'accès au fichier")
        self.assertEqual(text_mod.describe_error(RuntimeError("x")), "Erreur inattendue")
        self.assertEqual(text_mod.describe_error(ValueError("Sauvegarde invalide")), "Sauvegarde invalide")
        self.assertEqual(text_mod.describe_error(catalogue_mod.CatalogueError("Colonnes manquantes")),
                         "Colonnes manquantes")

    def test_unreadable_file_errors(self):
        self.assertEqual(text_mod.describe_error(UnicodeDecodeError("utf-8", b"\x81", 0, 1, "invalid")),
                         "Fichier illisible")
        self.assertEqual(text_mod.describe_error(json.JSONDecodeError("Expecting value", "", 0)),
                         "Fichier illisible")


class ErrorsTestCase(StorageTest):
    def setUp(self):
        super().setUp()
        self._orig = Session.error
        self.addCleanup(self._restore)
        errors.reset_for_tests()

    def _restore(self):
        errors.reset_for_tests()
        Session.error = self._orig

    def journal(self):
        path = self.storage / "journal.log"
        return path.read_text(encoding="utf-8") if path.exists() else ""


class LoggingTests(ErrorsTestCase):
    def test_writes_and_idempotent(self):
        errors.setup_logging()
        errors.setup_logging()
        for name in errors._LOGGER_NAMES:
            ours = [h for h in logging.getLogger(name).handlers if getattr(h, "_pc_journal", None)]
            self.assertEqual(len(ours), 1)
        logging.getLogger("prise_commande").info("message de test")
        self.assertEqual(errors.log_path(), self.storage / "journal.log")
        self.assertIn("message de test", self.journal())

    def test_unwritable_folder_never_raises(self):
        with mock.patch.dict("os.environ", {"FLET_APP_STORAGE_DATA": str(self.storage / "absent" / "x")}):
            errors.setup_logging()
            logging.getLogger("prise_commande").error("sans dossier")


class ConsoleFallbackTests(ErrorsTestCase):
    def stderr_handlers(self):
        return [h for h in logging.getLogger("flet").handlers if getattr(h, "_pc_stderr", False)]

    def test_added_only_when_root_has_no_handlers(self):
        root = logging.getLogger()
        saved = root.handlers[:]
        self.addCleanup(lambda: root.handlers.__setitem__(slice(None), saved))
        root.handlers[:] = [logging.NullHandler()]
        errors.setup_logging()
        self.assertEqual(self.stderr_handlers(), [])
        root.handlers[:] = []
        errors.setup_logging()
        errors.setup_logging()
        self.assertEqual(len(self.stderr_handlers()), 1)
        self.assertEqual(self.stderr_handlers()[0].level, logging.WARNING)

    def test_flet_level_untouched(self):
        before = logging.getLogger("flet").level
        errors.setup_logging()
        self.assertEqual(logging.getLogger("flet").level, before)


class SessionErrorTests(ErrorsTestCase):
    def fake_session(self, usable=True):
        page = TestPage()
        page.data = {"ctx": object()} if usable else None
        return SimpleNamespace(page=page), page

    def test_patch_is_applied_once(self):
        errors.install()
        first = Session.error
        self.assertIs(first, errors._patched_error)
        original = errors._original_error
        errors.install()
        self.assertIs(Session.error, first)
        self.assertIs(errors._original_error, original)

    def test_shows_dialog_and_logs(self):
        errors.setup_logging()
        errors.install()
        session, page = self.fake_session()
        with mock.patch.object(errors, "_original_error") as original:
            Session.error(session, "Traceback: boom")
        original.assert_not_called()
        self.assertEqual(len(page.dialogs), 1)
        self.assertEqual(page.dialogs[0].title.value, "Une erreur est survenue")
        self.assertIn("boom", self.journal())

    def test_no_usable_page_calls_original(self):
        errors.install()
        session, page = self.fake_session(usable=False)
        with mock.patch.object(errors, "_original_error") as original:
            Session.error(session, "connexion")
        original.assert_called_once_with(session, "connexion")
        self.assertEqual(page.dialogs, [])

    def test_usable_page(self):
        session, page = self.fake_session()
        self.assertIs(errors._usable_page(session), page)
        session, page = self.fake_session(usable=False)
        self.assertIsNone(errors._usable_page(session))
        page.controls.append(object())
        self.assertIs(errors._usable_page(session), page)

    def test_failing_dialog_calls_original(self):
        errors.install()
        session, page = self.fake_session()
        page.show_dialog = mock.Mock(side_effect=RuntimeError("dialog"))
        with mock.patch.object(errors, "_original_error") as original:
            Session.error(session, "x")
        original.assert_called_once()

    def test_no_recursion(self):
        errors.install()
        session, page = self.fake_session()
        calls = []

        def reentrant(dialog):
            calls.append(dialog)
            Session.error(session, "erreur pendant le traitement")

        page.show_dialog = reentrant
        with mock.patch.object(errors, "_original_error") as original:
            Session.error(session, "première")
        self.assertEqual(len(calls), 1)
        original.assert_called_once()

    def test_no_second_dialog_while_open(self):
        errors.install()
        session, page = self.fake_session()

        def show(dialog):
            dialog.open = True
            page.dialogs.append(dialog)

        page.show_dialog = show
        with mock.patch.object(errors, "_original_error"):
            Session.error(session, "un")
            Session.error(session, "deux")
            self.assertEqual(len(page.dialogs), 1)
            page.dialogs[0].open = False
            Session.error(session, "trois")
        self.assertEqual(len(page.dialogs), 2)

    def test_logs_first_line_only_except_effects(self):
        errors.setup_logging()
        errors.install()
        session, page = self.fake_session()
        with mock.patch.object(errors, "_original_error"):
            Session.error(session, "ligne un\nTRACE-DETAIL")
            Session.error(session, "Exception in effect: x\nTRACE-EFFET")
        self.assertIn("ligne un", self.journal())
        self.assertNotIn("TRACE-DETAIL", self.journal())
        self.assertIn("TRACE-EFFET", self.journal())

    def test_version_mismatch_leaves_flet_alone(self):
        with mock.patch.object(errors.ft, "__version__", "9.9.9"):
            errors.install()
        self.assertIs(Session.error, self._orig)


class JournalExportTests(ErrorsTestCase):
    def open_page(self):
        catalogue_mod.install_catalogue(catalogue_mod.sample_catalogue_path().read_bytes(), ".xlsx")
        page = TestPage()
        app.main(page)
        tile = page.find(ft.ListTile, title=page.find(ft.Text, value="Sauvegarder / restaurer"))
        asyncio.run(tile.on_click())
        return page

    def export(self, page, **save_kwargs):
        button = page.find(ft.OutlinedButton, content="Exporter le journal")
        with mock.patch.object(ft.FilePicker, "save_file", new_callable=mock.AsyncMock, **save_kwargs) as save:
            asyncio.run(button.on_click())
        self.assertFalse(button.disabled)
        return save

    def test_empty_journal(self):
        page = self.open_page()
        for name in ("journal.log", "journal.log.1"):
            (self.storage / name).unlink(missing_ok=True)
        save = self.export(page)
        save.assert_not_called()
        self.assertEqual(page.find(ft.Text, value="Le journal est vide.").value, "Le journal est vide.")

    def test_exports_previous_then_current_as_txt(self):
        page = self.open_page()
        (self.storage / "journal.log.1").write_bytes(b"ANCIEN\n")
        (self.storage / "journal.log").write_bytes(b"RECENT\n")
        page.web = False  # bureau : l'app écrit elle-même le fichier
        target = self.storage / "sortie"
        save = self.export(page, return_value=str(target))
        kwargs = save.call_args.kwargs
        self.assertEqual(kwargs["src_bytes"], b"ANCIEN\nRECENT\n")
        self.assertEqual(kwargs["file_name"], "journal-prise-commande.txt")
        self.assertEqual(kwargs["allowed_extensions"], ["txt"])
        self.assertEqual(target.with_suffix(".txt").read_bytes(), b"ANCIEN\nRECENT\n")


class CleanupTests(StorageTest):
    def test_main_installs_then_reset_restores(self):
        errors.reset_for_tests()
        original = Session.error
        catalogue_mod.install_catalogue(catalogue_mod.sample_catalogue_path().read_bytes(), ".xlsx")
        app.main(TestPage())
        self.assertIsNot(Session.error, original)
        errors.reset_for_tests()
        self.assertIs(Session.error, original)
        for name in errors._LOGGER_NAMES:
            self.assertFalse([h for h in logging.getLogger(name).handlers
                              if getattr(h, "_pc_journal", None) or getattr(h, "_pc_stderr", False)])


class StartupFailureTests(ErrorsTestCase):
    def test_failed_startup_shows_fallback_screen(self):
        page = TestPage()
        with mock.patch.object(app, "load_catalogue", side_effect=OSError(errno.ENOSPC, "disque plein")):
            app.main(page)
        texts = [c.value for c in page.find(ft.Column).controls if hasattr(c, "value")]
        self.assertIn("Démarrage impossible", texts)
        self.assertIn("Espace de stockage insuffisant", texts)
        self.assertIn("disque plein", self.journal())
        button = page.find(ft.FilledButton, content="Réessayer")
        with mock.patch.object(app, "load_catalogue", return_value=[]), \
                mock.patch.object(app, "show_import_screen") as shown:
            button.on_click(None)
        shown.assert_called_once()


if __name__ == "__main__":
    unittest.main()
