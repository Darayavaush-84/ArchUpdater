from __future__ import annotations

import sys
import unittest
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from archupdater.app import main
from archupdater.infrastructure.settings import AppSettings


class AppStartupTests(unittest.TestCase):
    def test_only_fresh_foreground_launch_requests_initial_check(self) -> None:
        for hidden, existing in ((False, False), (True, False), (False, True), (True, True)):
            with self.subTest(hidden=hidden, existing=existing), ExitStack() as stack:
                mocks = {
                    name: stack.enter_context(patch(f"archupdater.app.{name}"))
                    for name in (
                        "QApplication", "QFont", "QIcon", "QTimer", "SingleInstanceGuard",
                        "AutostartService", "SettingsService", "TranslationManager",
                        "MainWindow", "TrayController", "build_application_stylesheet",
                    )
                }
                argv = ["archupdater", "--start-hidden"] if hidden else ["archupdater"]
                stack.enter_context(patch.object(sys, "argv", argv))
                guard = mocks["SingleInstanceGuard"]
                guard.notify_existing.return_value = existing
                guard.return_value.acquire.return_value = True
                mocks["SettingsService"].return_value.load_app_settings.return_value = AppSettings()
                mocks["QApplication"].return_value.exec.return_value = 0

                self.assertEqual(main(), 0)

                guard.notify_existing.assert_called_once_with(activate=not hidden)
                window = mocks["MainWindow"]
                if existing:
                    window.assert_not_called()
                elif hidden:
                    window.return_value.request_initial_check.assert_not_called()
                else:
                    window.return_value.request_initial_check.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
