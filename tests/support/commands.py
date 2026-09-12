from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from datetime import datetime
from typing import Iterable

from archupdater.domain.command_log import CommandLogEntry


@dataclass(frozen=True)
class CommandResponse:
    exit_code: int = 0
    stdout: str = ""
    stderr: str = ""


class FakeCommandRunner:
    """Consume explicit responses, record calls, and reject unexpected commands."""

    def __init__(self, responses: Iterable[CommandResponse] = ()) -> None:
        self.responses = deque(responses)
        self.commands: list[list[str]] = []
        self.timeouts: list[float | None] = []
        self.environments: list[dict[str, str] | None] = []

    def run(
        self,
        command: list[str],
        *,
        timeout_seconds: float | None = None,
        extra_env: dict[str, str] | None = None,
    ) -> CommandLogEntry:
        self.commands.append(list(command))
        self.timeouts.append(timeout_seconds)
        self.environments.append(extra_env)
        if not self.responses:
            raise AssertionError(f"Unexpected command: {command}")
        result = self.responses.popleft()
        return CommandLogEntry(
            command=list(command),
            exit_code=result.exit_code,
            stdout=result.stdout,
            stderr=result.stderr,
            started_at=datetime(2026, 1, 1),
        )
