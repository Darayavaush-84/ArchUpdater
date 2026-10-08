from __future__ import annotations

import sys
import unittest
from dataclasses import replace
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from archupdater.domain.enums import UpdateProgressPhase, UpdateProgressStepState, UpdateResult
from archupdater.domain.progress import UpdateProgressSnapshot, UpdateProgressStep


class UpdateResultTests(unittest.TestCase):
    def test_only_a_fully_successful_final_result_is_success(self) -> None:
        complete = UpdateProgressSnapshot(
            "Done", "", [], 100, final_state=True, success=True,
        )
        self.assertEqual(complete.result, UpdateResult.SUCCESS)
        for changes, expected in (
            ({"final_state": False}, UpdateResult.IN_PROGRESS),
            ({"success": False}, UpdateResult.FAILED),
            ({"success": False, "summary_completed": ["System"]}, UpdateResult.PARTIAL_SUCCESS),
            ({"summary_failed": ["AUR"]}, UpdateResult.PARTIAL_SUCCESS),
            ({"summary_incomplete": ["AUR"]}, UpdateResult.PARTIAL_SUCCESS),
            ({"summary_not_executed": ["AUR"]}, UpdateResult.PARTIAL_SUCCESS),
            ({"cancelled": True, "summary_completed": ["System"]}, UpdateResult.CANCELLED),
        ):
            with self.subTest(changes=changes):
                self.assertEqual(replace(complete, **changes).result, expected)

    def test_step_states_prevent_false_success_even_without_summary_lists(self) -> None:
        for state in UpdateProgressStepState:
            with self.subTest(state=state):
                snapshot = UpdateProgressSnapshot(
                    "Done", "", [UpdateProgressStep(UpdateProgressPhase.AUR, "AUR", state)],
                    100, final_state=True, success=True,
                )
                expected = (
                    UpdateResult.SUCCESS if state is UpdateProgressStepState.COMPLETED
                    else UpdateResult.PARTIAL_SUCCESS
                )
                self.assertEqual(snapshot.result, expected)


if __name__ == "__main__":
    unittest.main()
