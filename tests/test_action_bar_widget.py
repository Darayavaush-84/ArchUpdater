from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from PySide6.QtCore import QSize
from PySide6.QtGui import QHelpEvent, QIcon
from PySide6.QtWidgets import QApplication, QToolTip

from archupdater.presentation.widgets.action_bar import ActionBarWidget


class ActionBarWidgetTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._app = QApplication.instance() or QApplication([])

    def setUp(self) -> None:
        self.widget: ActionBarWidget | None = None

    def tearDown(self) -> None:
        if self.widget is not None:
            self.widget.close()
            self.widget.deleteLater()
        QToolTip.hideText()

    def test_github_logo_is_available_without_desktop_theme_icons(self) -> None:
        with patch.object(QIcon, "fromTheme", return_value=QIcon()):
            self.widget = ActionBarWidget()
        button = self.widget.github_button
        self.assertFalse(button.icon().isNull())
        self.assertEqual(button.icon().pixmap(QSize(64, 64), 1.0).width(), 64)
        self.assertEqual(button.text(), "")
        self.assertFalse(button.property("updateAvailable"))

    def test_github_update_indicator_can_be_shown_and_cleared(self) -> None:
        self.widget = ActionBarWidget()
        button = self.widget.github_button
        self.widget.set_github_release("v1.1.0")
        self.assertEqual(button.text(), "Update")
        self.assertTrue(button.property("updateAvailable"))
        self.assertIn("v1.1.0", button.toolTip())
        self.assertIn("GitHub", button.accessibleName())
        self.assertGreater(button.width(), 40)
        self.widget.set_github_release("")
        self.assertEqual(button.text(), "")
        self.assertFalse(button.property("updateAvailable"))
        self.assertEqual(button.width(), 40)

    def test_preferences_tooltip_is_shown_when_button_is_disabled(self) -> None:
        self.widget = ActionBarWidget()
        assert self.widget is not None
        self.widget.show()
        self.widget.set_busy(True)

        button = self.widget.preferences_button
        local_pos = button.rect().center()
        global_pos = button.mapToGlobal(local_pos)
        help_event = QHelpEvent(QHelpEvent.Type.ToolTip, local_pos, global_pos)
        QApplication.sendEvent(button, help_event)

        self.assertIn("Preferences are not available", QToolTip.text())

    def test_arch_news_button_is_always_visible_and_marks_unread_state(self) -> None:
        self.widget = ActionBarWidget()
        assert self.widget is not None

        self.assertFalse(self.widget.arch_news_button.isHidden())
        self.assertEqual(self.widget.arch_news_button.property("newsState"), "read")

        self.widget.set_arch_news_count(2)
        self.assertFalse(self.widget.arch_news_button.isHidden())
        self.assertEqual(self.widget.arch_news_button.text(), "Arch News (2)")
        self.assertEqual(self.widget.arch_news_button.property("newsState"), "unread")

        self.widget.set_arch_news_count(0)
        self.assertFalse(self.widget.arch_news_button.isHidden())
        self.assertEqual(self.widget.arch_news_button.text(), "Arch News")
        self.assertEqual(self.widget.arch_news_button.property("newsState"), "read")

    def test_arch_news_button_stays_enabled_while_busy(self) -> None:
        self.widget = ActionBarWidget()
        assert self.widget is not None

        self.widget.set_busy(True)

        self.assertTrue(self.widget.arch_news_button.isEnabled())
        self.assertFalse(self.widget.check_button.isEnabled())

    def test_update_button_shows_selected_item_count(self) -> None:
        self.widget = ActionBarWidget()
        assert self.widget is not None

        self.widget.set_update_selection(3)

        self.assertTrue(self.widget.update_button.isEnabled())
        self.assertEqual(self.widget.update_button.text(), "Update 3 items")

        self.widget.set_update_selection(0)

        self.assertFalse(self.widget.update_button.isEnabled())
        self.assertEqual(self.widget.update_button.text(), "Update")

if __name__ == "__main__":
    unittest.main()
