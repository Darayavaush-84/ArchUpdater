from __future__ import annotations

import os
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path


@dataclass(slots=True)
class SessionLog:
    path: Path | None
    _bytes_written: int = field(default=0, init=False, repr=False)
    _truncated: bool = field(default=False, init=False, repr=False)

    MAX_BYTES = 16 * 1024 * 1024
    MAX_LINE_CHARACTERS = 16 * 1024

    @classmethod
    def create(cls, *, now: datetime | None = None) -> SessionLog:
        timestamp = (now or datetime.now()).strftime("%Y-%m-%d_%H-%M-%S_%f")
        directory = _cache_home() / "archupdater" / "logs"
        try:
            directory.mkdir(parents=True, exist_ok=True)
            directory.chmod(0o700)
            path = directory / f"{timestamp}.log"
            path.touch(exist_ok=False)
            path.chmod(0o600)
        except OSError:
            return cls(None)
        return cls(path)

    def write_line(self, text: str) -> None:
        if self.path is None or self._truncated:
            return
        rendered = text[: self.MAX_LINE_CHARACTERS]
        if len(text) > self.MAX_LINE_CHARACTERS:
            rendered += "…"
        encoded_size = len(rendered.encode("utf-8", errors="replace")) + 1
        if self._bytes_written + encoded_size > self.MAX_BYTES:
            rendered = "Further session output was suppressed after the safety limit."
            self._truncated = True
            encoded_size = len(rendered.encode("utf-8")) + 1
        try:
            with self.path.open("a", encoding="utf-8") as handle:
                handle.write(f"{rendered}\n")
            self._bytes_written += encoded_size
        except OSError:
            pass


def _cache_home() -> Path:
    configured = os.environ.get("XDG_CACHE_HOME")
    if configured:
        return Path(configured).expanduser()
    return Path.home() / ".cache"
