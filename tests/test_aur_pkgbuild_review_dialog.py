from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from PySide6.QtWidgets import QApplication, QDialog, QPlainTextEdit

from archupdater.domain.aur import AurPkgbuildReview, AurReviewFile
from archupdater.presentation.aur_pkgbuild_review_dialog import AurPkgbuildReviewDialog


class AurPkgbuildReviewDialogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._app = QApplication.instance() or QApplication([])

    def tearDown(self) -> None:
        if hasattr(self, "dialog"):
            self.dialog.deleteLater()
            self._process_events()

    def test_shows_pkgbuild_content_in_read_only_scrollable_editor(self) -> None:
        self.dialog = AurPkgbuildReviewDialog(
            AurPkgbuildReview(
                package_name="spotify",
                package_base="spotify",
                pkgbuild="pkgname=spotify\nsource=(spotify.deb)",
                commit="a" * 40,
                digest="b" * 64,
                files=(
                    AurReviewFile(
                        "PKGBUILD",
                        "c" * 64,
                        38,
                        "pkgname=spotify\nsource=(spotify.deb)",
                    ),
                    AurReviewFile(
                        "spotify.install",
                        "d" * 64,
                        22,
                        "post_install() { :; }",
                    ),
                ),
            )
        )

        self.assertTrue(self.dialog.pkgbuild_text.isReadOnly())
        self.assertIn("pkgname=spotify", self.dialog.pkgbuild_text.toPlainText())
        self.assertIn("Commit: " + "a" * 40, self.dialog.pkgbuild_text.toPlainText())
        self.assertIn("spotify.install", self.dialog.pkgbuild_text.toPlainText())
        self.assertIn("post_install", self.dialog.pkgbuild_text.toPlainText())
        self.assertEqual(
            self.dialog.pkgbuild_text.lineWrapMode(),
            QPlainTextEdit.LineWrapMode.WidgetWidth,
        )

    def test_window_title_names_split_package_base(self) -> None:
        self.dialog = AurPkgbuildReviewDialog(
            AurPkgbuildReview("libbar", "bar", "pkgname=libbar")
        )

        self.assertIn("libbar (bar)", self.dialog.windowTitle())
        self.assertIn("pkgname=libbar", self.dialog.pkgbuild_text.toPlainText())

    def test_continue_button_requires_scrolling_single_pkgbuild_to_bottom(self) -> None:
        self.dialog = AurPkgbuildReviewDialog(
            AurPkgbuildReview(
                "spotify",
                "spotify",
                "\n".join(f"# line {index}" for index in range(220)),
            )
        )
        self.dialog.show()
        self._process_events()

        self.assertFalse(self.dialog.continue_button.isEnabled())
        self.dialog.accept()
        self.assertEqual(self.dialog.result(), QDialog.DialogCode.Rejected)

        scrollbar = self.dialog.pkgbuild_text.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())
        self._process_events()

        self.assertTrue(self.dialog.continue_button.isEnabled())

    def _process_events(self) -> None:
        for _ in range(10):
            self._app.processEvents()


if __name__ == "__main__":
    unittest.main()
