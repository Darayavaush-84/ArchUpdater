from __future__ import annotations

import sys
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import Mock, patch
from zipfile import ZipFile

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QPlainTextEdit, QWidget

from archupdater.domain.enums import UpdateProgressPhase, UpdateProgressStepState
from archupdater.domain.progress import UpdateProgressSnapshot, UpdateProgressStep
from archupdater import __version__
from archupdater.presentation.update_progress_dialog import UpdateProgressDialog
from archupdater.presentation.update_progress_presenter import UpdateProgressPresenter


class UpdateProgressDialogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._app = QApplication.instance() or QApplication([])

    def setUp(self) -> None:
        self.dialog: UpdateProgressDialog | None = None

    def tearDown(self) -> None:
        if self.dialog is not None:
            self.dialog.close()
            self.dialog.deleteLater()
        self._process_events()

    def test_notice_and_live_logs_are_shown_for_widget_updates(self) -> None:
        self.dialog = UpdateProgressDialog()
        self.dialog.show()

        snapshot = UpdateProgressSnapshot(
            title="Installing Updates",
            subtitle="Updating KDE Store add-ons",
            steps=[
                UpdateProgressStep(
                    phase=UpdateProgressPhase.PLASMA_WIDGET,
                    label="Add-ons",
                    state=UpdateProgressStepState.RUNNING,
                    log_lines=["$ kpackagetool6 -t Plasma/Applet -u /tmp/example"],
                ),
            ],
            percent=75,
            console_lines=["$ kpackagetool6 -t Plasma/Applet -u /tmp/example"],
            notice_title="KDE Store Add-ons",
            notice_text="1 selected. Some add-ons may require restarting plasmashell after updating.",
            present_dialog=True,
            final_state=True,
            success=True,
        )
        self.dialog.apply_snapshot(snapshot)
        self._process_events()

        self.assertTrue(self.dialog.notice_card.isVisible())
        self.assertFalse(self.dialog._success_close_timer.isActive())
        first_row = self.dialog._step_rows[0]
        self.assertFalse(first_row.findChildren(QPlainTextEdit))
        self.assertTrue(self.dialog.console_log.isVisible())
        self.assertIn("kpackagetool6", self.dialog.console_log.toPlainText())

    def test_auto_close_checkbox_controls_success_close_timer(self) -> None:
        self.dialog = UpdateProgressDialog()
        snapshot = UpdateProgressSnapshot(
            title="Updates completed",
            subtitle="Selected updates completed successfully.",
            steps=[
                UpdateProgressStep(
                    phase=UpdateProgressPhase.SYSTEM,
                    label="Pacman",
                    state=UpdateProgressStepState.COMPLETED,
                )
            ],
            percent=100,
            final_state=True,
            success=True,
        )

        self.dialog.apply_snapshot(snapshot)
        self.assertFalse(self.dialog.auto_close_checkbox.isChecked())
        self.assertFalse(self.dialog._success_close_timer.isActive())

        self.dialog.auto_close_checkbox.setChecked(True)
        self.assertTrue(self.dialog._success_close_timer.isActive())
        self.dialog.auto_close_checkbox.setChecked(False)
        self.assertFalse(self.dialog._success_close_timer.isActive())

    def test_step_rows_do_not_duplicate_the_live_log_panel(self) -> None:
        self.dialog = UpdateProgressDialog()
        snapshot = UpdateProgressSnapshot(
            title="Installing Updates",
            subtitle="Updating pacman packages",
            steps=[
                UpdateProgressStep(
                    phase=UpdateProgressPhase.SYSTEM,
                    label="Pacman",
                    state=UpdateProgressStepState.RUNNING,
                )
            ],
            percent=30,
        )

        self.dialog.apply_snapshot(snapshot)

        self.assertFalse(self.dialog._step_rows[0].findChildren(QPlainTextEdit))

    def test_package_progress_lines_are_rendered_inside_console_log(self) -> None:
        self.dialog = UpdateProgressDialog()
        snapshot = UpdateProgressSnapshot(
            title="Installing Updates",
            subtitle="Updating pacman packages",
            steps=[
                UpdateProgressStep(
                    phase=UpdateProgressPhase.SYSTEM,
                    label="Pacman",
                    state=UpdateProgressStepState.RUNNING,
                )
            ],
            percent=25,
            console_lines=[
                "linux-6.10.1-arch1-x86_64.pkg.tar.zst       50.0 MiB  10.0 MiB/s 00:05 [##########----------] 50%",
                "(1/2) upgrading linux                                      [##########----------] 50%",
            ],
        )

        self.dialog.apply_snapshot(snapshot)

        rendered = self.dialog.console_log.toPlainText()
        self.assertIn("linux-6.10.1-arch1-x86_64.pkg.tar.zst", rendered)
        self.assertIn("(1/2) upgrading linux", rendered)
        self.assertIn("50%", rendered)

    def test_synthetic_completed_phase_is_not_rendered_as_step(self) -> None:
        self.dialog = UpdateProgressDialog()
        snapshot = UpdateProgressSnapshot(
            title="Updates completed",
            subtitle="Selected updates completed successfully.",
            steps=[
                UpdateProgressStep(
                    phase=UpdateProgressPhase.SYSTEM,
                    label="Pacman",
                    state=UpdateProgressStepState.COMPLETED,
                ),
                UpdateProgressStep(
                    phase=UpdateProgressPhase.COMPLETED,
                    label="Completed",
                    state=UpdateProgressStepState.COMPLETED,
                ),
            ],
            percent=100,
            final_state=True,
            success=True,
        )

        self.dialog.apply_snapshot(snapshot)

        self.assertEqual(len(self.dialog._step_rows), 1)
        self.assertEqual(self.dialog._step_rows[0].title.text(), "Pacman")

    def test_final_summary_is_rendered_for_partial_failure(self) -> None:
        self.dialog = UpdateProgressDialog()
        snapshot = UpdateProgressSnapshot(
            title="Update completed with issues",
            subtitle="AUR update failed. (exit code 1)",
            steps=[
                UpdateProgressStep(
                    phase=UpdateProgressPhase.SYSTEM,
                    label="Pacman",
                    state=UpdateProgressStepState.COMPLETED,
                ),
                UpdateProgressStep(
                    phase=UpdateProgressPhase.AUR,
                    label="AUR",
                    state=UpdateProgressStepState.FAILED,
                ),
                UpdateProgressStep(
                    phase=UpdateProgressPhase.FLATPAK,
                    label="Flatpak",
                    state=UpdateProgressStepState.NOT_EXECUTED,
                ),
            ],
            percent=50,
            final_state=True,
            success=False,
            summary_title="Session Summary",
            summary_completed=["Pacman"],
            summary_failed=["AUR"],
            summary_not_executed=["Flatpak"],
            summary_next_step="Review the live activity log, then run the remaining updates again.",
        )

        self.dialog.apply_snapshot(snapshot)

        self.assertFalse(self.dialog.summary_card.isHidden())
        self.assertEqual(self.dialog.summary_completed_text.text(), "Pacman")
        self.assertEqual(self.dialog.summary_failed_text.text(), "AUR")
        self.assertEqual(self.dialog.summary_not_executed_text.text(), "Flatpak")
        self.assertIn("remaining updates again", self.dialog.summary_next_text.text())

    def test_incomplete_step_is_not_presented_as_completed(self) -> None:
        self.dialog = UpdateProgressDialog()
        snapshot = UpdateProgressSnapshot(
            title="No updates installed",
            subtitle="No selected updates were installed.",
            steps=[
                UpdateProgressStep(
                    phase=UpdateProgressPhase.AUR,
                    label="AUR",
                    state=UpdateProgressStepState.INCOMPLETE,
                ),
            ],
            percent=100,
            final_state=True,
            success=True,
            summary_title="Session Summary",
            summary_incomplete=["AUR"],
            summary_next_step="No further action is required.",
        )

        self.dialog.apply_snapshot(snapshot)

        self.assertEqual(self.dialog._step_rows[0].state_text.text(), "Incomplete")
        self.assertEqual(self.dialog.summary_incomplete_text.text(), "AUR")
        self.assertTrue(self.dialog.summary_completed_text.isHidden())
        self.assertFalse(self.dialog._success_close_timer.isActive())

    def test_console_log_is_cleaned_for_gui_display(self) -> None:
        self.dialog = UpdateProgressDialog()
        snapshot = UpdateProgressSnapshot(
            title="Installing Updates",
            subtitle="Updating AUR packages",
            steps=[
                UpdateProgressStep(
                    phase=UpdateProgressPhase.AUR,
                    label="AUR",
                    state=UpdateProgressStepState.RUNNING,
                )
            ],
            percent=30,
            console_lines=[
                "Update session started.",
                "\x1b[1;93m--------------------------------------------------------\x1b[0m",
                "\x1b[1;96m\x1b[1mArchUpdater update session\x1b[0m",
                "\x1b[0;37m- AUR: 2 packages\x1b[0m",
                "",
                "\x1b[1;34m::\x1b[0m Resolving dependencies...\x1b[0m",
            ],
        )

        self.dialog.apply_snapshot(snapshot)

        rendered = self.dialog.console_log.toPlainText()
        self.assertNotIn("\x1b", rendered)
        self.assertNotIn("----", rendered)
        self.assertNotIn("ArchUpdater update session", rendered)
        self.assertIn("Update session started.", rendered)
        self.assertIn("- AUR: 2 packages", rendered)
        self.assertIn(":: Resolving dependencies...", rendered)

    def test_export_logs_button_and_zip_are_available_for_failed_updates(self) -> None:
        self.dialog = UpdateProgressDialog()
        snapshot = UpdateProgressSnapshot(
            title="Update failed",
            subtitle="AUR update failed. (exit code 130)",
            steps=[
                UpdateProgressStep(
                    phase=UpdateProgressPhase.AUR,
                    label="AUR",
                    state=UpdateProgressStepState.FAILED,
                    log_lines=["paru -S package", "error: can not install conflicting packages"],
                )
            ],
            percent=0,
            console_lines=[
                "Update session started.",
                "\x1b[1;34m::\x1b[0m Resolving dependencies...",
                "AUR update failed. (exit code 130)",
            ],
            final_state=True,
            success=False,
            summary_failed=["AUR"],
            summary_next_step="Review the live activity log, then try the update again.",
        )

        self.dialog.show()
        self.dialog.apply_snapshot(snapshot)
        self._process_events()

        self.assertTrue(self.dialog.export_logs_button.isVisible())
        with tempfile.TemporaryDirectory() as directory:
            archive_path = self.dialog._write_log_export(Path(directory))

            self.assertTrue(archive_path.exists())
            with ZipFile(archive_path) as archive:
                names = set(archive.namelist())
                self.assertIn("manifest.json", names)
                self.assertIn("update-session.log", names)
                self.assertNotIn("console-clean.log", names)
                self.assertNotIn("console-raw.log", names)
                self.assertNotIn("summary.txt", names)
                manifest = archive.read("manifest.json").decode("utf-8")
                exported_log = archive.read("update-session.log").decode("utf-8")

        self.assertIn(f'"archupdater_version": "{__version__}"', manifest)
        self.assertIn("AUR update failed. (exit code 130)", exported_log)
        self.assertNotIn("\x1b", exported_log)
        self.assertIn("Review the live activity log", exported_log)

    def test_only_measured_progress_is_displayed_and_queued_steps_remain_visible(self) -> None:
        self.dialog = UpdateProgressDialog()
        snapshot = UpdateProgressSnapshot(
            title="Installing Updates", subtitle="Building AUR packages", percent=67,
            steps=[
                UpdateProgressStep(UpdateProgressPhase.AUR, "AUR", UpdateProgressStepState.RUNNING),
                UpdateProgressStep(UpdateProgressPhase.FLATPAK, "Flatpak"),
            ],
        )
        self.dialog.apply_snapshot(snapshot)
        self.assertEqual(self.dialog.progress_bar.maximum(), 0)
        self.assertTrue(self.dialog.progress_percent.isHidden())
        self.assertEqual(len(self.dialog._step_rows), 2)
        self.assertEqual(self.dialog._step_rows[1].state_text.text(), "Queued")

        self.dialog.apply_snapshot(replace(
            snapshot, activity_text="Upgrading mesa — 42 of 139", activity_percent=30,
        ))
        self.assertEqual(self.dialog.progress_bar.maximum(), 100)
        self.assertEqual(self.dialog.progress_bar.value(), 30)
        self.assertEqual(self.dialog.hero_subtitle.text(), "Upgrading mesa — 42 of 139")

    def test_log_can_be_collapsed_and_failure_reopens_it_with_the_actual_error(self) -> None:
        self.dialog = UpdateProgressDialog()
        snapshot = UpdateProgressSnapshot(
            title="Installing Updates", subtitle="Running pacman", steps=[], percent=0,
            console_lines=["resolving dependencies..."],
        )
        self.dialog.apply_snapshot(snapshot)
        self.dialog.log_toggle.setChecked(False)
        self.assertTrue(self.dialog.console_log.isHidden())
        self.dialog.apply_snapshot(replace(
            snapshot, title="Update failed", subtitle="pacman exited with code 1.",
            final_state=True, success=False,
            console_lines=["error: package conflicts detected", "pacman exited with code 1."],
        ))
        self.assertFalse(self.dialog.console_log.isHidden())
        self.assertEqual(self.dialog.hero_subtitle.text(), "error: package conflicts detected")
        self.assertFalse(self.dialog._success_close_timer.isActive())
        self.dialog.apply_snapshot(replace(
            snapshot, title="Update failed", subtitle="pacman exited with code 1.",
            final_state=True, success=False,
            console_lines=[
                ":: qemu-common and qemu-block-gluster are in conflict",
                "error: failed to prepare transaction (conflicting dependencies)",
            ],
        ))
        self.assertEqual(
            self.dialog.hero_subtitle.text(), "qemu-common and qemu-block-gluster are in conflict"
        )

    def test_new_log_output_preserves_manual_scroll_position(self) -> None:
        self.dialog = UpdateProgressDialog()
        self.dialog.show()
        snapshot = UpdateProgressSnapshot(
            title="Installing Updates", subtitle="Running pacman", steps=[], percent=0,
            console_lines=[f"line {i}" for i in range(300)],
        )
        self.dialog.apply_snapshot(snapshot)
        self._process_events()
        scrollbar = self.dialog.console_log.verticalScrollBar()
        scrollbar.setValue(10)
        self.assertFalse(self.dialog._console_auto_scroll)
        self.dialog.apply_snapshot(replace(snapshot, console_lines=snapshot.console_lines + ["new line"]))
        self._process_events()
        self.assertEqual(scrollbar.value(), 10)
        self.assertIn("new line", self.dialog.console_log.toPlainText())

    def test_result_survives_background_refresh_and_question_displays_waiting_state(self) -> None:
        parent = QWidget()
        self.addCleanup(parent.deleteLater)
        presenter = UpdateProgressPresenter(parent, Mock())
        snapshot = UpdateProgressSnapshot(
            title="Installing Updates", subtitle="Running pacman", steps=[], percent=0,
            present_dialog=True,
        )
        presenter.apply_progress(snapshot)
        self.dialog = presenter.dialog

        def inspect_question(**kwargs):
            self.assertEqual(self.dialog.hero_subtitle.text(), "Waiting for your response")
            self.assertEqual(self.dialog.progress_bar.maximum(), 100)
            self.assertTrue(self.dialog.progress_percent.isHidden())

        with patch(
            "archupdater.presentation.update_progress_presenter.handle_question_request",
            side_effect=inspect_question,
        ):
            presenter.handle_question_request({"question_type": "pacman_confirmation"})
        self.assertEqual(self.dialog.hero_subtitle.text(), "Running pacman")
        final = replace(snapshot, title="Updates completed", final_state=True, success=True)
        presenter.apply_progress(final)
        presenter.apply_progress(UpdateProgressSnapshot(
            title="Checking", subtitle="Refreshing packages", steps=[], percent=0,
        ))
        self.assertIs(self.dialog._latest_snapshot, final)
        self.assertTrue(self.dialog.close_button.isEnabled())
        self.assertFalse(self.dialog.auto_close_checkbox.isChecked())

    def _process_events(self) -> None:
        for _ in range(30):
            self._app.processEvents()
            QTest.qWait(1)


if __name__ == "__main__":
    unittest.main()
