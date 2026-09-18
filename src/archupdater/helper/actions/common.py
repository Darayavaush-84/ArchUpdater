from __future__ import annotations

import fcntl
import os
import pty
import select
import signal
import struct
import subprocess
import threading
import termios
import time
from collections.abc import Callable
from pathlib import Path

from PySide6.QtCore import QCoreApplication

from archupdater.application.helper_protocol import HelperEventType
from archupdater.process_lifecycle import arm_parent_death_signal


EmitEvent = Callable[..., None]
EmitLog = Callable[[str], None]

PACMAN_PATH = Path("/usr/bin/pacman")
MAX_STREAM_LINE_CHARACTERS = 16 * 1024
MAX_STREAM_LOG_BYTES = 8 * 1024 * 1024
MAX_COLLECTED_OUTPUT_BYTES = 2 * 1024 * 1024
DEFAULT_PRIVILEGED_COMMAND_TIMEOUT_SECONDS = 6 * 60 * 60


def require_pacman(*, emit_event: EmitEvent, emit_log: EmitLog) -> bool:
    if PACMAN_PATH.exists():
        return True
    emit_log(
        QCoreApplication.translate(
            "PrivilegedHelper",
            "pacman executable not found at /usr/bin/pacman.",
        )
    )
    emit_event(
        HelperEventType.COMPLETED,
        success=False,
        message=QCoreApplication.translate(
            "PrivilegedHelper",
            "pacman is not available on this system.",
        ),
    )
    return False


def stream_command(
    command: list[str],
    *,
    emit_log: EmitLog,
    survive_parent_exit: bool = False,
    input_handler: Callable[[str], str | None] | None = None,
    env: dict[str, str] | None = None,
) -> tuple[int, list[str]]:
    return stream_subprocess(
        command,
        emit_log=emit_log,
        start_new_session=True,
        timeout_seconds=DEFAULT_PRIVILEGED_COMMAND_TIMEOUT_SECONDS,
        survive_parent_exit=survive_parent_exit,
        input_handler=input_handler,
        env=env,
    )


def stream_subprocess(
    command: list[str],
    *,
    emit_log: EmitLog,
    cwd: Path | None = None,
    env: dict[str, str] | None = None,
    preexec_fn: Callable[[], None] | None = None,
    start_new_session: bool = False,
    timeout_seconds: float | None = None,
    survive_parent_exit: bool = False,
    input_handler: Callable[[str], str | None] | None = None,
) -> tuple[int, list[str]]:
    with _CommandConnection(survive_parent_exit) as connection:
        return _stream_subprocess(
            command, emit_log=emit_log, cwd=cwd, env=env, preexec_fn=preexec_fn,
            start_new_session=start_new_session, timeout_seconds=timeout_seconds,
            survive_parent_exit=survive_parent_exit, input_handler=input_handler,
            connection=connection,
        )


def _stream_subprocess(
    command: list[str],
    *,
    emit_log: EmitLog,
    cwd: Path | None = None,
    env: dict[str, str] | None = None,
    preexec_fn: Callable[[], None] | None = None,
    start_new_session: bool = False,
    timeout_seconds: float | None = None,
    survive_parent_exit: bool = False,
    input_handler: Callable[[str], str | None] | None = None,
    connection: _CommandConnection,
) -> tuple[int, list[str]]:
    collected: list[str] = []
    collected_bytes = 0
    emitted_bytes = 0
    output_truncated = False
    output_limit_exceeded = False
    pending_line = ""
    dropping_oversize_line = False
    master_fd = -1
    slave_fd = -1

    try:
        if connection.disconnected:
            return 130, []
        master_fd, slave_fd = pty.openpty()
        _set_terminal_size(slave_fd)

        def child_setup() -> None:
            if not survive_parent_exit:
                arm_parent_death_signal(signal.SIGTERM)
            if preexec_fn is not None:
                preexec_fn()

        proc = subprocess.Popen(
            command,
            cwd=cwd,
            env=env,
            stdin=subprocess.PIPE if input_handler is not None else subprocess.DEVNULL,
            stdout=slave_fd,
            stderr=subprocess.STDOUT,
            close_fds=True,
            preexec_fn=child_setup,
            start_new_session=start_new_session,
        )
    except OSError:
        for file_descriptor in (master_fd, slave_fd):
            if file_descriptor >= 0:
                try:
                    os.close(file_descriptor)
                except OSError:
                    pass
        raise
    finally:
        if slave_fd >= 0:
            try:
                os.close(slave_fd)
            except OSError:
                pass

    def close_disconnected_input() -> None:
        if connection.disconnected and proc.stdin is not None and not proc.stdin.closed:
            try:
                proc.stdin.close()
            except OSError:
                pass

    def flush_completed_lines(text: str) -> None:
        nonlocal pending_line, dropping_oversize_line
        normalized = _normalize_terminal_output(text)
        while normalized:
            line_fragment, separator, normalized = normalized.partition("\n")
            if not dropping_oversize_line:
                remaining = MAX_STREAM_LINE_CHARACTERS - len(pending_line)
                pending_line += line_fragment[: max(0, remaining)]
                if len(line_fragment) > remaining:
                    dropping_oversize_line = True
            if input_handler is not None and pending_line and not dropping_oversize_line:
                response = connection.request_input(input_handler, pending_line)
                close_disconnected_input()
                if response is not None and not connection.disconnected:
                    emit_stream_line(pending_line)
                    pending_line = ""
                    close_disconnected_input()
                    if not connection.disconnected:
                        assert proc.stdin is not None
                        try:
                            proc.stdin.write(response.encode("utf-8"))
                            proc.stdin.flush()
                        except BrokenPipeError:
                            # The child can exit while its last prompt is drained.
                            try:
                                proc.stdin.close()
                            except OSError:
                                pass
            if not separator:
                break
            emit_stream_line(pending_line + ("…" if dropping_oversize_line else ""))
            pending_line = ""
            dropping_oversize_line = False

    def emit_stream_line(line: str) -> None:
        nonlocal collected_bytes, emitted_bytes, output_truncated, output_limit_exceeded
        clean_line = line.rstrip()
        if len(clean_line) > MAX_STREAM_LINE_CHARACTERS:
            clean_line = clean_line[:MAX_STREAM_LINE_CHARACTERS] + "…"
        encoded_size = len(clean_line.encode("utf-8", errors="replace")) + 1
        if collected_bytes < MAX_COLLECTED_OUTPUT_BYTES:
            remaining = MAX_COLLECTED_OUTPUT_BYTES - collected_bytes
            if encoded_size <= remaining:
                collected.append(clean_line)
                collected_bytes += encoded_size
        if clean_line and emitted_bytes + encoded_size <= MAX_STREAM_LOG_BYTES:
            connection.log(emit_log, clean_line)
            emitted_bytes += encoded_size
        elif clean_line and not output_truncated:
            output_truncated = True
            # Bound memory/logging without interrupting a critical transaction.
            output_limit_exceeded = not survive_parent_exit
            if survive_parent_exit:
                # No further decisions can be reviewed through a suppressed log.
                # EOF declines pending prompts, but leaves an install running.
                connection.disconnected = True
            if output_limit_exceeded:
                connection.log(emit_log, QCoreApplication.translate(
                    "PrivilegedHelper",
                    "The command was terminated after exceeding the output safety limit.",
                ))

    deadline = None if timeout_seconds is None else time.monotonic() + timeout_seconds
    timed_out = False
    os.set_blocking(master_fd, False)
    try:
        while True:
            close_disconnected_input()
            if deadline is not None and time.monotonic() >= deadline:
                timed_out = True
                _terminate_process(proc, process_group=start_new_session)
                _drain_stream_output(master_fd, flush_completed_lines)
                break
            if proc.poll() is not None:
                _drain_stream_output(master_fd, flush_completed_lines)
                break

            wait_seconds = 0.1
            if deadline is not None:
                wait_seconds = min(wait_seconds, max(0.0, deadline - time.monotonic()))
            readable, _, _ = select.select([master_fd], [], [], wait_seconds)
            if master_fd not in readable:
                continue

            try:
                data = os.read(master_fd, 4096)
            except BlockingIOError:
                continue
            except OSError:
                if proc.poll() is None:
                    continue
                break
            if data:
                flush_completed_lines(data.decode("utf-8", errors="replace"))
                if output_limit_exceeded:
                    _terminate_process(proc, process_group=start_new_session)
                    _drain_stream_output(master_fd, flush_completed_lines)
                    break
    except BaseException:
        _terminate_process(proc, process_group=start_new_session)
        raise
    finally:
        if proc.stdin is not None:
            try:
                proc.stdin.close()
            except OSError:
                pass
        try:
            os.close(master_fd)
        except OSError:
            pass

    if pending_line.strip() or dropping_oversize_line:
        emit_stream_line(pending_line + ("…" if dropping_oversize_line else ""))

    return_code = proc.returncode if proc.returncode is not None else proc.wait()
    if start_new_session:
        _signal_process_group(proc.pid, signal.SIGTERM)
    if timed_out:
        return 124, collected
    if output_limit_exceeded:
        return 125, collected
    return return_code, collected


class _DisconnectedInput(Exception):
    """Interrupt a pending frontend answer without terminating the child."""


class _CommandConnection:
    """Keep the supervisor alive until a critical child has finished.

    SIGTERM/SIGINT and broken frontend pipes are deferred; normal commands retain
    their existing cancellation behavior. Only the main-thread helper installs
    process-wide signal handlers. The PTY and caller-owned workspaces stay alive
    until the stream has been drained and this context exits.
    """

    def __init__(self, critical: bool) -> None:
        self.critical = critical
        self.disconnected = False
        self._waiting_for_input = False
        self._signal: int | None = None
        self._pipe_error: BrokenPipeError | None = None
        self._handlers: dict[int, object] = {}

    def __enter__(self) -> _CommandConnection:
        if self.critical and threading.current_thread() is threading.main_thread():
            for signum in (signal.SIGTERM, signal.SIGINT):
                self._handlers[signum] = signal.signal(signum, self._disconnect)
        return self

    def __exit__(self, exc_type, _exc, _traceback) -> None:  # noqa: ANN001
        for signum, handler in self._handlers.items():
            signal.signal(signum, handler)
        if exc_type is None:
            if self._signal is not None:
                raise SystemExit(128 + self._signal)
            if self._pipe_error is not None:
                raise self._pipe_error

    def _disconnect(self, signum: int, _frame: object) -> None:
        self.disconnected = True
        self._signal = signum
        if self._waiting_for_input:
            raise _DisconnectedInput()

    def log(self, emit_log: EmitLog, line: str) -> None:
        if self.disconnected:
            return
        try:
            emit_log(line)
        except BrokenPipeError as exc:
            if not self.critical:
                raise
            self.disconnected = True
            self._pipe_error = exc

    def request_input(self, handler: Callable[[str], str | None], line: str) -> str | None:
        if self.disconnected:
            return None
        self._waiting_for_input = True
        try:
            return handler(line)
        except _DisconnectedInput:
            return None
        except BrokenPipeError as exc:
            if not self.critical:
                raise
            self.disconnected = True
            self._pipe_error = exc
            return None
        finally:
            self._waiting_for_input = False


def _terminate_process(process: subprocess.Popen[bytes], *, process_group: bool) -> None:
    if process.poll() is not None:
        return
    if process_group:
        _signal_process_group(process.pid, signal.SIGTERM)
    else:
        process.terminate()
    try:
        process.wait(timeout=2)
    except subprocess.TimeoutExpired:
        if process_group:
            _signal_process_group(process.pid, signal.SIGKILL)
        else:
            process.kill()
        try:
            process.wait(timeout=1)
        except subprocess.TimeoutExpired:
            pass


def _signal_process_group(pid: int, signum: int) -> None:
    try:
        os.killpg(pid, signum)
    except ProcessLookupError:
        return
    except OSError:
        return


def _drain_stream_output(file_descriptor: int, callback: Callable[[str], None]) -> None:
    while True:
        try:
            data = os.read(file_descriptor, 4096)
        except BlockingIOError:
            return
        except OSError:
            return
        if not data:
            return
        callback(data.decode("utf-8", errors="replace"))


def _normalize_terminal_output(text: str) -> str:
    return text.replace("\r\n", "\n").replace("\r", "\n")


def _set_terminal_size(file_descriptor: int, *, rows: int = 24, columns: int = 120) -> None:
    try:
        fcntl.ioctl(
            file_descriptor,
            termios.TIOCSWINSZ,
            struct.pack("HHHH", rows, columns, 0, 0),
        )
    except OSError:
        pass
