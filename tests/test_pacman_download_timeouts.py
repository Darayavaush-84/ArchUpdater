from __future__ import annotations

import os
import sys
import tempfile
import time
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from PySide6.QtCore import QObject, QTimer, Signal
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QMessageBox, QWidget

from support.commands import CommandResponse, FakeCommandRunner
from archupdater.application.helper_protocol import HelperAction, HelperRequest
from archupdater.domain.check_results import UpdateCheckResult
from archupdater.domain.optional_sources import OptionalSourcesSnapshot
from archupdater.helper.actions import pacman_config
from archupdater.helper.privileged_helper import (
    HelperAuthorizationScope, HelperValidationError, validate_request,
)
from archupdater.presentation.pacman_timeout_dialog import PacmanTimeoutDialogCoordinator
from archupdater.presentation.privileged_client import PrivilegedUpdateClient
from archupdater.presentation.update_controller import UpdateController, UpdateCheckWorker
from archupdater.services.command_runner import CommandNotAvailableError
from archupdater.services.pacman import PacmanUpdateService


class PacmanConfigurationTests(unittest.TestCase):
    def test_probe_uses_effective_configuration_and_ignores_failed_queries(self) -> None:
        for response, expected in (
            (CommandResponse(stdout="DisableDownloadTimeout\n"), True),
            (CommandResponse(stdout=""), False),
            (CommandResponse(stdout="#DisableDownloadTimeout\n"), False),
            (CommandResponse(exit_code=1, stdout="DisableDownloadTimeout\n"), False),
        ):
            with self.subTest(response=response):
                runner = FakeCommandRunner([response])
                self.assertEqual(PacmanUpdateService(runner).download_timeouts_disabled(), expected)
                self.assertEqual(runner.commands, [["pacman-conf", "DisableDownloadTimeout"]])
        runner = Mock()
        runner.run.side_effect = CommandNotAvailableError("missing")
        self.assertFalse(PacmanUpdateService(runner).download_timeouts_disabled())

    def test_atomic_edit_preserves_comments_other_settings_and_mode_without_backup(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "pacman.conf"
            original = (
                "[options]\n#DisableDownloadTimeout\n  DisableDownloadTimeout # slow proxy\n"
                "DisableDownloadTimeout\nParallelDownloads = 10\n[core]\nInclude = /a/mirrorlist\n"
            )
            path.write_text(original)
            path.chmod(0o640)
            runner = FakeCommandRunner([CommandResponse(stdout="[options]\n")] * 2)
            pacman_config._enable_download_timeouts_in_file(path, runner)
            expected = original.replace("  Disable", "  #Disable").replace(
                "\nDisableDownloadTimeout\n", "\n#DisableDownloadTimeout\n",
            )
            self.assertEqual(path.read_text(), expected)
            self.assertEqual(path.stat().st_mode & 0o777, 0o640)
            # The candidate is verified before it replaces the original.
            candidate = Path(runner.commands[0][2])
            self.assertEqual(candidate.parent, Path(tmp))
            self.assertNotEqual(candidate, path)
            self.assertEqual(runner.commands[0], [
                "/usr/bin/pacman-conf", "--config", str(candidate), "DisableDownloadTimeout",
            ])
            inode = path.stat().st_ino
            pacman_config._enable_download_timeouts_in_file(path, runner)
            self.assertEqual(runner.commands[1][2], str(path))
            self.assertEqual(path.stat().st_ino, inode)
            self.assertEqual(list(Path(tmp).iterdir()), [path])

    def test_edit_refuses_symlinks_and_failed_replace_preserves_original(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "target"
            target.write_text("DisableDownloadTimeout\n")
            link = Path(tmp) / "pacman.conf"
            link.symlink_to(target)
            runner = FakeCommandRunner([CommandResponse(stdout="[options]\n")])
            with self.assertRaises(OSError):
                pacman_config._enable_download_timeouts_in_file(link, runner)
            with patch.object(os, "replace", side_effect=OSError("read only")):
                with self.assertRaises(OSError):
                    pacman_config._enable_download_timeouts_in_file(target, runner)
            self.assertEqual(target.read_text(), "DisableDownloadTimeout\n")
            self.assertEqual(len(list(Path(tmp).iterdir())), 2)

    def test_directive_kept_by_an_include_leaves_pacman_conf_untouched(self) -> None:
        for verification in (
            CommandResponse(stdout="DisableDownloadTimeout\n"),
            CommandResponse(exit_code=1),
        ):
            with self.subTest(verification=verification), tempfile.TemporaryDirectory() as tmp:
                path = Path(tmp) / "pacman.conf"
                path.write_text("[options]\nDisableDownloadTimeout\n")
                inode = path.stat().st_ino
                with self.assertRaises(OSError):
                    pacman_config._enable_download_timeouts_in_file(
                        path, FakeCommandRunner([verification]),
                    )
                self.assertEqual(path.read_text(), "[options]\nDisableDownloadTimeout\n")
                self.assertEqual(path.stat().st_ino, inode)
                self.assertEqual(list(Path(tmp).iterdir()), [path])
        with tempfile.TemporaryDirectory() as tmp:
            # Nothing to comment out locally, but an include still disables timeouts.
            path = Path(tmp) / "pacman.conf"
            path.write_text("[options]\nInclude = /etc/pacman.d/extra.conf\n")
            with self.assertRaises(OSError):
                pacman_config._enable_download_timeouts_in_file(
                    path, FakeCommandRunner([CommandResponse(stdout="DisableDownloadTimeout\n")]),
                )

    def test_helper_reports_effective_configuration_result(self) -> None:
        for output, expected in (("[options]\n", True), ("DisableDownloadTimeout\n", False)):
            with self.subTest(output=output), tempfile.TemporaryDirectory() as tmp:
                path = Path(tmp) / "pacman.conf"
                path.write_text("DisableDownloadTimeout\n")
                runner = FakeCommandRunner([CommandResponse(stdout=output)])
                emit = Mock()
                with patch.object(pacman_config, "PACMAN_CONFIG", path), patch.object(
                    pacman_config, "CommandRunner", return_value=runner,
                ):
                    status = pacman_config.enable_download_timeouts(emit_event=emit)
                self.assertEqual(status, 0 if expected else 1)
                self.assertEqual(emit.call_args.kwargs["success"], expected)
                self.assertEqual(
                    path.read_text(),
                    "#DisableDownloadTimeout\n" if expected else "DisableDownloadTimeout\n",
                )

    def test_configuration_action_has_its_own_scope_and_accepts_no_paths(self) -> None:
        payload = {"action": HelperAction.ENABLE_DOWNLOAD_TIMEOUTS.value}
        request = validate_request(payload, authorization_scope=HelperAuthorizationScope.PACMAN_CONFIG)
        self.assertEqual(request.action, HelperAction.ENABLE_DOWNLOAD_TIMEOUTS)
        for scope in (HelperAuthorizationScope.UPDATE_SESSION, HelperAuthorizationScope.SUPPORT_PACKAGES):
            with self.assertRaises(HelperValidationError):
                validate_request(payload, authorization_scope=scope)
        with self.assertRaises(HelperValidationError):
            validate_request({**payload, "path": "/tmp/other"})
        with self.assertRaises(HelperValidationError):
            validate_request(
                {"action": HelperAction.REMOVE_SUPPORT_PACKAGES.value, "package_names": ["flatpak"]},
                authorization_scope=HelperAuthorizationScope.PACMAN_CONFIG,
            )


class PacmanTimeoutUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def test_worker_waits_for_choice_without_blocking_gui_and_resumes(self) -> None:
        service = Mock()
        service.optional_sources_snapshot.return_value = OptionalSourcesSnapshot()
        service.download_timeouts_disabled.return_value = True
        service.check_updates.return_value = UpdateCheckResult([], datetime.now(), [])
        controller = UpdateController(service)
        prompts = []

        def confirm() -> None:
            prompts.append(True)
            service.check_updates.assert_not_called()
            QTimer.singleShot(20, controller.resume_check_after_configuration)

        controller.download_timeout_confirmation_requested.connect(confirm)
        try:
            self.assertTrue(controller.start_check_updates())
            deadline = time.monotonic() + 2
            while controller.is_busy() and time.monotonic() < deadline:
                QTest.qWait(10)
            self.assertFalse(controller.is_busy())
            self.assertEqual(prompts, [True])
            service.check_updates.assert_called_once()
        finally:
            controller.shutdown()

    def test_shutdown_releases_worker_waiting_for_configuration(self) -> None:
        service = Mock()
        service.optional_sources_snapshot.return_value = OptionalSourcesSnapshot()
        service.download_timeouts_disabled.return_value = True
        controller = UpdateController(service)
        prompted = []
        controller.download_timeout_confirmation_requested.connect(lambda: prompted.append(True))
        controller.start_check_updates()
        deadline = time.monotonic() + 2
        while not prompted and time.monotonic() < deadline:
            QTest.qWait(10)
        controller.shutdown()
        self.assertEqual(prompted, [True])
        self.assertFalse(controller.is_busy())
        service.check_updates.assert_not_called()

    def test_post_update_local_check_skips_configuration_prompt(self) -> None:
        service = Mock()
        worker = UpdateCheckWorker(service, use_local_system_db=True)
        worker.run()
        service.download_timeouts_disabled.assert_not_called()
        service.check_updates.assert_called_once()

    def test_dialog_decline_accept_auth_failure_and_background(self) -> None:
        class Client(QObject):
            completed = Signal(bool, str)

            def start_enable_download_timeouts(self) -> None:
                pass

        for choice, visible in (("Not now", True), ("Enable timeouts", True), ("", False)):
            with self.subTest(choice=choice, visible=visible):
                window = QWidget()
                if visible:
                    window.show()
                resume = Mock()
                coordinator = PacmanTimeoutDialogCoordinator(window, resume)
                client = Client()

                def choose() -> None:
                    box = QApplication.activeModalWidget()
                    self.assertIsInstance(box, QMessageBox)
                    self.assertIn("10 seconds", box.informativeText())
                    self.assertIn("/etc/pacman.conf", box.informativeText())
                    next(button for button in box.buttons() if button.text() == choice).click()

                with patch(
                    "archupdater.presentation.pacman_timeout_dialog.PrivilegedUpdateClient",
                    return_value=client,
                ) as factory:
                    if visible:
                        QTimer.singleShot(0, choose)
                    coordinator.confirm()
                    if choice == "Enable timeouts":
                        factory.assert_called_once_with(parent=coordinator, authorization_scope="pacman-config")
                        resume.assert_not_called()
                        with patch.object(QMessageBox, "warning") as warning:
                            client.completed.emit(False, "Authentication cancelled")
                            warning.assert_called_once()
                    else:
                        factory.assert_not_called()
                    resume.assert_called_once()
                    coordinator.confirm()
                    self.assertEqual(resume.call_count, 2)
                window.close()

    def test_shutdown_while_dialog_is_open_does_not_start_authentication(self) -> None:
        window = QWidget()
        window.show()
        resume = Mock()
        coordinator = PacmanTimeoutDialogCoordinator(window, resume)

        def shutdown_then_accept() -> None:
            box = QApplication.activeModalWidget()
            self.assertIsInstance(box, QMessageBox)
            coordinator.shutdown()
            next(button for button in box.buttons() if button.text() == "Enable timeouts").click()

        with patch(
            "archupdater.presentation.pacman_timeout_dialog.PrivilegedUpdateClient",
        ) as factory:
            QTimer.singleShot(0, shutdown_then_accept)
            coordinator.confirm()
        factory.assert_not_called()
        resume.assert_called_once()
        window.close()

    def test_window_deleted_while_dialog_is_open_is_handled(self) -> None:
        window = QWidget()
        window.show()
        resume = Mock()
        coordinator = PacmanTimeoutDialogCoordinator(window, resume)

        def close_window() -> None:
            box = QApplication.activeModalWidget()
            self.assertIsInstance(box, QMessageBox)
            coordinator.shutdown()
            window.deleteLater()
            QApplication.sendPostedEvents(None, 0)

        with patch(
            "archupdater.presentation.pacman_timeout_dialog.PrivilegedUpdateClient",
        ) as factory:
            QTimer.singleShot(0, close_window)
            coordinator.confirm()
        factory.assert_not_called()
        resume.assert_called_once()

    def test_success_resumes_without_another_dialog(self) -> None:
        window = QWidget()
        resume = Mock()
        coordinator = PacmanTimeoutDialogCoordinator(window, resume)
        with patch.object(QMessageBox, "warning") as warning:
            coordinator._completed(True, "Enabled")
        warning.assert_not_called()
        resume.assert_called_once()

    def test_privileged_client_uses_configuration_authentication_scope(self) -> None:
        client = PrivilegedUpdateClient(authorization_scope="pacman-config", language_code="it")
        self.assertIn("--archupdater-auth=pacman-config", client._process.arguments())
        with patch.object(client, "_start_request") as start:
            client.start_enable_download_timeouts()
        self.assertEqual(start.call_args.args[0], HelperRequest(
            action=HelperAction.ENABLE_DOWNLOAD_TIMEOUTS, language_code="it",
        ))


if __name__ == "__main__":
    unittest.main()
