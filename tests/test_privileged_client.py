from __future__ import annotations

import sys
import unittest
from pathlib import Path
import json

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from PySide6.QtCore import QProcess

from archupdater.application.helper_protocol import HelperAction, HelperRequest
from archupdater.presentation.privileged_client import PrivilegedUpdateClient


class _FakeProcess:
    def __init__(self, *, state: QProcess.ProcessState = QProcess.ProcessState.NotRunning) -> None:
        self._state = state
        self.killed = 0
        self.writes: list[bytes] = []

    def state(self) -> QProcess.ProcessState:
        return self._state

    def start(self) -> None:
        return None

    def write(self, payload: bytes) -> None:
        self.writes.append(payload)

    def closeWriteChannel(self) -> None:
        return None

    def kill(self) -> None:
        self.killed += 1
        self._state = QProcess.ProcessState.NotRunning


class PrivilegedUpdateClientTests(unittest.TestCase):
    def test_default_helper_path_matches_polkit_authorized_path(self) -> None:
        client = PrivilegedUpdateClient()

        self.assertEqual(
            client._helper_path,
            Path("/usr/lib/archupdater/archupdater-helper"),
        )
        self.assertEqual(
            client._process.arguments(),
            [
                "--disable-internal-agent",
                "/usr/lib/archupdater/archupdater-helper",
                "--archupdater-auth=support-packages",
            ],
        )

    def test_request_payload_includes_resolved_language_code(self) -> None:
        client = PrivilegedUpdateClient(language_code="it")
        client._process = _FakeProcess()  # type: ignore[assignment]

        client.start_install_support_packages(["flatpak"])
        client._on_started()

        self.assertEqual(len(client._process.writes), 1)
        payload = json.loads(client._process.writes[0].decode("utf-8"))
        self.assertEqual(payload["language_code"], "it")
        self.assertEqual(payload["package_names"], ["flatpak"])

    def test_support_install_payload_has_no_removed_aur_bootstrap_field(self) -> None:
        client = PrivilegedUpdateClient(language_code="it")
        client._process = _FakeProcess()  # type: ignore[assignment]

        client.start_install_support_packages(["flatpak"])
        client._on_started()

        payload = json.loads(client._process.writes[0].decode("utf-8"))
        self.assertNotIn("aur_bootstrap_confirmed", payload)

    def test_failed_start_emits_completed_only_once(self) -> None:
        client = PrivilegedUpdateClient()
        client._process = _FakeProcess()  # type: ignore[assignment]
        events: list[tuple[bool, str]] = []
        client.completed.connect(lambda success, message: events.append((success, message)))

        client._start_request(
            HelperRequest(
                action=HelperAction.INSTALL_SUPPORT_PACKAGES,
                package_names=["flatpak"],
            )
        )
        client._on_error(QProcess.ProcessError.FailedToStart)
        client._on_finished(1, QProcess.ExitStatus.CrashExit)

        self.assertEqual(events, [(False, "Failed to start pkexec.")])

    def test_start_timeout_kills_process_and_emits_failure(self) -> None:
        client = PrivilegedUpdateClient()
        client._process = _FakeProcess(state=QProcess.ProcessState.Starting)  # type: ignore[assignment]
        events: list[tuple[bool, str]] = []
        client.completed.connect(lambda success, message: events.append((success, message)))

        client._start_request(
            HelperRequest(
                action=HelperAction.INSTALL_SUPPORT_PACKAGES,
                package_names=["flatpak"],
            )
        )
        client._on_start_timeout()

        self.assertEqual(client._process.killed, 1)
        self.assertEqual(events, [(False, "Failed to start pkexec.")])

    def test_completed_payload_is_emitted_only_once(self) -> None:
        client = PrivilegedUpdateClient()
        events: list[tuple[bool, str]] = []
        client.completed.connect(lambda success, message: events.append((success, message)))
        client._completed_payload = (False, "boom")

        client._on_finished(1, QProcess.ExitStatus.CrashExit)
        client._on_finished(1, QProcess.ExitStatus.CrashExit)
        client._on_error(QProcess.ProcessError.Crashed)

        self.assertEqual(events, [(False, "boom")])

    def test_non_boolean_helper_completion_is_rejected(self) -> None:
        client = PrivilegedUpdateClient()

        client._handle_stdout_line(
            '{"event":"completed","success":"false","message":"invalid"}'
        )

        self.assertEqual(
            client._completed_payload,
            (False, "The privileged helper returned an invalid result."),
        )

    def test_non_object_helper_event_is_logged_without_crashing(self) -> None:
        client = PrivilegedUpdateClient()
        logs: list[str] = []
        client.log_received.connect(logs.append)

        client._handle_stdout_line("[]")

        self.assertEqual(logs, ["Unknown helper event: []"])

    def test_pkexec_cancel_exit_emits_password_required_message(self) -> None:
        client = PrivilegedUpdateClient()
        events: list[tuple[bool, str]] = []
        client.completed.connect(lambda success, message: events.append((success, message)))

        client._on_finished(126, QProcess.ExitStatus.NormalExit)

        self.assertEqual(len(events), 1)
        self.assertFalse(events[0][0])
        self.assertIn("administrator password is required", events[0][1])
        self.assertIn("operation has been interrupted", events[0][1])

    def test_pkexec_not_authorized_output_is_treated_as_cancelled(self) -> None:
        client = PrivilegedUpdateClient()
        events: list[tuple[bool, str]] = []
        logs: list[str] = []
        client.completed.connect(lambda success, message: events.append((success, message)))
        client.log_received.connect(logs.append)
        client._stderr_buffer = "Error executing command as another user: Not authorized\n"

        client._on_finished(127, QProcess.ExitStatus.NormalExit)

        self.assertEqual(len(events), 1)
        self.assertFalse(events[0][0])
        self.assertIn("administrator password is required", events[0][1])
        self.assertIn("operation has been interrupted", events[0][1])
        self.assertEqual(
            logs,
            ["pkexec: Error executing command as another user: Not authorized"],
        )


if __name__ == "__main__":
    unittest.main()
