from __future__ import annotations

from typing import Protocol

from archupdater.domain.check_results import UpdateCheckResult
from archupdater.domain.update_plan import UpdatePlan
from archupdater.presentation.update_controller import UpdateController


class MainWindowUpdateFlowView(Protocol):
    def build_update_plan(self) -> UpdatePlan: ...

    def begin_check_ui(self) -> None: ...

    def show_no_updates_selected_message(self) -> None: ...

    def has_post_update_refresh_pending(self) -> bool: ...

    def confirm_update_preconditions(self, plan: UpdatePlan) -> UpdatePlan | None: ...

    def prepare_update_start_ui(self) -> None: ...

    def handle_update_start_failure(self, exc: Exception) -> None: ...

    def apply_check_result(self, result: UpdateCheckResult) -> None: ...

    def apply_check_failure(self, message: str, logs: object) -> None: ...

    def apply_check_progress(self, label: str, percent: int) -> None: ...

    def apply_update_status(self, value: str) -> None: ...

    def apply_update_completed(self, success: bool, message: str, outcome: str) -> None: ...

    def refresh_selection_actions(self) -> None: ...


class MainWindowUpdateFlowCoordinator:
    def __init__(self, *, view: MainWindowUpdateFlowView, update_controller: UpdateController) -> None:
        self._view = view
        self._update_controller = update_controller

    def start_check_updates(self, *, use_local_system_db: bool = False) -> bool:
        if not self._update_controller.start_check_updates(
            use_local_system_db=use_local_system_db,
        ):
            return False

        self._view.begin_check_ui()
        return True

    def start_update(self) -> None:
        if self._view.has_post_update_refresh_pending():
            return
        plan = self._view.build_update_plan()
        if not plan.has_any:
            self._view.show_no_updates_selected_message()
            return
        try:
            confirmed_plan = self._view.confirm_update_preconditions(plan)
        except Exception as exc:
            self._view.handle_update_start_failure(exc)
            return
        if confirmed_plan is None:
            return
        self.run_update_plan(confirmed_plan)

    def run_update_plan(self, plan: UpdatePlan) -> None:
        if self._view.has_post_update_refresh_pending():
            return
        if not plan.has_any:
            self._view.show_no_updates_selected_message()
            return

        self._view.prepare_update_start_ui()
        try:
            self._update_controller.start_update(plan)
        except Exception as exc:
            self._view.handle_update_start_failure(exc)

    def handle_check_success(self, result: UpdateCheckResult) -> None:
        self._view.apply_check_result(result)

    def handle_check_failure(self, message: str, logs: object) -> None:
        self._view.apply_check_failure(message, logs)

    def handle_check_progress(self, label: str, percent: int) -> None:
        self._view.apply_check_progress(label, percent)

    def handle_update_status(self, value: str) -> None:
        self._view.apply_update_status(value)

    def handle_update_completed(self, success: bool, message: str, outcome: str) -> None:
        self._view.apply_update_completed(success, message, outcome)

    def handle_busy_changed(self, busy: bool) -> None:
        if not busy:
            self._view.refresh_selection_actions()
