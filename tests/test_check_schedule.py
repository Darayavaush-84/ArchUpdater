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
        self.waiting = Mock()
        self.controller = CheckScheduleController(
            is_busy=self.busy,
            start_check=self.start_check,
            show_waiting_for_network=self.waiting,
        )
        self.addCleanup(self.controller.stop)
        self.network = FakeNetworkInformation(FakeReachability.Online)
        self.api = FakeNetworkInformationApi(self.network)
        patcher = patch("archupdater.presentation.check_schedule.QNetworkInformation", self.api)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_due_check_waits_for_network_without_duplicate_subscriptions(self) -> None:
        self.network.set_reachability(FakeReachability.Disconnected)
        self.controller.request_scheduled_check()
        self.controller.request_scheduled_check()
        self.start_check.assert_not_called()
        self.assertTrue(self.controller.is_waiting_for_network())
        self.network.set_reachability(FakeReachability.Online)
        self.start_check.assert_called_once_with()
        self.assertFalse(self.controller.is_waiting_for_network())
        self.network.set_reachability(FakeReachability.Online)
        self.start_check.assert_called_once_with()

    def test_stop_disconnects_network_and_cancels_the_timer(self) -> None:
        self.network.set_reachability(FakeReachability.Disconnected)
        self.controller.request_scheduled_check()
        self.controller.timer.start(1000)
        self.controller.stop()
        self.network.set_reachability(FakeReachability.Online)
        self.controller.request_scheduled_check()
        self.start_check.assert_not_called()
        self.assertFalse(self.controller.timer.isActive())
        self.assertFalse(self.controller.is_waiting_for_network())

    def test_busy_check_retries_without_postponing_a_full_interval(self) -> None:
        self.busy.return_value = True
        self.controller.request_scheduled_check()
        self.start_check.assert_not_called()
        self.assertGreater(self.controller.timer.remainingTime(), 0)
        self.assertLessEqual(self.controller.timer.remainingTime(), self.controller.RETRY_DELAY_MS)

    def test_declined_check_retries_without_postponing_a_full_interval(self) -> None:
        self.start_check.return_value = False
        self.controller.request_scheduled_check()
        self.start_check.assert_called_once_with()
        self.assertGreater(self.controller.timer.remainingTime(), 0)
        self.assertLessEqual(self.controller.timer.remainingTime(), self.controller.RETRY_DELAY_MS)

    def test_due_check_can_proceed_without_a_network_backend(self) -> None:
        with patch.object(self.api, "loadDefaultBackend", return_value=False):
            self.controller.request_scheduled_check()
        self.start_check.assert_called_once_with()
        self.waiting.assert_not_called()

    def test_disabling_checks_cancels_a_pending_network_wait(self) -> None:
        self.network.set_reachability(FakeReachability.Disconnected)
        self.controller.request_scheduled_check()
        self.controller.schedule(None)
        self.network.set_reachability(FakeReachability.Online)
        self.start_check.assert_not_called()
        self.assertFalse(self.controller.timer.isActive())
        self.assertFalse(self.controller.is_waiting_for_network())

    def test_rescheduling_a_pending_check_cancels_its_network_trigger(self) -> None:
        self.network.set_reachability(FakeReachability.Disconnected)
        self.controller.request_scheduled_check()
        self.controller.schedule(86400000)
        self.network.set_reachability(FakeReachability.Online)
        self.start_check.assert_not_called()
        self.assertGreater(self.controller.timer.remainingTime(), 86399000)
