from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import QObject, QTimer, Slot
from PySide6.QtNetwork import QNetworkInformation


class CheckScheduleController(QObject):
    """Own check timers and startup connectivity; the window supplies UI callbacks."""

    STARTUP_NETWORK_RETRY_MS = 3000

    def __init__(
        self,
        *,
        is_busy: Callable[[], bool],
        start_check: Callable[[], bool],
        defer_next_check: Callable[[], None],
        show_waiting_for_network: Callable[[], None],
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._is_busy = is_busy
        self._start_check = start_check
        self._defer_next_check = defer_next_check
        self._show_waiting_for_network = show_waiting_for_network
        self._connected_network: QNetworkInformation | None = None
        self._stopped = False
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.timeout.connect(self.request_scheduled_check)
        self._startup_timer = QTimer(self)
        self._startup_timer.setSingleShot(True)
        self._startup_timer.timeout.connect(self.request_startup_check)

    def start(self) -> None:
        self._stopped = False
        self.timer.stop()
        self._startup_timer.start(0)

    def stop(self) -> None:
        self._stopped = True
        self.timer.stop()
        self._stop_startup_wait()

    def is_waiting_for_network(self) -> bool:
        return self._startup_timer.isActive()

    @Slot()
    def request_startup_check(self) -> None:
        if self._stopped or self._is_busy():
            return
        network = self._network_information()
        if network is None or network.reachability() == QNetworkInformation.Reachability.Online:
            self._stop_startup_wait()
            self._start_check()
            return
        self._show_waiting_for_network()
        if self._connected_network is None:
            try:
                network.reachabilityChanged.connect(self._on_reachability_changed)
            except (RuntimeError, TypeError):
                pass
            else:
                self._connected_network = network
        if not self._startup_timer.isActive():
            self._startup_timer.start(self.STARTUP_NETWORK_RETRY_MS)

    @Slot()
    def request_scheduled_check(self) -> None:
        if self._stopped:
            return
        if self._is_busy() or not self._start_check():
            self._defer_next_check()

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
            self.request_startup_check()

    def _stop_startup_wait(self) -> None:
        self._startup_timer.stop()
        if self._connected_network is not None:
            try:
                self._connected_network.reachabilityChanged.disconnect(
                    self._on_reachability_changed
                )
            except (RuntimeError, TypeError):
                pass
        self._connected_network = None
