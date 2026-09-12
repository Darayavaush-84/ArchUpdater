from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from archupdater.domain.enums import UpdateSource
from archupdater.domain.optional_sources import OptionalSourcesSnapshot
from archupdater.domain.progress import UpdateProgressSnapshot
from archupdater.domain.update_plan import UpdatePlan, UpdatePlanAction, UpdatePlanItem
from archupdater.presentation.update_controller import UpdateController
from archupdater.application.update_session.protocol import BatchOutcome


class _ServiceStub:
    def optional_sources_snapshot(self) -> OptionalSourcesSnapshot:
        return OptionalSourcesSnapshot()


class _UpdateClientStub:
    def __init__(self) -> None:
        self.terminated = 0
        self.status_changed = _SignalStub()
        self.log_received = _SignalStub()
        self.progress_changed = _SignalStub()
        self.question_requested = _SignalStub()
        self.completed = _SignalStub()

    def terminate(self) -> None:
        self.terminated += 1


class _WorkerStub:
    def __init__(self) -> None:
        self.progress_changed = _SignalStub()
        self.finished = _SignalStub()
        self.failed = _SignalStub()

    def deleteLater(self) -> None:
        return None


class _ThreadStub:
    def __init__(self, *, wait_result: bool = True) -> None:
        self.quit_calls = 0
        self.wait_calls: list[int | None] = []
        self.terminate_calls = 0
        self.wait_result = wait_result

    def quit(self) -> None:
        self.quit_calls += 1

    def wait(self, timeout: int | None = None) -> bool:
        self.wait_calls.append(timeout)
        return self.wait_result

    def deleteLater(self) -> None:
        return None

    def terminate(self) -> None:
        self.terminate_calls += 1


class _SignalStub:
    def connect(self, _slot=None) -> None:  # noqa: ANN001
        return None

    def disconnect(self, _slot=None) -> None:  # noqa: ANN001
        return None


class UpdateControllerTests(unittest.TestCase):
    def _plan(self, *items: UpdatePlanItem) -> UpdatePlan:
        return UpdatePlan(items=list(items))

    def test_start_update_uses_integrated_batch_client(self) -> None:
        started: list[UpdatePlan] = []

        class _IntegratedClientStub:
            def __init__(self, plan: UpdatePlan, *, parent=None) -> None:  # noqa: ANN001
                self.plan = plan
                self.parent = parent
                self.status_changed = _SignalStub()
                self.log_received = _SignalStub()
                self.progress_changed = _SignalStub()
                self.question_requested = _SignalStub()
                self.completed = _SignalStub()

            def start(self) -> None:
                started.append(self.plan)

        controller = UpdateController(_ServiceStub())  # type: ignore[arg-type]
        plan = self._plan(UpdatePlanItem(UpdateSource.SYSTEM, "linux"))

        with patch(
            "archupdater.presentation.update_controller.IntegratedBatchUpdateClient",
            _IntegratedClientStub,
        ):
            controller.start_update(plan)

        self.assertEqual(started, [plan])
        self.assertIsInstance(controller._update_client, _IntegratedClientStub)

    def test_shutdown_prevents_delayed_checks_and_updates_from_restarting(self) -> None:
        controller = UpdateController(_ServiceStub())  # type: ignore[arg-type]
        controller.shutdown()

        self.assertFalse(controller.start_check_updates())
        with self.assertRaisesRegex(RuntimeError, "shutting down"):
            controller.start_update(
                self._plan(UpdatePlanItem(UpdateSource.SYSTEM, "linux"))
            )
        self.assertIsNone(controller._worker_thread)
        self.assertIsNone(controller._update_client)

    def test_emits_plasma_restart_recommended_after_successful_widget_update(self) -> None:
        controller = UpdateController(_ServiceStub())  # type: ignore[arg-type]
        events: list[str] = []
        controller.plasma_restart_recommended.connect(lambda: events.append("restart"))

        controller._active_update_has_plasma_widgets = True
        controller._handle_update_completed(True, "ok", BatchOutcome.SUCCESS.value)

        self.assertEqual(events, ["restart"])

    def test_partial_success_has_an_explicit_final_state(self) -> None:
        controller = UpdateController(_ServiceStub())  # type: ignore[arg-type]
        snapshots: list[UpdateProgressSnapshot] = []
        controller.update_progress_changed.connect(snapshots.append)
        controller._initialize_progress(
            self._plan(
                UpdatePlanItem(UpdateSource.SYSTEM, "linux"),
                UpdatePlanItem(UpdateSource.AUR, "spotify"),
            )
        )
        controller._handle_runner_progress(
            {
                "type": "step_completed",
                "step": "system",
                "success": True,
                "incomplete": False,
            }
        )
        controller._handle_runner_progress(
            {
                "type": "step_completed",
                "step": "aur",
                "success": True,
                "incomplete": True,
            }
        )

        controller._handle_update_completed(
            True,
            "One AUR package was skipped.",
            BatchOutcome.PARTIAL_SUCCESS.value,
        )

        self.assertEqual(snapshots[-1].title, "Updates completed with skipped items")
        self.assertEqual(snapshots[-1].subtitle, "One AUR package was skipped.")
        self.assertTrue(snapshots[-1].success)
        self.assertEqual(snapshots[-1].summary_completed, ["Pacman"])
        self.assertEqual(snapshots[-1].summary_incomplete, ["AUR"])
        self.assertIn("can be retried later", snapshots[-1].summary_next_step or "")

    def test_no_changes_does_not_claim_that_updates_were_installed(self) -> None:
        controller = UpdateController(_ServiceStub())  # type: ignore[arg-type]
        snapshots: list[UpdateProgressSnapshot] = []
        controller.update_progress_changed.connect(snapshots.append)
        controller._initialize_progress(
            self._plan(UpdatePlanItem(UpdateSource.AUR, "spotify"))
        )
        controller._handle_runner_progress(
            {
                "type": "step_completed",
                "step": "aur",
                "success": True,
                "incomplete": True,
            }
        )

        controller._handle_update_completed(
            True,
            "No selected updates were installed.",
            BatchOutcome.NO_CHANGES.value,
        )

        self.assertEqual(snapshots[-1].title, "No updates installed")
        self.assertEqual(snapshots[-1].subtitle, "No selected updates were installed.")
        self.assertTrue(snapshots[-1].success)
        self.assertEqual(snapshots[-1].summary_completed, [])
        self.assertEqual(snapshots[-1].summary_incomplete, ["AUR"])
        self.assertEqual(
            snapshots[-1].summary_next_step,
            "Skipped AUR updates remain available and can be retried later.",
        )

    def test_cancelled_outcome_has_a_cancelled_final_state(self) -> None:
        controller = UpdateController(_ServiceStub())  # type: ignore[arg-type]
        snapshots: list[UpdateProgressSnapshot] = []
        controller.update_progress_changed.connect(snapshots.append)
        controller._initialize_progress(
            self._plan(UpdatePlanItem(UpdateSource.AUR, "spotify"))
        )
        controller._handle_update_status("running_aur")

        controller._handle_update_completed(
            False,
            "The update batch was interrupted.",
            BatchOutcome.CANCELLED.value,
        )

        snapshot = snapshots[-1]
        self.assertEqual(snapshot.title, "Update cancelled")
        self.assertEqual(snapshot.subtitle, "The update batch was interrupted.")
        self.assertFalse(snapshot.success)
        self.assertEqual(snapshot.summary_failed, [])
        self.assertEqual(snapshot.summary_not_executed, ["AUR"])

    def test_records_when_successful_system_step_changed_the_system(self) -> None:
        controller = UpdateController(_ServiceStub())  # type: ignore[arg-type]

        controller._handle_runner_progress(
            {
                "type": "step_completed",
                "step": "system",
                "success": True,
                "changed": True,
            }
        )

        self.assertTrue(controller.active_update_requires_restart_advisory())

    def test_records_partial_firmware_change_even_when_step_failed(self) -> None:
        controller = UpdateController(_ServiceStub())  # type: ignore[arg-type]

        controller._handle_runner_progress(
            {
                "type": "step_completed",
                "step": "firmware",
                "success": False,
                "changed": True,
                "incomplete": True,
            }
        )

        self.assertTrue(controller.active_update_requires_restart_advisory())

    def test_missing_changed_flag_does_not_assume_a_system_change(self) -> None:
        controller = UpdateController(_ServiceStub())  # type: ignore[arg-type]

        controller._handle_runner_progress(
            {
                "type": "step_completed",
                "step": "system",
                "success": True,
            }
        )

        self.assertFalse(controller.active_update_requires_restart_advisory())

    def test_buckets_update_logs_by_phase_and_exposes_widget_notice(self) -> None:
        controller = UpdateController(_ServiceStub())  # type: ignore[arg-type]
        snapshots: list[UpdateProgressSnapshot] = []
        controller.update_progress_changed.connect(snapshots.append)

        controller._initialize_progress(
            self._plan(
                UpdatePlanItem(UpdateSource.SYSTEM, "linux"),
                UpdatePlanItem(
                    UpdateSource.PLASMA_WIDGET,
                    "5555",
                    package_name="Example Widget",
                    package_kind="Plasma/Applet",
                    plugin_id="com.example.widget",
                ),
            )
        )

        controller._handle_update_status("starting_integrated")
        controller._handle_update_status("running_system")
        controller._handle_update_log("Privileged helper action: run_system_update")

        snapshot = snapshots[-1]
        steps = snapshot.steps

        self.assertEqual(snapshot.notice_title, "KDE Store Add-ons")
        self.assertIn("1 selected", snapshot.notice_text or "")
        self.assertEqual([step.label for step in steps], ["Pacman", "Add-ons"])
        self.assertEqual(steps[0].state.value, "running")
        self.assertEqual(
            steps[0].log_lines,
            ["Privileged helper action: run_system_update"],
        )

    def test_failure_snapshot_marks_not_executed_steps_and_builds_summary(self) -> None:
        controller = UpdateController(_ServiceStub())  # type: ignore[arg-type]
        snapshots: list[UpdateProgressSnapshot] = []
        controller.update_progress_changed.connect(snapshots.append)

        controller._initialize_progress(
            self._plan(
                UpdatePlanItem(UpdateSource.SYSTEM, "linux"),
                UpdatePlanItem(UpdateSource.AUR, "spotify"),
                UpdatePlanItem(UpdateSource.FIRMWARE, "device-id"),
            )
        )

        controller._handle_update_status("running_system")
        controller._handle_update_status("running_aur")
        controller._handle_update_completed(
            False,
            "AUR update failed. (exit code 1)",
            BatchOutcome.FAILED.value,
        )

        snapshot = snapshots[-1]
        steps = snapshot.steps

        self.assertEqual(snapshot.title, "Update completed with issues")
        self.assertEqual([step.state.value for step in steps], ["completed", "failed", "not_executed"])
        self.assertEqual(snapshot.summary_completed, ["Pacman"])
        self.assertEqual(snapshot.summary_failed, ["AUR"])
        self.assertEqual(snapshot.summary_not_executed, ["Device Firmware"])
        self.assertIn("remaining updates again", snapshot.summary_next_step or "")

    def test_cleanup_only_flatpak_plan_has_progress_step(self) -> None:
        controller = UpdateController(_ServiceStub())  # type: ignore[arg-type]
        snapshots: list[UpdateProgressSnapshot] = []
        controller.update_progress_changed.connect(snapshots.append)

        controller._initialize_progress(
            self._plan(
                UpdatePlanItem(
                    UpdateSource.FLATPAK,
                    "user",
                    action=UpdatePlanAction.CLEANUP,
                    installation_scope="user",
                )
            )
        )
        controller._handle_update_status("running_flatpak")

        self.assertEqual([step.label for step in snapshots[-1].steps], ["Flatpak"])
        self.assertEqual(snapshots[-1].steps[0].state.value, "running")

    def test_aur_skipped_progress_event_is_forwarded(self) -> None:
        controller = UpdateController(_ServiceStub())  # type: ignore[arg-type]
        events: list[object] = []
        controller.aur_update_skipped.connect(events.append)

        payload = {
            "type": "progress",
            "kind": "aur_pkgbuild_review_skipped",
            "target_id": "spotify",
        }
        controller._handle_runner_progress(payload)

        self.assertEqual(events, [payload])

    def test_pacman_progress_lines_update_console_row_and_unit_percent(self) -> None:
        controller = UpdateController(_ServiceStub())  # type: ignore[arg-type]
        snapshots: list[UpdateProgressSnapshot] = []
        controller.update_progress_changed.connect(snapshots.append)
        controller._initialize_progress(
            self._plan(
                UpdatePlanItem(UpdateSource.SYSTEM, "linux"),
                UpdatePlanItem(UpdateSource.SYSTEM, "mesa"),
            )
        )

        controller._handle_update_status("running_system")
        controller._handle_update_log(
            "linux-6.10.1-arch1-x86_64.pkg.tar.zst       10.0 MiB  10.0 MiB/s 00:09 [##------------------] 10%"
        )
        controller._handle_update_log(
            "linux-6.10.1-arch1-x86_64.pkg.tar.zst       50.0 MiB  10.0 MiB/s 00:05 [##########----------] 50%"
        )
        controller._handle_update_log(
            "(1/2) upgrading linux                                      [##########----------] 50%"
        )

        snapshot = snapshots[-1]
        self.assertEqual(snapshot.percent, 25)
        self.assertEqual(snapshot.activity_percent, 25)
        self.assertEqual(snapshot.activity_text, "Upgrading linux — 1 of 2")
        self.assertEqual(len(snapshot.console_lines), 2)
        self.assertIn("linux-6.10.1-arch1-x86_64.pkg.tar.zst", snapshot.console_lines[0])
        self.assertIn("50%", snapshot.console_lines[0])
        self.assertIn("(1/2) upgrading linux", snapshot.console_lines[1])

        controller._handle_update_status("running_aur")
        self.assertIsNone(snapshots[-1].activity_percent)
        self.assertIsNone(snapshots[-1].activity_text)

    def test_auth_cancelled_outcome_does_not_build_failure_snapshot(self) -> None:
        controller = UpdateController(_ServiceStub())  # type: ignore[arg-type]
        snapshots: list[UpdateProgressSnapshot] = []
        completed: list[tuple[bool, str, str]] = []
        controller.update_progress_changed.connect(snapshots.append)
        controller.update_completed.connect(
            lambda success, message, outcome: completed.append((success, message, outcome))
        )
        controller._initialize_progress(self._plan(UpdatePlanItem(UpdateSource.SYSTEM, "linux")))
        controller._handle_update_status("running_system")

        controller._handle_update_completed(
            False,
            "Authentication cancelled.",
            BatchOutcome.AUTH_CANCELLED.value,
        )

        self.assertEqual(
            completed,
            [(False, "Authentication cancelled.", BatchOutcome.AUTH_CANCELLED.value)],
        )
        self.assertEqual(snapshots[-1].success, None)
        self.assertEqual(snapshots[-1].summary_failed, [])

    def test_shutdown_terminates_active_update_client(self) -> None:
        controller = UpdateController(_ServiceStub())  # type: ignore[arg-type]
        events: list[bool] = []
        controller.busy_changed.connect(events.append)
        client = _UpdateClientStub()

        controller._update_client = client  # type: ignore[assignment]

        controller.shutdown()

        self.assertEqual(client.terminated, 1)
        self.assertIsNone(controller._update_client)
        self.assertIn(False, events)

    def test_shutdown_waits_for_active_worker_thread(self) -> None:
        controller = UpdateController(_ServiceStub())  # type: ignore[arg-type]
        events: list[bool] = []
        controller.busy_changed.connect(events.append)
        worker = _WorkerStub()
        thread = _ThreadStub()

        controller._worker = worker  # type: ignore[assignment]
        controller._worker_thread = thread  # type: ignore[assignment]

        controller.shutdown()

        self.assertEqual(thread.quit_calls, 1)
        self.assertEqual(thread.wait_calls, [UpdateController.WORKER_SHUTDOWN_TIMEOUT_MS])
        self.assertEqual(thread.terminate_calls, 0)
        self.assertIsNone(controller._worker)
        self.assertIsNone(controller._worker_thread)
        self.assertIn(False, events)

    def test_shutdown_does_not_force_terminate_worker_when_graceful_wait_times_out(self) -> None:
        controller = UpdateController(_ServiceStub())  # type: ignore[arg-type]
        worker = _WorkerStub()
        thread = _ThreadStub(wait_result=False)

        controller._worker = worker  # type: ignore[assignment]
        controller._worker_thread = thread  # type: ignore[assignment]

        controller.shutdown()

        self.assertEqual(thread.quit_calls, 1)
        self.assertEqual(thread.terminate_calls, 0)
        self.assertEqual(thread.wait_calls, [UpdateController.WORKER_SHUTDOWN_TIMEOUT_MS])
        self.assertIs(controller._worker, worker)
        self.assertIs(controller._worker_thread, thread)


if __name__ == "__main__":
    unittest.main()
