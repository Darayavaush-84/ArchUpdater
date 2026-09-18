from __future__ import annotations

import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))

from PySide6.QtWidgets import QApplication

from archupdater.infrastructure.settings import AppSettings
from archupdater.presentation.background_behavior import BackgroundBehaviorController
from archupdater.presentation.check_schedule import CheckScheduleController
from archupdater.presentation.main_window import MainWindow


class BackgroundBehaviorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self) -> None:
        self.settings = AppSettings(auto_check_enabled=True, auto_check_interval_hours=24)
        self.service = Mock()
        self.service.load_app_settings.side_effect = lambda **kwargs: self.settings
        self.service.save_app_settings.side_effect = lambda settings: setattr(self, 'settings', settings)
        self.schedule = CheckScheduleController(
            is_busy=lambda: False, start_check=lambda: True, show_waiting_for_network=lambda: None,
        )
        self.timer = self.schedule.timer
        self.addCleanup(self.schedule.stop)
        self.background = BackgroundBehaviorController(
            settings=self.service, autostart_service=SimpleNamespace(is_enabled=lambda: False),
            check_schedule=self.schedule,
        )

    def test_tray_frequency_change_uses_last_check_and_refreshes_label(self) -> None:
        window = SimpleNamespace(
            _background_behavior=self.background,
            _state=SimpleNamespace(last_checked_at=datetime.now() - timedelta(hours=2)),
            action_bar=Mock(), _update_next_check_label=Mock(),
        )
        MainWindow.set_auto_check_schedule(window, 6)
        self.assertAlmostEqual(self.timer.remainingTime() / 3600000, 4, delta=0.01)
        next_check = MainWindow.next_auto_check_at(window)
        self.assertAlmostEqual((next_check - datetime.now()).total_seconds() / 3600, 4, delta=0.01)
        window._update_next_check_label.assert_called_once_with()

    def test_overdue_check_runs_promptly_when_frequency_is_shortened(self) -> None:
        self.background.set_auto_check_schedule(6, last_checked_at=datetime.now() - timedelta(hours=8))
        self.assertLessEqual(self.timer.remainingTime(), 5)

    def test_deferred_check_display_uses_actual_timer_instead_of_past_deadline(self) -> None:
        last_checked = datetime.now() - timedelta(hours=30)
        self.background.apply_auto_check_settings(self.settings, last_checked_at=last_checked, defer_if_due=True)
        next_check = self.background.next_check_at(self.settings, last_checked_at=last_checked)
        self.assertAlmostEqual((next_check - datetime.now()).total_seconds() / 3600, 24, delta=0.01)

    def test_disabled_checks_have_no_timer_or_next_check(self) -> None:
        self.background.set_auto_check_schedule(None)
        self.assertFalse(self.timer.isActive())
        self.assertIsNone(self.background.next_check_at(self.settings, last_checked_at=None))

    def test_daily_interval_means_24_elapsed_hours_across_timezone_offsets(self) -> None:
        checked_at = datetime(2026, 10, 24, 10, tzinfo=timezone(timedelta(hours=2)))
        now = datetime(2026, 10, 25, 9, tzinfo=timezone(timedelta(hours=1)))
        self.assertEqual(
            self.background.auto_check_delay_ms(self.settings, last_checked_at=checked_at, now=now),
            0,
        )

    def test_startup_preference_reflects_entry_not_a_stale_saved_flag(self) -> None:
        self.settings.start_on_login = True
        self.assertFalse(self.background.load_app_settings().start_on_login)


if __name__ == '__main__':
    unittest.main()
