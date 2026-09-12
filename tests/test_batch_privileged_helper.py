from __future__ import annotations

import io
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from archupdater.application.helper_protocol import HelperAction, HelperRequest
from archupdater.application.update_session.errors import BatchAuthenticationCancelled
from archupdater.batch.privileged_helper import BatchPrivilegedHelperInvoker


class _CapturingStdin(io.StringIO):
    def close(self) -> None:
        return None


class _FakeProcess:
    def __init__(self, stdout: str, return_code: int = 0) -> None:
        self.stdin = _CapturingStdin()
        self.stdout = io.StringIO(stdout)
        self._return_code = return_code
        self.terminated = 0
        self.killed = 0

    def poll(self) -> int | None:
        return None

    def wait(self, timeout: int | None = None) -> int:
        return self._return_code

    def terminate(self) -> None:
        self.terminated += 1

    def kill(self) -> None:
        self.killed += 1


class BatchPrivilegedHelperInvokerTests(unittest.TestCase):
    def test_invoker_sends_request_and_uses_completed_event(self) -> None:
        printed: list[str] = []
        logs: list[str] = []
        fake_process = _FakeProcess(
            "\n".join(
                (
                    '{"event":"status","value":"ready"}',
                    '{"event":"completed","success":true,"message":"initialized"}',
                    '{"event":"status","value":"running"}',
                    '{"event":"log","message":"pacman output"}',
                    '{"event":"completed","success":true,"message":"done"}',
                    "",
                )
            )
        )
        popen_calls: list[list[str]] = []

        def fake_popen(command, **_kwargs):  # noqa: ANN001
            popen_calls.append(command)
            return fake_process

        invoker = BatchPrivilegedHelperInvoker(
            translate=lambda text: text,
            print_line=printed.append,
            emit_log=logs.append,
            helper_path=Path(sys.executable),
            pkexec_path=Path(sys.executable),
            auth_purpose="update-session",
        )

        with (
            patch("archupdater.batch.privileged_helper.os.geteuid", return_value=1000),
            patch("archupdater.batch.privileged_helper.subprocess.Popen", fake_popen),
        ):
            result = invoker.run(
                HelperRequest(action=HelperAction.RUN_SYSTEM_UPDATE),
                failure_message="System update failed.",
            )

        self.assertTrue(result.success)
        self.assertEqual(result.message, "")
        self.assertEqual(
            popen_calls,
            [
                [
                    sys.executable,
                    "--disable-internal-agent",
                    sys.executable,
                    "--archupdater-auth=update-session",
                ]
            ],
        )
        self.assertIn('"action": "run_system_update"', fake_process.stdin.getvalue())
        self.assertIn("pacman output", printed)
        self.assertIn("pacman output", logs)
        invoker.close()

    def test_invoker_reuses_single_authorized_helper_process(self) -> None:
        fake_process = _FakeProcess(
            "\n".join(
                (
                    '{"event":"status","value":"ready"}',
                    '{"event":"completed","success":true,"message":"initialized"}',
                    '{"event":"completed","success":true,"message":"system done"}',
                    '{"event":"completed","success":true,"message":"flatpak done"}',
                    "",
                )
            )
        )
        popen_calls: list[list[str]] = []

        def fake_popen(command, **_kwargs):  # noqa: ANN001
            popen_calls.append(command)
            return fake_process

        invoker = BatchPrivilegedHelperInvoker(
            translate=lambda text: text,
            print_line=lambda _message: None,
            emit_log=lambda _message: None,
            helper_path=Path(sys.executable),
            pkexec_path=Path(sys.executable),
            auth_purpose="update-session",
        )

        with (
            patch("archupdater.batch.privileged_helper.os.geteuid", return_value=1000),
            patch("archupdater.batch.privileged_helper.subprocess.Popen", fake_popen),
        ):
            first = invoker.run(
                HelperRequest(action=HelperAction.RUN_SYSTEM_UPDATE),
                failure_message="System update failed.",
            )
            second = invoker.run(
                HelperRequest(action=HelperAction.RUN_FLATPAK_SYSTEM_CLEANUP),
                failure_message="Flatpak cleanup failed.",
            )

        self.assertTrue(first.success)
        self.assertTrue(second.success)
        self.assertEqual(len(popen_calls), 1)
        stdin_payload = fake_process.stdin.getvalue()
        self.assertIn('"action": "run_system_update"', stdin_payload)
        self.assertIn('"action": "run_flatpak_system_cleanup"', stdin_payload)
        invoker.close()

    def test_authorize_consumes_ready_event_and_keeps_session_open(self) -> None:
        fake_process = _FakeProcess(
            "\n".join(
                (
                    '{"event":"status","value":"ready"}',
                    '{"event":"completed","success":true,"message":"initialized"}',
                    '{"event":"completed","success":true,"message":"system done"}',
                    "",
                )
            )
        )
        popen_calls: list[list[str]] = []

        def fake_popen(command, **_kwargs):  # noqa: ANN001
            popen_calls.append(command)
            return fake_process

        invoker = BatchPrivilegedHelperInvoker(
            translate=lambda text: text,
            print_line=lambda _message: None,
            emit_log=lambda _message: None,
            helper_path=Path(sys.executable),
            pkexec_path=Path(sys.executable),
            auth_purpose="update-session",
        )

        with (
            patch("archupdater.batch.privileged_helper.os.geteuid", return_value=1000),
            patch("archupdater.batch.privileged_helper.subprocess.Popen", fake_popen),
        ):
            auth_result = invoker.authorize()
            run_result = invoker.run(
                HelperRequest(action=HelperAction.RUN_SYSTEM_UPDATE),
                failure_message="System update failed.",
            )

        self.assertTrue(auth_result.success)
        self.assertTrue(run_result.success)
        self.assertEqual(len(popen_calls), 1)
        invoker.close()

    def test_invoker_raises_auth_cancelled_for_pkexec_cancel_exit(self) -> None:
        invoker = BatchPrivilegedHelperInvoker(
            translate=lambda text: text,
            print_line=lambda _message: None,
            emit_log=lambda _message: None,
            helper_path=Path(sys.executable),
            pkexec_path=Path(sys.executable),
        )

        with (
            patch("archupdater.batch.privileged_helper.os.geteuid", return_value=1000),
            patch(
                "archupdater.batch.privileged_helper.subprocess.Popen",
                lambda *_args, **_kwargs: _FakeProcess("", return_code=126),
            ),
        ):
            with self.assertRaisesRegex(
                BatchAuthenticationCancelled,
                "administrator password is required",
            ):
                invoker.run(
                    HelperRequest(action=HelperAction.RUN_SYSTEM_UPDATE),
                    failure_message="System update failed.",
                )

    def test_invoker_reports_pkexec_policy_denial_as_authorization_failure(self) -> None:
        invoker = BatchPrivilegedHelperInvoker(
            translate=lambda text: text,
            print_line=lambda _message: None,
            emit_log=lambda _message: None,
            helper_path=Path(sys.executable),
            pkexec_path=Path(sys.executable),
        )

        with (
            patch("archupdater.batch.privileged_helper.os.geteuid", return_value=1000),
            patch(
                "archupdater.batch.privileged_helper.subprocess.Popen",
                lambda *_args, **_kwargs: _FakeProcess(
                    "Error executing command as another user: Not authorized\n",
                    return_code=127,
                ),
            ),
        ):
            result = invoker.run(
                HelperRequest(action=HelperAction.RUN_SYSTEM_UPDATE),
                failure_message="System update failed.",
            )

        self.assertFalse(result.success)
        self.assertIn("Authorization failed", result.message)

    def test_invoker_aborts_session_on_oversized_helper_output(self) -> None:
        fake_process = _FakeProcess(
            "x" * (BatchPrivilegedHelperInvoker.MAX_HELPER_LINE_CHARACTERS + 1)
        )
        invoker = BatchPrivilegedHelperInvoker(
            translate=lambda text: text,
            print_line=lambda _message: None,
            emit_log=lambda _message: None,
            helper_path=Path(sys.executable),
            pkexec_path=Path(sys.executable),
        )
        with (
            patch("archupdater.batch.privileged_helper.os.geteuid", return_value=1000),
            patch(
                "archupdater.batch.privileged_helper.subprocess.Popen",
                lambda *_args, **_kwargs: fake_process,
            ),
        ):
            result = invoker.authorize()

        self.assertFalse(result.success)
        self.assertIn("safety limit", result.message)
        self.assertEqual(fake_process.terminated, 1)
        self.assertIsNone(invoker._process)

    def test_invoker_rejects_non_boolean_completion_status(self) -> None:
        fake_process = _FakeProcess(
            '\n'.join(
                (
                    '{"event":"status","value":"ready"}',
                    '{"event":"completed","success":"false","message":"invalid"}',
                    "",
                )
            )
        )
        invoker = BatchPrivilegedHelperInvoker(
            translate=lambda text: text,
            print_line=lambda _message: None,
            emit_log=lambda _message: None,
            helper_path=Path(sys.executable),
            pkexec_path=Path(sys.executable),
        )

        with (
            patch("archupdater.batch.privileged_helper.os.geteuid", return_value=1000),
            patch(
                "archupdater.batch.privileged_helper.subprocess.Popen",
                lambda *_args, **_kwargs: fake_process,
            ),
        ):
            result = invoker.authorize()

        self.assertFalse(result.success)
        self.assertIn("invalid result", result.message)
        self.assertEqual(fake_process.terminated, 1)


if __name__ == "__main__":
    unittest.main()
