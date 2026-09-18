from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from PySide6.QtCore import QTimer, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QMessageBox, QWidget

from archupdater.domain.enums import PreflightSeverity, UpdateSource
from archupdater.domain.preflight import PreflightIssue
from archupdater.domain.update_plan import UpdatePlan, UpdatePlanItem
from archupdater.presentation.main_window import MainWindow
from archupdater.presentation.preflight_dialogs import (
    ask_flatpak_cleanup_scopes,
    confirm_preflight_issues,
)
from archupdater.presentation.update_interaction_dialogs import handle_question_request


class DialogButtonResultsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self) -> None:
        self.parent = QWidget()
        self.addCleanup(self.parent.deleteLater)

    def _answer(self, callback, choice):
        clicked: list[bool] = []
        timed_out: list[bool] = []
        timer = QTimer()
        timeout = QTimer()
        timeout.setSingleShot(True)

        def click_button() -> None:
            dialog = self.app.activeModalWidget()
            if not isinstance(dialog, QMessageBox):
                return
            timer.stop()
            clicked.append(True)
            if choice is None:
                dialog.close()
            else:
                QTest.mouseClick(dialog.button(choice), Qt.MouseButton.LeftButton)

        def abort_dialog() -> None:
            timed_out.append(True)
            dialog = self.app.activeModalWidget()
            if dialog is not None:
                dialog.reject()

        timer.timeout.connect(click_button)
        timeout.timeout.connect(abort_dialog)
        timer.start(10)
        timeout.start(2000)
        try:
            result = callback()
        finally:
            timer.stop()
            timeout.stop()
        self.assertFalse(timed_out, "The confirmation dialog did not respond")
        self.assertEqual(clicked, [True], "No real QMessageBox was shown")
        return result

    def test_transaction_change_accepts_ok_and_rejects_cancel_or_close(self) -> None:
        for choice in (QMessageBox.StandardButton.Ok, QMessageBox.StandardButton.Cancel, None):
            with self.subTest(choice=choice):
                responses = []
                cancellations = []
                self._answer(lambda: handle_question_request(
                    parent=self.parent,
                    payload={
                        "question_id": "changed-plan", "question_type": "transaction_change",
                        "title": "System Update Changed", "message": "Review new versions.",
                        "versions": {"linux-cachyos": "7.2.5-1", "pyalpm": "0.12.0-1.1"},
                    },
                    submit_response=lambda *args: responses.append(args),
                    cancel_question=cancellations.append,
                ), choice)
                self.assertEqual(responses, [("changed-plan", choice == QMessageBox.StandardButton.Ok)])
                self.assertEqual(cancellations, [])

    def test_preflight_warning_accepts_ok_and_rejects_cancel(self) -> None:
        issue = PreflightIssue(PreflightSeverity.WARNING, "Warning", "Review before continuing")
        for choice in (QMessageBox.StandardButton.Ok, QMessageBox.StandardButton.Cancel):
            with self.subTest(choice=choice):
                accepted = self._answer(lambda: confirm_preflight_issues(self.parent, [issue]), choice)
                self.assertEqual(accepted, choice == QMessageBox.StandardButton.Ok)

    def test_blocking_preflight_cannot_be_approved(self) -> None:
        issue = PreflightIssue(PreflightSeverity.BLOCKING, "Blocked", "Cannot continue")
        accepted = self._answer(
            lambda: confirm_preflight_issues(self.parent, [issue]), QMessageBox.StandardButton.Ok,
        )
        self.assertFalse(accepted)

    def test_flatpak_cleanup_uses_and_saves_the_actual_answer(self) -> None:
        plan = UpdatePlan([UpdatePlanItem(
            UpdateSource.FLATPAK, "app/org.example.App/x86_64/stable", installation_scope="user",
        )])
        for choice in (QMessageBox.StandardButton.Yes, QMessageBox.StandardButton.No):
            with self.subTest(choice=choice):
                saved = []
                scopes = self._answer(lambda: ask_flatpak_cleanup_scopes(
                    self.parent, plan, cleanup_enabled=False, cleanup_preference_set=False,
                    save_cleanup_preference=saved.append,
                ), choice)
                accepted = choice == QMessageBox.StandardButton.Yes
                self.assertEqual(scopes, ["user"] if accepted else [])
                self.assertEqual(saved, [accepted])

    def test_plasma_restart_accepts_yes_and_rejects_no(self) -> None:
        for choice in (QMessageBox.StandardButton.Yes, QMessageBox.StandardButton.No):
            with self.subTest(choice=choice):
                accepted = self._answer(lambda: MainWindow._ask_plasma_restart(self.parent), choice)
                self.assertEqual(accepted, choice == QMessageBox.StandardButton.Yes)


if __name__ == "__main__":
    unittest.main()
