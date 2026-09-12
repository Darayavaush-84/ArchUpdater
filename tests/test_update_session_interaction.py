from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from archupdater.application.update_session.interaction import BatchInteractionController
from archupdater.application.update_session.errors import BatchCancelled
from archupdater.application.update_session.protocol import BatchEventType


class BatchInteractionControllerTests(unittest.TestCase):
    def test_question_request_ignores_other_question_responses(self) -> None:
        emitted: list[tuple[str, dict[str, object]]] = []
        lines = iter(
            [
                '{"type": "question_response", "question_id": "other", "response": "1"}\n',
                '{"type": "question_response", "question_id": "question-1", "response": "2"}\n',
            ]
        )
        controller = BatchInteractionController(
            emit_event=lambda event_type, **payload: emitted.append((event_type, payload)),
            read_line=lambda: next(lines),
            request_id_factory=lambda: "question-1",
        )

        response = controller.request_question({"message": "Choose"})

        self.assertEqual(response, "2")
        self.assertEqual(emitted[0][0], BatchEventType.QUESTION_REQUESTED.value)
        self.assertEqual(emitted[0][1]["question_id"], "question-1")

    def test_cancel_control_message_raises_batch_cancelled(self) -> None:
        controller = BatchInteractionController(
            emit_event=lambda _event_type, **_payload: None,
            read_line=lambda: '{"type": "cancel"}\n',
        )

        with self.assertRaises(BatchCancelled):
            controller.request_question({"message": "Choose"})


if __name__ == "__main__":
    unittest.main()
