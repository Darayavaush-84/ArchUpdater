from __future__ import annotations

from PySide6.QtCore import QObject, Signal

from archupdater.domain.enums import OperationState


class ProgressController(QObject):
    progress_changed = Signal(str, int, bool)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._check_label = self.tr("Preparing")
        self._check_percent = 10

    def sync_for_state(self, state: OperationState) -> None:
        if state is OperationState.CHECKING:
            self.progress_changed.emit(self._check_label, self._check_percent, True)
            return

        if state is OperationState.WAITING_AUTH:
            self.progress_changed.emit(self.tr("Waiting for Authentication"), 10, True)
            return

        if state is OperationState.UPDATING:
            self.progress_changed.emit(self.tr("Updating"), 70, True)
            return

        if state is OperationState.COMPLETED:
            self.progress_changed.emit(self.tr("Completed"), 100, False)
        else:
            self.progress_changed.emit("", 0, False)

    def set_check_progress(self, label: str, percent: int) -> None:
        self._check_label = label
        self._check_percent = max(0, min(100, percent))
        self.progress_changed.emit(self._check_label, self._check_percent, True)
