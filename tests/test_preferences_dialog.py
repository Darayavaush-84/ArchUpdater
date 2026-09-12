from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QDialogButtonBox, QMessageBox, QPushButton

from archupdater.domain.enums import UpdateSource
from archupdater.domain.optional_sources import OptionalSourceStatus, OptionalSourcesSnapshot
from archupdater.i18n.manager import TranslationManager
from archupdater.presentation.optional_sources_dialog import OptionalSourcesDialog
from archupdater.presentation.preferences_dialog import PreferencesDialog
from archupdater.infrastructure.settings import AppSettings


class _ControllableClient(QObject):
    log_received = Signal(str)
    completed = Signal(bool, str)

    def __init__(self) -> None:
        super().__init__()
        self.install_requests: list[list[str]] = []
        self.remove_requests: list[list[str]] = []

    def start_install_support_packages(
        self,
        package_names: list[str],
    ) -> None:
        self.install_requests.append(package_names)

    def start_remove_support_packages(self, package_names: list[str]) -> None:
        self.remove_requests.append(package_names)


class _ServiceStub:
    def __init__(self, snapshot: OptionalSourcesSnapshot) -> None:
        self._snapshot = snapshot
        self.client = _ControllableClient()

    def optional_sources_snapshot(self) -> OptionalSourcesSnapshot:
        return self._snapshot


class PreferencesDialogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._app = QApplication.instance() or QApplication([])

    def setUp(self) -> None:
        self.service: _ServiceStub | None = None
        self.sources_dialog: OptionalSourcesDialog | None = None
        self.dialog: PreferencesDialog | None = None

    def tearDown(self) -> None:
        if self.service is not None:
            self.service.client.completed.emit(True, "done")
            self._process_events()
        if self.sources_dialog is not None:
            self.sources_dialog.close()
            self.sources_dialog.deleteLater()
            self._process_events()
        if self.dialog is not None:
            self.dialog.close()
            self.dialog.deleteLater()
            self._process_events()

    def test_preferences_exposes_manage_update_sources_action(self) -> None:
        snapshot = OptionalSourcesSnapshot(
            statuses={
                UpdateSource.AUR: OptionalSourceStatus(
                    source=UpdateSource.AUR,
                    installed=False,
                    active=False,
                    status_text="Missing",
                    installable_packages=["paru"],
                ),
                UpdateSource.FLATPAK: OptionalSourceStatus(
                    source=UpdateSource.FLATPAK,
                    installed=True,
                    active=True,
                    status_text="Installed",
                    removable_packages=["flatpak"],
                ),
            }
        )
        self.service = _ServiceStub(snapshot)
        self.dialog = PreferencesDialog(
            AppSettings(),
            TranslationManager(self._app),
            update_service=self.service,  # type: ignore[arg-type]
            optional_sources_snapshot=snapshot,
        )

        manage_button = self._find_button("Manage Update Sources")

        self.assertIsNotNone(manage_button)

    def test_selected_app_settings_includes_plasma_restart_mode(self) -> None:
        self.dialog = PreferencesDialog(
            AppSettings(plasma_restart_mode="never"),
            TranslationManager(self._app),
        )

        auto_index = self.dialog.plasma_restart_combo.findData("auto")
        self.dialog.plasma_restart_combo.setCurrentIndex(auto_index)

        self.assertEqual(self.dialog.selected_app_settings().plasma_restart_mode, "auto")

    def test_optional_sources_dialog_cannot_close_while_operation_is_running(self) -> None:
        snapshot = OptionalSourcesSnapshot(
            statuses={
                UpdateSource.AUR: OptionalSourceStatus(
                    source=UpdateSource.AUR,
                    installed=False,
                    active=False,
                    status_text="Missing",
                    installable_packages=["paru"],
                ),
                UpdateSource.FLATPAK: OptionalSourceStatus(
                    source=UpdateSource.FLATPAK,
                    installed=True,
                    active=True,
                    status_text="Installed",
                    removable_packages=["flatpak"],
                ),
            }
        )
        self.service = _ServiceStub(snapshot)
        self.sources_dialog = OptionalSourcesDialog(
            self.service,  # type: ignore[arg-type]
            snapshot,
            client_factory=lambda _parent: self.service.client,
        )
        self.sources_dialog.show()
        self._process_events()

        install_button = self._find_button("Install", root=self.sources_dialog)

        from unittest.mock import patch

        with patch(
            "archupdater.presentation.optional_sources_panel.QMessageBox.question",
            return_value=QMessageBox.StandardButton.Yes,
        ):
            QTest.mouseClick(install_button, Qt.MouseButton.LeftButton)
            self._process_events()

        close_button = self.sources_dialog.buttons.button(QDialogButtonBox.StandardButton.Close)
        self.assertFalse(close_button.isEnabled())

        self.sources_dialog.reject()
        self._process_events()
        self.assertTrue(self.sources_dialog.isVisible())

        self.service.client.completed.emit(True, "done")
        self._process_events()

        self.assertTrue(close_button.isEnabled())

    def _find_button(self, text: str, *, root=None) -> QPushButton:  # noqa: ANN001
        search_root = root if root is not None else self.dialog
        for button in search_root.findChildren(QPushButton):
            if button.text() == text:
                return button
        self.fail(f"Button not found: {text}")

    def _process_events(self) -> None:
        for _ in range(40):
            self._app.processEvents()
            QTest.qWait(1)


if __name__ == "__main__":
    unittest.main()
