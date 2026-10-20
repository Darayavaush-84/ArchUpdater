from __future__ import annotations

import math
import time
from collections.abc import Callable

from PySide6.QtCore import QObject, QTimer, Qt, Slot
from PySide6.QtNetwork import QNetworkInformation


class CheckScheduleController(QObject):
    """Own the automatic check timer and connectivity wait."""

    RETRY_DELAY_MS = 3000
    # QTimer follows the monotonic clock, which stops during suspend. Waking up in
    # bounded slices lets the wall clock catch up after the system resumes.
    MAX_TIMER_SLICE_MS = 5 * 60 * 1000

    def __init__(
        self,
        *,
        is_busy: Callable[[], bool],
        start_check: Callable[[], bool],
        show_waiting_for_network: Callable[[], None],
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._is_busy = is_busy
        self._start_check = start_check
        self._show_waiting_for_network = show_waiting_for_network
        self._connected_network: QNetworkInformation | None = None
        self._stopped = False
        self._wall_deadline: float | None = None
        self._monotonic_deadline: float | None = None
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.setTimerType(Qt.TimerType.PreciseTimer)
        self.timer.timeout.connect(self._on_timeout)

    def schedule(self, delay_ms: int | None) -> None:
        self.timer.stop()
        self._clear_deadline()
        self._stop_network_wait()
        if not self._stopped and delay_ms is not None:
            delay_seconds = max(1, delay_ms) / 1000
            self._wall_deadline = time.time() + delay_seconds
            self._monotonic_deadline = time.monotonic() + delay_seconds
            self._start_slice()

    def remaining_ms(self) -> int | None:
        if not self.timer.isActive():
            return None
        deadline_remaining = self._deadline_remaining_ms()
        if deadline_remaining is None:
            return max(0, self.timer.remainingTime())
        return deadline_remaining

    def _deadline_remaining_ms(self) -> int | None:
        if self._wall_deadline is None or self._monotonic_deadline is None:
            return None
        # Suspend shortens the wall-clock wait; a clock set backwards never extends
        # it past the monotonic deadline.
        remaining_seconds = min(
            self._wall_deadline - time.time(),
            self._monotonic_deadline - time.monotonic(),
        )
        return max(0, math.ceil(remaining_seconds * 1000))

    def stop(self) -> None:
        self.schedule(None)
        self._stopped = True

    def is_waiting_for_network(self) -> bool:
        return self._connected_network is not None

    def _start_slice(self) -> None:
        remaining = self._deadline_remaining_ms() or 0
        self.timer.start(max(1, min(remaining, self.MAX_TIMER_SLICE_MS)))

    def _clear_deadline(self) -> None:
        self._wall_deadline = None
        self._monotonic_deadline = None

    @Slot()
    def _on_timeout(self) -> None:
        if self._deadline_remaining_ms():
            self._start_slice()
            return
        self.request_scheduled_check()

    @Slot()
    def request_scheduled_check(self) -> None:
        if self._stopped:
            return
        self.timer.stop()
        self._clear_deadline()
        if self._is_busy():
            self.timer.start(self.RETRY_DELAY_MS)
            return
        network = self._network_information()
        if network is None or network.reachability() == QNetworkInformation.Reachability.Online:
            self._stop_network_wait()
            if not self._start_check():
                self.timer.start(self.RETRY_DELAY_MS)
            return
        self._show_waiting_for_network()
        if self._connected_network is None:
            network.reachabilityChanged.connect(self._on_reachability_changed)
            self._connected_network = network
        self.timer.start(self.RETRY_DELAY_MS)

    def _network_information(self) -> QNetworkInformation | None:
        try:
            if not QNetworkInformation.loadDefaultBackend():
                return None
            return QNetworkInformation.instance()
        except RuntimeError:
            return None

    @Slot(object)
    def _on_reachability_changed(self, _reachability: object) -> None:
        network = self._connected_network
        if (
            network is not None
            and network.reachability() == QNetworkInformation.Reachability.Online
        ):
            self.request_scheduled_check()

    def _stop_network_wait(self) -> None:
        if self._connected_network is not None:
            try:
                self._connected_network.reachabilityChanged.disconnect(
                    self._on_reachability_changed
                )
            except (RuntimeError, TypeError):
                pass
        self._connected_network = None
