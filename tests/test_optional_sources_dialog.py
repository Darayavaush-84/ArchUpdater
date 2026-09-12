from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from PySide6.QtCore import QObject, QTimer, Qt, Signal
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QLabel, QMessageBox, QPushButton

from archupdater.domain.enums import UpdateSource
from archupdater.domain.optional_sources import OptionalSourceStatus, OptionalSourcesSnapshot
from archupdater.presentation.optional_sources_panel import OptionalSourcesPanel


class _ClientStub(QObject):
    log_received = Signal(str)
    completed = Signal(bool, str)

    def __init__(self, success_message: str, service=None) -> None:  # noqa: ANN001
        super().__init__()
        self._success_message = success_message
        self._service = service

    def start_install_support_packages(
        self,
        package_names: list[str],
    ) -> None:
        if self._service is not None:
            self._service.installs.append(package_names)
        QTimer.singleShot(0, lambda: self.completed.emit(True, self._success_message))

    def start_remove_support_packages(self, package_names: list[str]) -> None:
        if self._service is not None:
            self._service.removes.append(package_names)
        QTimer.singleShot(0, lambda: self.completed.emit(True, self._success_message))


class _EagerClientStub(QObject):
    log_received = Signal(str)
    completed = Signal(bool, str)

    def start_install_support_packages(
        self,
        package_names: list[str],
    ) -> None:
        self.log_received.emit(f"installing {' '.join(package_names)}")
        self.completed.emit(True, "installed")


class _ServiceStub:
    def __init__(self, snapshot: OptionalSourcesSnapshot) -> None:
        self._snapshot = snapshot
        self.installs: list[list[str]] = []
        self.removes: list[list[str]] = []
        self.aur_enabled_changes: list[bool] = []
        self.snapshot_requests = 0

    def optional_sources_snapshot(self) -> OptionalSourcesSnapshot:
        self.snapshot_requests += 1
        return self._snapshot

    def set_aur_updates_enabled(self, enabled: bool) -> None:
        self.aur_enabled_changes.append(enabled)
        status = self._snapshot.status_for(UpdateSource.AUR)
        if status is not None:
            status.active = enabled


class _RaisingClientStub(QObject):
    log_received = Signal(str)
    completed = Signal(bool, str)

    def start_install_support_packages(
        self,
        package_names: list[str],
    ) -> None:
        raise RuntimeError(f"boom {' '.join(package_names)}")


class OptionalSourcesPanelTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._app = QApplication.instance() or QApplication([])

    def setUp(self) -> None:
        self.panel: OptionalSourcesPanel | None = None

    def tearDown(self) -> None:
        if self.panel is not None:
            self.panel.deleteLater()
        self._process_events()

    def _client_factory(self, service: _ServiceStub, message: str = "installed"):
        return lambda _parent: _ClientStub(message, service=service)

    def test_only_repository_backends_offer_automatic_installation(self) -> None:
        service = _ServiceStub(
            OptionalSourcesSnapshot(
                statuses={
                    UpdateSource.AUR: OptionalSourceStatus(
                        source=UpdateSource.AUR,
                        installed=False,
                        active=False,
                        status_text="Missing",
                        installable_packages=[],
                    ),
                    UpdateSource.FLATPAK: OptionalSourceStatus(
                        source=UpdateSource.FLATPAK,
                        installed=False,
                        active=False,
                        status_text="Missing",
                        installable_packages=["flatpak"],
                    ),
                }
            )
        )
        self.panel = OptionalSourcesPanel(
            service,
            service.optional_sources_snapshot(),
            client_factory=self._client_factory(service),
        )

        with patch(
            "archupdater.presentation.optional_sources_panel.QMessageBox.question",
            return_value=QMessageBox.StandardButton.Yes,
        ):
            self._click_button("Enable")
            self._process_events()

        self.assertEqual(service.installs, [["flatpak"]])

    def test_support_install_can_be_cancelled_before_full_system_upgrade(self) -> None:
        service = _ServiceStub(
            OptionalSourcesSnapshot(
                statuses={
                    UpdateSource.FLATPAK: OptionalSourceStatus(
                        source=UpdateSource.FLATPAK,
                        installed=False,
                        active=False,
                        status_text="Missing",
                        installable_packages=["flatpak"],
                    ),
                }
            )
        )
        self.panel = OptionalSourcesPanel(
            service,
            service.optional_sources_snapshot(),
            client_factory=self._client_factory(service),
        )
        questions: list[tuple[str, str]] = []

        with patch(
            "archupdater.presentation.optional_sources_panel.QMessageBox.question",
            side_effect=lambda _parent, title, message, *_args: (
                questions.append((title, message)) or QMessageBox.StandardButton.Cancel
            ),
        ):
            self._click_button("Enable")
            self._process_events()

        self.assertEqual(service.installs, [])
        self.assertEqual(len(questions), 1)
        self.assertEqual(questions[0][0], "Full System Upgrade")
        self.assertIn("full system upgrade", questions[0][1])
        self.assertIn("flatpak", questions[0][1])

    def test_aur_disable_only_updates_archupdater_preference(self) -> None:
        service = _ServiceStub(
            OptionalSourcesSnapshot(
                statuses={
                    UpdateSource.AUR: OptionalSourceStatus(
                        source=UpdateSource.AUR,
                        installed=True,
                        active=True,
                        status_text="Installed (paru)",
                        removable_packages=["paru"],
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
        )
        self.panel = OptionalSourcesPanel(service, service.optional_sources_snapshot())

        self._click_button("Disable")
        self._process_events()

        self.assertEqual(service.aur_enabled_changes, [False])
        self.assertEqual(service.removes, [])

    def test_remove_selected_packages_calls_service_for_non_aur_backends(self) -> None:
        service = _ServiceStub(
            OptionalSourcesSnapshot(
                statuses={
                    UpdateSource.AUR: OptionalSourceStatus(
                        source=UpdateSource.AUR,
                        installed=True,
                        active=True,
                        status_text="Installed (paru)",
                        removable_packages=["paru"],
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
        )
        self.panel = OptionalSourcesPanel(
            service,
            service.optional_sources_snapshot(),
            client_factory=self._client_factory(service),
        )

        with patch(
            "archupdater.presentation.optional_sources_panel.QMessageBox.question",
            return_value=QMessageBox.StandardButton.Yes,
        ):
            self._click_button("Remove")
            self._process_events()

        self.assertEqual(service.removes, [["flatpak"]])

    def test_connects_privileged_client_signals_before_starting_operation(self) -> None:
        service = _ServiceStub(
            OptionalSourcesSnapshot(
                statuses={
                    UpdateSource.FLATPAK: OptionalSourceStatus(
                        source=UpdateSource.FLATPAK,
                        installed=False,
                        active=False,
                        status_text="Missing",
                        installable_packages=["flatpak"],
                    ),
                }
            )
        )
        created_clients = 0

        def create_client(_parent) -> _EagerClientStub:  # noqa: ANN001
            nonlocal created_clients
            created_clients += 1
            return _EagerClientStub()

        self.panel = OptionalSourcesPanel(
            service,
            service.optional_sources_snapshot(),
            client_factory=create_client,
        )

        with patch(
            "archupdater.presentation.optional_sources_panel.QMessageBox.question",
            return_value=QMessageBox.StandardButton.Yes,
        ):
            self._click_button("Enable")
            self._process_events()

        self.assertEqual(created_clients, 1)
        self.assertFalse(self.panel.is_busy())
        self.assertEqual(self.panel.status_label.text(), "installed")

    def test_start_failure_restores_panel_state(self) -> None:
        service = _ServiceStub(
            OptionalSourcesSnapshot(
                statuses={
                    UpdateSource.FLATPAK: OptionalSourceStatus(
                        source=UpdateSource.FLATPAK,
                        installed=False,
                        active=False,
                        status_text="Missing",
                        installable_packages=["flatpak"],
                    ),
                }
            )
        )
        self.panel = OptionalSourcesPanel(
            service,
            service.optional_sources_snapshot(),
            client_factory=lambda _parent: _RaisingClientStub(),
        )

        warnings: list[tuple[str, str]] = []

        with (
            patch(
                "archupdater.presentation.optional_sources_panel.QMessageBox.question",
                return_value=QMessageBox.StandardButton.Yes,
            ),
            patch(
                "archupdater.presentation.optional_sources_panel.QMessageBox.warning",
                side_effect=lambda _parent, title, message: warnings.append((title, message)),
            ),
        ):
            self._click_button("Enable")
            self._process_events()

        self.assertFalse(self.panel.is_busy())
        self.assertEqual(self.panel.status_label.text(), "boom flatpak")
        self.assertTrue(all(button.isEnabled() for button in self.panel.findChildren(QPushButton)))
        self.assertEqual(warnings, [("Operation Failed", "boom flatpak")])

    def test_panel_does_not_render_firmware_or_plasma_sources(self) -> None:
        service = _ServiceStub(
            OptionalSourcesSnapshot(
                statuses={
                    UpdateSource.AUR: OptionalSourceStatus(
                        source=UpdateSource.AUR,
                        installed=True,
                        active=True,
                        status_text="Installed (paru)",
                        removable_packages=["paru"],
                    ),
                    UpdateSource.FLATPAK: OptionalSourceStatus(
                        source=UpdateSource.FLATPAK,
                        installed=True,
                        active=True,
                        status_text="Installed",
                        removable_packages=["flatpak"],
                    ),
                    UpdateSource.PLASMA_WIDGET: OptionalSourceStatus(
                        source=UpdateSource.PLASMA_WIDGET,
                        installed=True,
                        active=True,
                        status_text="Installed",
                    ),
                    UpdateSource.FIRMWARE: OptionalSourceStatus(
                        source=UpdateSource.FIRMWARE,
                        installed=True,
                        active=True,
                        status_text="Installed",
                    ),
                }
            )
        )
        self.panel = OptionalSourcesPanel(
            service,
            service.optional_sources_snapshot(),
            client_factory=self._client_factory(service),
        )

        visible_texts = [label.text() for label in self.panel.findChildren(QLabel)]

        self.assertIn("AUR", visible_texts)
        self.assertIn("Flatpak", visible_texts)
        self.assertIn("Device Firmware", visible_texts)
        self.assertNotIn("KDE Store Add-ons", visible_texts)

    def test_panel_renders_firmware_install_and_remove_actions(self) -> None:
        service = _ServiceStub(
            OptionalSourcesSnapshot(
                statuses={
                    UpdateSource.AUR: OptionalSourceStatus(
                        source=UpdateSource.AUR,
                        installed=True,
                        active=True,
                        status_text="Installed (paru)",
                        removable_packages=["paru"],
                    ),
                    UpdateSource.FLATPAK: OptionalSourceStatus(
                        source=UpdateSource.FLATPAK,
                        installed=True,
                        active=True,
                        status_text="Installed",
                        removable_packages=["flatpak"],
                    ),
                    UpdateSource.FIRMWARE: OptionalSourceStatus(
                        source=UpdateSource.FIRMWARE,
                        installed=False,
                        active=False,
                        status_text="Missing",
                        installable_packages=["fwupd"],
                    ),
                }
            )
        )
        self.panel = OptionalSourcesPanel(
            service,
            service.optional_sources_snapshot(),
            client_factory=self._client_factory(service, "removed"),
        )

        with patch(
            "archupdater.presentation.optional_sources_panel.QMessageBox.question",
            return_value=QMessageBox.StandardButton.Yes,
        ):
            self._click_button("Enable")
            self._process_events()

        self.assertEqual(service.installs[-1], ["fwupd"])

        service = _ServiceStub(
            OptionalSourcesSnapshot(
                statuses={
                    UpdateSource.AUR: OptionalSourceStatus(
                        source=UpdateSource.AUR,
                        installed=True,
                        active=True,
                        status_text="Installed (paru)",
                        removable_packages=["paru"],
                    ),
                    UpdateSource.FLATPAK: OptionalSourceStatus(
                        source=UpdateSource.FLATPAK,
                        installed=True,
                        active=True,
                        status_text="Installed",
                        removable_packages=["flatpak"],
                    ),
                    UpdateSource.FIRMWARE: OptionalSourceStatus(
                        source=UpdateSource.FIRMWARE,
                        installed=True,
                        active=True,
                        status_text="Installed",
                        removable_packages=["fwupd"],
                    ),
                }
            )
        )
        self.panel.deleteLater()
        self.panel = OptionalSourcesPanel(
            service,
            service.optional_sources_snapshot(),
            client_factory=self._client_factory(service, "removed"),
        )

        with patch(
            "archupdater.presentation.optional_sources_panel.QMessageBox.question",
            return_value=QMessageBox.StandardButton.Yes,
        ):
            self._click_button("Remove", occurrence=1)
            self._process_events()

        self.assertEqual(service.removes[-1], ["fwupd"])

    def test_missing_aur_helper_offers_no_automatic_install_action(self) -> None:
        service = _ServiceStub(
            OptionalSourcesSnapshot(
                statuses={
                    UpdateSource.AUR: OptionalSourceStatus(
                        source=UpdateSource.AUR,
                        installed=False,
                        active=False,
                        status_text="Missing",
                        installable_packages=[],
                    ),
                }
            )
        )
        self.panel = OptionalSourcesPanel(
            service,
            service.optional_sources_snapshot(),
            client_factory=self._client_factory(service),
        )

        self.assertFalse(
            any(button.text() == "Install" for button in self.panel.findChildren(QPushButton))
        )
        self.assertEqual(service.installs, [])

    def test_installed_aur_enable_shows_security_warning_and_updates_preference(self) -> None:
        service = _ServiceStub(
            OptionalSourcesSnapshot(
                statuses={
                    UpdateSource.AUR: OptionalSourceStatus(
                        source=UpdateSource.AUR,
                        installed=True,
                        active=False,
                        status_text="Installed, disabled in ArchUpdater (paru)",
                        removable_packages=["paru"],
                    ),
                }
            )
        )
        self.panel = OptionalSourcesPanel(service, service.optional_sources_snapshot())

        questions: list[tuple[str, str]] = []
        with patch(
            "archupdater.presentation.optional_sources_panel.QMessageBox.question",
            side_effect=lambda _parent, title, message, *_args: (
                questions.append((title, message)) or QMessageBox.StandardButton.Yes
            ),
        ):
            self._click_button("Enable")
            self._process_events()

        self.assertEqual(service.aur_enabled_changes, [True])
        self.assertEqual(service.installs, [])
        self.assertIn("PKGBUILD", questions[0][1])

    def test_panel_refreshes_snapshot_automatically_on_init(self) -> None:
        service = _ServiceStub(
            OptionalSourcesSnapshot(
                statuses={
                    UpdateSource.AUR: OptionalSourceStatus(
                        source=UpdateSource.AUR,
                        installed=False,
                        active=False,
                        status_text="Missing",
                        installable_packages=["paru"],
                    ),
                }
            )
        )

        self.panel = OptionalSourcesPanel(service, service.optional_sources_snapshot())

        self.assertGreaterEqual(service.snapshot_requests, 2)

    def _click_button(self, text: str, *, occurrence: int = 0) -> None:
        matches = []
        for button in self.panel.findChildren(QPushButton):
            if button.text() == text:
                matches.append(button)
        if occurrence < len(matches):
            QTest.mouseClick(matches[occurrence], Qt.MouseButton.LeftButton)
            return
        self.fail(f"Button not found: {text}")

    def _process_events(self) -> None:
        for _ in range(40):
            self._app.processEvents()
            QTest.qWait(1)


if __name__ == "__main__":
    unittest.main()
