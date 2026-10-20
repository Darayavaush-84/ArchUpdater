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
        self.assertGreater(self.controller.remaining_ms(), 86399000)


class CheckScheduleSuspendTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self) -> None:
        self.start_check = Mock(return_value=True)
        self.controller = CheckScheduleController(
            is_busy=lambda: False, start_check=self.start_check, show_waiting_for_network=Mock(),
        )
        self.addCleanup(self.controller.stop)
        patcher = patch(
            "archupdater.presentation.check_schedule.QNetworkInformation",
            FakeNetworkInformationApi(FakeNetworkInformation(FakeReachability.Online)),
        )
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_long_delay_wakes_in_bounded_slices(self) -> None:
        self.controller.schedule(24 * 3600 * 1000)
        self.assertLessEqual(self.controller.timer.remainingTime(), self.controller.MAX_TIMER_SLICE_MS)
        self.assertGreater(self.controller.remaining_ms(), 24 * 3600 * 1000 - 1000)
        self.controller.timer.timeout.emit()
        self.start_check.assert_not_called()
        self.assertTrue(self.controller.timer.isActive())

    def test_deadline_passed_during_suspend_starts_the_check_on_next_slice(self) -> None:
        wall_clock = [1_000_000.0]
        monotonic_clock = [500.0]
        with patch("archupdater.presentation.check_schedule.time.time", lambda: wall_clock[0]), \
                patch("archupdater.presentation.check_schedule.time.monotonic",
                      lambda: monotonic_clock[0]):
            self.controller.schedule(24 * 3600 * 1000)
            # Suspended for a day: the wall clock advances, the monotonic clock does not.
            wall_clock[0] += 24 * 3600 + 60
            monotonic_clock[0] += 60
            self.assertEqual(self.controller.remaining_ms(), 0)
            self.controller.timer.timeout.emit()
        self.start_check.assert_called_once_with()

    def test_clock_set_backwards_does_not_postpone_the_check(self) -> None:
        wall_clock = [1_000_000.0]
        monotonic_clock = [500.0]
        with patch("archupdater.presentation.check_schedule.time.time", lambda: wall_clock[0]), \
                patch("archupdater.presentation.check_schedule.time.monotonic",
                      lambda: monotonic_clock[0]):
            self.controller.schedule(3600 * 1000)
            wall_clock[0] -= 7 * 24 * 3600
            monotonic_clock[0] += 3600
            self.assertEqual(self.controller.remaining_ms(), 0)
            self.controller.timer.timeout.emit()
        self.start_check.assert_called_once_with()
