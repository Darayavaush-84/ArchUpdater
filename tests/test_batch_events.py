from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from archupdater.batch.events import EventWriter


class EventWriterTests(unittest.TestCase):
    def test_nonterminal_event_cannot_grow_file_past_limit(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "events.jsonl"
            path.write_text("x" * 59 + "\n", encoding="utf-8")
            writer = EventWriter(path)

            with (
                patch.object(EventWriter, "MAX_EVENT_FILE_BYTES", 64),
                self.assertRaisesRegex(ValueError, "file exceeds"),
            ):
                writer.emit("progress", message="too large")

    def test_one_bounded_completion_event_is_reserved_after_file_limit(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "events.jsonl"
            path.write_text("x" * 63 + "\n", encoding="utf-8")
            writer = EventWriter(path)

            with patch.object(EventWriter, "MAX_EVENT_FILE_BYTES", 64):
                writer.emit("batch_completed", success=False, message="limited")
                with self.assertRaisesRegex(ValueError, "file exceeds"):
                    writer.emit("batch_completed", success=False, message="duplicate")

            payload = json.loads(path.read_text(encoding="utf-8").splitlines()[-1])
            self.assertEqual(payload["type"], "batch_completed")
            self.assertFalse(payload["success"])


if __name__ == "__main__":
    unittest.main()
