from __future__ import annotations

from typing import Protocol

from archupdater.domain.check_results import UpdateCheckResult
from archupdater.domain.enums import OperationState


class MainWindowCheckView(Protocol):
    def tr(self, text: str) -> str: ...

    def set_check_operation_state(self, state: OperationState, message: str) -> None: ...

    def has_post_update_refresh_pending(self) -> bool: ...

    def show_post_update_refreshing_state(self) -> None: ...

    def reset_for_fresh_check(self) -> None: ...

    def apply_successful_check_result_ui(self, result: UpdateCheckResult) -> None: ...

    def persist_successful_check_result(self) -> None: ...

    def apply_fresh_check_failure_ui(self, message: str, logs: object) -> None: ...

    def apply_check_progress(self, label: str, percent: int) -> None: ...


class MainWindowCheckCoordinator:
    def __init__(self, view: MainWindowCheckView) -> None:
        self._view = view

    def begin_check_ui(self) -> None:
        view = self._view
        view.set_check_operation_state(
            OperationState.CHECKING,
            view.tr("Checking repositories and package metadata..."),
        )
        view.apply_check_progress(view.tr("Preparing"), 10)
        if view.has_post_update_refresh_pending():
            view.show_post_update_refreshing_state()
            return
        view.reset_for_fresh_check()

    def apply_check_result(
        self,
        result: UpdateCheckResult,
        *,
        persist: bool = True,
    ) -> None:
        view = self._view
        view.apply_successful_check_result_ui(result)
        if persist:
            view.persist_successful_check_result()

    def apply_check_failure(self, message: str, logs: object) -> None:
        self._view.apply_fresh_check_failure_ui(message, logs)
