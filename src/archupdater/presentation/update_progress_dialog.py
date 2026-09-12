from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, QTimer, qVersion
from PySide6.QtGui import QCloseEvent, QFontDatabase
from PySide6.QtWidgets import (
    QDialog,
    QFileDialog,
    QFrame,
    QGridLayout,
    QToolButton,
    QCheckBox,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QProgressBar,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from archupdater.domain.enums import UpdateProgressPhase, UpdateProgressStepState
from archupdater.domain.progress import UpdateProgressSnapshot, UpdateProgressStep
from archupdater.presentation.update_log_export import (
    RuntimeExportInfo,
    clean_console_lines,
    write_update_log_export,
)


class UpdateStepRow(QFrame):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("updateStepRow")
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(10)
        self.badge = QLabel()
        self.badge.setObjectName("updateStepBadge")
        self.badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.badge.setFixedSize(28, 28)
        text_layout = QVBoxLayout()
        text_layout.setSpacing(3)
        self.title = QLabel()
        self.title.setObjectName("updateStepTitle")
        self.state_text = QLabel()
        self.state_text.setObjectName("updateStepState")
        self.state_text.setWordWrap(True)
        text_layout.addWidget(self.title)
        text_layout.addWidget(self.state_text)
        layout.addWidget(self.badge)
        layout.addLayout(text_layout, stretch=1)

    def apply_step(
        self, step: UpdateProgressStep, *, step_number: int, total_steps: int,
        state_text: str, badge_text: str,
    ) -> None:
        self.setToolTip(self.tr("Step {current} of {total}").format(
            current=step_number, total=total_steps,
        ))
        self.title.setText(step.label)
        self.state_text.setText(state_text)
        self.badge.setText(badge_text)
        for widget in (self, self.badge, self.state_text):
            widget.setProperty("stepState", step.state.value)
            widget.style().unpolish(widget)
            widget.style().polish(widget)


class UpdateProgressDialog(QDialog):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("updateProgressDialog")
        self.setWindowTitle(self.tr("Installing Updates"))
        self.setWindowModality(Qt.WindowModality.NonModal)
        self.setModal(False)
        self.resize(1080, 740)
        self.setMinimumSize(900, 620)
        self._final_state = False
        self._waiting_for_response = False
        self._latest_snapshot: UpdateProgressSnapshot | None = None
        self._console_auto_scroll = True
        self._updating_console_scroll = False
        self._success_close_timer = QTimer(self)
        self._success_close_timer.setSingleShot(True)
        self._success_close_timer.setInterval(1500)
        self._success_close_timer.timeout.connect(self.accept)

        self.root_layout = QVBoxLayout(self)
        self.root_layout.setContentsMargins(24, 22, 24, 20)
        self.root_layout.setSpacing(14)
        hero = QWidget()
        hero_layout = QVBoxLayout(hero)
        hero_layout.setContentsMargins(0, 0, 0, 0)
        hero_layout.setSpacing(8)
        self.hero_title = QLabel()
        self.hero_title.setObjectName("updateHeroTitle")
        self.hero_subtitle = QLabel()
        self.hero_subtitle.setObjectName("updateHeroSubtitle")
        self.hero_subtitle.setWordWrap(True)
        self.hero_subtitle.setMaximumHeight(70)
        hero_layout.addWidget(self.hero_title)
        hero_layout.addWidget(self.hero_subtitle)
        progress_row = QHBoxLayout()
        self.progress_bar = QProgressBar()
        self.progress_bar.setObjectName("updateProgressBar")
        self.progress_bar.setTextVisible(False)
        self.progress_bar.setFixedHeight(8)
        self.progress_percent = QLabel()
        self.progress_percent.setObjectName("updateHeroPercent")
        progress_row.addWidget(self.progress_bar, stretch=1)
        progress_row.addWidget(self.progress_percent)
        hero_layout.addLayout(progress_row)
        self.root_layout.addWidget(hero)

        self.steps_container = QWidget()
        self.steps_layout = QHBoxLayout(self.steps_container)
        self.steps_layout.setContentsMargins(0, 0, 0, 0)
        self.steps_layout.setSpacing(8)
        self.root_layout.addWidget(self.steps_container)
        self._step_rows: list[UpdateStepRow] = []

        self.notice_card = QFrame()
        self.notice_card.setObjectName("updateNoticeCard")
        notice_layout = QVBoxLayout(self.notice_card)
        notice_layout.setContentsMargins(12, 10, 12, 10)
        notice_layout.setSpacing(4)
        self.notice_title = QLabel()
        self.notice_title.setObjectName("updateNoticeTitle")
        self.notice_text = QLabel()
        self.notice_text.setObjectName("updateNoticeText")
        self.notice_text.setWordWrap(True)
        notice_layout.addWidget(self.notice_title)
        notice_layout.addWidget(self.notice_text)
        self.notice_card.hide()
        self.root_layout.addWidget(self.notice_card)

        self.summary_card = QFrame()
        self.summary_card.setObjectName("updateSummaryCard")
        summary_layout = QGridLayout(self.summary_card)
        self._summary_layout = summary_layout
        self._summary_column = 0
        summary_layout.setContentsMargins(14, 12, 14, 12)
        summary_layout.setHorizontalSpacing(18)
        summary_layout.setVerticalSpacing(6)
        self.summary_caption = QLabel(self.tr("Session Summary"))
        self.summary_caption.setObjectName("sectionCaption")
        summary_layout.addWidget(self.summary_caption, 0, 0, 1, 4)
        for column, (key, title) in enumerate((
            ("completed", self.tr("Completed")),
            ("incomplete", self.tr("Incomplete")),
            ("failed", self.tr("Failed")),
            ("not_executed", self.tr("Not executed")),
        )):
            heading = QLabel(title)
            heading.setObjectName("updateSummaryHeading")
            body = QLabel()
            body.setObjectName("updateSummaryText")
            body.setWordWrap(True)
            setattr(self, f"summary_{key}_heading", heading)
            setattr(self, f"summary_{key}_text", body)
            summary_layout.addWidget(heading, 1, column)
            summary_layout.addWidget(body, 2, column)
            summary_layout.setColumnStretch(column, 1)
        self.summary_next_heading = QLabel(self.tr("Next step"))
        self.summary_next_heading.setObjectName("updateSummaryHeading")
        self.summary_next_text = QLabel()
        self.summary_next_text.setObjectName("updateSummaryText")
        self.summary_next_text.setWordWrap(True)
        summary_layout.addWidget(self.summary_next_heading, 3, 0, 1, 4)
        summary_layout.addWidget(self.summary_next_text, 4, 0, 1, 4)
        self.summary_card.hide()
        self.root_layout.addWidget(self.summary_card)

        self.log_panel = QFrame()
        self.log_panel.setObjectName("updateLogPanel")
        log_layout = QVBoxLayout(self.log_panel)
        log_layout.setContentsMargins(12, 8, 12, 12)
        log_layout.setSpacing(8)
        self.log_toggle = QToolButton()
        self.log_toggle.setText(self.tr("Live Activity"))
        self.log_toggle.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.log_toggle.setCheckable(True)
        self.log_toggle.setChecked(True)
        self.log_toggle.setArrowType(Qt.ArrowType.DownArrow)
        self.log_toggle.toggled.connect(self._set_log_expanded)
        log_layout.addWidget(self.log_toggle, alignment=Qt.AlignmentFlag.AlignLeft)
        self.console_log = QPlainTextEdit()
        self.console_log.setObjectName("updateConsoleLog")
        self.console_log.setReadOnly(True)
        self.console_log.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self.console_log.setMaximumBlockCount(2000)
        self.console_log.setFont(QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont))
        self.console_log.verticalScrollBar().valueChanged.connect(self._sync_console_auto_scroll)
        log_layout.addWidget(self.console_log, stretch=1)
        self.root_layout.addWidget(self.log_panel, stretch=1)
        self.root_layout.addStretch(0)
        self._spacer_index = self.root_layout.count() - 1
        actions = QHBoxLayout()
        self.auto_close_checkbox = QCheckBox(
            self.tr("Close automatically if all updates succeed")
        )
        self.auto_close_checkbox.setChecked(False)
        self.auto_close_checkbox.toggled.connect(self._sync_success_close_timer)
        actions.addWidget(self.auto_close_checkbox)
        actions.addStretch(1)
        self.export_logs_button = QPushButton(self.tr("Export Logs"))
        self.export_logs_button.setEnabled(False)
        self.export_logs_button.clicked.connect(self._export_logs)
        self.close_button = QPushButton(self.tr("Close"))
        self.close_button.setEnabled(False)
        self.close_button.clicked.connect(self.accept)
        actions.addWidget(self.export_logs_button)
        actions.addWidget(self.close_button)
        self.root_layout.addLayout(actions)

    def apply_snapshot(self, snapshot: UpdateProgressSnapshot) -> None:
        self._latest_snapshot = snapshot
        self.hero_title.setText(snapshot.title)
        self._apply_operation(snapshot)
        self._apply_console_lines(snapshot.console_lines)
        self.notice_card.setVisible(bool(snapshot.notice_title or snapshot.notice_text))
        self.notice_title.setText(snapshot.notice_title or "")
        self.notice_text.setText(snapshot.notice_text or "")
        self._apply_summary(snapshot)
        visible_steps = self._visible_steps(snapshot.steps)
        self._ensure_step_rows(visible_steps)
        for index, (row, step) in enumerate(zip(self._step_rows, visible_steps)):
            row.apply_step(
                step,
                step_number=index + 1,
                total_steps=len(visible_steps),
                state_text=self._state_text(step.state),
                badge_text=self._badge_text(index, step.state),
            )

        if snapshot.final_state and snapshot.success is False and not self._final_state:
            self.log_toggle.setChecked(True)
        self._final_state = snapshot.final_state
        self.close_button.setEnabled(snapshot.final_state)
        self.export_logs_button.setEnabled(bool(snapshot.console_lines) or snapshot.final_state)
        self._sync_success_close_timer()

    def _apply_operation(self, snapshot: UpdateProgressSnapshot) -> None:
        if self._waiting_for_response and not snapshot.final_state:
            subtitle = self.tr("Waiting for your response")
            self.progress_bar.show()
            self.progress_bar.setRange(0, 100)
            self.progress_bar.setValue(0)
            self.progress_percent.hide()
        elif snapshot.final_state:
            subtitle = self._failure_detail(snapshot) or snapshot.subtitle
            self.progress_bar.setRange(0, 100)
            complete = bool(snapshot.success and not snapshot.summary_incomplete)
            self.progress_bar.setValue(100 if complete else 0)
            self.progress_bar.setVisible(complete)
            self.progress_percent.setVisible(complete)
            self.progress_percent.setText("100%" if complete else "")
        else:
            subtitle = snapshot.activity_text or snapshot.subtitle
            self.progress_bar.show()
            measured = snapshot.activity_percent
            self.progress_bar.setRange(0, 0 if measured is None else 100)
            if measured is not None:
                self.progress_bar.setValue(max(0, min(100, measured)))
            self.progress_percent.setVisible(measured is not None)
            self.progress_percent.setText("" if measured is None else f"{measured}%")
        self.hero_subtitle.setText(subtitle)
        self.hero_subtitle.setToolTip(subtitle)

    def _failure_detail(self, snapshot: UpdateProgressSnapshot) -> str:
        if snapshot.success is not False:
            return ""
        failed_logs = [
            line for step in snapshot.steps
            if step.state is UpdateProgressStepState.FAILED for line in step.log_lines
        ]
        lines = clean_console_lines(failed_logs or snapshot.console_lines)
        for line in reversed(lines):
            if " are in conflict" in line.casefold():
                return line.removeprefix(":: ")
        for line in reversed(lines):
            lowered = line.casefold()
            if lowered.startswith(("error:", "fatal:", "==> error:")):
                return line.removeprefix(":: ")
        return ""

    def set_waiting_for_response(self, waiting: bool) -> None:
        self._waiting_for_response = waiting
        if self._latest_snapshot is not None:
            self._apply_operation(self._latest_snapshot)

    def _set_log_expanded(self, expanded: bool) -> None:
        self.console_log.setVisible(expanded)
        self.log_toggle.setArrowType(Qt.ArrowType.DownArrow if expanded else Qt.ArrowType.RightArrow)
        self.log_panel.setMaximumHeight(16777215 if expanded else 52)
        self.root_layout.setStretch(self.root_layout.indexOf(self.log_panel), int(expanded))
        self.root_layout.setStretch(self._spacer_index, int(not expanded))

    def _sync_success_close_timer(self) -> None:
        snapshot = self._latest_snapshot
        if (
            snapshot is not None
            and snapshot.final_state
            and snapshot.success
            and not snapshot.summary_incomplete
            and self.auto_close_checkbox.isChecked()
        ):
            self._success_close_timer.start()
        else:
            self._success_close_timer.stop()

    def _visible_steps(self, steps: list[UpdateProgressStep]) -> list[UpdateProgressStep]:
        return [
            step
            for step in steps
            if step.phase is not UpdateProgressPhase.COMPLETED
        ]

    def _ensure_step_rows(self, steps: list[UpdateProgressStep]) -> None:
        while len(self._step_rows) < len(steps):
            row = UpdateStepRow()
            self.steps_layout.addWidget(row, stretch=1)
            self._step_rows.append(row)

        while len(self._step_rows) > len(steps):
            row = self._step_rows.pop()
            self.steps_layout.removeWidget(row)
            row.hide()
            row.deleteLater()

    def _apply_console_lines(self, lines: list[str]) -> None:
        text = "\n".join(clean_console_lines(lines))
        if self.console_log.toPlainText() == text:
            if self._console_auto_scroll:
                self._scroll_console_to_bottom()
            return

        scrollbar = self.console_log.verticalScrollBar()
        previous_position = scrollbar.value()
        horizontal_position = self.console_log.horizontalScrollBar().value()
        self._updating_console_scroll = True
        self.console_log.setPlainText(text)
        scrollbar.setValue(scrollbar.maximum() if self._console_auto_scroll else previous_position)
        self.console_log.horizontalScrollBar().setValue(horizontal_position)
        self._updating_console_scroll = False
        if self._console_auto_scroll:
            QTimer.singleShot(0, self._scroll_console_to_bottom_if_auto)

    def _sync_console_auto_scroll(self, value: int) -> None:
        if self._updating_console_scroll:
            return
        scrollbar = self.console_log.verticalScrollBar()
        self._console_auto_scroll = value >= scrollbar.maximum() - 4

    def _scroll_console_to_bottom_if_auto(self) -> None:
        if self._console_auto_scroll:
            self._scroll_console_to_bottom()

    def _scroll_console_to_bottom(self) -> None:
        scrollbar = self.console_log.verticalScrollBar()
        self._updating_console_scroll = True
        scrollbar.setValue(scrollbar.maximum())
        self._updating_console_scroll = False

    def _state_text(self, state: UpdateProgressStepState) -> str:
        mapping = {
            UpdateProgressStepState.PENDING: self.tr("Queued"),
            UpdateProgressStepState.RUNNING: self.tr("In progress"),
            UpdateProgressStepState.COMPLETED: self.tr("Completed"),
            UpdateProgressStepState.INCOMPLETE: self.tr("Incomplete"),
            UpdateProgressStepState.FAILED: self.tr("Failed"),
            UpdateProgressStepState.NOT_EXECUTED: self.tr("Not executed"),
        }
        return mapping[state]

    def _badge_text(self, index: int, state: UpdateProgressStepState) -> str:
        mapping = {
            UpdateProgressStepState.PENDING: str(index + 1),
            UpdateProgressStepState.RUNNING: str(index + 1),
            UpdateProgressStepState.COMPLETED: "✓",
            UpdateProgressStepState.INCOMPLETE: "!",
            UpdateProgressStepState.FAILED: "!",
            UpdateProgressStepState.NOT_EXECUTED: "–",
        }
        return mapping[state]

    def _apply_summary(self, snapshot: UpdateProgressSnapshot) -> None:
        has_summary = bool(
            snapshot.summary_title
            or snapshot.summary_completed
            or snapshot.summary_incomplete
            or snapshot.summary_failed
            or snapshot.summary_not_executed
            or snapshot.summary_next_step
        )
        self.summary_card.setVisible(has_summary)
        if not has_summary:
            self.summary_caption.setText(self.tr("Session Summary"))
            self.summary_completed_text.clear()
            self.summary_incomplete_text.clear()
            self.summary_failed_text.clear()
            self.summary_not_executed_text.clear()
            self.summary_next_text.clear()
            return

        self.summary_caption.setText(snapshot.summary_title or self.tr("Session Summary"))
        self._summary_column = 0
        for column in range(4):
            self._summary_layout.setColumnStretch(column, 0)
        self._set_summary_section(
            self.summary_completed_heading,
            self.summary_completed_text,
            snapshot.summary_completed,
        )
        self._set_summary_section(
            self.summary_incomplete_heading,
            self.summary_incomplete_text,
            snapshot.summary_incomplete,
        )
        self._set_summary_section(
            self.summary_failed_heading,
            self.summary_failed_text,
            snapshot.summary_failed,
        )
        self._set_summary_section(
            self.summary_not_executed_heading,
            self.summary_not_executed_text,
            snapshot.summary_not_executed,
        )
        self.summary_next_heading.setVisible(bool(snapshot.summary_next_step))
        self.summary_next_text.setVisible(bool(snapshot.summary_next_step))
        self.summary_next_text.setText(snapshot.summary_next_step or "")

    def _set_summary_section(self, heading: QLabel, body: QLabel, items: list[str]) -> None:
        visible = bool(items)
        self._summary_layout.removeWidget(heading)
        self._summary_layout.removeWidget(body)
        if visible:
            self._summary_layout.addWidget(heading, 1, self._summary_column)
            self._summary_layout.addWidget(body, 2, self._summary_column)
            self._summary_layout.setColumnStretch(self._summary_column, 1)
            self._summary_column += 1
        heading.setVisible(visible)
        body.setVisible(visible)
        body.setText(", ".join(items))

    def _export_logs(self) -> None:
        folder = QFileDialog.getExistingDirectory(
            self,
            self.tr("Choose Export Folder"),
            str(Path.home()),
            QFileDialog.Option.ShowDirsOnly,
        )
        if not folder:
            return

        try:
            archive_path = self._write_log_export(Path(folder))
        except OSError as exc:
            QMessageBox.warning(
                self,
                self.tr("Export Failed"),
                self.tr("Could not export update logs: {error}").format(error=exc),
            )
            return

        QMessageBox.information(
            self,
            self.tr("Logs Exported"),
            self.tr("Update logs were exported to:\n{path}").format(path=archive_path),
        )

    def _write_log_export(self, folder: Path) -> Path:
        if self._latest_snapshot is None:
            raise OSError("No update session is available to export.")

        return write_update_log_export(
            folder=folder,
            snapshot=self._latest_snapshot,
            runtime=RuntimeExportInfo.current(qt_version=qVersion()),
        )

    def reject(self) -> None:
        if self._final_state:
            super().reject()

    def closeEvent(self, event: QCloseEvent) -> None:
        if not self._final_state:
            event.ignore()
            return
        super().closeEvent(event)
