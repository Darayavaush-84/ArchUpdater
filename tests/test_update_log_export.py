from __future__ import annotations

import sys
import json
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from archupdater.domain.progress import UpdateProgressSnapshot
from archupdater.presentation.update_log_export import (
    RuntimeExportInfo,
    write_update_log_export,
)


class _FixedDatetime(datetime):
    @classmethod
    def now(cls, tz=None):  # noqa: ANN001, ANN206
        return cls(2026, 7, 23, 12, 0, 0, 123456, tzinfo=tz)


class UpdateLogExportTests(unittest.TestCase):
    def test_text_and_manifest_agree_on_partial_cancelled_and_running_results(self) -> None:
        runtime = RuntimeExportInfo("3.12", "6.11", "test")
        for flags, expected, success in (
            ({"final_state": True, "success": True}, "success", True),
            ({"final_state": True, "success": True, "summary_failed": ["AUR"],
              "summary_completed": ["System"]}, "partial_success", False),
            ({"final_state": True, "success": False}, "failed", False),
            ({"final_state": True, "success": False, "cancelled": True}, "cancelled", False),
            ({"final_state": False}, "in_progress", None),
        ):
            with self.subTest(result=expected), tempfile.TemporaryDirectory() as directory:
                snapshot = UpdateProgressSnapshot("Session", "", [], 0, **flags)
                path = write_update_log_export(
                    folder=Path(directory), snapshot=snapshot, runtime=runtime,
                )
                with zipfile.ZipFile(path) as archive:
                    manifest = json.loads(archive.read("manifest.json"))
                    self.assertEqual(manifest["session"]["result"], expected)
                    self.assertIs(manifest["session"]["success"], success)
                    self.assertIn(
                        f"Result: {expected}\n", archive.read("update-session.log").decode(),
                    )

    def test_export_refuses_to_overwrite_an_existing_archive(self) -> None:
        snapshot = UpdateProgressSnapshot("Done", "Completed", [], 100, success=True)
        runtime = RuntimeExportInfo("3.12", "6.8", "test")

        with tempfile.TemporaryDirectory() as directory, patch(
            "archupdater.presentation.update_log_export.datetime",
            _FixedDatetime,
        ):
            folder = Path(directory)
            first = write_update_log_export(
                folder=folder,
                snapshot=snapshot,
                runtime=runtime,
            )
            original = first.read_bytes()

            with self.assertRaises(FileExistsError):
                write_update_log_export(
                    folder=folder,
                    snapshot=snapshot,
                    runtime=runtime,
                )

            self.assertEqual(first.read_bytes(), original)

    def test_failed_export_removes_only_its_partial_archive(self) -> None:
        snapshot = UpdateProgressSnapshot("Done", "Completed", [], 100, success=False)
        runtime = RuntimeExportInfo("3.12", "6.11", "test")

        with (
            tempfile.TemporaryDirectory() as directory,
            patch(
                "archupdater.presentation.update_log_export.datetime",
                _FixedDatetime,
            ),
            patch.object(zipfile.ZipFile, "writestr", side_effect=OSError("disk full")),
        ):
            folder = Path(directory)
            with self.assertRaisesRegex(OSError, "disk full"):
                write_update_log_export(
                    folder=folder,
                    snapshot=snapshot,
                    runtime=runtime,
                )
            self.assertEqual(list(folder.iterdir()), [])


if __name__ == "__main__":
    unittest.main()
