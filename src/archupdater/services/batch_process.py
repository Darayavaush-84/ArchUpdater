from __future__ import annotations

import os
import pty
import select
import signal
import subprocess
import time
from collections.abc import Callable
from archupdater.domain.process_result import CommandProcessResult
from archupdater.process_lifecycle import arm_parent_death_signal


class BatchProcessRunner:
    NONINTERACTIVE_TIMEOUT_SECONDS = 30 * 60
    MAX_LINE_CHARACTERS = 16 * 1024
    MAX_LOG_OUTPUT_BYTES = 8 * 1024 * 1024
    MAX_COMBINED_OUTPUT_BYTES = 2 * 1024 * 1024

    def __init__(
        self,
        *,
        print_line: Callable[[str], None],
        emit_log: Callable[[str], None],
        translate: Callable[[str], str],
    ) -> None:
        self._print_line = print_line
        self._emit_log = emit_log
        self._t = translate

    def run_process(
        self,
        command: list[str],
        *,
        extra_env: dict[str, str] | None = None,
    ) -> CommandProcessResult:
        combined_output: list[str] = []
        combined_output_bytes = 0
        emitted_output_bytes = 0
        output_suppressed = False
        pending_line = ""
        dropping_oversize_line = False
        master_fd = -1
        slave_fd = -1
        try:
            master_fd, slave_fd = pty.openpty()
            env = os.environ.copy()
            if extra_env:
                env.update(extra_env)
            process = subprocess.Popen(
                command,
                stdin=subprocess.DEVNULL,
                stdout=slave_fd,
                stderr=subprocess.STDOUT,
                env=env,
                start_new_session=True,
                preexec_fn=arm_parent_death_signal,
            )
        except OSError as exc:
            for file_descriptor in (master_fd, slave_fd):
                if file_descriptor >= 0:
                    try:
                        os.close(file_descriptor)
                    except OSError:
                        pass
            return CommandProcessResult(False, 1, str(exc))
        finally:
            if slave_fd >= 0:
                try:
                    os.close(slave_fd)
                except OSError:
                    pass

        def flush_completed_lines(text: str) -> None:
            nonlocal pending_line, dropping_oversize_line
            normalized = text.replace("\r\n", "\n").replace("\r", "\n")
            while normalized:
                fragment, separator, normalized = normalized.partition("\n")
                if not dropping_oversize_line:
                    remaining = self.MAX_LINE_CHARACTERS - len(pending_line)
                    pending_line += fragment[: max(0, remaining)]
                    if len(fragment) > remaining:
                        dropping_oversize_line = True
                if not separator:
                    break
                emit_process_line(pending_line + ("…" if dropping_oversize_line else ""))
                pending_line = ""
                dropping_oversize_line = False

        def emit_process_line(line: str) -> None:
            nonlocal combined_output_bytes, emitted_output_bytes, output_suppressed
            encoded_size = len(line.encode("utf-8", errors="replace")) + 1
            if combined_output_bytes + encoded_size <= self.MAX_COMBINED_OUTPUT_BYTES:
                combined_output.append(line)
                combined_output_bytes += encoded_size
            if emitted_output_bytes + encoded_size <= self.MAX_LOG_OUTPUT_BYTES:
                self._print_line(line)
                if line:
                    self._emit_log(line)
                emitted_output_bytes += encoded_size
            elif not output_suppressed:
                output_suppressed = True
                marker = self._t("Further command output was suppressed after the safety limit.")
                self._print_line(marker)
                self._emit_log(marker)

        deadline = time.monotonic() + self.NONINTERACTIVE_TIMEOUT_SECONDS
        os.set_blocking(master_fd, False)
        try:
            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    self._terminate_process(process)
                    self._drain_stream_output(master_fd, flush_completed_lines)
                    if pending_line.strip() or dropping_oversize_line:
                        emit_process_line(
                            pending_line.rstrip() + ("…" if dropping_oversize_line else "")
                        )
                    self._close_process_pipes(process)
                    return CommandProcessResult(
                        False,
                        124,
                        self._t("Update command timed out."),
                    )

                readable, _, _ = select.select([master_fd], [], [], min(0.1, remaining))
                if master_fd in readable:
                    try:
                        data = os.read(master_fd, 4096)
                    except BlockingIOError:
                        data = b""
                    except OSError:
                        if process.poll() is None:
                            time.sleep(0.02)
                            continue
                        break
                    if data:
                        flush_completed_lines(data.decode("utf-8", errors="replace"))
                    elif process.poll() is not None:
                        break

                if process.poll() is not None:
                    self._drain_stream_output(master_fd, flush_completed_lines)
                    break
        finally:
            try:
                os.close(master_fd)
            except OSError:
                pass
            self._close_process_pipes(process)

        if pending_line.strip() or dropping_oversize_line:
            emit_process_line(pending_line.rstrip() + ("…" if dropping_oversize_line else ""))

        return_code = process.returncode if process.returncode is not None else process.wait()
        output = "\n".join(combined_output)
        return CommandProcessResult(return_code == 0, return_code, output)

    def _terminate_process(self, process: subprocess.Popen[bytes]) -> None:
        if process.poll() is not None:
            return
        self._signal_process(process, signal.SIGTERM)
        try:
            process.wait(timeout=2)
        except subprocess.TimeoutExpired:
            self._signal_process(process, signal.SIGKILL)
            try:
                process.wait(timeout=1)
            except subprocess.TimeoutExpired:
                pass

    def _signal_process(
        self,
        process: subprocess.Popen[bytes],
        signum: int,
    ) -> None:
        if isinstance(process, subprocess.Popen):
            try:
                os.killpg(process.pid, signum)
                return
            except ProcessLookupError:
                process.poll()
                return
            except OSError:
                try:
                    process.send_signal(signum)
                except ProcessLookupError:
                    process.poll()
                return

        # Test doubles and protocol-compatible process objects.
        if signum == signal.SIGTERM:
            process.terminate()  # type: ignore[attr-defined]
        else:
            process.kill()  # type: ignore[attr-defined]

    def _close_process_pipes(self, process: subprocess.Popen[str]) -> None:
        for stream in (process.stdin, process.stdout, process.stderr):
            if stream is not None:
                stream.close()

    def _drain_stream_output(self, file_descriptor: int, callback: Callable[[str], None]) -> None:
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
