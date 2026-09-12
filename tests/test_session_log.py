from __future__ import annotations

import sys
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from archupdater.services.session_log import SessionLog


class SessionLogTests(unittest.TestCase):
    def test_creates_session_log_under_xdg_cache_home(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            with patch.dict("os.environ", {"XDG_CACHE_HOME": directory}):
                log = SessionLog.create(now=datetime(2026, 5, 20, 14, 30, 1, 123456))

            log.write_line("ArchUpdater batch started.")

            self.assertEqual(
                log.path,
                Path(directory) / "archupdater" / "logs" / "2026-05-20_14-30-01_123456.log",
            )
            self.assertEqual(log.path.read_text(encoding="utf-8"), "ArchUpdater batch started.\n")

    def test_logging_failure_does_not_prevent_update_session_from_starting(self) -> None:
        with patch("archupdater.services.session_log.Path.mkdir", side_effect=PermissionError):
            log = SessionLog.create()

        self.assertIsNone(log.path)
        log.write_line("This must remain non-fatal.")


if __name__ == "__main__":
    unittest.main()
