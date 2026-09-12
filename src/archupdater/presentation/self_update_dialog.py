from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QDesktopServices, QCloseEvent
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QLabel,
    QPlainTextEdit,
    QProgressBar,
    QVBoxLayout,
    QWidget,
)

from archupdater import __version__
from archupdater.domain.self_update import SelfUpdateRelease
from archupdater.infrastructure.app_releases import RELEASES_URL
from archupdater.infrastructure.self_updates import SELF_UPDATE_HELPER, SelfUpdateClient


class SelfUpdateDialog(QDialog):
    def __init__(
        self,
        release: SelfUpdateRelease | None,
        tag: str,
        *,
        restart: Callable[[], bool] | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.release = release
        self._restart = restart
        self._installed = False
        self._rolling_back = False
        self.client = SelfUpdateClient(self)
        self.client.stage_changed.connect(self._stage_changed)
        self.client.completed.connect(self._completed)
        self.setWindowTitle(self.tr("Update ArchUpdater"))
        self.setMinimumWidth(620)
        layout = QVBoxLayout(self)
        self.summary = QLabel(
            self.tr("Installed: {current} · Available: {latest}").format(
                current=__version__, latest=tag
            )
        )
        self.summary.setTextFormat(Qt.TextFormat.PlainText)
        layout.addWidget(self.summary)
        notes = QPlainTextEdit(release.notes if release else "")
        notes.setReadOnly(True)
        notes.setMinimumHeight(200)
        layout.addWidget(notes)
        self.status = QLabel(
            self.tr(
                "The update is verified before installation. Administrator authorization is required."
            )
        )
        self.status.setWordWrap(True)
        self.status.setTextFormat(Qt.TextFormat.PlainText)
        layout.addWidget(self.status)
        self.progress = QProgressBar()
        self.progress.setRange(0, 0)
        self.progress.hide()
        layout.addWidget(self.progress)
        self.buttons = QDialogButtonBox()
        self.install_button = self.buttons.addButton(
            self.tr("Update and Restart"), QDialogButtonBox.ButtonRole.AcceptRole
        )
        self.install_button.clicked.connect(self._install)
        self.github_button = self.buttons.addButton(
            self.tr("View on GitHub"), QDialogButtonBox.ButtonRole.HelpRole
        )
        self.github_button.clicked.connect(lambda: QDesktopServices.openUrl(QUrl(RELEASES_URL)))
        self.rollback_button = self.buttons.addButton(
            self.tr("Restore Previous Version"), QDialogButtonBox.ButtonRole.ActionRole
        )
        self.rollback_button.hide()
        self.rollback_button.clicked.connect(self._rollback)
        self.close_button = self.buttons.addButton(
            self.tr("Close"), QDialogButtonBox.ButtonRole.RejectRole
        )
        self.close_button.clicked.connect(self.reject)
        layout.addWidget(self.buttons)
        if release is None:
            self.status.setText(
                self.tr(
                    "This release has no verified update package. Open GitHub for installation instructions."
                )
            )
            self.install_button.setEnabled(False)
        elif not Path(SELF_UPDATE_HELPER).is_file() or not Path("/usr/bin/gh").is_file():
            self.status.setText(
                self.tr("Run the latest install.sh once to enable updates from this window.")
            )
            self.install_button.setEnabled(False)

    def _install(self) -> None:
        if self._installed:
            self._restart_now()
        elif self.release is not None and not self.client.busy:
            self._set_busy(True)
            self.client.start(self.release)

    def _rollback(self) -> None:
        self._rolling_back = True
        self._set_busy(True)
        self.client.rollback()

    def _set_busy(self, busy: bool) -> None:
        self.install_button.setEnabled(not busy)
        self.close_button.setEnabled(not busy)
        self.rollback_button.setEnabled(not busy)
        self.progress.setVisible(busy)

    def _stage_changed(self, stage: str) -> None:
        self.status.setText(
            self.tr("Downloading and verifying the release...")
            if stage == "download"
            else self.tr("Authorizing and installing the verified release...")
        )

    def _completed(self, success: bool, details: str) -> None:
        self._set_busy(False)
        if not success:
            self.status.setText(
                self.tr(
                    "Update cancelled or failed. The current version remains available.\n{details}"
                ).format(details=details)
            )
            self._rolling_back = False
            return
        self._installed = True
        self.install_button.setText(self.tr("Restart Now"))
        self.rollback_button.setVisible(not self._rolling_back)
        self.status.setText(
            self.tr("Previous version restored.")
            if self._rolling_back
            else self.tr("ArchUpdater was updated successfully.")
        )
        self._restart_now()

    def _restart_now(self) -> None:
        if self._restart is not None and self._restart():
            self.accept()
        else:
            self.status.setText(
                self.tr(
                    "Could not restart automatically. Close and reopen ArchUpdater, or restore the previous version."
                )
            )

    def reject(self) -> None:
        if not self.client.busy:
            super().reject()

    def closeEvent(self, event: QCloseEvent) -> None:
        if self.client.busy:
            event.ignore()
        else:
            super().closeEvent(event)
