from __future__ import annotations

import json
import sys
import types
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from PySide6.QtCore import QProcess
from PySide6.QtWidgets import QApplication

from archupdater.domain.update_plan import UpdatePlan
from archupdater.application.update_session.protocol import BatchEventType, BatchOutcome
from archupdater.presentation.integrated_batch_client import IntegratedBatchUpdateClient


class IntegratedBatchUpdateClientTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._app = QApplication.instance() or QApplication([])

    def test_batch_completed_requires_structured_outcome(self) -> None:
        client = IntegratedBatchUpdateClient(UpdatePlan())
        completed: list[tuple[bool, str, str]] = []
        client.completed.connect(
            lambda success, message, outcome: completed.append((success, message, outcome))
        )

        client._handle_event_line(
            json.dumps(
                {
                    "type": BatchEventType.BATCH_COMPLETED.value,
                    "success": True,
                    "message": "done",
                    "outcome": BatchOutcome.SUCCESS.value,
                }
            )
        )

        self.assertEqual(completed, [(True, "done", BatchOutcome.SUCCESS.value)])

    def test_batch_completed_waits_for_process_exit_before_notifying_controller(self) -> None:
        client = IntegratedBatchUpdateClient(UpdatePlan())
        completed: list[tuple[bool, str, str]] = []
        client.completed.connect(
            lambda success, message, outcome: completed.append((success, message, outcome))
        )
        client._process = types.SimpleNamespace(  # type: ignore[assignment]
            state=lambda: QProcess.ProcessState.Running
        )

        client._handle_event_line(
            json.dumps(
                {
                    "type": BatchEventType.BATCH_COMPLETED.value,
                    "success": True,
                    "message": "done",
                    "outcome": BatchOutcome.SUCCESS.value,
                }
            )
        )

        self.assertEqual(completed, [])
        self.assertEqual(
            client._pending_completion,
            (True, "done", BatchOutcome.SUCCESS.value),
        )

    def test_batch_completed_without_valid_outcome_is_protocol_failure(self) -> None:
        client = IntegratedBatchUpdateClient(UpdatePlan())
        completed: list[tuple[bool, str, str]] = []
        client.completed.connect(
            lambda success, message, outcome: completed.append((success, message, outcome))
        )

        client._handle_event_line(
            json.dumps(
                {
                    "type": BatchEventType.BATCH_COMPLETED.value,
                    "success": True,
                    "message": "done",
                }
            )
        )

        self.assertEqual(len(completed), 1)
        self.assertEqual(completed[0][0], False)
        self.assertEqual(completed[0][2], BatchOutcome.FAILED.value)
        self.assertIn("invalid completion result", completed[0][1])

    def test_batch_completed_rejects_success_flag_that_contradicts_outcome(self) -> None:
        cases = (
            (False, BatchOutcome.SUCCESS.value),
            (False, BatchOutcome.PARTIAL_SUCCESS.value),
            (False, BatchOutcome.NO_CHANGES.value),
            (True, BatchOutcome.FAILED.value),
            (True, BatchOutcome.CANCELLED.value),
            (True, BatchOutcome.AUTH_CANCELLED.value),
        )

        for success, outcome in cases:
            with self.subTest(success=success, outcome=outcome):
                client = IntegratedBatchUpdateClient(UpdatePlan())
                completed: list[tuple[bool, str, str]] = []
                client.completed.connect(
                    lambda value, message, result: completed.append(
                        (value, message, result)
                    )
                )

                client._handle_event_line(
                    json.dumps(
                        {
                            "type": BatchEventType.BATCH_COMPLETED.value,
                            "success": success,
                            "message": "done",
                            "outcome": outcome,
                        }
                    )
                )

                self.assertEqual(len(completed), 1)
                self.assertFalse(completed[0][0])
                self.assertEqual(completed[0][2], BatchOutcome.FAILED.value)
                self.assertIn("invalid completion result", completed[0][1])

    def test_batch_completed_rejects_non_boolean_success_flag(self) -> None:
        client = IntegratedBatchUpdateClient(UpdatePlan())
        completed: list[tuple[bool, str, str]] = []
        client.completed.connect(
            lambda success, message, outcome: completed.append((success, message, outcome))
        )

        client._handle_event_line(
            json.dumps(
                {
                    "type": BatchEventType.BATCH_COMPLETED.value,
                    "success": "false",
                    "message": "invalid",
                    "outcome": BatchOutcome.SUCCESS.value,
                }
            )
        )

        self.assertEqual(len(completed), 1)
        self.assertFalse(completed[0][0])
        self.assertEqual(completed[0][2], BatchOutcome.FAILED.value)

    def test_non_object_event_is_ignored(self) -> None:
        client = IntegratedBatchUpdateClient(UpdatePlan())
        completed: list[tuple[bool, str, str]] = []
        client.completed.connect(
            lambda success, message, outcome: completed.append((success, message, outcome))
        )

        client._handle_event_line("[]")

        self.assertEqual(completed, [])

    def test_log_events_are_emitted_to_live_log(self) -> None:
        client = IntegratedBatchUpdateClient(UpdatePlan())
        logs: list[str] = []
        client.log_received.connect(logs.append)

        client._handle_event_line(
            json.dumps(
                {
                    "type": BatchEventType.LOG.value,
                    "message": "Retrieving packages...",
                }
            )
        )

        self.assertEqual(logs, ["Retrieving packages..."])

    def test_stdout_and_event_logs_are_deduplicated(self) -> None:
        client = IntegratedBatchUpdateClient(UpdatePlan())
        logs: list[str] = []
        client.log_received.connect(logs.append)

        client._emit_stdout_log("linux 10%")  # type: ignore[attr-defined]
        client._handle_event_line(
            json.dumps(
                {
                    "type": BatchEventType.LOG.value,
                    "message": "linux 10%",
                }
            )
        )

        self.assertEqual(logs, ["linux 10%"])


if __name__ == "__main__":
    unittest.main()
