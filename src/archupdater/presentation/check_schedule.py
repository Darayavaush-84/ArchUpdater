from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import QObject, QTimer, Qt, Slot
from PySide6.QtNetwork import QNetworkInformation


class CheckScheduleController(QObject):
    """Own the automatic check timer and connectivity wait."""

    RETRY_DELAY_MS = 3000

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
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.setTimerType(Qt.TimerType.PreciseTimer)
        self.timer.timeout.connect(self.request_scheduled_check)

    def schedule(self, delay_ms: int | None) -> None:
        self.timer.stop()
        self._stop_network_wait()
        if not self._stopped and delay_ms is not None:
            self.timer.start(max(1, delay_ms))

    def stop(self) -> None:
        self.schedule(None)
        self._stopped = True

    def is_waiting_for_network(self) -> bool:
        return self._connected_network is not None

    @Slot()
    def request_scheduled_check(self) -> None:
        if self._stopped:
            return
        self.timer.stop()
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
