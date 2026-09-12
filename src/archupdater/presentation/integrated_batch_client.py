from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

from PySide6.QtCore import QObject, QProcess, QProcessEnvironment, QTimer, Signal

from archupdater.domain.update_plan import UpdatePlan
from archupdater.application.update_session.protocol import (
    BatchControlType,
    BatchEventType,
    BatchOutcome,
    MAX_UPDATE_PLAN_BYTES,
    deserialize_update_plan_payload,
    running_status_for_step,
    serialize_update_plan,
)


class IntegratedBatchUpdateClient(QObject):
    LOG_DEDUPE_LIMIT = 200
    START_TIMEOUT_MS = 3000
    EVENT_READ_CHUNK_CHARACTERS = 1024 * 1024
    MAX_EVENT_LINE_CHARACTERS = 24 * 1024 * 1024
    MAX_STDOUT_LINE_CHARACTERS = 16 * 1024

    status_changed = Signal(str)
    log_received = Signal(str)
    progress_changed = Signal(object)
    question_requested = Signal(object)
    completed = Signal(bool, str, str)

    def __init__(
        self,
        plan: UpdatePlan,
        *,
        python_executable: str | None = None,
        module_search_path: Path | None = None,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._plan = plan
        self._python_executable = python_executable or sys.executable
        self._module_search_path = module_search_path or Path(__file__).resolve().parents[2]
        self._process = QProcess(self)
        self._process.setProcessChannelMode(QProcess.ProcessChannelMode.MergedChannels)
        self._process.started.connect(self._on_started)
        self._process.readyReadStandardOutput.connect(self._read_process_output)
        self._process.finished.connect(self._on_finished)
        self._process.errorOccurred.connect(self._on_error)
        self._poll_timer = QTimer(self)
        self._poll_timer.setInterval(80)
        self._poll_timer.timeout.connect(self._poll_events)
        self._start_timer = QTimer(self)
        self._start_timer.setSingleShot(True)
        self._start_timer.setInterval(self.START_TIMEOUT_MS)
        self._start_timer.timeout.connect(self._on_start_timeout)
        self._temporary_dir: tempfile.TemporaryDirectory[str] | None = None
        self._events_path: Path | None = None
        self._read_offset = 0
        self._event_buffer = ""
        self._output_buffer = ""
        self._stdout_log_dedupe: list[str] = []
        self._event_log_dedupe: list[str] = []
        self._did_emit_completed = False
        self._batch_completed = False
        self._pending_completion: tuple[bool, str, str] | None = None
        self._process_started = False
        self._discarding_oversize_stdout_line = False

    def start(self) -> None:
        if self._process.state() != QProcess.ProcessState.NotRunning:
            raise RuntimeError(self.tr("Update process is already running."))

        self._did_emit_completed = False
        self._batch_completed = False
        self._pending_completion = None
        self._process_started = False
        self._read_offset = 0
        self._event_buffer = ""
        self._output_buffer = ""
        self._stdout_log_dedupe = []
        self._event_log_dedupe = []
        self._discarding_oversize_stdout_line = False
        serialized_plan = json.dumps(self._serialize_plan(self._plan), ensure_ascii=False)
        if len(serialized_plan.encode("utf-8")) > MAX_UPDATE_PLAN_BYTES:
            raise ValueError(self.tr("Update plan exceeds the safety limit."))
        self._temporary_dir = tempfile.TemporaryDirectory(prefix="archupdater-batch-")
        temporary_root = Path(self._temporary_dir.name)
        plan_path = temporary_root / "plan.json"
        self._events_path = temporary_root / "events.jsonl"
        plan_path.write_text(serialized_plan, encoding="utf-8")
        self._events_path.write_text("", encoding="utf-8")

        environment = QProcessEnvironment.systemEnvironment()
        existing_pythonpath = environment.value("PYTHONPATH", "")
        module_search_path = str(self._module_search_path)
        if existing_pythonpath:
            environment.insert("PYTHONPATH", f"{module_search_path}:{existing_pythonpath}")
        else:
            environment.insert("PYTHONPATH", module_search_path)

        self._process.setProcessEnvironment(environment)
        self._process.setProgram(self._python_executable)
        self._process.setArguments(
            [
                "-m",
                "archupdater.batch_update_runner",
                "--plan",
                str(plan_path),
                "--events",
                str(self._events_path),
            ]
        )
        self._process.start()
        self._start_timer.start()

    def terminate(self) -> None:
        self._send_control({"type": BatchControlType.CANCEL.value})
        self._start_timer.stop()
        self._poll_timer.stop()
        self._did_emit_completed = True
        if self._process.state() != QProcess.ProcessState.NotRunning:
            self._process.terminate()
            QTimer.singleShot(1000, self._kill_if_still_running)
            return
        self._cleanup_temporary_files()
        self.deleteLater()

    def submit_question_response(self, question_id: str, response: object) -> None:
        self._send_control(
            {
                "type": BatchControlType.QUESTION_RESPONSE.value,
                "question_id": question_id,
                "response": response,
            }
        )

    def cancel_question(self, question_id: str) -> None:
        self._send_control(
            {
                "type": BatchControlType.QUESTION_RESPONSE.value,
                "question_id": question_id,
                "cancelled": True,
            }
        )

    def _serialize_plan(self, plan: UpdatePlan) -> dict[str, object]:
        payload = serialize_update_plan(plan)
        deserialize_update_plan_payload(payload)
        return payload

    def _poll_events(self) -> None:
        if self._events_path is None or not self._events_path.exists():
            return

        with self._events_path.open("r", encoding="utf-8") as handle:
            handle.seek(self._read_offset)
            chunk = handle.read(self.EVENT_READ_CHUNK_CHARACTERS)
            self._read_offset = handle.tell()

        if not chunk:
            return

        self._event_buffer += chunk
        if len(self._event_buffer) > self.MAX_EVENT_LINE_CHARACTERS:
            self._event_buffer = ""
            self._record_completion(
                False,
                self.tr("The update process returned an oversized event."),
                BatchOutcome.FAILED.value,
            )
            self._process.kill()
            return
        while "\n" in self._event_buffer:
            line, self._event_buffer = self._event_buffer.split("\n", 1)
            line = line.strip()
            if line:
                self._handle_event_line(line)

    def _handle_event_line(self, line: str) -> None:
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            return
        if not isinstance(payload, dict):
            return

        event_type = str(payload.get("type") or "")
        if event_type == BatchEventType.BATCH_STARTED.value:
            message = str(payload.get("message") or "")
            if message:
                self.log_received.emit(message)
            return

        if event_type == BatchEventType.STEP_STARTED.value:
            step = str(payload.get("step") or "")
            if step:
                self.status_changed.emit(running_status_for_step(step))
            return

        if event_type == BatchEventType.COMMAND_STARTED.value:
            self.progress_changed.emit(payload)
            return

        if event_type == BatchEventType.LOG.value:
            message = str(payload.get("message") or "")
            if message:
                self._emit_event_log(message)
            return

        if event_type == BatchEventType.STEP_COMPLETED.value:
            self.progress_changed.emit(payload)
            return

        if event_type == BatchEventType.PROGRESS.value:
            self.progress_changed.emit(payload)
            return

        if event_type == BatchEventType.QUESTION_REQUESTED.value:
            self.question_requested.emit(payload)
            return

        if event_type == BatchEventType.BATCH_COMPLETED.value:
            self._batch_completed = True
            raw_success = payload.get("success")
            message = str(payload.get("message") or "")
            if not isinstance(raw_success, bool):
                self._record_completion(
                    False,
                    self.tr("The update process returned an invalid completion result."),
                    BatchOutcome.FAILED.value,
                )
                return
            try:
                outcome = BatchOutcome(str(payload["outcome"])).value
            except (KeyError, ValueError):
                self._record_completion(
                    False,
                    self.tr("The update process returned an invalid completion result."),
                    BatchOutcome.FAILED.value,
                )
                return
            successful_outcomes = {
                BatchOutcome.SUCCESS.value,
                BatchOutcome.PARTIAL_SUCCESS.value,
                BatchOutcome.NO_CHANGES.value,
            }
            if raw_success != (outcome in successful_outcomes):
                self._record_completion(
                    False,
                    self.tr("The update process returned an invalid completion result."),
                    BatchOutcome.FAILED.value,
                )
                return
            self._record_completion(raw_success, message, outcome)

    def _read_process_output(self) -> None:
        data = bytes(self._process.readAllStandardOutput()).decode("utf-8", errors="replace")
        if not data:
            return
        normalized = data.replace("\r\n", "\n").replace("\r", "\n")
        while normalized:
            fragment, separator, normalized = normalized.partition("\n")
            if not self._discarding_oversize_stdout_line:
                remaining = self.MAX_STDOUT_LINE_CHARACTERS - len(self._output_buffer)
                self._output_buffer += fragment[: max(0, remaining)]
                if len(fragment) > remaining:
                    self._discarding_oversize_stdout_line = True
            if not separator:
                break
            self._emit_stdout_log(
                self._output_buffer
                + ("…" if self._discarding_oversize_stdout_line else "")
            )
            self._output_buffer = ""
            self._discarding_oversize_stdout_line = False

    def _on_started(self) -> None:
        self._start_timer.stop()
        self._process_started = True
        self.status_changed.emit("starting_integrated")
        self.log_received.emit(self.tr("Update session started."))
        self._poll_timer.start()

    def _on_start_timeout(self) -> None:
        if self._process_started or self._did_emit_completed:
            return
        if self._process.state() == QProcess.ProcessState.Starting:
            self._process.kill()
        self._emit_completed(
            False,
            self.tr("Failed to start the update process."),
            BatchOutcome.FAILED.value,
        )

    def _on_finished(self, exit_code: int, _exit_status: QProcess.ExitStatus) -> None:
        self._start_timer.stop()
        self._read_process_output()
        if self._output_buffer or self._discarding_oversize_stdout_line:
            self._emit_stdout_log(
                self._output_buffer
                + ("…" if self._discarding_oversize_stdout_line else "")
            )
            self._output_buffer = ""
            self._discarding_oversize_stdout_line = False
        self._drain_events()
        if self._pending_completion is not None and not self._did_emit_completed:
            self._emit_completed(*self._pending_completion)
        elif not self._process_started and not self._did_emit_completed:
            self._emit_completed(
                False,
                self.tr("Failed to start the update process."),
                BatchOutcome.FAILED.value,
            )
        elif not self._batch_completed and not self._did_emit_completed:
            message = (
                self.tr("The update process exited before the batch completed.")
                if exit_code == 0
                else self.tr("The update process failed before the batch completed.")
            )
            self._emit_completed(False, message, BatchOutcome.FAILED.value)
        if self._did_emit_completed:
            self._cleanup_temporary_files()
            self.deleteLater()

    def _drain_events(self) -> None:
        for _ in range(128):
            previous_offset = self._read_offset
            self._poll_events()
            if self._read_offset == previous_offset:
                break

    def _record_completion(self, success: bool, message: str, outcome: str) -> None:
        if self._did_emit_completed or self._pending_completion is not None:
            return
        self._pending_completion = (success, message, outcome)
        if self._process.state() == QProcess.ProcessState.NotRunning:
            self._emit_completed(success, message, outcome)

    def _on_error(self, _error: QProcess.ProcessError) -> None:
        self._start_timer.stop()
        if self._process.state() == QProcess.ProcessState.NotRunning and not self._did_emit_completed:
            self._emit_completed(
                False,
                self.tr("Failed to start the update process."),
                BatchOutcome.FAILED.value,
            )
            self._cleanup_temporary_files()
            self.deleteLater()

    def _emit_completed(self, success: bool, message: str, outcome: str) -> None:
        if self._did_emit_completed:
            return
        self._did_emit_completed = True
        self._start_timer.stop()
        self._poll_timer.stop()
        self.completed.emit(success, message, outcome)
        if self._process.state() == QProcess.ProcessState.NotRunning:
            self._cleanup_temporary_files()
            self.deleteLater()

    def _send_control(self, payload: dict[str, object]) -> None:
        if self._process.state() == QProcess.ProcessState.NotRunning:
            return
        self._process.write((json.dumps(payload) + "\n").encode("utf-8"))

    def _kill_if_still_running(self) -> None:
        if self._process.state() != QProcess.ProcessState.NotRunning:
            self._process.kill()

    def _emit_stdout_log(self, message: str) -> None:
        if self._consume_dedupe(self._event_log_dedupe, message):
            return
        self._remember_dedupe(self._stdout_log_dedupe, message)
        self.log_received.emit(message)

    def _emit_event_log(self, message: str) -> None:
        if self._consume_dedupe(self._stdout_log_dedupe, message):
            return
        self._remember_dedupe(self._event_log_dedupe, message)
        self.log_received.emit(message)

    def _consume_dedupe(self, cache: list[str], message: str) -> bool:
        try:
            index = cache.index(message)
        except ValueError:
            return False
        del cache[index]
        return True

    def _remember_dedupe(self, cache: list[str], message: str) -> None:
        cache.append(message)
        if len(cache) > self.LOG_DEDUPE_LIMIT:
            del cache[: len(cache) - self.LOG_DEDUPE_LIMIT]

    def _cleanup_temporary_files(self) -> None:
        if self._temporary_dir is not None:
            self._temporary_dir.cleanup()
            self._temporary_dir = None
        self._events_path = None
        self._read_offset = 0
        self._event_buffer = ""
        self._output_buffer = ""
        self._stdout_log_dedupe = []
        self._pending_completion = None
        self._event_log_dedupe = []
        self._process_started = False
        self._discarding_oversize_stdout_line = False
