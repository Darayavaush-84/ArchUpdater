"""AUR state verification and propagation through the real batch backend."""
from __future__ import annotations

from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from archupdater.application.update_session.backend import CommandRunResult
from archupdater.application.update_session.step_backends import AurBackend
from archupdater.domain.aur import AurPkgbuildReview
from archupdater.domain.enums import UpdateSource
from archupdater.domain.update_plan import UpdatePlan, UpdatePlanItem
from archupdater.helper.actions import aur_updates, update_commands
import test_batch_update_runner as batch_tests


class AurTransactionResultTests(unittest.TestCase):
    def test_helper_reports_verified_state_for_success_noop_and_partial_failure(self):
        cases = [
            ({"foo": "1-1"}, {"foo": "2-1"}, 0, {"foo": "2-1"}, True, True),
            ({"foo": "2-1"}, {"foo": "2-1"}, 0, {"foo": "2-1"}, True, False),
            ({"foo": "1-1"}, {"foo": "1-1"}, 0, {"foo": "2-1"}, False, False),
            ({"foo": "1-1"}, {"foo": "2-1"}, 1, {"foo": "2-1"}, False, True),
            ({"foo": "1-1"}, {"foo": "1-1"}, 1, {"foo": "2-1"}, False, False),
            ({"foo": "1-1", "bar": "1-1"}, {"foo": "2-1", "bar": "1-1"},
             1, {"foo": "2-1", "bar": "2-1"}, False, True),
        ]
        for before, after, exit_code, expected, success, changed in cases:
            with self.subTest(before=before, after=after, exit_code=exit_code):
                events = []
                with (
                    patch.object(update_commands, "installed_package_versions", side_effect=[before, after]),
                    patch.object(update_commands, "stream_command", return_value=(exit_code, [])),
                    patch.object(update_commands, "_critical_command", side_effect=lambda cmd: cmd),
                ):
                    code = aur_updates._install_verified_artifacts(
                        [Path("/unused/verified.pkg.tar")], expected,
                        emit_event=lambda event, **p: events.append(p), emit_log=lambda line: None,
                    )
                self.assertEqual(code == 0, success)
                self.assertEqual(len(events), 1)
                self.assertIs(events[-1]["success"], success)
                self.assertIs(events[-1]["changed"], changed)
                self.assertEqual(events[-1]["actual_versions"], after)
                if success and not changed:
                    self.assertEqual(events[-1]["message"], "No selected updates were installed.")

    def test_unreadable_before_state_prevents_installation(self):
        events = []
        with (
            patch.object(update_commands, "installed_package_versions", return_value=None),
            patch.object(update_commands, "_run_helper_command") as install,
        ):
            code = aur_updates._install_verified_artifacts(
                [], {"foo": "2-1"}, emit_event=lambda event, **p: events.append(p),
                emit_log=lambda line: None,
            )
        install.assert_not_called()
        self.assertNotEqual(code, 0)
        self.assertIs(events[-1]["changed"], False)
        self.assertEqual(events[-1]["reason"], "preparation_failed")

    def test_unreadable_after_state_is_never_reported_as_success(self):
        events = []
        with (
            patch.object(update_commands, "installed_package_versions", side_effect=[{"foo": "1-1"}, None]),
            patch.object(update_commands, "stream_command", return_value=(0, [])),
            patch.object(update_commands, "_critical_command", side_effect=lambda cmd: cmd),
        ):
            code = aur_updates._install_verified_artifacts(
                [], {"foo": "2-1"}, emit_event=lambda event, **p: events.append(p),
                emit_log=lambda line: None,
            )
        self.assertNotEqual(code, 0)
        self.assertIs(events[-1]["success"], False)
        self.assertIsNone(events[-1]["changed"])
        self.assertEqual(events[-1]["actual_versions"], {})
        self.assertEqual(events[-1]["reason"], "postcondition_failed")

    def runner(self, responses):
        plan = UpdatePlan([UpdatePlanItem(
            UpdateSource.AUR, name, package_name=name, package_base=name, expected_version="2-1"
        ) for name in responses])
        runner = batch_tests.BatchRunnerTests()._runner(plan)
        runner._service = SimpleNamespace(
            aur_pkgbuild_review=lambda name, base: AurPkgbuildReview(name, base, "fixture"),
            aur_missing_build_dependencies=lambda review: [],
            discard_aur_pkgbuild_review=lambda review: None,
        )
        runner._command_available = lambda command: True
        runner._run_privileged = lambda request, **kwargs: responses[request.aur_review.package_name]
        runner._backends = [AurBackend()]
        runner._print_line = lambda line: None
        events = []
        runner._events = SimpleNamespace(emit=lambda event_type, **payload: events.append((event_type, payload)))
        return runner, events

    def test_batch_noop_has_no_changes_outcome(self):
        runner, events = self.runner({"foo": CommandRunResult(True, payload={"changed": False})})
        self.assertEqual(runner.run(), 0)
        self.assertEqual(events[-1][1]["outcome"], "no_changes")
        self.assertEqual(events[-1][1]["message"], "No selected updates were installed.")

    def test_noop_and_skipped_review_still_report_no_changes(self):
        runner, events = self.runner({
            "foo": CommandRunResult(True, payload={"changed": False}),
            "bar": CommandRunResult(True, payload={"changed": False}),
        })
        answers = iter([True, False])
        runner._interaction.request_question = lambda payload: next(answers)
        self.assertEqual(runner.run(), 0)
        self.assertEqual(events[-1][1]["outcome"], "no_changes")
        step = next(p for kind, p in events if kind == "step_completed")
        self.assertIs(step["changed"], False)
        self.assertIs(step["incomplete"], True)

    def test_batch_partial_install_failure_keeps_evidence_of_changes(self):
        runner, events = self.runner({"foo": CommandRunResult(False, "failed", {"changed": True})})
        self.assertEqual(runner.run(), 0)
        self.assertEqual(events[-1][1]["outcome"], "partial_success")
        step = next(p for kind, p in events if kind == "step_completed")
        self.assertIs(step["success"], False)
        self.assertIs(step["changed"], True)
        self.assertIs(step["incomplete"], True)

    def test_batch_unknown_result_fails_without_claiming_verified_changes(self):
        runner, events = self.runner({"foo": CommandRunResult(False, "unverified", {
            "changed": None, "reason": "postcondition_failed",
        })})
        self.assertNotEqual(runner.run(), 0)
        self.assertEqual(events[-1][1]["outcome"], "failed")
        step = next(p for kind, p in events if kind == "step_completed")
        self.assertIs(step["changed"], False)
        self.assertIs(step["incomplete"], True)

    def test_later_failure_does_not_erase_prior_changes(self):
        runner, events = self.runner({
            "foo": CommandRunResult(True, payload={"changed": True}),
            "bar": CommandRunResult(False, "build failed", {"changed": False}),
        })
        self.assertEqual(runner.run(), 0)
        self.assertEqual(events[-1][1]["outcome"], "partial_success")


if __name__ == "__main__":
    unittest.main()
