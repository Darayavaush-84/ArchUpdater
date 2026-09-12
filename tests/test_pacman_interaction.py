from __future__ import annotations

import io
import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from PySide6.QtWidgets import QMessageBox

from archupdater.application.update_session.errors import BatchCancelled
from archupdater.batch.privileged_helper import BatchPrivilegedHelperInvoker
from archupdater.helper.actions.common import stream_subprocess
from archupdater.helper.actions.pacman_prompts import PacmanPromptHandler
from archupdater.presentation.update_interaction_dialogs import handle_question_request


CONFLICT = (
    ":: qemu-common-11.1.0-1 and qemu-block-gluster-11.0.3-1 are in conflict. "
    "Remove qemu-block-gluster? [y/N] "
)


class PacmanInteractionTests(unittest.TestCase):
    def test_conflicts_and_replacements_require_explicit_boolean_approval(self) -> None:
        for prompt in (CONFLICT, ":: Replace old-lib with extra/new-lib? [Y/n] "):
            for answer in (True, False, None, "yes", 1):
                with self.subTest(prompt=prompt, answer=answer):
                    events = []
                    handler = PacmanPromptHandler(
                        emit_event=lambda kind, **payload: events.append(payload),
                        emit_log=lambda text: None,
                        read_line=lambda limit: json.dumps({
                            "question_id": events[-1]["question_id"], "response": answer,
                        }) + "\n",
                    )
                    reply = handler(prompt)
                    self.assertEqual(reply, "y\n" if answer is True else "n\n")
                    self.assertEqual(len(events), 1)
                    self.assertEqual(events[0]["question_type"], "pacman_confirmation")
                    self.assertIn(prompt.split("?")[0].removeprefix(":: "), events[0]["message"])

    def test_automatic_confirmations_and_provider_defaults_do_not_open_dialogs(self) -> None:
        events = []
        handler = PacmanPromptHandler(
            emit_event=lambda kind, **payload: events.append(payload),
            emit_log=lambda text: None,
            read_line=lambda limit: self.fail("Automatic prompt waited for user input"),
        )
        for prompt, expected in (
            (":: Proceed with installation? [Y/n] ", "y\n"),
            (":: Proceed with download? [Y/n] ", "y\n"),
            ("Enter a number (default=1): ", "\n"),
            ("Enter a selection (default=all): ", "\n"),
            ("resolving dependencies...", None),
            (":: Remove qemu-block-gluster? [y/", None),
        ):
            self.assertEqual(handler(prompt), expected)
        self.assertEqual(events, [])

    def test_missing_invalid_or_mismatched_response_never_approves(self) -> None:
        for raw in ("", "not json\n", "[]\n", "x" * 4097,
                    '{"question_id":"wrong","response":true}\n'):
            with self.subTest(raw=raw[:40]):
                handler = PacmanPromptHandler(
                    emit_event=lambda *args, **kwargs: None,
                    emit_log=lambda text: None,
                    read_line=lambda limit: raw,
                )
                self.assertEqual(handler(CONFLICT), "n\n")

    def test_real_child_waits_for_split_prompt_and_receives_yes_or_no(self) -> None:
        script = (
            "import sys, time\n"
            f"prompt = {CONFLICT!r}\n"
            "for fragment in (prompt[:-4], prompt[-4:]):\n"
            "    sys.stdout.write(fragment); sys.stdout.flush(); time.sleep(0.05)\n"
            "answer = sys.stdin.readline().strip()\n"
            "print('conflict-answer=' + answer, flush=True)\n"
            "if answer != 'y': sys.exit(1)\n"
            "sys.stdout.write(':: Proceed with installation? [Y/n] '); sys.stdout.flush()\n"
            "answer = sys.stdin.readline().strip()\n"
            "print('install-answer=' + answer, flush=True)\n"
            "sys.exit(0 if answer == 'y' else 2)\n"
        )
        for accepted in (True, False):
            with self.subTest(accepted=accepted):
                events = []
                logs = []
                handler = PacmanPromptHandler(
                    emit_event=lambda kind, **payload: events.append(payload),
                    emit_log=logs.append,
                    read_line=lambda limit: json.dumps({
                        "question_id": events[-1]["question_id"], "response": accepted,
                    }) + "\n",
                )
                code, output = stream_subprocess(
                    [sys.executable, "-u", "-c", script],
                    emit_log=logs.append,
                    input_handler=handler,
                    start_new_session=True,
                    timeout_seconds=3,
                )
                self.assertEqual(code, 0 if accepted else 1)
                self.assertEqual(len(events), 1)
                self.assertIn("conflict-answer=" + ("y" if accepted else "n"), output)
                self.assertEqual("install-answer=y" in output, accepted)

    def test_batch_relays_question_to_yes_no_dialog_and_writes_boolean_response(self) -> None:
        for button in (QMessageBox.StandardButton.Yes, QMessageBox.StandardButton.No,
                       QMessageBox.StandardButton.Cancel):
            with self.subTest(button=button):
                payload = {
                    "event": "question", "question_id": "pacman-1",
                    "question_type": "pacman_confirmation", "message": CONFLICT,
                }
                process = type("Process", (), {
                    "stdin": io.StringIO(),
                    "stdout": io.StringIO(json.dumps(payload) + "\n"
                                         + '{"event":"completed","success":true}\n'),
                })()

                def ask(question):
                    responses = []
                    handle_question_request(
                        parent=object(), payload=question,
                        submit_response=lambda question_id, answer: responses.append(answer),
                        cancel_question=lambda question_id: responses.append(None),
                    )
                    return responses[0]

                invoker = BatchPrivilegedHelperInvoker(
                    translate=lambda text: text, print_line=lambda text: None,
                    emit_log=lambda text: None, request_question=ask,
                )
                with patch(
                    "archupdater.presentation.update_interaction_dialogs.QMessageBox.question",
                    return_value=button,
                ) as dialog:
                    result = invoker._read_command_result(process, failure_message="failed")
                self.assertTrue(result.success)
                self.assertEqual(json.loads(process.stdin.getvalue()), {
                    "question_id": "pacman-1", "response": button == QMessageBox.StandardButton.Yes,
                })
                self.assertEqual(dialog.call_args.args[3],
                                 QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
                self.assertEqual(dialog.call_args.args[4], QMessageBox.StandardButton.No)
                self.assertIn("qemu-block-gluster", dialog.call_args.args[2])

    def test_batch_cancellation_sends_no_before_unwinding(self) -> None:
        process = type("Process", (), {
            "stdin": io.StringIO(),
            "stdout": io.StringIO(json.dumps({
                "event": "question", "question_id": "pacman-1",
                "question_type": "pacman_confirmation", "message": CONFLICT,
            }) + "\n"),
        })()

        def cancel(question):
            raise BatchCancelled()

        invoker = BatchPrivilegedHelperInvoker(
            translate=lambda text: text, print_line=lambda text: None,
            emit_log=lambda text: None, request_question=cancel,
        )
        with self.assertRaises(BatchCancelled):
            invoker._read_command_result(process, failure_message="failed")
        self.assertEqual(json.loads(process.stdin.getvalue()), {
            "question_id": "pacman-1", "response": False,
        })


if __name__ == "__main__":
    unittest.main()
