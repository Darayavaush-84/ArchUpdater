from __future__ import annotations

import json
import re
import sys
import uuid
from collections.abc import Callable

from PySide6.QtCore import QCoreApplication

from archupdater.application.helper_protocol import HelperEventType
from archupdater.helper.actions.pacman_transaction import PacmanTransactionPreview
from archupdater.helper.actions.common import EmitEvent, EmitLog


_YES_NO = re.compile(r"^(?P<message>.+?)\s+\[(?:Y/n|y/N)\]\s*$")
_DEFAULT_SELECTION = re.compile(r"^Enter a (?:number \(default=1\)|selection \(default=all\)):\s*$")
_ANSI = re.compile(r"\x1b\[[0-9;?]*[ -/]*[@-~]")
_AUTOMATIC_CONFIRMATIONS = frozenset({
    "Proceed with installation?",
    "Proceed with download?",
})


class PacmanPromptHandler:
    """Relay decisions to the GUI; only the already requested install is automatic."""

    def __init__(
        self,
        *,
        emit_event: EmitEvent,
        emit_log: EmitLog,
        read_line: Callable[[int], str] | None = None,
        expected_versions: dict[str, str] | None = None,
    ) -> None:
        self._emit_event = emit_event
        self._emit_log = emit_log
        self._read_line = read_line or sys.stdin.readline
        self.transaction_declined = False
        self._expected_versions = expected_versions
        self._preview = PacmanTransactionPreview()

    def observe_output(self, line: str) -> None:
        self._preview.observe(line)
        self._emit_log(line)

    def __call__(self, pending_line: str) -> str | None:
        text = _ANSI.sub("", pending_line).strip()
        if _DEFAULT_SELECTION.fullmatch(text):
            return "\n"
        match = _YES_NO.fullmatch(text)
        if match is None:
            return None
        message = match["message"].removeprefix(":: ").strip()
        if message in _AUTOMATIC_CONFIRMATIONS:
            if self._expected_versions is None or self._preview.versions() == self._expected_versions:
                return "y\n"
            if self._preview.truncated or not self._preview.lines:
                self.transaction_declined = True
                self._emit_log("Could not verify the final pacman transaction summary; installation declined.")
                return "n\n"
            accepted = self._request_confirmation(
                QCoreApplication.translate(
                    "BatchUpdateRunner",
                    "The available transaction changed after the original review. Review the new versions before continuing.",
                ),
                details=self._preview.details(),
            )
            self.transaction_declined = not accepted
            return "y\n" if accepted else "n\n"
        accepted = self._request_confirmation(message)
        self._emit_log(f"Pacman: {message} {'Yes' if accepted else 'No'}")
        return "y\n" if accepted else "n\n"

    def _request_confirmation(self, message: str, *, details: str = "") -> bool:
        question_id = str(uuid.uuid4())
        self._emit_event(
            HelperEventType.QUESTION,
            question_type="pacman_confirmation",
            question_id=question_id,
            message=message,
            **({"details": details} if details else {}),
        )
        raw = self._read_line(4097)
        if not raw or len(raw) > 4096:
            return False
        try:
            response = json.loads(raw)
        except (ValueError, TypeError):
            return False
        return (
            isinstance(response, dict)
            and set(response) == {"question_id", "response"}
            and response["question_id"] == question_id
            and response["response"] is True
        )
