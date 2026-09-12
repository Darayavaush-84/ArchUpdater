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
    duration_ms: int
    timed_out: bool = False

    def to_text(self) -> str:
        parts = [
            f"[{self.started_at.strftime('%H:%M:%S')}] $ {' '.join(self.command)}",
            f"exit={self.exit_code} duration={self.duration_ms}ms",
        ]
        if self.timed_out:
            parts.append("timed out")
        if self.stdout.strip():
            parts.append(self.stdout.rstrip())
        if self.stderr.strip():
            parts.append("--- stderr ---")
            parts.append(self.stderr.rstrip())
        return "\n".join(parts)


CheckLogEntry = CommandLogEntry | str
