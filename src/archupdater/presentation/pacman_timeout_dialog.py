from __future__ import annotations

from collections.abc import Callable

import shiboken6
from PySide6.QtCore import QObject
from PySide6.QtWidgets import QMessageBox, QWidget

from archupdater.presentation.privileged_client import PrivilegedUpdateClient


class PacmanTimeoutDialogCoordinator(QObject):
    def __init__(self, parent: QWidget, resume_check: Callable[[], None]) -> None:
        super().__init__(parent)
        self._window = parent
        self._resume_check = resume_check
        self._prompted = False
        self._shutting_down = False
        self._client: PrivilegedUpdateClient | None = None

    def confirm(self) -> None:
        # Background checks must not open a dialog or wait for user input.
        if (
            self._shutting_down or self._prompted
            or not self._window.isVisible() or self._window.isMinimized()
        ):
            self._resume_check()
            return
        self._prompted = True
        box = QMessageBox(self._window)
        box.setIcon(QMessageBox.Icon.Warning)
        box.setWindowTitle(self.tr("Pacman download timeouts"))
        box.setText(self.tr(
            "Pacman download timeouts are disabled. A mirror that stops sending data can delay or interrupt the update check."
        ))
        box.setInformativeText(self.tr(
            "Enable timeouts so pacman can try the next mirror after about 10 seconds without data. ArchUpdater will comment out DisableDownloadTimeout in /etc/pacman.conf. This applies system-wide and requires administrator authentication."
        ))
        enable_button = box.addButton(self.tr("Enable timeouts"), QMessageBox.ButtonRole.AcceptRole)
        later_button = box.addButton(self.tr("Not now"), QMessageBox.ButtonRole.RejectRole)
        box.setDefaultButton(later_button)
        box.setEscapeButton(later_button)
        # The nested event loop may close the window and delete the box: record the
        # choice through the signal instead of querying the box after exec().
        clicked: list[object] = []
        box.buttonClicked.connect(clicked.append)
        box.exec()
        enable_requested = bool(clicked) and clicked[-1] is enable_button
        if shiboken6.isValid(box):
            box.deleteLater()
        if self._shutting_down:
            # shutdown() already released the waiting check.
            return
        if not enable_requested:
            self._resume_check()
            return
        client = PrivilegedUpdateClient(parent=self, authorization_scope="pacman-config")
        self._client = client
        client.completed.connect(self._completed)
        try:
            client.start_enable_download_timeouts()
        except Exception as exc:
            self._completed(False, str(exc))

    def _completed(self, success: bool, message: str) -> None:
        if self._client is not None:
            self._client.deleteLater()
            self._client = None
        if self._shutting_down:
            return
        if not success:
            QMessageBox.warning(self._window, self.tr("Pacman download timeouts"), message)
        self._resume_check()

    def shutdown(self) -> None:
        self._shutting_down = True
        if self._client is not None:
            self._client.terminate()
        self._resume_check()
