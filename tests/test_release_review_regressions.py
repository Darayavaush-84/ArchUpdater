"""Regression tests for critical process lifetime, event files and Pacman outcomes."""

from __future__ import annotations

import os
import signal
from pathlib import Path
import select
import subprocess
import sys
import tempfile
import time
import unittest
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from PySide6.QtCore import QProcess
from PySide6.QtWidgets import QApplication

from archupdater.application.update_session.backend import BackendRunContext, CommandRunResult
from archupdater.application.update_session.plan import BatchPlanInspector
from archupdater.application.update_session.step_backends import PacmanBackend
from archupdater.domain.enums import UpdateSource
from archupdater.domain.update_plan import UpdatePlan, UpdatePlanItem
from archupdater.helper.actions.common import stream_subprocess
from archupdater.helper.actions.system_updates import run_system_update
from archupdater.presentation.integrated_batch_client import IntegratedBatchUpdateClient


ROOT = Path(__file__).resolve().parents[1]

CHILD = """
from pathlib import Path
import signal, sys, time
marker = Path(sys.argv[1])
def terminated(*args):
    marker.write_text('terminated')
    raise SystemExit(12)
signal.signal(signal.SIGTERM, terminated)
print('ready', flush=True)
time.sleep(0.2)
marker.write_text('completed')
"""

HELPER = """
import signal, sys
from archupdater.helper.privileged_helper import _raise_termination
from archupdater.helper.actions.common import stream_subprocess
signal.signal(signal.SIGTERM, _raise_termination)
stream_subprocess(
    [sys.executable, '-c', sys.argv[1], sys.argv[2]],
    emit_log=lambda line: print(line, flush=True),
    start_new_session=True, survive_parent_exit=True, timeout_seconds=3,
)
"""


class ReleaseReviewRegressions(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        cls.app = QApplication.instance() or QApplication([])

    def child_state(self, marker):
        deadline = time.monotonic() + 2
        while time.monotonic() < deadline:
            if marker.exists() and (value := marker.read_text()):
                return value
            time.sleep(0.01)
        return "missing"

    def test_f1_critical_child_survives_helper_sigterm(self):
        with tempfile.TemporaryDirectory(prefix="archupdater-review-") as directory:
            marker = Path(directory) / "state"
            environment = dict(os.environ, PYTHONPATH=str(ROOT / "src"))
            with subprocess.Popen(
                [sys.executable, "-c", HELPER, CHILD, str(marker)],
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=environment,
            ) as process:
                try:
                    self.assertTrue(select.select([process.stdout], [], [], 5)[0])
                    self.assertEqual(process.stdout.readline().strip(), "ready")
                    process.terminate()
                    process.communicate(timeout=5)
                finally:
                    if process.poll() is None:
                        process.kill()
                        process.wait()
            self.assertEqual(self.child_state(marker), "completed")

    def test_f1_critical_child_survives_disconnected_log_consumer(self):
        with tempfile.TemporaryDirectory(prefix="archupdater-review-") as directory:
            marker = Path(directory) / "state"

            def disconnected_log(_line):
                raise BrokenPipeError("Batch/GUI pipe closed")

            try:
                stream_subprocess(
                    [sys.executable, "-c", CHILD, str(marker)],
                    emit_log=disconnected_log,
                    start_new_session=True, survive_parent_exit=True, timeout_seconds=3,
                )
            except BrokenPipeError:
                pass
            self.assertEqual(self.child_state(marker), "completed")

    def test_f2_truncated_utf8_still_reports_batch_failure(self):
        with tempfile.TemporaryDirectory(prefix="archupdater-review-") as directory:
            events = Path(directory) / "events.jsonl"
            events.write_bytes(b'{"type":"log","message":"\xc3')
            client = IntegratedBatchUpdateClient(UpdatePlan())
            client._events_path = events
            client._process_started = True
            completed = []
            client.completed.connect(lambda *values: completed.append(values))
            client._on_finished(1, QProcess.ExitStatus.NormalExit)
            self.assertEqual(len(completed), 1)
            self.assertFalse(completed[0][0])

    def test_f3_empty_pacman_transaction_is_not_reported_as_changed(self):
        plan = UpdatePlan(items=[
            UpdatePlanItem(UpdateSource.SYSTEM, "review-package", expected_version="2-1"),
        ])
        events = []

        def no_operation(_command, *, emit_log, **_kwargs):
            emit_log(":: Synchronizing package databases...")
            emit_log(":: Starting full system upgrade...")
            emit_log(" there is nothing to do")
            return 0, [" there is nothing to do"]

        def helper(request, **_kwargs):
            with (
                patch("archupdater.helper.actions.update_commands.stream_command", no_operation),
                patch("archupdater.helper.actions.system_updates._installed_package_versions",
                      return_value={"review-package": "2-1"}),
                patch("archupdater.helper.actions.update_commands._require_executable", return_value=True),
            ):
                code = run_system_update(
                    request.expected_versions,
                    emit_event=lambda event, **payload: events.append(payload),
                    emit_log=lambda _line: None,
                )
            self.assertEqual(code, 0)
            return CommandRunResult(events[-1]["success"], payload=events[-1])

        context = BackendRunContext(
            plan=plan,
            service=SimpleNamespace(),
            plan_inspector=BatchPlanInspector(plan, translate=lambda text: text),
            translate=lambda text: text,
            print_line=lambda _line: None,
            emit_log=lambda _line: None,
            emit_progress=lambda _event: None,
            request_question=lambda _question: False,
            run_command=lambda *_args, **_kwargs: CommandRunResult(
                True, payload={"output": "review-package 1-1 -> 2-1"},
            ),
            run_privileged=helper,
            summarize_items=lambda items: ", ".join(items),
            command_available=lambda _command: True,
        )
        result = PacmanBackend().run(context)
        self.assertTrue(result.success)
        self.assertFalse(result.changed)


class CriticalProcessRegressionTests(unittest.TestCase):
    def test_normal_command_is_still_terminated_on_broken_log_pipe(self):
        with tempfile.TemporaryDirectory() as directory:
            marker = Path(directory) / "state"
            with self.assertRaises(BrokenPipeError):
                stream_subprocess(
                    [sys.executable, "-c", CHILD, str(marker)],
                    emit_log=lambda _line: (_ for _ in ()).throw(BrokenPipeError()),
                    start_new_session=True, timeout_seconds=3,
                )
            self.assertEqual(marker.read_text(), "terminated")

    def test_critical_output_limit_suppresses_logs_without_stopping_child(self):
        with tempfile.TemporaryDirectory() as directory:
            marker = Path(directory) / "state"
            with patch("archupdater.helper.actions.common.MAX_STREAM_LOG_BYTES", 8):
                code, _ = stream_subprocess(
                    [sys.executable, "-c", "from pathlib import Path; import sys; "
                     "print('x'*100, flush=True); Path(sys.argv[1]).write_text('completed')", str(marker)],
                    emit_log=lambda _line: None, start_new_session=True,
                    survive_parent_exit=True, timeout_seconds=3,
                )
            self.assertEqual(code, 0)
            self.assertEqual(marker.read_text(), "completed")

    def test_critical_command_restores_signal_handlers(self):
        before = {sig: signal.getsignal(sig) for sig in (signal.SIGTERM, signal.SIGINT)}
        stream_subprocess(
            [sys.executable, "-c", "pass"], emit_log=lambda _line: None,
            survive_parent_exit=True, start_new_session=True, timeout_seconds=3,
        )
        self.assertEqual(before, {sig: signal.getsignal(sig) for sig in before})

    def test_disconnect_during_question_closes_input_without_confirming(self):
        child = (
            "from pathlib import Path; import sys; "
            "print('prompt?', flush=True); answer=sys.stdin.readline(); "
            "Path(sys.argv[1]).write_text('approved' if answer.strip() == 'y' else 'declined')"
        )
        helper = """
import signal, sys
from archupdater.helper.privileged_helper import _raise_termination
from archupdater.helper.actions.common import stream_subprocess
signal.signal(signal.SIGTERM, _raise_termination)
def answer(line):
    if line.strip() == 'prompt?':
        print('waiting', flush=True)
        return sys.stdin.readline()
stream_subprocess([sys.executable, '-c', sys.argv[1], sys.argv[2]],
    emit_log=lambda line: None, input_handler=answer,
    survive_parent_exit=True, start_new_session=True, timeout_seconds=3)
"""
        with tempfile.TemporaryDirectory() as directory:
            marker = Path(directory) / "state"
            with subprocess.Popen(
                [sys.executable, "-c", helper, child, str(marker)],
                env=dict(os.environ, PYTHONPATH=str(ROOT / "src")),
                stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
            ) as process:
                try:
                    self.assertTrue(select.select([process.stdout], [], [], 5)[0])
                    self.assertEqual(process.stdout.readline().strip(), "waiting")
                    process.terminate()
                    # Keep stdin open: the signal must interrupt the pending read.
                    self.assertEqual(process.wait(timeout=5), 143)
                finally:
                    if process.poll() is None:
                        process.kill()
                        process.wait()
            self.assertEqual(marker.read_text(), "declined")

    def test_log_pipe_loss_before_answer_does_not_send_yes(self):
        child = (
            "from pathlib import Path; import sys; "
            "print('prompt?', flush=True); answer=sys.stdin.readline(); "
            "Path(sys.argv[1]).write_text('approved' if answer.strip() == 'y' else 'declined')"
        )
        with tempfile.TemporaryDirectory() as directory:
            marker = Path(directory) / "state"
            with self.assertRaises(BrokenPipeError):
                stream_subprocess(
                    [sys.executable, "-c", child, str(marker)],
                    emit_log=lambda _line: (_ for _ in ()).throw(BrokenPipeError()),
                    input_handler=lambda line: "y\n" if line.strip() == "prompt?" else None,
                    survive_parent_exit=True, start_new_session=True, timeout_seconds=3,
                )
            self.assertEqual(marker.read_text(), "declined")

    def test_parent_death_preserves_workspace_until_child_finishes(self):
        child = CHILD.replace(
            "marker.write_text('completed')",
            "marker.write_text('completed:' + Path(sys.argv[2]).read_text())",
        )
        helper = """
from pathlib import Path
import signal, sys, tempfile
from archupdater.process_lifecycle import arm_parent_death_signal
from archupdater.helper.privileged_helper import _raise_termination
from archupdater.helper.actions.common import stream_subprocess
signal.signal(signal.SIGTERM, _raise_termination)
arm_parent_death_signal()
with tempfile.TemporaryDirectory(dir=sys.argv[2]) as workspace:
    source=Path(workspace)/'package'
    source.write_text('verified')
    Path(sys.argv[2], 'workspace').write_text(workspace)
    stream_subprocess([sys.executable, '-c', sys.argv[1], sys.argv[3], str(source)],
        emit_log=lambda line: print(line, flush=True),
        survive_parent_exit=True, start_new_session=True, timeout_seconds=3)
"""
        parent = (
            "import subprocess,sys,time; "
            "subprocess.Popen([sys.executable,'-c',sys.argv[1],*sys.argv[2:]]); time.sleep(10)"
        )
        with tempfile.TemporaryDirectory() as directory:
            marker = Path(directory) / "state"
            with subprocess.Popen(
                [sys.executable, "-c", parent, helper, child, directory, str(marker)],
                env=dict(os.environ, PYTHONPATH=str(ROOT / "src")),
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
            ) as process:
                try:
                    self.assertTrue(select.select([process.stdout], [], [], 5)[0])
                    self.assertEqual(process.stdout.readline().strip(), "ready")
                    process.terminate()
                    process.communicate(timeout=5)
                finally:
                    if process.poll() is None:
                        process.kill()
                        process.wait()
            self.assertEqual(marker.read_text(), "completed:verified")
            self.assertFalse(Path((Path(directory) / "workspace").read_text()).exists())


class EventFileRegressionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.events = Path(directory.name) / "events.jsonl"
        self.events.write_bytes(b"")
        self.client = IntegratedBatchUpdateClient(UpdatePlan())
        self.client._events_path = self.events
        self.client._process_started = True
        self.completed = []
        self.logs = []
        self.client.completed.connect(lambda *args: self.completed.append(args))
        self.client.log_received.connect(self.logs.append)

    def append(self, data):
        with self.events.open("ab") as stream:
            stream.write(data)
        self.client._poll_events()

    def finish(self, code=0):
        self.client._on_finished(code, QProcess.ExitStatus.NormalExit)

    def test_utf8_and_json_split_at_every_byte_are_reassembled(self):
        import json
        line = (json.dumps({"type": "log", "message": "Aggiornamento è 更新"}, ensure_ascii=False) + "\n").encode()
        for value in line:
            self.append(bytes([value]))
        self.assertEqual(self.logs, ["Aggiornamento è 更新"])
        self.assertEqual(self.completed, [])
        self.append(b'{"type":"batch_completed","success":true,"outcome":"success","message":"done"}\n')
        self.assertEqual(self.completed, [])
        self.finish()
        self.assertEqual(self.completed, [(True, "done", "success")])

    def test_incomplete_ascii_record_reports_failure_once(self):
        self.append(b'{"type":"batch_completed","success":true')
        self.finish(1)
        self.finish(1)
        self.assertEqual(len(self.completed), 1)
        self.assertFalse(self.completed[0][0])

    def test_malformed_utf8_complete_record_reports_failure(self):
        self.append(b'{"type":"log","message":"\xff"}\n')
        self.finish(1)
        self.assertEqual(len(self.completed), 1)
        self.assertFalse(self.completed[0][0])

    def test_read_error_does_not_prevent_completion_or_cleanup(self):
        with patch.object(Path, "open", side_effect=OSError("simulated I/O failure")):
            self.client._poll_events()
        self.finish(1)
        self.assertEqual(len(self.completed), 1)
        self.assertFalse(self.completed[0][0])
        self.assertIsNone(self.client._events_path)

    def test_trailing_partial_record_invalidates_pending_success(self):
        self.append(b'{"type":"batch_completed","success":true,"outcome":"success"}\n{')
        self.finish()
        self.assertEqual(len(self.completed), 1)
        self.assertFalse(self.completed[0][0])

    def test_limit_is_per_record_and_not_per_chunk(self):
        self.client.MAX_EVENT_LINE_BYTES = 40
        self.append(b'{"type":"log","message":"ok"}\n' * 10)
        self.assertEqual(self.logs, ["ok"] * 10)
        self.assertIsNone(self.client._event_error)

    def test_oversized_unterminated_record_reports_failure(self):
        self.client.MAX_EVENT_LINE_BYTES = 40
        self.append(b'x' * 41)
        self.finish(1)
        self.assertEqual(len(self.completed), 1)
        self.assertFalse(self.completed[0][0])

    def test_real_qprocess_with_truncated_event_completes_once(self):
        self.client._process.setProgram(sys.executable)
        self.client._process.setArguments([
            "-c", "from pathlib import Path; import sys; "
            "Path(sys.argv[1]).write_bytes(bytes([123,34,109,34,58,34,195])); sys.exit(1)",
            str(self.events),
        ])
        self.client._process.start()
        self.assertTrue(self.client._process.waitForFinished(5000))
        self.assertEqual(self.events.read_bytes(), bytes([123,34,109,34,58,34,195]))
        self.assertEqual(len(self.completed), 1)
        self.assertFalse(self.completed[0][0])
        self.assertIsNone(self.client._events_path)


class PacmanOutcomeRegressionTests(unittest.TestCase):
    def run_fake_pacman(self, mode):
        # Exercise the real process runner and both local-state queries. This
        # executable only changes a version file inside its temporary directory.
        with tempfile.TemporaryDirectory() as directory:
            state = Path(directory) / "version"
            state.write_text("2-1" if mode == "noop" else "1-1")
            executable = Path(directory) / "pacman"
            script = f"#!{sys.executable}\n" + f"STATE={str(state)!r}\nMODE={mode!r}\n" + """
from pathlib import Path
import sys
state = Path(STATE)
if '-Q' in sys.argv:
    if MODE == 'verification_error' and state.read_text() == '2-1':
        sys.exit(1)
    print('review-package ' + state.read_text())
    sys.exit(0)
if MODE == 'preparation_error':
    sys.exit(1)
if state.read_text() == '2-1':
    print(' there is nothing to do')
    sys.exit(0)
print('Packages (1) review-package-2-1', flush=True)
print('Total Installed Size: 1 MiB', flush=True)
print(':: Proceed with installation? [Y/n] ', end='', flush=True)
if sys.stdin.readline().strip() != 'y':
    sys.exit(1)
state.write_text('2-1')
print('upgraded review-package')
sys.exit(1 if MODE == 'hook_error' else 0)
"""
            executable.write_text(script)
            executable.chmod(0o700)
            events = []
            with (
                patch("archupdater.helper.actions.update_commands.PACMAN_PATH", executable),
                patch("archupdater.helper.actions.update_commands.SYSTEMD_INHIBIT_PATH", Path('/missing')),
            ):
                code = run_system_update(
                    {"review-package": "2-1"},
                    emit_event=lambda event, **payload: events.append(payload),
                    emit_log=lambda _line: None,
                )
            return code, events[-1]

    def test_real_noop_reports_no_change(self):
        code, result = self.run_fake_pacman("noop")
        self.assertEqual(code, 0)
        self.assertTrue(result["success"])
        self.assertIs(result["changed"], False)

    def test_real_install_reports_changed(self):
        code, result = self.run_fake_pacman("install")
        self.assertEqual(code, 0)
        self.assertIs(result["changed"], True)

    def test_hook_failure_keeps_evidence_of_changed_packages(self):
        code, result = self.run_fake_pacman("hook_error")
        self.assertNotEqual(code, 0)
        self.assertFalse(result["success"])
        self.assertIs(result["changed"], True)

    def test_failure_before_install_does_not_report_changed(self):
        code, result = self.run_fake_pacman("preparation_error")
        self.assertNotEqual(code, 0)
        self.assertIs(result["changed"], False)

    def test_failed_postcondition_is_not_success(self):
        code, result = self.run_fake_pacman("verification_error")
        self.assertNotEqual(code, 0)
        self.assertFalse(result["success"])
        self.assertIsNone(result["changed"])
        self.assertEqual(result["reason"], "postcondition_failed")

    def test_initial_query_failure_prevents_transaction(self):
        with (
            patch("archupdater.helper.actions.system_updates._installed_package_versions", return_value=None),
            patch("archupdater.helper.actions.update_commands._require_executable", return_value=True),
            patch("archupdater.helper.actions.update_commands.stream_command") as command,
        ):
            events = []
            code = run_system_update(
                {"review-package": "2-1"}, emit_event=lambda _event, **payload: events.append(payload),
                emit_log=lambda _line: None,
            )
        self.assertNotEqual(code, 0)
        command.assert_not_called()
        self.assertIs(events[-1]["changed"], False)


if __name__ == "__main__":
    unittest.main()
