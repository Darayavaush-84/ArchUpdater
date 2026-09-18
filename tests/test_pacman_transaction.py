from __future__ import annotations

import io
import json
import sys
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))

from PySide6.QtWidgets import QApplication, QMessageBox

from archupdater.batch.privileged_helper import BatchPrivilegedHelperInvoker
from archupdater.helper.actions.common import stream_subprocess
from archupdater.helper.actions.pacman_prompts import PacmanPromptHandler
from archupdater.helper.actions.pacman_transaction import PacmanTransactionPreview
from archupdater.helper.actions.system_updates import run_system_update
from archupdater.presentation.update_interaction_dialogs import handle_question_request


class PacmanTransactionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def preview(self, lines):
        preview = PacmanTransactionPreview()
        for line in lines:
            preview.observe(line)
        return preview

    def test_wrapped_summary_includes_hyphenated_names_and_epoch_versions(self) -> None:
        preview = self.preview([
            '\x1b[1mPackages (2)\x1b[0m lib-foo-1:2.3-4',
            '             another-1.0.r2-1',
            'Total Installed Size: 100 MiB',
            'unrelated-output-after-summary',
        ])
        self.assertEqual(preview.versions(), {'lib-foo': '1:2.3-4', 'another': '1.0.r2-1'})

    def test_verbose_columns_preserve_empty_old_and_new_versions(self) -> None:
        header = f'{"Package (2)":24}{"Old Version":18}{"New Version":18}Net Change   Download Size'
        preview = self.preview([
            header,
            f'{"core/lib-foo":24}{"1-1":18}{"2-1":18}0.00 MiB',
            f'{"extra/another":24}{"":18}{"3-1":18}0.10 MiB',
            'Total Installed Size: 2 MiB',
        ])
        self.assertEqual(preview.versions(), {'lib-foo': '2-1', 'another': '3-1'})
        removal = self.preview([header, f'{"core/lib-foo":24}{"1-1":18}{"":18}-1.00 MiB'])
        self.assertIsNone(removal.versions())

    def test_missing_duplicate_removed_or_truncated_entries_never_match(self) -> None:
        cases = [
            [], ['Packages (2) foo-2-1'], ['Packages (2) foo-2-1 foo-2-1'],
            ['Packages (2) foo-2-1 old-1-1 [removal]'],
            ['Packages (1) foo-2-1', 'unexpected text'],
            ['Package (1) unrecognized table', 'foo 2-1'],
        ]
        for lines in cases:
            with self.subTest(lines=lines):
                self.assertIsNone(self.preview(lines).versions())
        preview = self.preview(['Packages (1) foo-2-1', 'x' * (PacmanTransactionPreview.MAX_CHARACTERS + 1)])
        self.assertTrue(preview.truncated)
        self.assertIsNone(preview.versions())

    def test_final_summary_replaces_any_earlier_preview(self) -> None:
        preview = self.preview(['Packages (1) foo-2-1', 'Total Installed Size: 1 MiB',
                                'Packages (1) foo-3-1', 'Total Installed Size: 1 MiB'])
        self.assertEqual(preview.versions(), {'foo': '3-1'})

    def test_helper_checks_final_transaction_and_relays_explicit_answer(self) -> None:
        for actual, approval in [('2-1', False), ('3-1', False), ('3-1', True)]:
            with self.subTest(actual=actual, approval=approval):
                events, commands, installed = [], [], []

                def process(command, *, emit_log, input_handler, **kwargs):
                    commands.append(command)
                    emit_log(f'Packages (1) audit-package-{actual}')
                    emit_log('Total Installed Size: 1 MiB')
                    answer = input_handler(':: Proceed with installation? [Y/n] ')
                    if answer == 'y\n':
                        installed.append(actual)
                    return (0 if installed else 1), []

                def read_response(limit):
                    return json.dumps({'question_id': events[-1]['question_id'], 'response': approval}) + '\n'

                with patch('archupdater.helper.actions.system_updates._installed_package_versions',
                           side_effect=lambda: {'audit-package': installed[-1] if installed else '1-1'}), \
                     patch('archupdater.helper.actions.update_commands.stream_command', process), \
                     patch('archupdater.helper.actions.update_commands._require_executable', return_value=True), \
                     patch('sys.stdin.readline', side_effect=read_response):
                    code = run_system_update({'audit-package': '2-1'},
                        emit_log=lambda line: None,
                        emit_event=lambda event, **payload: events.append({'kind': event.value, **payload}))
                self.assertEqual(len(commands), 1)
                self.assertIn('-Syu', commands[0])
                self.assertEqual(installed, [actual] if actual == '2-1' or approval else [])
                self.assertEqual(code == 0, bool(installed))
                if not installed:
                    self.assertEqual(events[-1]['reason'], 'plan_changed')
                questions = [event for event in events if event['kind'] == 'question']
                self.assertEqual(len(questions), int(actual != '2-1'))
                if questions:
                    self.assertIn('audit-package-3-1', questions[0]['details'])

    def test_real_child_output_and_split_prompt_are_verified_before_yes(self) -> None:
        for actual in ('2-1', '3-1'):
            events = []
            handler = PacmanPromptHandler(
                expected_versions={'audit-package': '2-1'},
                emit_event=lambda event, **payload: events.append(payload), emit_log=lambda line: None,
                read_line=lambda limit: json.dumps({'question_id': events[-1]['question_id'], 'response': False}) + '\n',
            )
            script = (
                'import sys, time\n'
                f'print("Packages (1) audit-package-{actual}", flush=True)\n'
                'print("Total Installed Size: 1 MiB", flush=True)\n'
                'for part in (":: Proceed with installation? [Y/", "n] "):\n'
                '    sys.stdout.write(part); sys.stdout.flush(); time.sleep(0.03)\n'
                'answer = sys.stdin.readline().strip()\n'
                'print("answer=" + answer, flush=True)\n'
                'sys.exit(0 if answer == "y" else 1)\n'
            )
            code, output = stream_subprocess([sys.executable, '-u', '-c', script],
                emit_log=handler.observe_output, input_handler=handler, start_new_session=True, timeout_seconds=3)
            self.assertEqual(code, 0 if actual == '2-1' else 1)
            self.assertIn('answer=' + ('y' if actual == '2-1' else 'n'), output)
            self.assertEqual(len(events), int(actual != '2-1'))

    def test_missing_summary_declines_without_automatic_confirmation(self) -> None:
        handler = PacmanPromptHandler(expected_versions={'foo': '2-1'},
            emit_event=Mock(), emit_log=Mock(), read_line=Mock(side_effect=AssertionError('unexpected read')))
        self.assertEqual(handler(':: Proceed with installation? [Y/n] '), 'n\n')

    def test_transaction_details_survive_privileged_relay(self) -> None:
        question = {'event': 'question', 'question_type': 'pacman_confirmation',
                    'question_id': 'p-1', 'message': 'Transaction changed', 'details': 'Packages (1) foo-3-1'}
        process = type('Process', (), {'stdin': io.StringIO(), 'stdout': io.StringIO(
            json.dumps(question) + '\n' + '{"event":"completed","success":true}\n')})()
        received = []
        invoker = BatchPrivilegedHelperInvoker(translate=lambda text: text,
            print_line=lambda text: None, emit_log=lambda text: None,
            request_question=lambda payload: received.append(payload) or False)
        invoker._read_command_result(process, failure_message='failed')
        self.assertEqual(received[0]['details'], question['details'])
        self.assertIs(json.loads(process.stdin.getvalue())['response'], False)

    def test_transaction_dialog_contains_full_details_and_defaults_to_no(self) -> None:
        responses = []
        with patch.object(QMessageBox, 'exec', return_value=QMessageBox.StandardButton.No), \
             patch.object(QMessageBox, 'setDetailedText') as details, \
             patch.object(QMessageBox, 'setDefaultButton') as default:
            handle_question_request(parent=None,
                payload={'question_type': 'pacman_confirmation', 'question_id': 'p-1',
                         'message': 'Transaction changed', 'details': 'Packages (1) foo-3-1'},
                submit_response=lambda _qid, answer: responses.append(answer),
                cancel_question=lambda _qid: self.fail('unexpected cancellation'))
        details.assert_called_once_with('Packages (1) foo-3-1')
        default.assert_called_once_with(QMessageBox.StandardButton.No)
        self.assertEqual(responses, [False])


if __name__ == '__main__':
    unittest.main()
