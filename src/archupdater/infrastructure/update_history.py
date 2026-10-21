from __future__ import annotations

import json
import os
import tempfile
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path

from archupdater.domain.enums import (
    UpdatePackageOutcome, UpdateProgressPhase, UpdateProgressStepState, UpdateSource,
)
from archupdater.domain.progress import (
    UpdateProgressPackage, UpdateProgressSnapshot, UpdateProgressStep,
)


@dataclass(frozen=True, slots=True)
class SavedUpdate:
    completed_at: datetime
    snapshot: UpdateProgressSnapshot


class UpdateHistoryStore:
    MAX_ENTRIES = 5
    MAX_BYTES = 64 * 1024 * 1024

    def __init__(self, path: Path | None = None) -> None:
        state_home = os.environ.get("XDG_STATE_HOME")
        root = Path(state_home) if state_home else Path.home() / ".local" / "state"
        self.path = path if path is not None else root / "archupdater" / "update-history.json"
        # Versions up to 1.1.1 kept only the latest session in this file.
        self.legacy_path = self.path.with_name("last-update.json")

    def load(self) -> list[SavedUpdate]:
        """Return the saved sessions, newest first."""
        try:
            payload = self._read_json(self.path)
        except FileNotFoundError:
            return self._load_legacy()
        except (OSError, ValueError):
            return []
        if not isinstance(payload, dict) or payload.get("schema_version") != 1:
            return []
        entries = payload.get("entries")
        if not isinstance(entries, list):
            return []
        history = []
        for entry in entries[: self.MAX_ENTRIES]:
            try:
                history.append(self._decode_entry(entry))
            except (ValueError, TypeError, KeyError):
                continue
        return history

    def save(
        self, snapshot: UpdateProgressSnapshot, *, completed_at: datetime | None = None,
    ) -> list[SavedUpdate]:
        if not snapshot.final_state or type(snapshot.success) is not bool:
            raise ValueError("Only a finished update session can be saved.")
        completed_at = (completed_at or datetime.now().astimezone()).astimezone()
        history = self.load()
        # A finished session is saved again when messages are added to its log afterwards.
        same_session = next(
            (
                index for index, entry in enumerate(history)
                if snapshot.session_id and entry.snapshot.session_id == snapshot.session_id
            ),
            None,
        )
        if same_session is not None:
            completed_at = history[same_session].completed_at
        try:
            saved = self._decode_entry(self._encode_entry(SavedUpdate(completed_at, snapshot)))
        except (TypeError, KeyError) as exc:
            raise ValueError("Invalid update snapshot.") from exc
        if same_session is not None:
            history[same_session] = saved
        else:
            history = [saved, *history][: self.MAX_ENTRIES]
        raw = self._serialize(history)
        while len(raw) > self.MAX_BYTES and len(history) > 1:
            history.pop()
            raw = self._serialize(history)
        if len(raw) > self.MAX_BYTES:
            raise ValueError("The update session exceeds the size limit.")
        self.path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        temporary_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="wb", dir=self.path.parent, prefix=".update-history-", delete=False,
            ) as handle:
                temporary_path = Path(handle.name)
                handle.write(raw)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary_path, self.path)
        finally:
            if temporary_path is not None:
                temporary_path.unlink(missing_ok=True)
        try:
            self.legacy_path.unlink(missing_ok=True)
        except OSError:
            pass
        return history

    def _load_legacy(self) -> list[SavedUpdate]:
        try:
            payload = self._read_json(self.legacy_path)
            if not isinstance(payload, dict) or payload.get("schema_version") != 1:
                return []
            return [self._decode_entry(payload)]
        except (OSError, ValueError, TypeError, KeyError):
            return []

    def _read_json(self, path: Path) -> object:
        with path.open("rb") as handle:
            raw = handle.read(self.MAX_BYTES + 1)
        if len(raw) > self.MAX_BYTES:
            raise ValueError("The update history exceeds the size limit.")
        return json.loads(raw)

    def _serialize(self, history: list[SavedUpdate]) -> bytes:
        payload = {
            "schema_version": 1,
            "entries": [self._encode_entry(entry) for entry in history],
        }
        return json.dumps(payload, ensure_ascii=False).encode("utf-8")

    @staticmethod
    def _encode_entry(entry: SavedUpdate) -> dict[str, object]:
        return {
            "completed_at": entry.completed_at.isoformat(),
            "snapshot": asdict(entry.snapshot),
        }

    @classmethod
    def _decode_entry(cls, data: object) -> SavedUpdate:
        if not isinstance(data, dict):
            raise ValueError("Invalid update history entry.")
        completed_at = datetime.fromisoformat(data["completed_at"])
        if completed_at.tzinfo is None:
            raise ValueError("Update completion time has no time zone.")
        return SavedUpdate(completed_at, cls._decode_snapshot(data["snapshot"]))

    @staticmethod
    def _decode_snapshot(data: object) -> UpdateProgressSnapshot:
        if not isinstance(data, dict):
            raise ValueError("Invalid update snapshot.")
        snapshot = UpdateProgressSnapshot(**data)
        if snapshot.final_state is not True or type(snapshot.success) is not bool:
            raise ValueError("Unfinished update snapshot.")
        if type(snapshot.cancelled) is not bool or type(snapshot.present_dialog) is not bool:
            raise ValueError("Invalid update flags.")
        for value in (snapshot.title, snapshot.subtitle, snapshot.session_id):
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
        if not isinstance(snapshot.packages, list):
            raise ValueError("Invalid updated packages.")
        packages = []
        for data_package in snapshot.packages:
            package = UpdateProgressPackage(**data_package)
            package.source = UpdateSource(package.source)
            if package.outcome is not None:
                package.outcome = UpdatePackageOutcome(package.outcome)
            if not all(
                isinstance(value, str)
                for value in (
                    package.name, package.current_version, package.new_version, package.scope,
                )
            ):
                raise ValueError("Invalid updated package.")
            packages.append(package)
        snapshot.packages = packages
        return snapshot
