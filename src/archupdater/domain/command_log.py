from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(slots=True)
class CommandLogEntry:
    command: list[str]
    exit_code: int
    stdout: str
    stderr: str
    started_at: datetime
    timed_out: bool = False


CheckLogEntry = CommandLogEntry | str
