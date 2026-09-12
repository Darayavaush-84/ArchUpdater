from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from archupdater.infrastructure.autostart import AutostartService


class AutostartServiceTests(unittest.TestCase):
    def test_enabling_writes_private_regular_desktop_entry(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            service = AutostartService()
            service._desktop_entry_path = Path(tmp) / "autostart" / service.DESKTOP_FILE_NAME

            service.set_enabled(True)

            self.assertTrue(service.is_enabled())
            self.assertIn("--start-hidden", service._desktop_entry_path.read_text(encoding="utf-8"))
            self.assertEqual(service._desktop_entry_path.stat().st_mode & 0o777, 0o600)

    def test_symlinked_desktop_entry_is_never_followed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            target = root / "target"
            target.write_text("keep", encoding="utf-8")
            service = AutostartService()
            service._desktop_entry_path = root / service.DESKTOP_FILE_NAME
            service._desktop_entry_path.symlink_to(target)

            with self.assertRaisesRegex(OSError, "symlinked"):
                service.set_enabled(True)

            self.assertEqual(target.read_text(encoding="utf-8"), "keep")
            self.assertFalse(service.is_enabled())


if __name__ == "__main__":
    unittest.main()
