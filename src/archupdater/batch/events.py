from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path


@dataclass(slots=True)
class EventWriter:
    path: Path
    _bytes_written: int = field(default=0, init=False, repr=False)
    _logs_suppressed: bool = field(default=False, init=False, repr=False)
    _terminal_event_written: bool = field(default=False, init=False, repr=False)

    MAX_EVENT_BYTES = 24 * 1024 * 1024
    MAX_LOG_FILE_BYTES = 64 * 1024 * 1024
    MAX_EVENT_FILE_BYTES = 256 * 1024 * 1024
    MAX_TERMINAL_EVENT_BYTES = 1024 * 1024

    def __post_init__(self) -> None:
        try:
            self._bytes_written = self.path.stat().st_size
        except OSError:
            self._bytes_written = 0

    def emit(self, event_type: str, **payload: object) -> None:
        event = {"type": event_type, **payload}
        encoded = (json.dumps(event, ensure_ascii=False) + "\n").encode("utf-8")
        if len(encoded) > self.MAX_EVENT_BYTES:
            raise ValueError("Batch event exceeds the safety limit.")
        if event_type == "log" and self._bytes_written + len(encoded) > self.MAX_LOG_FILE_BYTES:
            if self._logs_suppressed:
                return
            self._logs_suppressed = True
            encoded = (
                json.dumps(
                    {
                        "type": "log",
                        "message": "Further event log output was suppressed after the safety limit.",
                    }
                )
                + "\n"
            ).encode("utf-8")
        terminal_event = event_type == "batch_completed"
        if self._bytes_written + len(encoded) > self.MAX_EVENT_FILE_BYTES:
            if (
                not terminal_event
                or self._terminal_event_written
                or len(encoded) > self.MAX_TERMINAL_EVENT_BYTES
            ):
                raise ValueError("Batch event file exceeds the safety limit.")
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(encoded.decode("utf-8"))
            handle.flush()
        self._bytes_written += len(encoded)
        self._terminal_event_written = self._terminal_event_written or terminal_event
