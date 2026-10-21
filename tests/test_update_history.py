from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from dataclasses import asdict, replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import Mock, patch
from zipfile import ZipFile

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QWidget

from archupdater.domain.enums import (
    UpdatePackageOutcome, UpdateProgressPhase, UpdateProgressStepState, UpdateResult, UpdateSource,
)
from archupdater.domain.package_metadata import (
    AurPackageMetadata, FlatpakPackageMetadata, SystemPackageMetadata,
)
from archupdater.domain.packages import PackageUpdate
from archupdater.domain.progress import (
    UpdateProgressPackage, UpdateProgressSnapshot, UpdateProgressStep,
)
from archupdater.application.update_session.protocol import BatchOutcome
from archupdater.domain.optional_sources import OptionalSourcesSnapshot
from archupdater.domain.update_plan import UpdatePlan, UpdatePlanItem
from archupdater.infrastructure.settings import AppSettings
from archupdater.infrastructure.update_history import UpdateHistoryStore
from archupdater.presentation.update_controller import UpdateController
from archupdater.presentation.update_progress_model import UpdateProgressModel
from archupdater.presentation.update_progress_presenter import UpdateProgressPresenter


def finished_snapshot(title: str = "Updates completed with issues") -> UpdateProgressSnapshot:
    return UpdateProgressSnapshot(
        title=title, subtitle="One source failed", percent=0,
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
        packages=[
            UpdateProgressPackage(
                UpdateSource.SYSTEM, "linux", "6.18", "6.19",
                outcome=UpdatePackageOutcome.UPDATED,
            ),
            UpdateProgressPackage(
                UpdateSource.AUR, "spotify", "1.2", "1.3",
                outcome=UpdatePackageOutcome.NOT_UPDATED,
            ),
        ],
    )


class UpdateHistoryStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.path = Path(directory.name) / "state" / "update-history.json"
        self.store = UpdateHistoryStore(self.path)

    def test_result_timestamp_packages_and_logs_survive_a_separate_process(self) -> None:
        completed_at = datetime(2026, 10, 8, 12, 30, tzinfo=timezone.utc)
        snapshot = finished_snapshot()
        self.store.save(snapshot, completed_at=completed_at)
        [loaded] = UpdateHistoryStore(self.path).load()
        self.assertEqual(loaded.snapshot, snapshot)
        self.assertEqual(loaded.completed_at, completed_at)
        self.assertEqual(self.path.stat().st_mode & 0o777, 0o600)
        code = """
import sys
from pathlib import Path
from archupdater.infrastructure.update_history import UpdateHistoryStore
[saved] = UpdateHistoryStore(Path(sys.argv[1])).load()
assert saved.snapshot.summary_failed == ['AUR']
assert saved.snapshot.steps[0].log_lines == ['Updated linux 6.18 → 6.19']
assert saved.snapshot.packages[1].outcome.value == 'not_updated'
assert saved.completed_at.isoformat() == sys.argv[2]
"""
        subprocess.run(
            [sys.executable, "-c", code, str(self.path), loaded.completed_at.isoformat()],
            env=dict(os.environ, PYTHONPATH=str(Path(__file__).resolve().parents[1] / "src")),
            check=True, capture_output=True, text=True,
        )

    def test_keeps_the_five_newest_sessions_newest_first(self) -> None:
        start = datetime(2026, 10, 1, 8, 0, tzinfo=timezone.utc)
        for day in range(7):
            self.store.save(
                finished_snapshot(f"Session {day}"), completed_at=start + timedelta(days=day),
            )
        history = UpdateHistoryStore(self.path).load()
        self.assertEqual(
            [entry.snapshot.title for entry in history],
            ["Session 6", "Session 5", "Session 4", "Session 3", "Session 2"],
        )

    def test_latest_session_from_older_versions_is_kept_and_migrated(self) -> None:
        legacy_path = self.path.with_name("last-update.json")
        legacy_path.parent.mkdir(parents=True)
        legacy_snapshot = asdict(finished_snapshot("Legacy session"))
        del legacy_snapshot["packages"]
        legacy_path.write_text(json.dumps({
            "schema_version": 1,
            "completed_at": "2026-10-08T12:30:00+00:00",
            "snapshot": legacy_snapshot,
        }))
        [legacy] = self.store.load()
        self.assertEqual(legacy.snapshot.title, "Legacy session")
        self.assertEqual(legacy.snapshot.packages, [])

        self.store.save(finished_snapshot("New session"))
        self.assertEqual(
            [entry.snapshot.title for entry in self.store.load()],
            ["New session", "Legacy session"],
        )
        self.assertFalse(legacy_path.exists())

    def test_saving_the_same_session_again_updates_its_entry(self) -> None:
        completed_at = datetime(2026, 10, 8, 12, 30, tzinfo=timezone.utc)
        self.store.save(finished_snapshot("Previous"))
        session = replace(finished_snapshot("Current"), session_id="session-1")
        self.store.save(session, completed_at=completed_at)
        self.store.save(
            replace(session, console_lines=[*session.console_lines, "Plasma restarted."]),
            completed_at=completed_at + timedelta(minutes=1),
        )
        history = self.store.load()
        self.assertEqual([entry.snapshot.title for entry in history], ["Current", "Previous"])
        self.assertEqual(history[0].snapshot.console_lines[-1], "Plasma restarted.")
        self.assertEqual(history[0].completed_at, completed_at)

    def test_unfinished_snapshot_does_not_change_the_history(self) -> None:
        history = self.store.save(finished_snapshot())
        with self.assertRaises(ValueError):
            self.store.save(replace(history[0].snapshot, final_state=False))
        self.assertEqual(self.store.load(), history)

    def test_failed_atomic_write_preserves_previous_history(self) -> None:
        history = self.store.save(finished_snapshot())
        with patch("archupdater.infrastructure.update_history.os.replace", side_effect=OSError):
            with self.assertRaises(OSError):
                self.store.save(replace(history[0].snapshot, title="Another session"))
        self.assertEqual(self.store.load(), history)
        self.assertEqual(list(self.path.parent.iterdir()), [self.path])

    def test_invalid_snapshot_never_replaces_previous_history(self) -> None:
        history = self.store.save(finished_snapshot())
        original_bytes = self.path.read_bytes()
        snapshot = history[0].snapshot
        for changes in (
            {"percent": 101}, {"percent": True}, {"title": None}, {"console_lines": [None]},
            {"activity_percent": -1}, {"cancelled": "false"}, {"present_dialog": "true"},
            {"steps": [replace(snapshot.steps[0], state="invalid")]},
            {"steps": [None]},
            {"packages": [replace(snapshot.packages[0], outcome="invalid")]},
            {"packages": [replace(snapshot.packages[0], name=None)]},
        ):
            with self.subTest(changes=changes):
                with self.assertRaises(ValueError):
                    self.store.save(replace(snapshot, **changes))
                self.assertEqual(self.path.read_bytes(), original_bytes)
                self.assertEqual(self.store.load(), history)
                self.assertEqual(list(self.path.parent.iterdir()), [self.path])

    def test_cancelled_result_survives_reopening(self) -> None:
        self.store.save(replace(finished_snapshot(), cancelled=True))
        [saved] = UpdateHistoryStore(self.path).load()
        self.assertEqual(saved.snapshot.result, UpdateResult.CANCELLED)

    def test_missing_corrupt_and_incompatible_records_are_ignored(self) -> None:
        self.assertEqual(self.store.load(), [])
        self.store.save(finished_snapshot())
        valid = json.loads(self.path.read_text())
        entry = valid["entries"][0]
        bad_snapshot = dict(entry["snapshot"], console_lines=[None])
        bad_step = dict(entry["snapshot"], steps=[{"phase": "unknown", "label": "Test"}])
        for payload in (
            "{", "null", json.dumps(dict(valid, schema_version=2)),
            json.dumps(dict(valid, entries=None)),
            json.dumps(dict(valid, entries=[dict(entry, completed_at="invalid")])),
            json.dumps(dict(valid, entries=[dict(entry, snapshot=bad_snapshot)])),
            json.dumps(dict(valid, entries=[dict(entry, snapshot=bad_step)])),
            json.dumps(dict(valid, entries=[
                dict(entry, snapshot=dict(entry["snapshot"], final_state=False)),
            ])),
        ):
            with self.subTest(payload=payload[:80]):
                self.path.write_text(payload)
                self.assertEqual(self.store.load(), [])

    def test_one_damaged_session_does_not_hide_the_others(self) -> None:
        self.store.save(finished_snapshot("Older"))
        self.store.save(finished_snapshot("Newer"))
        payload = json.loads(self.path.read_text())
        payload["entries"][0]["completed_at"] = "invalid"
        self.path.write_text(json.dumps(payload))
        self.assertEqual([entry.snapshot.title for entry in self.store.load()], ["Older"])


class UpdatePackageOutcomeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.model = UpdateProgressModel(lambda text: text)

    def _initialize(self, *packages: PackageUpdate) -> None:
        plan = UpdatePlan([UpdatePlanItem.from_package(package) for package in packages])
        self.model.initialize(plan, packages)

    def _outcomes(self) -> dict[str, UpdatePackageOutcome | None]:
        snapshot = self.model.snapshot("Done", "", final_state=True, success=True)
        return {package.name: package.outcome for package in snapshot.packages}

    def test_completed_steps_mark_their_packages_updated(self) -> None:
        self._initialize(
            PackageUpdate("linux", "6.18", "6.19", UpdateSource.SYSTEM, SystemPackageMetadata()),
            PackageUpdate(
                "GIMP", "3.0.4", "3.0.6", UpdateSource.FLATPAK,
                FlatpakPackageMetadata(ref="org.gimp.GIMP", installation_scope="user"),
            ),
        )
        self.model.handle_step_completed("system", success=True)
        self.model.handle_step_completed("flatpak", success=True)
        self.model.complete_success()
        snapshot = self.model.snapshot("Done", "", final_state=True, success=True)
        self.assertEqual(
            [(package.name, package.current_version, package.new_version, package.scope)
             for package in snapshot.packages],
            [("linux", "6.18", "6.19", ""), ("GIMP", "3.0.4", "3.0.6", "user")],
        )
        self.assertEqual(set(self._outcomes().values()), {UpdatePackageOutcome.UPDATED})

    def test_failed_unchanged_and_never_started_steps_are_not_updated(self) -> None:
        self._initialize(
            PackageUpdate("linux", "6.18", "6.19", UpdateSource.SYSTEM, SystemPackageMetadata()),
            PackageUpdate(
                "spotify", "1.2", "1.3", UpdateSource.AUR,
                AurPackageMetadata(package_base="spotify"),
            ),
        )
        self.model.handle_step_completed("system", success=False, changed=False)
        self.model.complete_failure()
        self.assertEqual(self._outcomes(), {
            "linux": UpdatePackageOutcome.NOT_UPDATED,
            "spotify": UpdatePackageOutcome.NOT_EXECUTED,
        })

    def test_partially_applied_steps_ask_to_check_the_log(self) -> None:
        self._initialize(
            PackageUpdate("linux", "6.18", "6.19", UpdateSource.SYSTEM, SystemPackageMetadata()),
            PackageUpdate(
                "spotify", "1.2", "1.3", UpdateSource.AUR,
                AurPackageMetadata(package_base="spotify"),
            ),
        )
        self.model.handle_step_completed("system", success=True, incomplete=True, changed=True)
        self.model.start_running_status("running_aur")
        # The session stops while AUR packages are being built.
        self.model.complete_failure()
        self.assertEqual(self._outcomes(), {
            "linux": UpdatePackageOutcome.UNCONFIRMED,
            "spotify": UpdatePackageOutcome.UNCONFIRMED,
        })

    def test_declined_pkgbuild_review_skips_only_that_aur_package(self) -> None:
        self._initialize(
            PackageUpdate(
                "spotify", "1.2", "1.3", UpdateSource.AUR,
                AurPackageMetadata(package_base="spotify"),
            ),
            PackageUpdate(
                "yay", "12.4", "12.5", UpdateSource.AUR, AurPackageMetadata(package_base="yay"),
            ),
        )
        self.model.mark_aur_package_skipped("spotify")
        self.model.handle_step_completed("aur", success=True, incomplete=True, changed=True)
        self.model.complete_success()
        self.assertEqual(self._outcomes(), {
            "spotify": UpdatePackageOutcome.SKIPPED,
            "yay": UpdatePackageOutcome.UPDATED,
        })


class UpdateHistoryPresentationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.store = UpdateHistoryStore(Path(self.directory.name) / "update-history.json")
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
            self.parent, Mock(), settings=self.settings, update_history_store=self.store,
        )

    def test_history_lists_sessions_and_what_was_updated(self) -> None:
        self.assertFalse(self.presenter.has_update_history())
        older = replace(
            finished_snapshot("Older"), success=True, summary_failed=[], summary_not_executed=[],
            steps=[finished_snapshot().steps[0]], packages=[finished_snapshot().packages[0]],
            console_lines=["Updated linux 6.18 → 6.19"],
        )
        self.presenter.apply_progress(older)
        self.presenter.apply_progress(finished_snapshot("Newer"))
        self.presenter.close_dialog()
        self.presenter = self._new_presenter()
        self.assertTrue(self.presenter.has_update_history())
        self.presenter.show_update_history()
        dialog = self.presenter._history_dialog
        tree = dialog.tree

        self.assertEqual(tree.topLevelItemCount(), 2)
        newest, previous = tree.topLevelItem(0), tree.topLevelItem(1)
        self.assertTrue(newest.isExpanded())
        self.assertFalse(previous.isExpanded())
        self.assertEqual(newest.text(1), "Updated: 1 · Not updated: 1")
        self.assertEqual(newest.text(2), "Completed with issues")
        self.assertEqual(previous.text(1), "Updated: 1")
        self.assertEqual(previous.text(2), "Completed")
        groups = [newest.child(index) for index in range(newest.childCount())]
        self.assertEqual(
            [(group.text(0), group.text(2)) for group in groups],
            [("Pacman (1)", "Completed"), ("AUR (1)", "Failed")],
        )
        self.assertTrue(all(group.isExpanded() for group in groups))
        self.assertEqual(
            [groups[1].child(0).text(column) for column in range(3)],
            ["spotify", "1.2 → 1.3", "Not updated"],
        )
        self.assertTrue(dialog.console_log.isHidden())
        self.assertIn("error: build failed", dialog.console_log.toPlainText())
        self.assertIn("Review the log", dialog.detail_label.text())

        tree.setCurrentItem(previous)
        self.assertEqual(dialog.selected_entry.snapshot.title, "Older")
        self.assertNotIn("error: build failed", dialog.console_log.toPlainText())
        dialog.log_toggle.click()
        self.assertFalse(dialog.console_log.isHidden())

        tree.setCurrentItem(groups[1].child(0))
        exported = dialog._write_log_export(Path(self.directory.name))
        with ZipFile(exported) as archive:
            manifest = json.loads(archive.read("manifest.json"))
            self.assertEqual(manifest["summary"]["failed"], ["AUR"])
            self.assertEqual(manifest["session"]["result"], "partial_success")
            self.assertEqual(
                manifest["session"]["completed_at"],
                self.store.load()[0].completed_at.isoformat(),
            )
            self.assertEqual(
                [(package["name"], package["outcome"]) for package in manifest["packages"]],
                [("linux", "updated"), ("spotify", "not_updated")],
            )
            log = archive.read("update-session.log").decode()
            self.assertIn("error: build failed", log)
            self.assertIn("- [aur] spotify 1.2 -> 1.3 - not_updated", log)
        self.settings.save_app_settings.assert_not_called()
        dialog.close_button.click()
        self.assertIsNone(self.presenter._history_dialog)

    def test_history_stays_open_and_is_independent_of_live_progress(self) -> None:
        snapshot = replace(
            finished_snapshot("Updates completed"), success=True,
            summary_failed=[], summary_not_executed=[],
        )
        self.store.save(snapshot)
        self.presenter = self._new_presenter()
        self.presenter.show_update_history()
        history = self.presenter._history_dialog
        self.presenter.apply_progress(UpdateProgressSnapshot("Checking", "", [], 0))
        self.presenter.apply_progress(UpdateProgressSnapshot(
            "Installing Updates", "New session", [], 0, present_dialog=True,
        ))
        QTest.qWait(1600)
        self.assertTrue(history.isVisible())
        self.assertEqual(history.selected_entry.snapshot, snapshot)
        self.assertIsNot(history, self.presenter.dialog)
        self.presenter.apply_progress(finished_snapshot())
        self.assertEqual(history.tree.topLevelItemCount(), 1)
        self.presenter.show_update_history()
        self.assertIsNot(self.presenter._history_dialog, history)
        self.assertEqual(self.presenter._history_dialog.tree.topLevelItemCount(), 2)
        self.assertEqual(
            self.presenter._history_dialog.selected_entry.snapshot, finished_snapshot(),
        )
        self.presenter.close_dialog()
        self.presenter._history_dialog.close()

    def test_sessions_saved_before_package_tracking_show_their_sources(self) -> None:
        self.store.save(replace(finished_snapshot(), packages=[]))
        self.presenter = self._new_presenter()
        self.presenter.show_update_history()
        session = self.presenter._history_dialog.tree.topLevelItem(0)
        self.assertEqual(session.text(1), "")
        self.assertEqual(
            [(session.child(index).text(0), session.child(index).childCount())
             for index in range(session.childCount())],
            [("Pacman", 0), ("AUR", 0)],
        )
        self.presenter._history_dialog.close()

    def test_messages_logged_after_completion_do_not_duplicate_the_session(self) -> None:
        service = Mock()
        service.optional_sources_snapshot.return_value = OptionalSourcesSnapshot()
        controller = UpdateController(service)
        controller.update_progress_changed.connect(self.presenter.apply_progress)
        package = PackageUpdate(
            "linux", "6.18", "6.19", UpdateSource.SYSTEM, SystemPackageMetadata(),
        )
        for _session in range(2):
            controller._initialize_progress(
                UpdatePlan([UpdatePlanItem.from_package(package)]), [package],
            )
            controller._progress_model.reveal_dialog()
            controller._handle_runner_progress(
                {"type": "step_completed", "step": "system", "success": True},
            )
            controller._handle_update_completed(True, "", BatchOutcome.SUCCESS.value)
            controller.append_external_log("System update completed successfully.")
        history = self.store.load()
        self.assertEqual(len(history), 2)
        self.assertNotEqual(history[0].snapshot.session_id, history[1].snapshot.session_id)
        self.assertEqual(
            history[0].snapshot.console_lines[-1], "System update completed successfully.",
        )
        self.assertEqual(history[0].snapshot.packages[0].outcome, UpdatePackageOutcome.UPDATED)
        self.presenter.close_dialog()

    def test_save_failure_does_not_interrupt_the_live_result(self) -> None:
        with (
            patch.object(self.store, "save", side_effect=OSError("disk full")),
            self.assertLogs("archupdater.presentation.update_progress_presenter", level="WARNING"),
        ):
            self.presenter.apply_progress(finished_snapshot())
        self.assertFalse(self.presenter.has_update_history())
        self.assertTrue(self.presenter.dialog.close_button.isEnabled())
        self.presenter.close_dialog()


if __name__ == "__main__":
    unittest.main()
