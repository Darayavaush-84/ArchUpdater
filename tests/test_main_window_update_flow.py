from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from archupdater.domain.enums import UpdateSource
from archupdater.domain.update_plan import UpdatePlan, UpdatePlanItem
from archupdater.presentation.main_window.update_flow import MainWindowUpdateFlowCoordinator


class _UpdateControllerStub:
    def __init__(
        self,
        *,
        start_check_result: bool = True,
        busy: bool = False,
        start_update_error: Exception | None = None,
    ) -> None:
        self.start_check_result = start_check_result
        self.busy = busy
        self.start_update_error = start_update_error
        self.started_update_plan: UpdatePlan | None = None
        self.local_system_db_calls: list[bool] = []

    def start_check_updates(self, *, use_local_system_db: bool = False) -> bool:
        self.local_system_db_calls.append(use_local_system_db)
        return self.start_check_result

    def is_busy(self) -> bool:
        return self.busy

    def start_update(self, plan: UpdatePlan) -> None:
        if self.start_update_error is not None:
            raise self.start_update_error
        self.started_update_plan = plan


class _ViewStub:
    def __init__(
        self,
        plan: UpdatePlan | None = None,
        *,
        post_update_refresh_pending: bool = False,
    ) -> None:
        self.plan = plan or UpdatePlan()
        self.post_update_refresh_pending = post_update_refresh_pending
        self.calls: list[str] = []

    def build_update_plan(self) -> UpdatePlan:
        return self.plan

    def begin_check_ui(self) -> None:
        self.calls.append("begin_check_ui")

    def show_no_updates_selected_message(self) -> None:
        self.calls.append("show_no_updates_selected_message")

    def has_post_update_refresh_pending(self) -> bool:
        return self.post_update_refresh_pending

    def confirm_update_preconditions(self, plan: UpdatePlan) -> UpdatePlan | None:
        self.calls.append("confirm_update_preconditions")
        return plan

    def prepare_update_start_ui(self) -> None:
        self.calls.append("prepare_update_start_ui")

    def handle_update_start_failure(self, exc: Exception) -> None:
        self.calls.append(f"handle_update_start_failure:{exc}")

    def apply_check_result(self, result) -> None:  # noqa: ANN001
        self.calls.append("apply_check_result")

    def apply_check_failure(self, message: str, logs: object) -> None:
        self.calls.append(f"apply_check_failure:{message}")

    def apply_check_progress(self, label: str, percent: int) -> None:
        self.calls.append(f"apply_check_progress:{label}:{percent}")

    def apply_update_status(self, value: str) -> None:
        self.calls.append(f"apply_update_status:{value}")

    def apply_update_completed(self, success: bool, message: str, outcome: str) -> None:
        self.calls.append(f"apply_update_completed:{success}:{outcome}")

    def refresh_selection_actions(self) -> None:
        self.calls.append("refresh_selection_actions")


class MainWindowUpdateFlowCoordinatorTests(unittest.TestCase):
    def test_start_check_updates_initializes_ui_only_when_controller_accepts(self) -> None:
        view = _ViewStub()
        controller = _UpdateControllerStub(start_check_result=True)
        flow = MainWindowUpdateFlowCoordinator(view=view, update_controller=controller)

        started = flow.start_check_updates()

        self.assertTrue(started)
        self.assertEqual(view.calls, ["begin_check_ui"])
        self.assertEqual(controller.local_system_db_calls, [False])

    def test_start_check_updates_can_request_local_system_database(self) -> None:
        view = _ViewStub()
        controller = _UpdateControllerStub(start_check_result=True)
        flow = MainWindowUpdateFlowCoordinator(view=view, update_controller=controller)

        started = flow.start_check_updates(use_local_system_db=True)

        self.assertTrue(started)
        self.assertEqual(controller.local_system_db_calls, [True])

    def test_start_update_shows_message_when_plan_is_empty(self) -> None:
        view = _ViewStub(plan=UpdatePlan())
        controller = _UpdateControllerStub()
        flow = MainWindowUpdateFlowCoordinator(view=view, update_controller=controller)

        flow.start_update()

        self.assertEqual(view.calls, ["show_no_updates_selected_message"])
        self.assertIsNone(controller.started_update_plan)

    def test_run_update_plan_prepares_ui_and_starts_controller(self) -> None:
        plan = UpdatePlan([UpdatePlanItem(UpdateSource.SYSTEM, "linux")])
        view = _ViewStub(plan=plan)
        controller = _UpdateControllerStub()
        flow = MainWindowUpdateFlowCoordinator(view=view, update_controller=controller)

        flow.run_update_plan(plan)

        self.assertEqual(view.calls, ["prepare_update_start_ui"])
        self.assertIs(controller.started_update_plan, plan)

    def test_update_cannot_start_while_post_update_refresh_is_pending(self) -> None:
        plan = UpdatePlan([UpdatePlanItem(UpdateSource.SYSTEM, "linux")])
        view = _ViewStub(plan=plan, post_update_refresh_pending=True)
        controller = _UpdateControllerStub()
        flow = MainWindowUpdateFlowCoordinator(view=view, update_controller=controller)

        flow.start_update()
        flow.run_update_plan(plan)

        self.assertEqual(view.calls, [])
        self.assertIsNone(controller.started_update_plan)

    def test_synchronous_client_start_failure_is_reported_after_preparing_ui(self) -> None:
        plan = UpdatePlan([UpdatePlanItem(UpdateSource.SYSTEM, "linux")])
        view = _ViewStub(plan=plan)
        controller = _UpdateControllerStub(start_update_error=OSError("disk full"))
        flow = MainWindowUpdateFlowCoordinator(view=view, update_controller=controller)

        flow.run_update_plan(plan)

        self.assertEqual(
            view.calls,
            ["prepare_update_start_ui", "handle_update_start_failure:disk full"],
        )

    def test_run_empty_update_plan_uses_generic_no_selection_message(self) -> None:
        view = _ViewStub()
        controller = _UpdateControllerStub()
        flow = MainWindowUpdateFlowCoordinator(view=view, update_controller=controller)

        flow.run_update_plan(UpdatePlan())

        self.assertEqual(view.calls, ["show_no_updates_selected_message"])
        self.assertIsNone(controller.started_update_plan)

    def test_start_update_checks_preconditions_before_running_plan(self) -> None:
        plan = UpdatePlan([UpdatePlanItem(UpdateSource.SYSTEM, "linux")])
        view = _ViewStub(plan=plan)
        controller = _UpdateControllerStub()
        flow = MainWindowUpdateFlowCoordinator(view=view, update_controller=controller)

        flow.start_update()

        self.assertEqual(view.calls, ["confirm_update_preconditions", "prepare_update_start_ui"])

    def test_start_update_reports_precondition_failures(self) -> None:
        class _FailingPreconditionsView(_ViewStub):
            def confirm_update_preconditions(self, plan: UpdatePlan) -> UpdatePlan | None:
                self.calls.append("confirm_update_preconditions")
                raise RuntimeError("precondition failed")

        view = _FailingPreconditionsView(
            plan=UpdatePlan([UpdatePlanItem(UpdateSource.SYSTEM, "linux")])
        )
        controller = _UpdateControllerStub()
        flow = MainWindowUpdateFlowCoordinator(view=view, update_controller=controller)

        flow.start_update()

        self.assertEqual(
            view.calls,
            ["confirm_update_preconditions", "handle_update_start_failure:precondition failed"],
        )
        self.assertIsNone(controller.started_update_plan)

    def test_handle_busy_changed_refreshes_actions_only_when_idle(self) -> None:
        view = _ViewStub()
        controller = _UpdateControllerStub()
        flow = MainWindowUpdateFlowCoordinator(view=view, update_controller=controller)

        flow.handle_busy_changed(True)
        flow.handle_busy_changed(False)

        self.assertEqual(view.calls, ["refresh_selection_actions"])


if __name__ == "__main__":
    unittest.main()
