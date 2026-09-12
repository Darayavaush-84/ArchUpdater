from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from PySide6.QtWidgets import QApplication

from archupdater.presentation.check_schedule import CheckScheduleController
from support.network import FakeNetworkInformation, FakeNetworkInformationApi, FakeReachability


class CheckScheduleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self) -> None:
        self.busy = Mock(return_value=False)
        self.start_check = Mock(return_value=True)
        self.defer = Mock()
        self.waiting = Mock()
        self.controller = CheckScheduleController(
            is_busy=self.busy,
            start_check=self.start_check,
            defer_next_check=self.defer,
            show_waiting_for_network=self.waiting,
        )
        self.addCleanup(self.controller.stop)
        self.network = FakeNetworkInformation(FakeReachability.Disconnected)
        self.api = FakeNetworkInformationApi(self.network)
        patcher = patch("archupdater.presentation.check_schedule.QNetworkInformation", self.api)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_offline_retries_do_not_duplicate_the_online_subscription(self) -> None:
        self.controller.request_startup_check()
        self.controller.request_startup_check()
        self.start_check.assert_not_called()
        self.assertTrue(self.controller.is_waiting_for_network())
        self.network.set_reachability(FakeReachability.Online)
        self.start_check.assert_called_once_with()
        self.assertFalse(self.controller.is_waiting_for_network())
        self.network.set_reachability(FakeReachability.Online)
        self.start_check.assert_called_once_with()

    def test_stop_disconnects_network_and_cancels_both_timers(self) -> None:
        self.controller.request_startup_check()
        self.controller.timer.start(1000)
        self.controller.stop()
        self.network.set_reachability(FakeReachability.Online)
        self.controller.request_scheduled_check()
        self.start_check.assert_not_called()
        self.assertFalse(self.controller.timer.isActive())
        self.assertFalse(self.controller.is_waiting_for_network())

    def test_busy_scheduled_check_is_deferred(self) -> None:
        self.busy.return_value = True
        self.controller.request_scheduled_check()
        self.start_check.assert_not_called()
        self.defer.assert_called_once_with()

    def test_declined_scheduled_check_is_deferred(self) -> None:
        self.start_check.return_value = False
        self.controller.request_scheduled_check()
        self.start_check.assert_called_once_with()
        self.defer.assert_called_once_with()

    def test_startup_can_proceed_without_a_network_backend(self) -> None:
        with patch.object(self.api, "loadDefaultBackend", return_value=False):
            self.controller.request_startup_check()
        self.start_check.assert_called_once_with()
        self.waiting.assert_not_called()

    def test_busy_startup_does_not_launch_a_second_scan(self) -> None:
        self.busy.return_value = True
        self.network.set_reachability(FakeReachability.Online)
        self.controller.request_startup_check()
        self.start_check.assert_not_called()
