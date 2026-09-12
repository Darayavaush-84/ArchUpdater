from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from PySide6.QtWidgets import QApplication, QMessageBox, QWidget

from archupdater.domain.enums import UpdateSource
from archupdater.domain.update_plan import UpdatePlan, UpdatePlanItem
from archupdater.presentation.preflight_dialogs import ask_flatpak_cleanup_scopes


class _MessageBoxStub:
    Icon = QMessageBox.Icon
    StandardButton = QMessageBox.StandardButton

    def __init__(self, _parent: QWidget) -> None:
        self.checkbox = None
        self.exec_result = QMessageBox.StandardButton.Yes

    def setIcon(self, _icon: QMessageBox.Icon) -> None:
        return None

    def setWindowTitle(self, _title: str) -> None:
        return None

    def setText(self, _text: str) -> None:
        return None

    def setCheckBox(self, checkbox) -> None:  # noqa: ANN001
        self.checkbox = checkbox
        checkbox.setChecked(True)

    def setStandardButtons(self, _buttons: QMessageBox.StandardButton) -> None:
        return None

    def setDefaultButton(self, _button: QMessageBox.StandardButton) -> None:
        return None

    def exec(self) -> QMessageBox.StandardButton:
        return self.exec_result


class FlatpakCleanupDialogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._app = QApplication.instance() or QApplication([])

    def setUp(self) -> None:
        self.parent = QWidget()

    def tearDown(self) -> None:
        self.parent.close()
        self.parent.deleteLater()

    def _plan(self) -> UpdatePlan:
        return UpdatePlan(
            [
                UpdatePlanItem(
                    UpdateSource.FLATPAK,
                    "app/org.example.App/x86_64/stable",
                    installation_scope="user",
                )
            ]
        )

    def test_saved_enabled_preference_adds_cleanup_without_prompt(self) -> None:
        with patch("archupdater.presentation.preflight_dialogs.QMessageBox") as message_box:
            scopes = ask_flatpak_cleanup_scopes(
                self.parent,
                self._plan(),
                cleanup_enabled=True,
                cleanup_preference_set=True,
            )

        self.assertEqual(scopes, ["user"])
        message_box.assert_not_called()

    def test_saved_disabled_preference_skips_cleanup_without_prompt(self) -> None:
        with patch("archupdater.presentation.preflight_dialogs.QMessageBox") as message_box:
            scopes = ask_flatpak_cleanup_scopes(
                self.parent,
                self._plan(),
                cleanup_enabled=False,
                cleanup_preference_set=True,
            )

        self.assertEqual(scopes, [])
        message_box.assert_not_called()

    def test_missing_preference_can_be_saved_from_first_prompt(self) -> None:
        saved_preferences: list[bool] = []

        with patch("archupdater.presentation.preflight_dialogs.QMessageBox", _MessageBoxStub):
            scopes = ask_flatpak_cleanup_scopes(
                self.parent,
                self._plan(),
                cleanup_enabled=False,
                cleanup_preference_set=False,
                save_cleanup_preference=saved_preferences.append,
            )

        self.assertEqual(scopes, ["user"])
        self.assertEqual(saved_preferences, [True])


if __name__ == "__main__":
    unittest.main()
