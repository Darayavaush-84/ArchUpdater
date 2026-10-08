from __future__ import annotations

import json
import os
import tempfile
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path

from archupdater.domain.enums import UpdateProgressPhase, UpdateProgressStepState
from archupdater.domain.progress import UpdateProgressSnapshot, UpdateProgressStep


@dataclass(frozen=True, slots=True)
class SavedUpdate:
    completed_at: datetime
    snapshot: UpdateProgressSnapshot


class LastUpdateStore:
    MAX_BYTES = 64 * 1024 * 1024

    def __init__(self, path: Path | None = None) -> None:
        state_home = os.environ.get("XDG_STATE_HOME")
        root = Path(state_home) if state_home else Path.home() / ".local" / "state"
        self.path = path if path is not None else root / "archupdater" / "last-update.json"

    def load(self) -> SavedUpdate | None:
        try:
            with self.path.open("rb") as handle:
                raw = handle.read(self.MAX_BYTES + 1)
            if len(raw) > self.MAX_BYTES:
                return None
            payload = json.loads(raw)
            if not isinstance(payload, dict) or payload.get("schema_version") != 1:
                return None
            completed_at = datetime.fromisoformat(payload["completed_at"])
            if completed_at.tzinfo is None:
                return None
            return SavedUpdate(completed_at, self._decode_snapshot(payload["snapshot"]))
        except (OSError, ValueError, TypeError, KeyError):
            return None

    def save(
        self, snapshot: UpdateProgressSnapshot, *, completed_at: datetime | None = None,
    ) -> SavedUpdate:
        if not snapshot.final_state or type(snapshot.success) is not bool:
            raise ValueError("Only a finished update session can be saved.")
        completed_at = (completed_at or datetime.now().astimezone()).astimezone()
        payload = {
            "schema_version": 1,
            "completed_at": completed_at.isoformat(),
            "snapshot": asdict(snapshot),
        }
        try:
            saved = SavedUpdate(completed_at, self._decode_snapshot(payload["snapshot"]))
        except (TypeError, KeyError) as exc:
            raise ValueError("Invalid update snapshot.") from exc
        raw = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        if len(raw) > self.MAX_BYTES:
            raise ValueError("The last update session exceeds the size limit.")
        self.path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        temporary_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="wb", dir=self.path.parent, prefix=".last-update-", delete=False,
            ) as handle:
                temporary_path = Path(handle.name)
                handle.write(raw)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary_path, self.path)
        finally:
            if temporary_path is not None:
                temporary_path.unlink(missing_ok=True)
        return saved

    @staticmethod
    def _decode_snapshot(data: object) -> UpdateProgressSnapshot:
        if not isinstance(data, dict):
            raise ValueError("Invalid update snapshot.")
        snapshot = UpdateProgressSnapshot(**data)
        if snapshot.final_state is not True or type(snapshot.success) is not bool:
            raise ValueError("Unfinished update snapshot.")
        if type(snapshot.cancelled) is not bool or type(snapshot.present_dialog) is not bool:
            raise ValueError("Invalid update flags.")
        for value in (snapshot.title, snapshot.subtitle):
            if not isinstance(value, str):
                raise ValueError("Invalid update text.")
        for value in (
            snapshot.notice_title, snapshot.notice_text, snapshot.summary_title,
            snapshot.summary_next_step, snapshot.activity_text,
        ):
            if value is not None and not isinstance(value, str):
                raise ValueError("Invalid optional update text.")
        for value in (
            snapshot.console_lines, snapshot.summary_completed, snapshot.summary_incomplete,
            snapshot.summary_failed, snapshot.summary_not_executed,
        ):
            if not isinstance(value, list) or not all(isinstance(line, str) for line in value):
                raise ValueError("Invalid update summary or log.")
        if type(snapshot.percent) is not int or not 0 <= snapshot.percent <= 100:
            raise ValueError("Invalid update percentage.")
        if snapshot.activity_percent is not None and (
            type(snapshot.activity_percent) is not int or not 0 <= snapshot.activity_percent <= 100
        ):
            raise ValueError("Invalid activity percentage.")
        if snapshot.current_phase is not None:
            snapshot.current_phase = UpdateProgressPhase(snapshot.current_phase)
        if not isinstance(snapshot.steps, list):
            raise ValueError("Invalid update steps.")
        steps = []
        for data_step in snapshot.steps:
            step = UpdateProgressStep(**data_step)
            step.phase = UpdateProgressPhase(step.phase)
            step.state = UpdateProgressStepState(step.state)
            if (
                not isinstance(step.label, str)
                or not isinstance(step.log_lines, list)
                or not all(isinstance(line, str) for line in step.log_lines)
            ):
                raise ValueError("Invalid update step.")
            steps.append(step)
        snapshot.steps = steps
        return snapshot
