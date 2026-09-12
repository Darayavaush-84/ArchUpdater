from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from PySide6.QtWidgets import QApplication, QWidget

from archupdater.application.update_session.protocol import BatchOutcome
from archupdater.presentation.update_completion_coordinator import UpdateCompletionCoordinator


class _StateCacheStub:
    def __init__(self) -> None:
        self.clear_calls = 0

    def clear_update_session(self) -> None:
        self.clear_calls += 1


class UpdateCompletionCoordinatorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._app = QApplication.instance() or QApplication([])

    def test_failure_schedules_refresh_because_an_earlier_step_may_have_changed_system(self) -> None:
        parent = QWidget()
        calls: list[object] = []
        cache = _StateCacheStub()
        coordinator = UpdateCompletionCoordinator(
            parent=parent,
            state_cache=cache,  # type: ignore[arg-type]
            clear_selection=lambda: calls.append("clear"),
            set_operation_state=lambda state, message: calls.append((state, message)),
            set_header_status=lambda value: calls.append(("header", value)),
            append_log=lambda value: calls.append(("log", value)),
            maybe_prompt_plasma_restart=lambda: None,
            maybe_show_reboot_advisory=lambda: calls.append("reboot"),
            should_show_reboot_advisory_after_failure=lambda: True,
            close_progress_dialog=lambda: None,
            update_selection_actions=lambda: calls.append("actions"),
            mark_post_update_refresh_pending=lambda: calls.append("pending"),
            use_local_system_db_for_post_update_refresh=lambda: True,
            start_check_updates=lambda use_local: calls.append(("refresh", use_local)),
            progress_dialog_parent=lambda: None,
            translate=lambda text: text,
        )
        with patch("archupdater.presentation.update_completion_coordinator.QTimer.singleShot") as timer:
            coordinator.apply(
                success=False,
                message="AUR failed",
                outcome=BatchOutcome.FAILED.value,
            )

        self.assertIn("pending", calls)
        self.assertIn("reboot", calls)
        callback = timer.call_args.args[1]
        callback()
        self.assertIn(("refresh", True), calls)
        self.assertEqual(cache.clear_calls, 1)
        parent.deleteLater()

    def test_authentication_cancel_closes_and_refreshes_unchanged_system(self) -> None:
        parent = QWidget()
        calls: list[str] = []
        coordinator = UpdateCompletionCoordinator(
            parent=parent,
            state_cache=_StateCacheStub(),  # type: ignore[arg-type]
            clear_selection=lambda: None,
            set_operation_state=lambda _state, _message: None,
            set_header_status=lambda _value: None,
            append_log=lambda _value: None,
            maybe_prompt_plasma_restart=lambda: None,
            maybe_show_reboot_advisory=lambda: None,
            should_show_reboot_advisory_after_failure=lambda: False,
            close_progress_dialog=lambda: None,
            update_selection_actions=lambda: None,
            mark_post_update_refresh_pending=lambda: calls.append("pending"),
            use_local_system_db_for_post_update_refresh=lambda: False,
            start_check_updates=lambda _use_local: calls.append("refresh"),
            progress_dialog_parent=lambda: None,
            translate=lambda text: text,
        )

        with patch("archupdater.presentation.update_completion_coordinator.QTimer.singleShot") as timer:
            coordinator.apply(
                success=False,
                message="cancelled",
                outcome=BatchOutcome.AUTH_CANCELLED.value,
            )
            self.assertNotIn("pending", calls)
            self.assertEqual(calls, [])
            timer.call_args.args[1]()

        self.assertEqual(calls, ["refresh"])
        parent.deleteLater()

    def test_partial_success_refreshes_the_changed_system(self) -> None:
        parent = QWidget()
        calls: list[object] = []
        coordinator = UpdateCompletionCoordinator(
            parent=parent,
            state_cache=_StateCacheStub(),  # type: ignore[arg-type]
            clear_selection=lambda: calls.append("clear"),
            set_operation_state=lambda state, message: calls.append((state, message)),
            set_header_status=lambda value: calls.append(("header", value)),
            append_log=lambda value: calls.append(("log", value)),
            maybe_prompt_plasma_restart=lambda: calls.append("plasma"),
            maybe_show_reboot_advisory=lambda: calls.append("reboot"),
            should_show_reboot_advisory_after_failure=lambda: False,
            close_progress_dialog=lambda: None,
            update_selection_actions=lambda: None,
            mark_post_update_refresh_pending=lambda: calls.append("pending"),
            use_local_system_db_for_post_update_refresh=lambda: False,
            start_check_updates=lambda use_local: calls.append(("refresh", use_local)),
            progress_dialog_parent=lambda: None,
            translate=lambda text: text,
        )

        with patch(
            "archupdater.presentation.update_completion_coordinator.QTimer.singleShot"
        ) as timer:
            coordinator.apply(
                success=True,
                message="One AUR package was skipped.",
                outcome=BatchOutcome.PARTIAL_SUCCESS.value,
            )

        self.assertIn(("header", "Updates installed with skipped items"), calls)
        self.assertIn("pending", calls)
        self.assertIn("plasma", calls)
        self.assertIn("reboot", calls)
        timer.call_args.args[1]()
        self.assertIn(("refresh", False), calls)
        parent.deleteLater()

    def test_no_changes_clears_selection_without_refresh_or_advisories(self) -> None:
        parent = QWidget()
        calls: list[object] = []
        coordinator = UpdateCompletionCoordinator(
            parent=parent,
            state_cache=_StateCacheStub(),  # type: ignore[arg-type]
            clear_selection=lambda: calls.append("clear"),
            set_operation_state=lambda state, message: calls.append((state, message)),
            set_header_status=lambda value: calls.append(("header", value)),
            append_log=lambda value: calls.append(("log", value)),
            maybe_prompt_plasma_restart=lambda: calls.append("plasma"),
            maybe_show_reboot_advisory=lambda: calls.append("reboot"),
            should_show_reboot_advisory_after_failure=lambda: False,
            close_progress_dialog=lambda: None,
            update_selection_actions=lambda: calls.append("actions"),
            mark_post_update_refresh_pending=lambda: calls.append("pending"),
            use_local_system_db_for_post_update_refresh=lambda: False,
            start_check_updates=lambda _use_local: calls.append("refresh"),
            progress_dialog_parent=lambda: None,
            translate=lambda text: text,
        )

        with patch(
            "archupdater.presentation.update_completion_coordinator.QTimer.singleShot"
        ) as timer:
            coordinator.apply(
                success=True,
                message="No selected updates were installed.",
                outcome=BatchOutcome.NO_CHANGES.value,
            )

        self.assertIn("clear", calls)
        self.assertIn("actions", calls)
        self.assertIn(("header", "No updates installed"), calls)
        self.assertNotIn("pending", calls)
        self.assertNotIn("refresh", calls)
        self.assertNotIn("plasma", calls)
        self.assertNotIn("reboot", calls)
        timer.assert_not_called()
        parent.deleteLater()


if __name__ == "__main__":
    unittest.main()
