from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable


@dataclass
class FakePreflightEnvironment:
    available_commands: set[str] = field(
        default_factory=lambda: {
            "pacman",
            "pacman-conf",
            "checkupdates",
            "git",
            "makepkg",
            "pkexec",
            "flatpak",
            "fwupdmgr",
            "kpackagetool6",
        }
    )
    free_bytes: int = 100 * 1024**3
    home: Path = Path("/home/test-user")
    command_runner: Callable[[list[str], float], tuple[int, str, str]] | None = None
    command_calls: list[list[str]] = field(default_factory=list)
    disk_paths: list[Path] = field(default_factory=list)

    def command_available(self, command: str) -> bool:
        return command in self.available_commands

    def run_command(self, command: list[str], timeout_seconds: float) -> tuple[int, str, str]:
        self.command_calls.append(list(command))
        if self.command_runner is None:
            raise AssertionError(f"Unexpected command: {command}")
        return self.command_runner(command, timeout_seconds)

    def command_details(self, stdout: str, stderr: str) -> list[str]:
        return (stderr or stdout).strip().splitlines()

    def disk_space(self, path: Path) -> tuple[Path, int]:
        self.disk_paths.append(path)
        return path, self.free_bytes

    def home_dir(self) -> Path:
        return self.home
