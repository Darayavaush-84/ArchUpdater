from __future__ import annotations

from typing import Any

from PySide6.QtCore import QCoreApplication

from archupdater.domain.enums import OperationState
from archupdater.domain.update_plan import UpdatePlan
from archupdater.presentation.main_window.logic import build_update_plan
from archupdater.presentation.main_window.state import MainWindowState


class MainWindowOperationPresenter:
    def __init__(self, window: Any, state: MainWindowState) -> None:
        self._window = window
        self._state = state

    def set_operation_state(self, state: OperationState, message: str) -> None:
        self._state.operation_state = state
        if state in {
            OperationState.CHECKING,
            OperationState.WAITING_AUTH,
            OperationState.UPDATING,
            OperationState.COMPLETED,
        }:
            self._window.action_bar.clear_status_text()
        else:
            self._window.action_bar.set_status_text(
                f"{self._operation_state_text(state)}: {message}"
            )

        busy = state in {
            OperationState.CHECKING,
            OperationState.WAITING_AUTH,
            OperationState.UPDATING,
        }
        self._window._progress_controller.sync_for_state(state)
        self._window.action_bar.set_busy(busy)
        self._window.package_updates_widget.set_enabled_for_operations(not busy)
        if busy:
            self._window.action_bar.set_update_enabled(False)
        elif state is not OperationState.ERROR:
            self.update_selection_actions()

        self.refresh_details_empty_state()

    def refresh_details_empty_state(self) -> None:
        self._window._details_presenter.show_empty_state(
            current_state=self._state.operation_state,
            has_packages=bool(self._state.packages),
            failure_message=self._state.check_failure_message,
        )
        self._window._sync_side_panel_mode()

    def update_selection_actions(self) -> None:
        if (
            self._window._update_controller.is_busy()
            or self._state.post_update_refresh_pending
            or self._state.operation_state is OperationState.ERROR
        ):
            self._window.action_bar.set_update_enabled(False)
            return

        plan = self.build_update_plan()
        self._window.action_bar.set_update_selection(len(plan.update_items()))

    def build_update_plan(self) -> UpdatePlan:
        return build_update_plan(self._state.packages)

    def _operation_state_text(self, state: OperationState) -> str:
        mapping = {
            OperationState.IDLE: QCoreApplication.translate("MainWindow", "Idle"),
            OperationState.CHECKING: QCoreApplication.translate("MainWindow", "Checking"),
            OperationState.WAITING_AUTH: QCoreApplication.translate(
                "MainWindow", "Waiting for Authentication"
            ),
            OperationState.UPDATING: QCoreApplication.translate("MainWindow", "Updating"),
            OperationState.COMPLETED: QCoreApplication.translate("MainWindow", "Completed"),
            OperationState.ERROR: QCoreApplication.translate("MainWindow", "Error"),
        }
        return mapping[state]
