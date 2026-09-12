from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QIcon, QPixmap
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from archupdater.domain.enums import UpdateSource
from archupdater.domain.optional_sources import OptionalSourceStatus, OptionalSourcesSnapshot
from archupdater.resources.assets import counter_logo_path
from archupdater.presentation.privileged_client import PrivilegedUpdateClient
from archupdater.application.updates import UpdateApplication


@dataclass(frozen=True, slots=True)
class OptionalSourceUi:
    title: str
    summary: str
    icon_key: str
    install_limit: int | None = 1
    remove_limit: int | None = 1


class OptionalSourcesPanel(QWidget):
    snapshot_changed = Signal(object)
    busy_changed = Signal(bool)
    _SOURCE_ORDER = (
        UpdateSource.AUR,
        UpdateSource.FLATPAK,
        UpdateSource.FIRMWARE,
    )

    def __init__(
        self,
        service: UpdateApplication,
        snapshot: OptionalSourcesSnapshot,
        parent: QWidget | None = None,
        client_factory: Callable[[QWidget], PrivilegedUpdateClient] | None = None,
    ) -> None:
        super().__init__(parent)
        self._service = service
        self._snapshot = snapshot
        self._client_factory = client_factory
        self._active_client: PrivilegedUpdateClient | None = None
        self._operation_buttons: list[QPushButton] = []
        self._pending_client_start: Callable[[], None] | None = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(16)

        self._list_container = QFrame()
        self._list_container.setObjectName("optionalSourcesList")
        self._cards_layout = QVBoxLayout(self._list_container)
        self._cards_layout.setContentsMargins(16, 10, 16, 10)
        self._cards_layout.setSpacing(0)
        layout.addWidget(self._list_container)

        self.status_label = QLabel()
        self.status_label.setObjectName("optionalSourcesStatus")
        self.status_label.setWordWrap(True)
        self.status_label.setText(
            self.tr("Optional source status updates automatically while this window is open.")
        )
        layout.addWidget(self.status_label)

        self._refresh_snapshot(notify_parent=False)

    def snapshot(self) -> OptionalSourcesSnapshot:
        return self._snapshot

    def is_busy(self) -> bool:
        return self._active_client is not None

    def _rebuild_cards(self) -> None:
        self._operation_buttons = []
        while self._cards_layout.count():
            item = self._cards_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.hide()
                widget.setParent(None)
                widget.deleteLater()
        visible_statuses = [
            self._snapshot.status_for(source)
            for source in self._SOURCE_ORDER
        ]
        visible_statuses = [status for status in visible_statuses if status is not None]

        for index, status in enumerate(visible_statuses):
            assert status is not None
            self._cards_layout.addWidget(self._build_source_row(status))
            if index < len(visible_statuses) - 1:
                self._cards_layout.addWidget(self._divider())
        self._cards_layout.addStretch(1)

    def _build_source_row(self, status: OptionalSourceStatus) -> QFrame:
        row = QFrame()
        row.setObjectName("optionalSourceRow")
        row.setProperty("stateKind", self._state_kind(status))
        row.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        layout = QHBoxLayout(row)
        layout.setContentsMargins(0, 12, 0, 12)
        layout.setSpacing(14)

        layout.addWidget(self._source_icon_badge(status.source), 0, Qt.AlignmentFlag.AlignTop)

        content = QVBoxLayout()
        content.setContentsMargins(0, 0, 0, 0)
        content.setSpacing(4)

        title_row = QHBoxLayout()
        title_row.setContentsMargins(0, 0, 0, 0)
        title_row.setSpacing(8)

        title = QLabel(self._source_title(status.source))
        title.setObjectName("optionalSourceTitle")
        title.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed)
        state_badge = QLabel(self._status_badge_text(status))
        state_badge.setObjectName("sourceStateBadge")
        state_badge.setProperty("stateKind", self._state_kind(status))
        state_badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        state_badge.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed)

        title_row.addWidget(title, 0, Qt.AlignmentFlag.AlignLeft)
        title_row.addWidget(state_badge, 0, Qt.AlignmentFlag.AlignLeft)
        title_row.addStretch(1)

        summary = QLabel(self._source_summary_text(status.source))
        summary.setObjectName("optionalSourceSummary")
        summary.setWordWrap(False)
        summary.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)

        content.addLayout(title_row)
        content.addWidget(summary)

        details_text = self._status_detail_text(status)
        if details_text:
            details = QLabel(details_text)
            details.setObjectName("optionalSourceMeta")
            details.setWordWrap(False)
            details.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
            content.addWidget(details)

        layout.addLayout(content, 1)

        actions = self._build_inline_actions(status)
        if actions is not None:
            layout.addWidget(
                actions,
                0,
                Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignRight,
            )

        return row

    def _divider(self) -> QFrame:
        divider = QFrame()
        divider.setObjectName("optionalSourceDivider")
        divider.setFixedHeight(1)
        return divider

    def _build_inline_actions(self, status: OptionalSourceStatus) -> QWidget | None:
        action_label = self._primary_action_label(status)
        action_handler = self._primary_action_handler(status)
        if action_label is None or action_handler is None:
            return None

        widget = QWidget()
        widget.setObjectName("optionalSourceActions")
        widget.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Preferred)
        actions_layout = QVBoxLayout(widget)
        actions_layout.setContentsMargins(0, 0, 0, 0)
        actions_layout.setSpacing(0)
        actions_layout.addWidget(
            self._action_button(action_label, action_handler),
            0,
            Qt.AlignmentFlag.AlignRight,
        )

        return widget

    def _action_button(self, text: str, handler) -> QPushButton:  # noqa: ANN001
        button = QPushButton(text)
        button.setProperty("actionKind", "neutral")
        button.setProperty("uiRole", "sourceAction")
        button.setProperty("density", "compact")
        button.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed)
        button.setMinimumHeight(24)
        button.setMinimumWidth(0)
        button.setMaximumWidth(140)
        button.clicked.connect(handler)
        self._operation_buttons.append(button)
        return button

    def _primary_action_label(self, status: OptionalSourceStatus) -> str | None:
        if status.source is UpdateSource.AUR and status.installed:
            return self.tr("Disable") if status.active else self.tr("Enable")
        if status.installed or status.active:
            return self.tr("Remove")
        if status.installable_packages:
            return self.tr("Install") if status.source is UpdateSource.AUR else self.tr("Enable")
        return None

    def _primary_action_handler(self, status: OptionalSourceStatus):  # noqa: ANN001
        if status.source is UpdateSource.AUR and status.installed:
            enabled = not status.active
            return lambda _checked=False, value=enabled: self._set_aur_enabled(value)

        if status.installed or status.active:
            packages = self._packages_to_disable(status)
            if not packages:
                return None
            return lambda _checked=False, names=packages: self._remove_packages(names)

        packages = self._packages_to_enable(status)
        if not packages:
            return None
        return lambda _checked=False, names=packages: self._install_packages(names)

    def _packages_to_enable(self, status: OptionalSourceStatus) -> list[str]:
        limit = self._source_ui(status.source).install_limit
        return list(status.installable_packages if limit is None else status.installable_packages[:limit])

    def _packages_to_disable(self, status: OptionalSourceStatus) -> list[str]:
        limit = self._source_ui(status.source).remove_limit
        return list(status.removable_packages if limit is None else status.removable_packages[:limit])

    def _install_packages(self, package_names: list[str]) -> None:
        if not self._confirm_install_packages(package_names):
            return
        client = self._create_privileged_update_client()
        self._pending_client_start = lambda: client.start_install_support_packages(package_names)
        self._start_client(
            client,
            self.tr("Installing optional source support..."),
        )

    def _confirm_install_packages(self, package_names: list[str]) -> bool:
        message = self.tr(
            "Pacman will perform a full system upgrade and install these support packages: {packages}.\n\nContinue?"
        ).format(packages=", ".join(package_names))
        return (
            QMessageBox.question(
                self,
                self.tr("Full System Upgrade"),
                message,
                QMessageBox.StandardButton.Cancel | QMessageBox.StandardButton.Yes,
                QMessageBox.StandardButton.Cancel,
            )
            == QMessageBox.StandardButton.Yes
        )

    def _remove_packages(self, package_names: list[str]) -> None:
        if not self._confirm_remove_packages(package_names):
            return
        client = self._create_privileged_update_client()
        self._pending_client_start = lambda: client.start_remove_support_packages(package_names)
        self._start_client(
            client,
            self.tr("Removing optional source support..."),
        )

    def _set_aur_enabled(self, enabled: bool) -> None:
        if enabled and not self._confirm_enable_aur():
            return
        try:
            self._service.set_aur_updates_enabled(enabled)
        except Exception as exc:
            message = str(exc).strip() or self.tr("The selected optional source operation failed.")
            self.status_label.setText(message)
            QMessageBox.warning(
                self,
                self.tr("Operation Failed"),
                message,
            )
            return

        self.status_label.setText(
            self.tr("AUR support is enabled in ArchUpdater.")
            if enabled
            else self.tr("AUR support is disabled in ArchUpdater. Installed helpers were not removed.")
        )
        self._refresh_snapshot(notify_parent=True)

    def _confirm_enable_aur(self) -> bool:
        message = self.tr(
            "AUR packages are maintained by the community and PKGBUILD files are build scripts. ArchUpdater will require you to review each PKGBUILD in a separate scrollable window before installing AUR updates.\n\nEnable AUR checks and updates in ArchUpdater?"
        )
        return (
            QMessageBox.question(
                self,
                self.tr("Enable AUR Support"),
                message,
                QMessageBox.StandardButton.Cancel | QMessageBox.StandardButton.Yes,
                QMessageBox.StandardButton.Cancel,
            )
            == QMessageBox.StandardButton.Yes
        )

    def _confirm_remove_packages(self, package_names: list[str]) -> bool:
        message = self.tr(
            "ArchUpdater will remove these packages from the system: {packages}.\n\nThey may be used by other tools outside ArchUpdater."
        ).format(packages=", ".join(package_names))
        return (
            QMessageBox.question(
                self,
                self.tr("Remove package"),
                message,
                QMessageBox.StandardButton.Cancel | QMessageBox.StandardButton.Yes,
                QMessageBox.StandardButton.Cancel,
            )
            == QMessageBox.StandardButton.Yes
        )

    def _start_client(self, client: PrivilegedUpdateClient, status_text: str) -> None:
        self._active_client = client
        self.status_label.setText(status_text)
        self._set_operation_controls_enabled(False)
        self.busy_changed.emit(True)
        client.log_received.connect(self.status_label.setText)
        client.completed.connect(self._handle_client_completed)
        pending_start = self._pending_client_start
        self._pending_client_start = None
        try:
            if pending_start is None:
                raise RuntimeError(self.tr("The selected optional source operation failed."))
            pending_start()
        except Exception as exc:
            self._set_operation_controls_enabled(True)
            self._active_client = None
            self.busy_changed.emit(False)
            message = str(exc).strip() or self.tr("The selected optional source operation failed.")
            self.status_label.setText(message)
            QMessageBox.warning(
                self,
                self.tr("Operation Failed"),
                message,
            )

    def _create_privileged_update_client(self) -> PrivilegedUpdateClient:
        if self._client_factory is not None:
            return self._client_factory(self)
        return PrivilegedUpdateClient(parent=self)

    def _handle_client_completed(self, success: bool, message: str) -> None:
        self._set_operation_controls_enabled(True)
        self._active_client = None
        self.busy_changed.emit(False)
        if not success:
            self.status_label.setText(message)
            QMessageBox.warning(
                self,
                self.tr("Operation Failed"),
                message or self.tr("The selected optional source operation failed."),
            )
            return

        self.status_label.setText(message)
        self._refresh_snapshot(notify_parent=True)

    def _refresh_snapshot(self, *, notify_parent: bool) -> None:
        snapshot = self._service.optional_sources_snapshot()
        self._snapshot = snapshot
        self._rebuild_cards()
        if notify_parent:
            self.snapshot_changed.emit(snapshot)

    def _set_operation_controls_enabled(self, enabled: bool) -> None:
        for button in self._operation_buttons:
            button.setEnabled(enabled)

    def _source_title(self, source: UpdateSource) -> str:
        return self._source_ui(source).title

    def _source_summary_text(self, source: UpdateSource) -> str:
        return self._source_ui(source).summary

    def _source_ui(self, source: UpdateSource) -> OptionalSourceUi:
        return {
            UpdateSource.AUR: OptionalSourceUi(
                title=self.tr("AUR"),
                summary=self.tr("Community package updates via a supported helper."),
                icon_key="aur",
                remove_limit=None,
            ),
            UpdateSource.FLATPAK: OptionalSourceUi(
                title=self.tr("Flatpak"),
                summary=self.tr("App and runtime updates from Flatpak remotes."),
                icon_key="flatpak",
            ),
            UpdateSource.FIRMWARE: OptionalSourceUi(
                title=self.tr("Device Firmware"),
                summary=self.tr("BIOS, UEFI, and device firmware updates via fwupd/LVFS."),
                icon_key="firmware",
            ),
        }[source]

    def _state_kind(self, status: OptionalSourceStatus) -> str:
        if status.source is UpdateSource.AUR:
            return "enabled" if status.active else "disabled"
        if status.active or status.installed:
            return "enabled"
        return "disabled"

    def _status_badge_text(self, status: OptionalSourceStatus) -> str:
        return self.tr("Enabled") if self._state_kind(status) == "enabled" else self.tr("Disabled")

    def _status_detail_text(self, status: OptionalSourceStatus) -> str:
        if status.source is UpdateSource.AUR:
            if status.active:
                return self.tr(
                    "{status}. PKGBUILD review is required before AUR installation."
                ).format(status=status.status_text)
            return status.status_text

        if status.source is UpdateSource.FLATPAK:
            if status.installed:
                return self.tr("Flatpak support is available on this system.")
            return self.tr("Install Flatpak to enable app and runtime updates.")

        if status.source is UpdateSource.FIRMWARE:
            if status.active:
                return self.tr("fwupd is ready. Device firmware updates will appear only when available.")
            if status.installed:
                return status.status_text
            return self.tr("Install fwupd to enable device firmware updates.")

        return status.status_text

    def _source_icon_badge(self, source: UpdateSource) -> QLabel:
        label = QLabel()
        label.setObjectName("optionalSourceIconBadge")
        label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        pixmap = self._source_icon_pixmap(source)
        if pixmap.isNull():
            label.setText(self._source_title(source)[:1])
        else:
            label.setPixmap(pixmap)
        return label

    def _source_icon_pixmap(self, source: UpdateSource) -> QPixmap:
        logo_path = counter_logo_path(self._source_ui(source).icon_key)
        if logo_path is None:
            return QPixmap()
        return QIcon(str(Path(logo_path))).pixmap(20, 20)
