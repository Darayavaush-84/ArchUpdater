from __future__ import annotations

import os
import selectors
import signal
import subprocess
import time
from dataclasses import dataclass
from datetime import datetime

from archupdater.domain.command_log import CommandLogEntry
from archupdater.domain.errors import BackendError, BackendUnavailableError
from archupdater.process_lifecycle import arm_parent_death_signal


class CommandRunnerError(BackendError):
    def __init__(self, message: str, *, log_entry: CommandLogEntry | None = None) -> None:
        super().__init__(message)
        self.log_entry = log_entry


class CommandNotAvailableError(CommandRunnerError, BackendUnavailableError):
    pass


@dataclass(slots=True)
class CommandRunner:
    default_env: dict[str, str] | None = None
    default_timeout_seconds: float | None = 120
    max_output_bytes: int = 32 * 1024 * 1024
    termination_grace_seconds: float = 2
    kill_drain_seconds: float = 1

    def run(
        self,
        command: list[str],
        *,
        timeout_seconds: float | None = None,
        extra_env: dict[str, str] | None = None,
    ) -> CommandLogEntry:
        env = os.environ.copy()
        if self.default_env:
            env.update(self.default_env)
        if extra_env:
            env.update(extra_env)

        started_at = datetime.now()
        timeout = self.default_timeout_seconds if timeout_seconds is None else timeout_seconds
        process: subprocess.Popen[bytes] | None = None
        try:
            process = subprocess.Popen(
                command,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                env=env,
                start_new_session=True,
                preexec_fn=arm_parent_death_signal,
            )
        except FileNotFoundError as exc:
            raise CommandNotAvailableError(f"Command not available: {command[0]}") from exc
        except OSError as exc:
            raise CommandRunnerError(f"Could not start command {command[0]}: {exc}") from exc

        stdout, stderr, timed_out, output_limited = self._communicate_bounded(
            process,
            timeout=timeout,
        )

        exit_code = process.returncode if process.returncode is not None else process.wait()
        if timed_out:
            timeout_message = (
                f"Command timed out after {timeout:g} seconds." if timeout else "Command timed out."
            )
            stderr = f"{stderr.rstrip()}\n{timeout_message}" if stderr.strip() else timeout_message
            exit_code = -124
        elif output_limited:
            limit_message = f"Command output exceeded the {self.max_output_bytes}-byte safety limit."
            stderr = f"{stderr.rstrip()}\n{limit_message}" if stderr.strip() else limit_message
            exit_code = -125
        return CommandLogEntry(
            command=command,
            exit_code=exit_code,
            stdout=stdout,
            stderr=stderr,
            started_at=started_at,
            timed_out=timed_out,
        )

    def _communicate_bounded(
        self,
        process: subprocess.Popen[bytes],
        *,
        timeout: float | None,
    ) -> tuple[str, str, bool, bool]:
        stdout = bytearray()
        stderr = bytearray()
        total_bytes = 0
        timed_out = False
        output_limited = False
        deadline = None if timeout is None else time.monotonic() + timeout
        selector = selectors.DefaultSelector()
        assert process.stdout is not None and process.stderr is not None
        os.set_blocking(process.stdout.fileno(), False)
        os.set_blocking(process.stderr.fileno(), False)
        selector.register(process.stdout, selectors.EVENT_READ, stdout)
        selector.register(process.stderr, selectors.EVENT_READ, stderr)
        termination_deadline: float | None = None
        kill_drain_deadline: float | None = None

        def begin_group_termination() -> None:
            nonlocal termination_deadline
            if termination_deadline is not None:
                return
            self._signal_process_group(process.pid, signal.SIGTERM)
            termination_deadline = time.monotonic() + self.termination_grace_seconds

        def force_group_termination() -> None:
            nonlocal kill_drain_deadline
            self._signal_process_group(process.pid, signal.SIGKILL)
            if process.poll() is None:
                process.kill()
            kill_drain_deadline = time.monotonic() + self.kill_drain_seconds

        try:
            while selector.get_map() or process.poll() is None:
                now = time.monotonic()
                if deadline is not None and not timed_out and now >= deadline:
                    timed_out = True
                    begin_group_termination()
                if process.poll() is not None:
                    begin_group_termination()
                    if not selector.get_map() and kill_drain_deadline is None:
                        force_group_termination()
                if (
                    termination_deadline is not None
                    and kill_drain_deadline is None
                    and now >= termination_deadline
                ):
                    force_group_termination()
                if kill_drain_deadline is not None and now >= kill_drain_deadline:
                    break

                wait_seconds = 0.1
                if deadline is not None and not timed_out:
                    wait_seconds = min(wait_seconds, max(0.0, deadline - time.monotonic()))
                if termination_deadline is not None and kill_drain_deadline is None:
                    wait_seconds = min(
                        wait_seconds,
                        max(0.0, termination_deadline - time.monotonic()),
                    )
                if kill_drain_deadline is not None:
                    wait_seconds = min(
                        wait_seconds,
                        max(0.0, kill_drain_deadline - time.monotonic()),
                    )
                events = selector.select(wait_seconds)
                for key, _mask in events:
                    try:
                        chunk = os.read(key.fd, 64 * 1024)
                    except BlockingIOError:
                        continue
                    if not chunk:
                        selector.unregister(key.fileobj)
                        continue
                    total_bytes += len(chunk)
                    remaining = self.max_output_bytes - len(stdout) - len(stderr)
                    if remaining > 0:
                        key.data.extend(chunk[:remaining])
                    if total_bytes > self.max_output_bytes and not output_limited:
                        output_limited = True
                        begin_group_termination()
                if process.poll() is not None and termination_deadline is None:
                    begin_group_termination()
                if (
                    process.poll() is not None
                    and not selector.get_map()
                    and kill_drain_deadline is None
                ):
                    force_group_termination()
        finally:
            selector.close()
            process.stdout.close()
            process.stderr.close()
        if process.poll() is None:
            force_group_termination()
            try:
                process.wait(timeout=self.kill_drain_seconds)
            except subprocess.TimeoutExpired as exc:
                raise CommandRunnerError(
                    f"Could not terminate command {process.args[0]}."
                ) from exc
        return (
            stdout.decode("utf-8", errors="replace"),
            stderr.decode("utf-8", errors="replace"),
            timed_out,
            output_limited,
        )

    def _signal_process_group(self, pid: int, signum: int) -> None:
        try:
            os.killpg(pid, signum)
        except ProcessLookupError:
            return
        except OSError:
            return
