from __future__ import annotations

import sys
from pathlib import Path
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from PySide6.QtCore import QCoreApplication, QEvent, QEventLoop, QTimer
from PySide6.QtWidgets import QApplication, QDialog, QDialogButtonBox

from archupdater.infrastructure.self_updates import SelfUpdateClient
from archupdater.infrastructure.settings import AppSettings
from archupdater.i18n.manager import TranslationManager
from archupdater.presentation.preferences_dialog import PreferencesDialog
from archupdater.presentation.self_update_dialog import SelfUpdateDialog
from archupdater.domain.self_update import self_update_release
from test_self_update import release_payload


class SelfUpdateUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.release = self_update_release(release_payload(), "1.0.0")

    def tearDown(self):
        self.doCleanups()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        self.app.processEvents()

    def make_dialog(self, release=True, restart=None):
        with patch("archupdater.presentation.self_update_dialog.Path.is_file", return_value=True):
            dialog = SelfUpdateDialog(self.release if release else None, "v1.0.1", restart=restart)
        self.addCleanup(dialog.deleteLater)
        return dialog

    def test_unsigned_release_offers_manual_installation(self):
        dialog = self.make_dialog(release=False)
        self.assertFalse(dialog.install_button.isEnabled())
        self.assertIn("no verified update package", dialog.status.text())

    def test_bootstrap_installation_is_required_if_helper_is_missing(self):
        with patch("archupdater.presentation.self_update_dialog.Path.is_file", return_value=False):
            dialog = SelfUpdateDialog(self.release, "v1.0.1")
        self.addCleanup(dialog.deleteLater)
        self.assertFalse(dialog.install_button.isEnabled())
        self.assertIn("install.sh", dialog.status.text())

    def test_busy_dialog_cannot_close_or_start_a_second_install(self):
        dialog = self.make_dialog()
        def start(release):
            dialog.client.busy = True
        with patch.object(dialog.client, "start", side_effect=start) as request:
            dialog.show()
            dialog.install_button.click()
            dialog._install()
            dialog.reject()
            dialog.close()
            self.assertTrue(dialog.isVisible())
            self.assertFalse(dialog.close_button.isEnabled())
            request.assert_called_once_with(self.release)
        dialog.client.busy = False
        dialog.client.completed.emit(False, "verification failure")
        self.assertTrue(dialog.close_button.isEnabled())
        self.assertIn("verification failure", dialog.status.text())
        dialog.close()

    def test_success_restarts_and_failed_restart_offers_recovery(self):
        restart = Mock(return_value=False)
        dialog = self.make_dialog(restart=restart)
        dialog.client.completed.emit(True, "")
        restart.assert_called_once_with()
        self.assertEqual(dialog.install_button.text(), "Restart Now")
        self.assertFalse(dialog.rollback_button.isHidden())
        self.assertIn("Could not restart", dialog.status.text())
        restart.return_value = True
        dialog.install_button.click()
        self.assertEqual(dialog.result(), QDialog.DialogCode.Accepted)

    def test_temporary_directory_failure_restores_idle_state(self):
        client = SelfUpdateClient()
        completed = []
        client.completed.connect(lambda ok, details: completed.append((ok, details)))
        with patch("archupdater.infrastructure.self_updates.tempfile.TemporaryDirectory", side_effect=OSError("disk full")):
            client.start(self.release)
        self.assertFalse(client.busy)
        self.assertEqual(completed, [(False, "disk full")])

    def test_download_failure_stops_thread_without_requesting_authorization(self):
        client = SelfUpdateClient()
        loop = QEventLoop()
        completed = []
        client.completed.connect(lambda ok, detail: (completed.append((ok, detail)), loop.quit()))
        timeout = QTimer()
        timeout.setSingleShot(True)
        timeout.timeout.connect(loop.quit)
        with patch("archupdater.infrastructure.self_updates.download_release", side_effect=ValueError("bad signature")), patch.object(client, "_start_helper") as helper:
            client.start(self.release)
            timeout.start(3000)
            loop.exec()
            timeout.stop()
        self.assertIsNone(client._thread)
        self.assertIsNone(client._temporary)
        self.assertFalse(client.busy)
        self.assertEqual(completed, [(False, "bad signature")])
        helper.assert_not_called()

    def test_successful_download_reaches_helper_after_thread_stops(self):
        client = SelfUpdateClient()
        loop = QEventLoop()
        arguments = []
        def install(args):
            self.assertIsNone(client._thread)
            self.assertTrue(client.busy)
            arguments.extend(args)
            client._finish(True, "")
            loop.quit()
        timeout = QTimer()
        timeout.setSingleShot(True)
        timeout.timeout.connect(loop.quit)
        with patch("archupdater.infrastructure.self_updates.download_release", return_value=(Path("wheel"), Path("bundle"))), patch.object(client, "_start_helper", side_effect=install):
            client.start(self.release)
            timeout.start(3000)
            loop.exec()
            timeout.stop()
        self.assertEqual(arguments, ["--install", "1.0.1", "wheel", "bundle"])
        self.assertFalse(client.busy)

    def test_preferences_dynamic_options_and_buttons_are_translated_in_all_languages(self):
        manager = TranslationManager(self.app)
        self.addCleanup(manager.install, "en")
        for lang in ("it", "de", "fr", "es"):
            with self.subTest(language=lang):
                self.assertEqual(manager.install(lang), lang)
                dialog = PreferencesDialog(AppSettings(language_preference=lang), manager)
                self.addCleanup(dialog.deleteLater)
                for i, english in enumerate(("Ask every time", "Restart automatically", "Do not restart automatically")):
                    self.assertNotEqual(dialog.plasma_restart_combo.itemText(i), english)
                    self.assertTrue(dialog.plasma_restart_combo.itemText(i))
                buttons = dialog.findChild(QDialogButtonBox)
                self.assertNotEqual(buttons.button(QDialogButtonBox.StandardButton.Save).text(), "Save")
                self.assertNotEqual(buttons.button(QDialogButtonBox.StandardButton.Cancel).text(), "Cancel")
