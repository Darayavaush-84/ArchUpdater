from __future__ import annotations

from collections.abc import Callable
import json
import sys
import uuid

from archupdater.application.update_session.errors import BatchCancelled
from archupdater.application.update_session.protocol import BatchControlType, BatchEventType


class BatchInteractionController:
    def __init__(
        self,
        *,
        emit_event: Callable[..., None],
        read_line: Callable[[], str] = sys.stdin.readline,
        request_id_factory: Callable[[], str] | None = None,
    ) -> None:
        self._emit = emit_event
        self._read_line = read_line
        self._request_id_factory = request_id_factory or (lambda: str(uuid.uuid4()))

    @classmethod
    def from_event_writer(cls, events) -> BatchInteractionController:  # noqa: ANN001
        return cls(
            emit_event=lambda event_type, **payload: events.emit(event_type, **payload)  # type: ignore[misc]
        )

    def request_question(self, payload: dict[str, object]) -> object | None:
        question_id = str(payload.get("question_id") or self._request_id_factory())
        self._emit(
            BatchEventType.QUESTION_REQUESTED.value,
            **{**payload, "question_id": question_id},
        )
        while True:
            response = self._read_control_message()
            if response.get("type") == BatchControlType.CANCEL.value:
                raise BatchCancelled()
            if response.get("type") != BatchControlType.QUESTION_RESPONSE.value:
                continue
            if response.get("question_id") != question_id:
                continue
            if response.get("cancelled"):
                return None
            return response.get("response")

    def _read_control_message(self) -> dict[str, object]:
        line = self._read_line()
        if not line:
            raise BatchCancelled()
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            return {}
        return payload if isinstance(payload, dict) else {}
