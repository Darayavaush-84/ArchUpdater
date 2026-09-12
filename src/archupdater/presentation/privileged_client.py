from __future__ import annotations

import json
from pathlib import Path

from PySide6.QtCore import QObject, QProcess, QTimer, Signal, Slot

from archupdater.i18n.manager import resolve_language_code
from archupdater.application.helper_protocol import HelperAction, HelperEventType, HelperRequest
from archupdater.infrastructure.settings import SettingsService


class PrivilegedUpdateClient(QObject):
    MAX_PARTIAL_OUTPUT_CHARACTERS = 256 * 1024
    status_changed = Signal(str)
    log_received = Signal(str)
    completed = Signal(bool, str)

    def __init__(
        self,
        parent: QObject | None = None,
        helper_path: Path | None = None,
        language_code: str | None = None,
    ) -> None:
        super().__init__(parent)
        self._helper_path = helper_path or self._resolve_default_helper_path()
        self._language_code = language_code or resolve_language_code(
            SettingsService().language_preference()
        )
        self._process = QProcess(self)
        self._stdout_buffer = ""
        self._stderr_buffer = ""
        self._completed_payload: tuple[bool, str] | None = None
        self._did_emit_completed = False
        self._pending_request: HelperRequest | None = None
        self._start_timer = QTimer(self)
        self._start_timer.setSingleShot(True)
        self._start_timer.setInterval(3000)
        self._start_timer.timeout.connect(self._on_start_timeout)

        self._process.setProgram("pkexec")
        self._process.setArguments(
            [
                "--disable-internal-agent",
                str(self._helper_path),
                "--archupdater-auth=support-packages",
            ]
        )
        self._process.started.connect(self._on_started)
        self._process.readyReadStandardOutput.connect(self._on_stdout_ready)
        self._process.readyReadStandardError.connect(self._on_stderr_ready)
        self._process.finished.connect(self._on_finished)
        self._process.errorOccurred.connect(self._on_error)

    def start_install_support_packages(
        self,
        package_names: list[str],
    ) -> None:
        self._ensure_not_running()
        self._start_request(
            HelperRequest(
                action=HelperAction.INSTALL_SUPPORT_PACKAGES,
                package_names=package_names,
                language_code=self._language_code,
            )
        )

    def start_remove_support_packages(self, package_names: list[str]) -> None:
        self._ensure_not_running()
        self._start_request(
            HelperRequest(
                action=HelperAction.REMOVE_SUPPORT_PACKAGES,
                package_names=package_names,
                language_code=self._language_code,
            )
        )

    def _ensure_not_running(self) -> None:
        if self._process.state() != QProcess.ProcessState.NotRunning:
            raise RuntimeError(self.tr("Privileged update is already running."))

    def _start_request(self, request: HelperRequest) -> None:
        self._stdout_buffer = ""
        self._stderr_buffer = ""
        self._completed_payload = None
        self._did_emit_completed = False
        self._pending_request = request

        self.status_changed.emit("waiting_authentication")
        self.log_received.emit(self.tr("Requesting authorization from the system authentication agent..."))
        self._process.start()
        self._start_timer.start()

    def terminate(self) -> None:
        self._start_timer.stop()
        self._pending_request = None
        if self._process.state() != QProcess.ProcessState.NotRunning:
            self._process.kill()

    def _resolve_default_helper_path(self) -> Path:
        return Path("/usr/lib/archupdater/archupdater-helper")

    @Slot()
    def _on_started(self) -> None:
        self._start_timer.stop()
        if self._pending_request is None:
            return
        request = self._pending_request
        self._pending_request = None
        self._process.write(request.to_json_bytes())
        self._process.closeWriteChannel()

    @Slot()
    def _on_start_timeout(self) -> None:
        if self._process.state() == QProcess.ProcessState.Starting:
            self._process.kill()
        if self._completed_payload is None:
            self._emit_completed(False, self.tr("Failed to start pkexec."))

    def _on_stdout_ready(self) -> None:
        chunk = bytes(self._process.readAllStandardOutput()).decode("utf-8", errors="replace")
        self._stdout_buffer += chunk

        while "\n" in self._stdout_buffer:
            line, self._stdout_buffer = self._stdout_buffer.split("\n", 1)
            line = line.strip()
            if not line:
                continue
            self._handle_stdout_line(line)
        if len(self._stdout_buffer) > self.MAX_PARTIAL_OUTPUT_CHARACTERS:
            self._abort_oversized_output()

    def _handle_stdout_line(self, line: str) -> None:
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            self.log_received.emit(self.tr("helper: {line}").format(line=line))
            return
        if not isinstance(payload, dict):
            self.log_received.emit(self.tr("Unknown helper event: {line}").format(line=line))
            return

        event_name = payload.get("event")
        if event_name == HelperEventType.STATUS.value:
            value = str(payload.get("value", ""))
            self.status_changed.emit(value)
            return

        if event_name == HelperEventType.LOG.value:
            message = str(payload.get("message", ""))
            if message:
                self.log_received.emit(message)
            return

        if event_name == HelperEventType.COMPLETED.value:
            raw_success = payload.get("success")
            if not isinstance(raw_success, bool):
                self._completed_payload = (
                    False,
                    self.tr("The privileged helper returned an invalid result."),
                )
                return
            message = str(payload.get("message", ""))
            self._completed_payload = (raw_success, message)
            return

        self.log_received.emit(self.tr("Unknown helper event: {line}").format(line=line))

    def _on_stderr_ready(self) -> None:
        chunk = bytes(self._process.readAllStandardError()).decode("utf-8", errors="replace")
        self._stderr_buffer += chunk

        while "\n" in self._stderr_buffer:
            line, self._stderr_buffer = self._stderr_buffer.split("\n", 1)
            line = line.strip()
            if line:
                self.log_received.emit(self.tr("pkexec: {line}").format(line=line))
        if len(self._stderr_buffer) > self.MAX_PARTIAL_OUTPUT_CHARACTERS:
            self._abort_oversized_output()

    def _abort_oversized_output(self) -> None:
        self._stdout_buffer = ""
        self._stderr_buffer = ""
        if self._process.state() != QProcess.ProcessState.NotRunning:
            self._process.kill()
        self._emit_completed(
            False,
            self.tr("Privileged helper output exceeded the safety limit."),
        )

    def _on_finished(self, exit_code: int, _exit_status: QProcess.ExitStatus) -> None:
        self._start_timer.stop()
        self._pending_request = None
        stderr_text = self._stderr_buffer.strip()
        if stderr_text:
            self.log_received.emit(self.tr("pkexec: {line}").format(line=stderr_text))
            self._stderr_buffer = ""

        if self._completed_payload is not None:
            self._emit_completed(*self._completed_payload)
            return

        if exit_code == 126:
            self._emit_completed(False, self._authentication_cancelled_message())
            return

        if exit_code == 127:
            if self._looks_like_auth_cancelled(stderr_text):
                self._emit_completed(False, self._authentication_cancelled_message())
                return
            self._emit_completed(
                False,
                self.tr("Authorization failed or no authentication agent was available."),
            )
            return

        self._emit_completed(
            False,
            self.tr("Privileged helper exited unexpectedly with code {code}.").format(code=exit_code),
        )

    def _on_error(self, _error: QProcess.ProcessError) -> None:
        self._start_timer.stop()
        self._pending_request = None
        if self._process.state() == QProcess.ProcessState.NotRunning and self._completed_payload is None:
            self._emit_completed(False, self.tr("Failed to start pkexec."))

    def _emit_completed(self, success: bool, message: str) -> None:
        if self._did_emit_completed:
            return
        self._did_emit_completed = True
        self._start_timer.stop()
        self._pending_request = None
        self.completed.emit(success, message)

    def _authentication_cancelled_message(self) -> str:
        return self.tr(
            "Authentication was cancelled. The administrator password is required to continue, so the operation has been interrupted."
        )

    def _looks_like_auth_cancelled(self, output: str) -> bool:
        lowered = output.lower()
        return any(
            marker in lowered
            for marker in (
                "not authorized",
                "authentication was cancelled",
                "authentication cancelled",
                "authorization cancelled",
                "canceled by user",
                "cancelled by user",
            )
        )
