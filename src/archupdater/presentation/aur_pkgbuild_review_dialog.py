from __future__ import annotations

from PySide6.QtGui import QFontDatabase, QTextCursor
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QLabel,
    QPlainTextEdit,
    QVBoxLayout,
    QWidget,
)

from archupdater.domain.aur import AurPkgbuildReview


class AurPkgbuildReviewDialog(QDialog):
    def __init__(
        self,
        review: AurPkgbuildReview,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._reached_bottom = False
        self.setWindowTitle(
            self.tr("Review AUR PKGBUILD: {package}").format(
                package=self._review_label(review)
            )
        )
        self.setModal(True)
        self.setMinimumSize(860, 620)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(12)

        title = QLabel(
            self.tr("Review AUR PKGBUILD: {package}").format(
                package=self._review_label(review)
            )
        )
        title.setObjectName("sectionTitle")
        layout.addWidget(title)

        warning = QLabel(
            self.tr(
                "AUR PKGBUILD files are community-maintained build scripts. Read them before continuing."
            )
        )
        warning.setObjectName("mutedText")
        warning.setWordWrap(True)
        layout.addWidget(warning)

        self.pkgbuild_text = QPlainTextEdit()
        self.pkgbuild_text.setReadOnly(True)
        self.pkgbuild_text.setLineWrapMode(QPlainTextEdit.LineWrapMode.WidgetWidth)
        self.pkgbuild_text.setFont(QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont))
        self.pkgbuild_text.setMinimumHeight(420)
        self.pkgbuild_text.verticalScrollBar().valueChanged.connect(
            self._handle_scroll_position_changed
        )
        layout.addWidget(self.pkgbuild_text, 1)

        self.buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel)
        self.continue_button = self.buttons.addButton(
            self.tr("I have read the PKGBUILD and continue"),
            QDialogButtonBox.ButtonRole.AcceptRole,
        )
        self.continue_button.setEnabled(False)
        self.continue_button.setProperty("actionKind", "primary")
        self.continue_button.setProperty("density", "compact")
        cancel_button = self.buttons.button(QDialogButtonBox.StandardButton.Cancel)
        if cancel_button is not None:
            cancel_button.setProperty("actionKind", "neutral")
            cancel_button.setProperty("density", "compact")
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        layout.addWidget(self.buttons)

        self.pkgbuild_text.setPlainText(review.rendered_content())
        self.pkgbuild_text.moveCursor(QTextCursor.MoveOperation.Start)
        self._handle_scroll_position_changed(self.pkgbuild_text.verticalScrollBar().value())

    def _handle_scroll_position_changed(self, _value: int) -> None:
        scrollbar = self.pkgbuild_text.verticalScrollBar()
        if scrollbar.value() >= scrollbar.maximum():
            self._reached_bottom = True
        self._update_continue_button()

    def _update_continue_button(self) -> None:
        self.continue_button.setEnabled(self._reached_bottom)

    def _review_label(self, review: AurPkgbuildReview) -> str:
        if review.package_name == review.package_base:
            return review.package_name
        return f"{review.package_name} ({review.package_base})"

    def accept(self) -> None:
        if not self.continue_button.isEnabled():
            return
        super().accept()


def confirm_aur_pkgbuild_review(parent: QWidget, review: AurPkgbuildReview) -> bool:
    dialog = AurPkgbuildReviewDialog(review, parent)
    return dialog.exec() == QDialog.DialogCode.Accepted
