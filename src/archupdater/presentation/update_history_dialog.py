from __future__ import annotations

from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QDateTime, QLocale, Qt
from PySide6.QtGui import QFont, QFontDatabase, QIcon, QPixmap
from PySide6.QtWidgets import (
    QDialog,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QStyle,
    QToolButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from archupdater.application.update_sources.descriptors import UPDATE_STEP_ORDER, source_descriptors
from archupdater.domain.enums import UpdatePackageOutcome, UpdateProgressStepState, UpdateResult
from archupdater.domain.progress import UpdateProgressPackage, UpdateProgressSnapshot
from archupdater.infrastructure.update_history import SavedUpdate
from archupdater.presentation.update_log_export import clean_console_lines
from archupdater.presentation.update_progress_dialog import export_update_logs, write_logs_to_folder


SESSION_ROLE = Qt.ItemDataRole.UserRole
STATUS_ICONS = {
    "ok": ("emblem-success", QStyle.StandardPixmap.SP_DialogApplyButton),
    "warning": ("emblem-warning", QStyle.StandardPixmap.SP_MessageBoxWarning),
    "error": ("emblem-error", QStyle.StandardPixmap.SP_MessageBoxCritical),
}


class UpdateHistoryDialog(QDialog):
    def __init__(self, history: list[SavedUpdate], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._history = history
        self._selected_index = 0
        self.setObjectName("updateHistoryDialog")
        self.setWindowTitle(self.tr("Update History"))
        self.setWindowModality(Qt.WindowModality.NonModal)
        self.setModal(False)
        self.resize(1080, 740)
        self.setMinimumSize(760, 520)
        self._icons = {
            status: QIcon.fromTheme(name, self.style().standardIcon(fallback))
            for status, (name, fallback) in STATUS_ICONS.items()
        }
        # Rows without a status keep their text aligned with the rows that have an icon.
        blank = QPixmap(16, 16)
        blank.fill(Qt.GlobalColor.transparent)
        self._icons[None] = QIcon(blank)

        self.root_layout = root_layout = QVBoxLayout(self)
        root_layout.setContentsMargins(24, 22, 24, 20)
        root_layout.setSpacing(12)
        title = QLabel(self.tr("Update History"))
        title.setObjectName("updateHeroTitle")
        subtitle = QLabel(self.tr(
            "The last {count} update sessions, newest first. Expand a session to see what was "
            "updated and what was not."
        ).format(count=len(history)))
        subtitle.setObjectName("updateHeroSubtitle")
        subtitle.setWordWrap(True)
        root_layout.addWidget(title)
        root_layout.addWidget(subtitle)

        self.tree = QTreeWidget()
        self.tree.setObjectName("updateHistoryTree")
        self.tree.setColumnCount(3)
        self.tree.setHeaderLabels([self.tr("Update"), self.tr("Details"), self.tr("Result")])
        self.tree.setUniformRowHeights(True)
        header = self.tree.header()
        header.setStretchLastSection(False)
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        for index, entry in enumerate(history):
            session = self._session_item(index, entry)
            self.tree.addTopLevelItem(session)
            for child in range(session.childCount()):
                session.child(child).setExpanded(True)
        self.tree.currentItemChanged.connect(self._on_current_item_changed)
        root_layout.addWidget(self.tree, stretch=1)

        self.detail_label = QLabel()
        self.detail_label.setObjectName("mutedText")
        self.detail_label.setWordWrap(True)
        self.detail_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        root_layout.addWidget(self.detail_label)

        self.log_panel = QFrame()
        self.log_panel.setObjectName("updateLogPanel")
        log_layout = QVBoxLayout(self.log_panel)
        log_layout.setContentsMargins(12, 8, 12, 12)
        log_layout.setSpacing(8)
        self.log_toggle = QToolButton()
        self.log_toggle.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.log_toggle.setCheckable(True)
        self.log_toggle.toggled.connect(self._set_log_expanded)
        log_layout.addWidget(self.log_toggle, alignment=Qt.AlignmentFlag.AlignLeft)
        self.console_log = QPlainTextEdit()
        self.console_log.setObjectName("updateConsoleLog")
        self.console_log.setReadOnly(True)
        self.console_log.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self.console_log.setFont(QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont))
        self.console_log.setMinimumHeight(120)
        log_layout.addWidget(self.console_log)
        root_layout.addWidget(self.log_panel)
        self._set_log_expanded(False)

        actions = QHBoxLayout()
        actions.addStretch(1)
        self.export_logs_button = QPushButton(self.tr("Export Logs"))
        self.export_logs_button.clicked.connect(self._export_logs)
        self.close_button = QPushButton(self.tr("Close"))
        self.close_button.clicked.connect(self.accept)
        actions.addWidget(self.export_logs_button)
        actions.addWidget(self.close_button)
        root_layout.addLayout(actions)

        if history:
            newest = self.tree.topLevelItem(0)
            newest.setExpanded(True)
            self.tree.setCurrentItem(newest)
        self._show_session(0)

    @property
    def selected_entry(self) -> SavedUpdate | None:
        if not self._history:
            return None
        return self._history[self._selected_index]

    def _session_item(self, index: int, entry: SavedUpdate) -> QTreeWidgetItem:
        snapshot = entry.snapshot
        item = QTreeWidgetItem([
            self._format_date(entry.completed_at),
            self._session_counts(snapshot),
            self._result_text(snapshot.result),
        ])
        item.setData(0, SESSION_ROLE, index)
        font = QFont(item.font(0))
        font.setBold(True)
        for column in range(3):
            item.setFont(column, font)
        item.setIcon(2, self._icons[{
            UpdateResult.SUCCESS: "ok",
            UpdateResult.PARTIAL_SUCCESS: "warning",
            UpdateResult.FAILED: "error",
        }.get(snapshot.result)])
        item.addChildren(self._source_items(index, snapshot))
        return item

    def _source_items(self, index: int, snapshot: UpdateProgressSnapshot) -> list[QTreeWidgetItem]:
        descriptors = source_descriptors(self.tr)
        step_states = {step.phase: step.state for step in snapshot.steps}
        groups = []
        for source in UPDATE_STEP_ORDER:
            descriptor = descriptors[source]
            packages = [package for package in snapshot.packages if package.source is source]
            state = step_states.get(descriptor.progress_phase)
            if not packages and state is None:
                continue
            label = descriptor.update_list_title
            if packages:
                label = self.tr("{source} ({count})").format(source=label, count=len(packages))
            group = QTreeWidgetItem([label, "", self._state_text(state) if state else ""])
            group.setData(0, SESSION_ROLE, index)
            group.setIcon(2, self._icons[{
                UpdateProgressStepState.COMPLETED: "ok",
                UpdateProgressStepState.INCOMPLETE: "warning",
                UpdateProgressStepState.RUNNING: "warning",
                UpdateProgressStepState.FAILED: "error",
            }.get(state)])
            for package in packages:
                group.addChild(self._package_item(index, package))
            groups.append(group)
        return groups

    def _package_item(self, index: int, package: UpdateProgressPackage) -> QTreeWidgetItem:
        name = package.name
        if package.scope == "user":
            name = self.tr("{name} (user)").format(name=name)
        elif package.scope == "system":
            name = self.tr("{name} (system)").format(name=name)
        if package.current_version and package.new_version:
            version = f"{package.current_version} → {package.new_version}"
        else:
            version = package.new_version or package.current_version
        item = QTreeWidgetItem([name, version, self._outcome_text(package.outcome)])
        item.setData(0, SESSION_ROLE, index)
        item.setToolTip(0, package.name)
        item.setToolTip(1, version)
        item.setIcon(2, self._icons[{
            UpdatePackageOutcome.UPDATED: "ok",
            UpdatePackageOutcome.UNCONFIRMED: "warning",
            UpdatePackageOutcome.NOT_UPDATED: "error",
        }.get(package.outcome)])
        return item

    def _session_counts(self, snapshot: UpdateProgressSnapshot) -> str:
        outcomes = [package.outcome for package in snapshot.packages]
        updated = outcomes.count(UpdatePackageOutcome.UPDATED)
        unconfirmed = outcomes.count(UpdatePackageOutcome.UNCONFIRMED)
        not_updated = len(outcomes) - updated - unconfirmed
        parts = []
        if updated:
            parts.append(self.tr("Updated: {count}").format(count=updated))
        if not_updated:
            parts.append(self.tr("Not updated: {count}").format(count=not_updated))
        if unconfirmed:
            parts.append(self.tr("To verify: {count}").format(count=unconfirmed))
        return " · ".join(parts)

    def _format_date(self, completed_at: datetime) -> str:
        local = completed_at.astimezone().replace(tzinfo=None)
        return QLocale().toString(QDateTime(local), QLocale.FormatType.ShortFormat)

    def _result_text(self, result: UpdateResult) -> str:
        return {
            UpdateResult.SUCCESS: self.tr("Completed"),
            UpdateResult.PARTIAL_SUCCESS: self.tr("Completed with issues"),
            UpdateResult.FAILED: self.tr("Failed"),
            UpdateResult.CANCELLED: self.tr("Cancelled"),
            UpdateResult.IN_PROGRESS: "",
        }[result]

    def _state_text(self, state: UpdateProgressStepState) -> str:
        return {
            UpdateProgressStepState.PENDING: self.tr("Not executed"),
            UpdateProgressStepState.RUNNING: self.tr("Incomplete"),
            UpdateProgressStepState.COMPLETED: self.tr("Completed"),
            UpdateProgressStepState.INCOMPLETE: self.tr("Incomplete"),
            UpdateProgressStepState.FAILED: self.tr("Failed"),
            UpdateProgressStepState.NOT_EXECUTED: self.tr("Not executed"),
        }[state]

    def _outcome_text(self, outcome: UpdatePackageOutcome | None) -> str:
        if outcome is None:
            return ""
        return {
            UpdatePackageOutcome.UPDATED: self.tr("Updated"),
            UpdatePackageOutcome.SKIPPED: self.tr("Skipped"),
            UpdatePackageOutcome.NOT_UPDATED: self.tr("Not updated"),
            UpdatePackageOutcome.NOT_EXECUTED: self.tr("Not executed"),
            UpdatePackageOutcome.UNCONFIRMED: self.tr("Check the log"),
        }[outcome]

    def _on_current_item_changed(
        self, current: QTreeWidgetItem | None, _previous: QTreeWidgetItem | None,
    ) -> None:
        if current is None:
            return
        index = current.data(0, SESSION_ROLE)
        if isinstance(index, int) and index != self._selected_index:
            self._show_session(index)

    def _show_session(self, index: int) -> None:
        entry = self._history[index] if 0 <= index < len(self._history) else None
        self._selected_index = index if entry is not None else 0
        self.export_logs_button.setEnabled(entry is not None)
        if entry is None:
            self.detail_label.clear()
            self.console_log.clear()
            self._sync_log_toggle_text("")
            return
        snapshot = entry.snapshot
        details = [snapshot.subtitle]
        if snapshot.result is not UpdateResult.SUCCESS and snapshot.summary_next_step:
            details.append(snapshot.summary_next_step)
        self.detail_label.setText("\n".join(text for text in details if text))
        lines = clean_console_lines(snapshot.console_lines)
        self.console_log.setPlainText(
            "\n".join(lines) if lines else self.tr("No update log was captured.")
        )
        self._sync_log_toggle_text(self._format_date(entry.completed_at))

    def _sync_log_toggle_text(self, date: str) -> None:
        self.log_toggle.setText(
            self.tr("Update Log ({date})").format(date=date) if date else self.tr("Update Log")
        )

    def _set_log_expanded(self, expanded: bool) -> None:
        self.console_log.setVisible(expanded)
        self.log_toggle.setArrowType(Qt.ArrowType.DownArrow if expanded else Qt.ArrowType.RightArrow)
        # The sessions stay the main content: an open log takes a third of the space.
        self.root_layout.setStretch(self.root_layout.indexOf(self.tree), 2)
        self.root_layout.setStretch(self.root_layout.indexOf(self.log_panel), int(expanded))

    def _export_logs(self) -> None:
        entry = self.selected_entry
        if entry is not None:
            export_update_logs(self, entry.snapshot, completed_at=entry.completed_at)

    def _write_log_export(self, folder: Path) -> Path:
        entry = self.selected_entry
        if entry is None:
            raise OSError("No update session is available to export.")
        return write_logs_to_folder(folder, entry.snapshot, completed_at=entry.completed_at)
