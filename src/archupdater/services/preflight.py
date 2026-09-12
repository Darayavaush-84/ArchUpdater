from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from archupdater.services.command_runner import (
    CommandNotAvailableError,
    CommandRunner,
    CommandRunnerError,
)


PreflightCommandRunner = Callable[[list[str], float], tuple[int, str, str]]
Translate = Callable[[str], str]


@dataclass(slots=True)
class SystemPreflightEnvironment:
    command_runner: PreflightCommandRunner | None = None
    translate: Translate = lambda text: text

    def command_available(self, command: str) -> bool:
        return shutil.which(command) is not None

    def run_command(self, command: list[str], timeout_seconds: float) -> tuple[int, str, str]:
        if self.command_runner is not None:
            return self.command_runner(command, timeout_seconds)
        try:
            completed = CommandRunner(
                default_env={"LC_ALL": "C.UTF-8"},
                default_timeout_seconds=timeout_seconds,
                max_output_bytes=1024 * 1024,
            ).run(
                command,
                timeout_seconds=timeout_seconds,
            )
        except CommandNotAvailableError:
            return 127, "", self._t("Command not found: {command}").format(command=command[0])
        except CommandRunnerError as exc:
            return 1, "", str(exc)
        return completed.exit_code, completed.stdout, completed.stderr

    def command_details(self, stdout: str, stderr: str) -> list[str]:
        lines = [
            line.strip()
            for line in (stderr or stdout).splitlines()
            if line.strip()
        ]
        if len(lines) > 8:
            return [*lines[:4], "...", *lines[-3:]]
        return lines

    def disk_space(self, path: Path) -> tuple[Path, int] | None:
        existing_path = self._existing_parent(path)
        try:
            usage = shutil.disk_usage(existing_path)
        except OSError:
            return None
        return existing_path, usage.free

    def home_dir(self) -> Path:
        return Path.home()

    def _existing_parent(self, path: Path) -> Path:
        candidate = path.expanduser()
        while not candidate.exists() and candidate.parent != candidate:
            candidate = candidate.parent
        return candidate

    def _t(self, text: str) -> str:
        return self.translate(text)
