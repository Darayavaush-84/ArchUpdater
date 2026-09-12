from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from PySide6.QtCore import QCoreApplication, QSettings
from PySide6.QtWidgets import QApplication

from archupdater.infrastructure.settings import AppSettings, SettingsService


class SettingsServiceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._app = QApplication.instance() or QApplication([])
        QCoreApplication.setOrganizationName("ArchUpdaterTests")
        QCoreApplication.setApplicationName("ArchUpdaterTests")

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        QSettings.setDefaultFormat(QSettings.Format.IniFormat)
        QSettings.setPath(QSettings.Format.IniFormat, QSettings.Scope.UserScope, self._tmp.name)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_load_defaults_to_ask_for_plasma_restart_mode(self) -> None:
        service = SettingsService()

        self.assertEqual(service.load_app_settings().plasma_restart_mode, "ask")

    def test_load_defaults_for_optional_update_behaviors(self) -> None:
        service = SettingsService()
        settings = service.load_app_settings()

        self.assertFalse(settings.cleanup_unused_flatpak_runtimes)
        self.assertFalse(settings.aur_updates_enabled)

    def test_save_and_load_persists_plasma_restart_mode(self) -> None:
        service = SettingsService()
        service.save_app_settings(AppSettings(plasma_restart_mode="auto"))

        self.assertEqual(service.load_app_settings().plasma_restart_mode, "auto")

    def test_save_and_load_persists_optional_update_preferences(self) -> None:
        service = SettingsService()
        self.assertFalse(service.has_cleanup_unused_flatpak_runtimes_preference())

        service.save_app_settings(
            AppSettings(
                cleanup_unused_flatpak_runtimes=True,
                aur_updates_enabled=True,
            )
        )
        loaded = service.load_app_settings()

        self.assertTrue(loaded.cleanup_unused_flatpak_runtimes)
        self.assertTrue(loaded.aur_updates_enabled)
        self.assertTrue(service.has_cleanup_unused_flatpak_runtimes_preference())

    def test_invalid_plasma_restart_mode_falls_back_to_ask(self) -> None:
        settings = QSettings()
        settings.setValue(SettingsService.PLASMA_RESTART_MODE_KEY, "broken")
        settings.sync()

        service = SettingsService()

        self.assertEqual(service.load_app_settings().plasma_restart_mode, "ask")

    def test_invalid_auto_check_interval_falls_back_to_supported_default(self) -> None:
        settings = QSettings()
        settings.setValue(SettingsService.AUTO_CHECK_INTERVAL_HOURS_KEY, 100_000)
        settings.sync()

        service = SettingsService()

        self.assertEqual(service.load_app_settings().auto_check_interval_hours, 24)


if __name__ == "__main__":
    unittest.main()
