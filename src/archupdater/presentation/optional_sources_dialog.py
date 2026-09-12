from __future__ import annotations

from collections.abc import Callable

from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import QDialog, QDialogButtonBox, QLabel, QVBoxLayout, QWidget

from archupdater.domain.optional_sources import OptionalSourcesSnapshot
from archupdater.presentation.optional_sources_panel import OptionalSourcesPanel
from archupdater.presentation.privileged_client import PrivilegedUpdateClient
from archupdater.application.updates import UpdateApplication


class OptionalSourcesDialog(QDialog):
    def __init__(
        self,
        service: UpdateApplication,
        snapshot: OptionalSourcesSnapshot,
        parent: QDialog | None = None,
        client_factory: Callable[[QWidget], PrivilegedUpdateClient] | None = None,
    ) -> None:
        super().__init__(parent)
        self._snapshot = snapshot
        self._modified = False
        self._busy = False

        self.setWindowTitle(self.tr("Manage Update Sources"))
        self.setModal(True)
        self.setMinimumWidth(760)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(16)

        title = QLabel(self.tr("Manage Update Sources"))
        title.setObjectName("sectionTitle")
        layout.addWidget(title)

        description = QLabel(
            self.tr(
                "Install or remove optional update sources. Matching sections in the main window appear automatically once support is available."
            )
        )
        description.setWordWrap(True)
        description.setObjectName("mutedText")
        layout.addWidget(description)

        self.panel = OptionalSourcesPanel(
            service,
            snapshot,
            self,
            client_factory=client_factory,
        )
        self.panel.snapshot_changed.connect(self._handle_snapshot_changed)
        self.panel.busy_changed.connect(self._handle_busy_changed)
        layout.addWidget(self.panel)

        self.buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        close_button = self.buttons.button(QDialogButtonBox.StandardButton.Close)
        if close_button is not None:
            close_button.setProperty("actionKind", "neutral")
            close_button.setProperty("uiRole", "dialogFooter")
            close_button.setProperty("density", "compact")
        self.buttons.rejected.connect(self.reject)
        layout.addWidget(self.buttons)

    def snapshot(self) -> OptionalSourcesSnapshot:
        return self._snapshot

    def modified(self) -> bool:
        return self._modified

    def _handle_snapshot_changed(self, snapshot: object) -> None:
        if isinstance(snapshot, OptionalSourcesSnapshot):
            self._snapshot = snapshot
        self._modified = True

    def _handle_busy_changed(self, busy: bool) -> None:
        self._busy = busy
        for button in self.buttons.buttons():
            button.setEnabled(not busy)

    def reject(self) -> None:
        if self._busy:
            return
        super().reject()

    def closeEvent(self, event: QCloseEvent) -> None:
        if self._busy:
            event.ignore()
            return
        super().closeEvent(event)
