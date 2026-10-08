from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import Mock, patch
from zipfile import ZipFile

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QWidget

from archupdater.domain.enums import UpdateProgressPhase, UpdateProgressStepState, UpdateResult
from archupdater.domain.progress import UpdateProgressSnapshot, UpdateProgressStep
from archupdater.infrastructure.last_update import LastUpdateStore
from archupdater.infrastructure.settings import AppSettings
from archupdater.presentation.update_progress_presenter import UpdateProgressPresenter


def finished_snapshot() -> UpdateProgressSnapshot:
    return UpdateProgressSnapshot(
        title="Updates completed with issues", subtitle="One source failed", percent=0,
        steps=[
            UpdateProgressStep(
                UpdateProgressPhase.SYSTEM, "System", UpdateProgressStepState.COMPLETED,
                ["Updated linux 6.18 → 6.19"],
            ),
            UpdateProgressStep(
                UpdateProgressPhase.AUR, "AUR", UpdateProgressStepState.FAILED,
                ["error: build failed"],
            ),
        ],
        console_lines=["Updated linux 6.18 → 6.19", "error: build failed"],
        present_dialog=True, final_state=True, success=False,
        summary_title="Result", summary_completed=["System"], summary_failed=["AUR"],
        summary_not_executed=["Flatpak"], summary_next_step="Review the log",
    )


class LastUpdateStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.path = Path(directory.name) / "state" / "last-update.json"
        self.store = LastUpdateStore(self.path)

    def test_result_timestamp_and_logs_survive_a_separate_process(self) -> None:
        completed_at = datetime(2026, 10, 8, 12, 30, tzinfo=timezone.utc)
        snapshot = finished_snapshot()
        self.store.save(snapshot, completed_at=completed_at)
        loaded = LastUpdateStore(self.path).load()
        self.assertEqual(loaded.snapshot, snapshot)
        self.assertEqual(loaded.completed_at, completed_at)
        self.assertEqual(self.path.stat().st_mode & 0o777, 0o600)
        code = """
import sys
from pathlib import Path
from archupdater.infrastructure.last_update import LastUpdateStore
saved = LastUpdateStore(Path(sys.argv[1])).load()
assert saved.snapshot.summary_failed == ['AUR']
assert saved.snapshot.steps[0].log_lines == ['Updated linux 6.18 → 6.19']
assert saved.completed_at.isoformat() == sys.argv[2]
"""
        subprocess.run(
            [sys.executable, "-c", code, str(self.path), loaded.completed_at.isoformat()],
            env=dict(os.environ, PYTHONPATH=str(Path(__file__).resolve().parents[1] / "src")),
            check=True, capture_output=True, text=True,
        )

    def test_unfinished_snapshot_does_not_overwrite_the_saved_result(self) -> None:
        original = self.store.save(finished_snapshot())
        with self.assertRaises(ValueError):
            self.store.save(replace(original.snapshot, final_state=False))
        self.assertEqual(self.store.load(), original)

    def test_failed_atomic_write_preserves_previous_result(self) -> None:
        original = self.store.save(finished_snapshot())
        with patch("archupdater.infrastructure.last_update.os.replace", side_effect=OSError):
            with self.assertRaises(OSError):
                self.store.save(replace(original.snapshot, title="Another session"))
        self.assertEqual(self.store.load(), original)
        self.assertEqual(list(self.path.parent.iterdir()), [self.path])

    def test_invalid_snapshot_never_replaces_previous_result(self) -> None:
        original = self.store.save(finished_snapshot())
        original_bytes = self.path.read_bytes()
        for changes in (
            {"percent": 101}, {"percent": True}, {"title": None}, {"console_lines": [None]},
            {"activity_percent": -1}, {"cancelled": "false"}, {"present_dialog": "true"},
            {"steps": [replace(original.snapshot.steps[0], state="invalid")]},
            {"steps": [None]},
        ):
            with self.subTest(changes=changes):
                with self.assertRaises(ValueError):
                    self.store.save(replace(original.snapshot, **changes))
                self.assertEqual(self.path.read_bytes(), original_bytes)
                self.assertEqual(self.store.load(), original)
                self.assertEqual(list(self.path.parent.iterdir()), [self.path])

    def test_cancelled_result_survives_reopening_and_old_records_remain_readable(self) -> None:
        self.store.save(replace(finished_snapshot(), cancelled=True))
        self.assertEqual(LastUpdateStore(self.path).load().snapshot.result, UpdateResult.CANCELLED)
        payload = json.loads(self.path.read_text())
        del payload["snapshot"]["cancelled"]
        self.path.write_text(json.dumps(payload))
        self.assertEqual(self.store.load().snapshot.result, UpdateResult.PARTIAL_SUCCESS)

    def test_missing_corrupt_and_incompatible_records_are_ignored(self) -> None:
        self.assertIsNone(self.store.load())
        self.store.save(finished_snapshot())
        valid = json.loads(self.path.read_text())
        bad_snapshot = dict(valid["snapshot"], console_lines=[None])
        bad_step = dict(valid["snapshot"], steps=[{"phase": "unknown", "label": "Test"}])
        for payload in (
            "{", "null", json.dumps(dict(valid, schema_version=2)),
            json.dumps(dict(valid, completed_at="invalid")),
            json.dumps(dict(valid, snapshot=bad_snapshot)),
            json.dumps(dict(valid, snapshot=bad_step)),
            json.dumps(dict(valid, snapshot=dict(valid["snapshot"], final_state=False))),
        ):
            with self.subTest(payload=payload[:80]):
                self.path.write_text(payload)
                self.assertIsNone(self.store.load())


class LastUpdatePresentationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.store = LastUpdateStore(Path(self.directory.name) / "last-update.json")
        self.parent = QWidget()
        self.settings = Mock()
        self.settings.load_app_settings.return_value = AppSettings(auto_close_after_success=True)
        self.presenter = self._new_presenter()

    def tearDown(self) -> None:
        self.parent.close()
        self.parent.deleteLater()
        self.app.processEvents()

    def _new_presenter(self) -> UpdateProgressPresenter:
        return UpdateProgressPresenter(
            self.parent, Mock(), settings=self.settings, last_update_store=self.store,
        )

    def test_reopened_result_is_manual_persistent_and_exportable(self) -> None:
        self.assertFalse(self.presenter.has_last_update())
        self.presenter.apply_progress(finished_snapshot())
        self.presenter.close_dialog()
        self.presenter = self._new_presenter()
        self.assertTrue(self.presenter.has_last_update())
        self.presenter.show_last_update()
        dialog = self.presenter._history_dialog
        self.assertTrue(dialog.auto_close_checkbox.isHidden())
        self.assertTrue(dialog.close_button.isEnabled())
        self.assertEqual(dialog._latest_snapshot.summary_failed, ["AUR"])
        self.assertIn("error: build failed", dialog.console_log.toPlainText())
        self.assertIn("Completed:", dialog.session_date_label.text())
        exported = dialog._write_log_export(Path(self.directory.name))
        with ZipFile(exported) as archive:
            manifest = json.loads(archive.read("manifest.json"))
            self.assertEqual(manifest["summary"]["failed"], ["AUR"])
            self.assertEqual(manifest["session"]["result"], "partial_success")
            self.assertFalse(manifest["session"]["success"])
            self.assertEqual(
                manifest["session"]["completed_at"], self.store.load().completed_at.isoformat(),
            )
            self.assertIn("error: build failed", archive.read("update-session.log").decode())
        self.settings.save_app_settings.assert_not_called()
        dialog.close_button.click()
        self.assertIsNone(self.presenter._history_dialog)

    def test_history_stays_open_and_is_independent_of_live_progress(self) -> None:
        snapshot = replace(
            finished_snapshot(), title="Updates completed", success=True,
            summary_failed=[], summary_not_executed=[],
        )
        self.store.save(snapshot)
        self.presenter = self._new_presenter()
        self.presenter.show_last_update()
        history = self.presenter._history_dialog
        # Even a changed checkbox cannot activate automatic closing in this view.
        history.auto_close_checkbox.setChecked(True)
        self.presenter.apply_progress(UpdateProgressSnapshot("Checking", "", [], 0))
        self.presenter.apply_progress(UpdateProgressSnapshot(
            "Installing Updates", "New session", [], 0, present_dialog=True,
        ))
        QTest.qWait(history._success_close_timer.interval() + 100)
        self.assertTrue(history.isVisible())
        self.assertFalse(history._success_close_timer.isActive())
        self.assertEqual(history._latest_snapshot, snapshot)
        self.assertEqual(self.store.load().snapshot, snapshot)
        self.assertIsNot(history, self.presenter.dialog)
        self.presenter.apply_progress(finished_snapshot())
        self.assertEqual(history._latest_snapshot, snapshot)
        self.presenter.show_last_update()
        self.assertIsNot(self.presenter._history_dialog, history)
        self.assertEqual(self.presenter._history_dialog._latest_snapshot, finished_snapshot())
        self.presenter.close_dialog()
        self.presenter._history_dialog.close()

    def test_save_failure_does_not_interrupt_the_live_result(self) -> None:
        with (
            patch.object(self.store, "save", side_effect=OSError("disk full")),
            self.assertLogs("archupdater.presentation.update_progress_presenter", level="WARNING"),
        ):
            self.presenter.apply_progress(finished_snapshot())
        self.assertFalse(self.presenter.has_last_update())
        self.assertTrue(self.presenter.dialog.close_button.isEnabled())
        self.presenter.close_dialog()


if __name__ == "__main__":
    unittest.main()
