from __future__ import annotations

import sys
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from PySide6.QtWidgets import QApplication

from archupdater.domain.check_results import UpdateCheckResult
from archupdater.presentation.plasma_restart_coordinator import PlasmaRestartCoordinator
from archupdater.infrastructure.settings import AppSettings


class _SettingsStub:
    def __init__(self, mode: str) -> None:
        self.mode = mode

    def load_app_settings(self, default_start_on_login: bool = False) -> AppSettings:
        return AppSettings(
            start_on_login=default_start_on_login,
            systray_enabled=False,
            systray_notifications_enabled=False,
            auto_check_enabled=False,
            auto_check_interval_hours=24,
            plasma_restart_mode=self.mode,
        )

    def save_app_settings(self, app_settings: AppSettings) -> None:
        self.mode = app_settings.plasma_restart_mode


class _ServiceStub:
    def __init__(self, *, can_restart: bool, restart_result: bool) -> None:
        self.can_restart = can_restart
        self.restart_result = restart_result
        self.restart_calls = 0

    def check_updates(  # noqa: ANN001
        self,
        progress_callback=None,
        active_optional_sources=None,
        use_local_system_db=False,
        cancel_requested=None,
    ):
        if progress_callback is not None:
            progress_callback("Preparing", 10)
            progress_callback("Completed", 100)
        return UpdateCheckResult(packages=[], checked_at=datetime.now(), logs=[], warnings=[])

    def optional_sources_snapshot(self):  # noqa: ANN001
        from archupdater.domain.optional_sources import OptionalSourcesSnapshot

        return OptionalSourcesSnapshot()

    def can_restart_plasma_shell(self) -> bool:
        return self.can_restart

    def restart_plasma_shell(self) -> bool:
        self.restart_calls += 1
        return self.restart_result


class _AutostartStub:
    def is_enabled(self) -> bool:
        return False


class MainWindowRestartBehaviorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._app = QApplication.instance() or QApplication([])

    def test_never_mode_only_logs_manual_restart_message(self) -> None:
        service = _ServiceStub(can_restart=True, restart_result=True)
        logs: list[str] = []
        coordinator = self._coordinator(
            mode="never",
            service=service,
            append_log=logs.append,
        )

        coordinator.maybe_prompt(True)

        self.assertEqual(service.restart_calls, 0)
        self.assertIn("Restart plasmashell manually", "\n".join(logs))

    def test_auto_mode_restarts_plasma_shell_without_prompt(self) -> None:
        service = _ServiceStub(can_restart=True, restart_result=True)
        logs: list[str] = []
        coordinator = self._coordinator(
            mode="auto",
            service=service,
            append_log=logs.append,
        )

        with patch.object(coordinator, "_ask_restart") as question:
            coordinator.maybe_prompt(True)

        self.assertEqual(service.restart_calls, 1)
        question.assert_not_called()
        self.assertIn("restart requested successfully", "\n".join(logs))

    def test_ask_mode_in_background_does_not_show_prompt(self) -> None:
        service = _ServiceStub(can_restart=True, restart_result=True)
        logs: list[str] = []
        coordinator = self._coordinator(
            mode="ask",
            service=service,
            append_log=logs.append,
            interactive=False,
        )

        with patch.object(coordinator, "_ask_restart") as question:
            coordinator.maybe_prompt(True)

        question.assert_not_called()
        self.assertEqual(service.restart_calls, 0)
        self.assertIn("Restart plasmashell manually", "\n".join(logs))

    def _coordinator(
        self,
        *,
        mode: str,
        service: _ServiceStub,
        append_log,
        interactive: bool = True,
    ) -> PlasmaRestartCoordinator:
        return PlasmaRestartCoordinator(
            service=service,
            settings=_SettingsStub(mode),  # type: ignore[arg-type]
            autostart_service=_AutostartStub(),
            append_log=append_log,
            is_interactive_foreground=lambda: interactive,
            ask_restart=lambda: True,
            warn_restart_failed=lambda: None,
        )


if __name__ == "__main__":
    unittest.main()
