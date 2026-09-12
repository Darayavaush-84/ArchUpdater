from __future__ import annotations

import json
import os
import subprocess
import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from archupdater.application.helper_protocol import HelperAction, HelperEventType, HelperRequest
from archupdater.application.update_session.backend import CommandRunResult
from archupdater.application.update_session.errors import BatchAuthenticationCancelled
from archupdater.domain.aur import AurInstallTarget


Translate = Callable[[str], str]
PrintLine = Callable[[str], None]
EmitLog = Callable[[str], None]


@dataclass(slots=True)
class BatchPrivilegedHelperInvoker:
    MAX_HELPER_LINE_CHARACTERS = 16 * 1024 * 1024
    translate: Translate
    print_line: PrintLine
    emit_log: EmitLog
    helper_path: Path = Path("/usr/lib/archupdater/archupdater-helper")
    pkexec_path: Path = Path("/usr/bin/pkexec")
    auth_purpose: str = "update-session"
    aur_targets: list[AurInstallTarget] = field(default_factory=list)
    request_question: Callable[[dict[str, object]], object | None] | None = None
    _process: subprocess.Popen[str] | None = field(default=None, init=False, repr=False)
    _authorized: bool = field(default=False, init=False, repr=False)
    _lock: threading.RLock = field(default_factory=threading.RLock, init=False, repr=False)

    def authorize(self) -> CommandRunResult:
        with self._lock:
            if self._authorized and self._process is not None:
                return CommandRunResult(True)
            process = self._ensure_process()
            if isinstance(process, CommandRunResult):
                return process
            ready_result = self._read_ready_result(process)
            if not ready_result.success:
                return ready_result
            if self.auth_purpose == "update-session":
                initialization_result = self._write_request(
                    process,
                    HelperRequest(
                        action=HelperAction.INITIALIZE_UPDATE_SESSION,
                        aur_targets=self.aur_targets,
                    ),
                    failure_message=self.translate(
                        "Could not initialize the privileged update session."
                    ),
                )
                if not initialization_result.success:
                    return initialization_result
            self._authorized = True
            return CommandRunResult(True)

    def run(self, request: HelperRequest, *, failure_message: str) -> CommandRunResult:
        with self._lock:
            authorization_result = self.authorize()
            if not authorization_result.success:
                return authorization_result
            process = self._process
            if process is None:
                return CommandRunResult(False, failure_message)

            return self._write_request(
                process,
                request,
                failure_message=failure_message,
            )

    def _write_request(
        self,
        process: subprocess.Popen[str],
        request: HelperRequest,
        *,
        failure_message: str,
    ) -> CommandRunResult:
        self.emit_log(
            self.translate("Privileged helper action: {action}").format(
                action=request.action.value
            )
        )
        assert process.stdin is not None
        try:
            process.stdin.write(request.to_json_bytes().decode("utf-8"))
            process.stdin.flush()
        except (BrokenPipeError, OSError, ValueError):
            return self._unexpected_exit_result(process)

        return self._read_command_result(process, failure_message=failure_message)

    def close(self) -> None:
        with self._lock:
            process = self._process
            self._process = None
            self._authorized = False
            if process is None:
                return
            self._stop_process(process, terminate_first=False)

    def _ensure_process(self) -> subprocess.Popen[str] | CommandRunResult:
        if self._process is not None and self._process.poll() is None:
            return self._process

        command = self._helper_command()
        if command is None:
            return CommandRunResult(
                False,
                self.translate("pkexec is required for privileged update steps."),
            )
        if not self.helper_path.exists():
            return CommandRunResult(
                False,
                self.translate("ArchUpdater privileged helper is not installed."),
            )

        self.print_line(
            self.translate("Requesting administrator authorization for privileged update session.")
        )

        try:
            self._process = subprocess.Popen(
                command,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
            )
        except OSError as exc:
            return CommandRunResult(
                False,
                self.translate("Failed to start privileged helper: {error}").format(error=exc),
            )
        return self._process

    def _read_command_result(
        self,
        process: subprocess.Popen[str],
        *,
        failure_message: str,
    ) -> CommandRunResult:
        assert process.stdout is not None
        while True:
            raw_line = process.stdout.readline(self.MAX_HELPER_LINE_CHARACTERS + 1)
            if not raw_line:
                return self._unexpected_exit_result(process)
            if len(raw_line) > self.MAX_HELPER_LINE_CHARACTERS:
                self._abort_process(process)
                return CommandRunResult(
                    False,
                    self.translate("Privileged helper output exceeded the safety limit."),
                )
            line = raw_line.strip()
            if not line:
                continue
            parsed = self._parse_helper_line(line)
            if parsed is None:
                self._log_helper_output(line)
                continue
            event_type, payload = parsed
            if event_type == HelperEventType.LOG.value:
                message = str(payload.get("message") or "")
                if message:
                    self._log_helper_output(message)
                continue
            if event_type == HelperEventType.STATUS.value:
                value = str(payload.get("value") or "")
                if value:
                    self.emit_log(
                        self.translate("Privileged helper status: {status}").format(
                            status=value
                        )
                    )
                continue
            if event_type == HelperEventType.QUESTION.value:
                question_id = payload.get("question_id")
                message = payload.get("message")
                if (
                    not isinstance(question_id, str) or not question_id or len(question_id) > 128
                    or payload.get("question_type") != "pacman_confirmation"
                    or not isinstance(message, str) or not message.strip() or len(message) > 16384
                ):
                    self._abort_process(process)
                    return CommandRunResult(False, self.translate("Invalid Pacman question."))
                accepted = False
                try:
                    if self.request_question is not None:
                        accepted = self.request_question({
                            "question_id": question_id,
                            "question_type": "pacman_confirmation",
                            "message": message,
                        }) is True
                finally:
                    assert process.stdin is not None
                    process.stdin.write(json.dumps({
                        "question_id": question_id, "response": accepted,
                    }) + "\n")
                    process.stdin.flush()
                continue
            if event_type == HelperEventType.COMPLETED.value:
                raw_success = payload.get("success")
                if not isinstance(raw_success, bool):
                    self._abort_process(process)
                    return CommandRunResult(
                        False,
                        self.translate("The privileged helper returned an invalid result."),
                    )
                message = str(payload.get("message") or "")
                return CommandRunResult(
                    raw_success,
                    "" if raw_success else message or failure_message,
                    payload=payload,
                )
            self._log_helper_output(line)

    def _unexpected_exit_result(
        self,
        process: subprocess.Popen[str],
    ) -> CommandRunResult:
        return_code = process.wait()
        self._process = None
        self._authorized = False
        if return_code == 126:
            raise BatchAuthenticationCancelled(self._authentication_cancelled_message())
        if return_code == 127:
            return CommandRunResult(
                False,
                self.translate("Authorization failed or no authentication agent was available."),
            )
        return CommandRunResult(
            False,
            self.translate("Privileged helper exited unexpectedly with code {code}.").format(
                code=return_code
            ),
        )

    def _read_ready_result(self, process: subprocess.Popen[str]) -> CommandRunResult:
        assert process.stdout is not None
        while True:
            raw_line = process.stdout.readline(self.MAX_HELPER_LINE_CHARACTERS + 1)
            if not raw_line:
                return self._unexpected_exit_result(process)
            if len(raw_line) > self.MAX_HELPER_LINE_CHARACTERS:
                self._abort_process(process)
                return CommandRunResult(
                    False,
                    self.translate("Privileged helper output exceeded the safety limit."),
                )
            line = raw_line.strip()
            if not line:
                continue
            parsed = self._parse_helper_line(line)
            if parsed is None:
                self._log_helper_output(line)
                continue
            event_type, payload = parsed
            if event_type == HelperEventType.LOG.value:
                message = str(payload.get("message") or "")
                if message:
                    self._log_helper_output(message)
                continue
            if event_type == HelperEventType.STATUS.value:
                value = str(payload.get("value") or "")
                if value:
                    self.emit_log(
                        self.translate("Privileged helper status: {status}").format(
                            status=value
                        )
                    )
                if value == "ready":
                    return CommandRunResult(True)
                continue
            if event_type == HelperEventType.COMPLETED.value:
                raw_success = payload.get("success")
                if not isinstance(raw_success, bool):
                    self._abort_process(process)
                    return CommandRunResult(
                        False,
                        self.translate("The privileged helper returned an invalid result."),
                    )
                message = str(payload.get("message") or "")
                return CommandRunResult(raw_success, "" if raw_success else message)
            self._log_helper_output(line)

    def _helper_command(self) -> list[str] | None:
        helper_command = [str(self.helper_path), self._auth_purpose_argument()]
        if os.geteuid() == 0:
            return helper_command
        if not self.pkexec_path.exists():
            return None
        return [str(self.pkexec_path), "--disable-internal-agent", *helper_command]

    def _auth_purpose_argument(self) -> str:
        return f"--archupdater-auth={self.auth_purpose}"

    def _authentication_cancelled_message(self) -> str:
        return self.translate(
            "Authentication was cancelled. The administrator password is required to continue, so the update has been interrupted."
        )

    def _abort_process(self, process: subprocess.Popen[str]) -> None:
        if self._process is process:
            self._process = None
        self._authorized = False
        self._stop_process(process, terminate_first=True)

    def _stop_process(
        self,
        process: subprocess.Popen[str],
        *,
        terminate_first: bool,
    ) -> None:
        if process.stdin is not None and not process.stdin.closed:
            try:
                process.stdin.close()
            except OSError:
                pass
        if terminate_first and process.poll() is None:
            process.terminate()
        try:
            process.wait(timeout=2 if terminate_first else 5)
        except subprocess.TimeoutExpired:
            process.kill()
            try:
                process.wait(timeout=1)
            except subprocess.TimeoutExpired:
                pass

    def _parse_helper_line(self, line: str) -> tuple[str, dict[str, object]] | None:
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            return None
        if not isinstance(payload, dict):
            return None
        event_type = payload.get("event")
        if not isinstance(event_type, str):
            return None
        return event_type, payload

    def _log_helper_output(self, message: str) -> None:
        if len(message) > self.MAX_HELPER_LINE_CHARACTERS:
            message = message[: self.MAX_HELPER_LINE_CHARACTERS] + "…"
        self.print_line(message)
        self.emit_log(message)
