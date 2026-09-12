from __future__ import annotations

from PySide6.QtCore import QEvent, QSize, QTimer, Signal
from PySide6.QtGui import QHelpEvent, QIcon, QPalette
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QToolTip,
    QVBoxLayout,
    QWidget,
)


from archupdater.resources.assets import github_logo_path


class ActionBarWidget(QFrame):
    check_requested = Signal()
    update_requested = Signal()
    arch_news_requested = Signal()
    preferences_requested = Signal()
    github_requested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("actionBar")
        self._persistent_status_text = ""
        self._preferences_busy_tooltip = self.tr(
            "Preferences are not available while a scan or installation is running."
        )
        self.setMouseTracking(True)

        outer_layout = QVBoxLayout(self)
        outer_layout.setContentsMargins(0, 0, 0, 0)
        outer_layout.setSpacing(10)

        layout = QHBoxLayout()
        layout.setSpacing(12)

        self.check_button = QPushButton(self.tr("Check for Updates"))
        self.check_button.setObjectName("checkButton")
        self.check_button.setProperty("actionRole", "secondary")
        self.check_button.setIcon(QIcon.fromTheme("view-refresh"))
        self.check_button.clicked.connect(self.check_requested)

        self.update_button = QPushButton(self.tr("Update"))
        self.update_button.setObjectName("updateButton")
        self.update_button.setProperty("actionRole", "primary")
        self.update_button.setIcon(QIcon.fromTheme("system-software-update"))
        self.update_button.clicked.connect(self.update_requested)

        self.arch_news_button = QPushButton(self.tr("Arch News"))
        self.arch_news_button.setObjectName("utilityButton")
        self.arch_news_button.setIcon(QIcon.fromTheme("news-subscribe"))
        self.arch_news_button.setProperty("newsState", "read")
        self.arch_news_button.clicked.connect(self.arch_news_requested)

        self.preferences_button = QPushButton(self.tr("Preferences"))
        self.preferences_button.setObjectName("preferencesButton")
        self.preferences_button.setIcon(QIcon.fromTheme("configure"))
        self.preferences_button.clicked.connect(self.preferences_requested)
        self.preferences_button.setToolTip(self._preferences_busy_tooltip)
        self.preferences_button.setMouseTracking(True)
        self.installEventFilter(self)
        self.preferences_button.installEventFilter(self)

        self.github_button = QPushButton(self.tr("GitHub"))
        self.github_button.setObjectName("githubButton")
        self.github_button.setIconSize(QSize(20, 20))
        self._sync_github_icon()
        self.github_button.clicked.connect(self.github_requested)

        self.status_label = QLabel()
        self.status_label.setObjectName("statusLabel")
        self._transient_timer = QTimer(self)
        self._transient_timer.setSingleShot(True)
        self._transient_timer.timeout.connect(self._restore_persistent_status)

        layout.addWidget(self.preferences_button)
        layout.addWidget(self.arch_news_button)
        self.set_github_release("")
        layout.addWidget(self.github_button)
        layout.addStretch(1)
        layout.addWidget(self.status_label)
        layout.addWidget(self.check_button)
        layout.addWidget(self.update_button)

        self.notice_label = QLabel()
        self.notice_label.setObjectName("warningText")
        self.notice_label.setWordWrap(True)
        self.notice_label.hide()

        outer_layout.addLayout(layout)
        outer_layout.addWidget(self.notice_label)

    def _sync_github_icon(self) -> None:
        dark = self.palette().color(QPalette.ColorRole.Button).lightness() < 128
        self.github_button.setIcon(QIcon(str(github_logo_path(dark=dark))))

    def changeEvent(self, event: QEvent) -> None:
        super().changeEvent(event)
        if event.type() == QEvent.Type.PaletteChange and hasattr(self, "github_button"):
            self._sync_github_icon()

    def set_github_release(self, tag: str) -> None:
        available = bool(tag)
        self.github_button.setText(self.tr("Update") if available else "")
        self.github_button.setProperty("updateAvailable", available)
        tooltip = (
            self.tr("ArchUpdater {version} is available on GitHub").format(version=tag)
            if available else self.tr("GitHub")
        )
        self.github_button.setToolTip(tooltip)
        self.github_button.setAccessibleName(tooltip)
        self._refresh_style(self.github_button)
        self.github_button.setFixedWidth(
            max(96, self.github_button.sizeHint().width()) if available else 40
        )

    def set_status_text(self, text: str) -> None:
        self._persistent_status_text = text
        self.status_label.setToolTip(text)
        if not self._transient_timer.isActive():
            self.status_label.setText(text)

    def clear_status_text(self) -> None:
        self._persistent_status_text = ""
        self.status_label.setToolTip("")
        if not self._transient_timer.isActive():
            self.status_label.clear()

    def show_transient_message(self, text: str, timeout_ms: int = 3200) -> None:
        self.status_label.setText(text)
        self._transient_timer.start(timeout_ms)

    def set_notice_text(self, text: str) -> None:
        self.notice_label.setText(text)
        self.notice_label.setVisible(bool(text))

    def clear_notice_text(self) -> None:
        self.notice_label.clear()
        self.notice_label.hide()

    def set_update_enabled(self, enabled: bool) -> None:
        self.update_button.setEnabled(enabled)

    def set_update_selection(self, count: int) -> None:
        self.update_button.setEnabled(count > 0)
        if count <= 0:
            self.update_button.setText(self.tr("Update"))
        elif count == 1:
            self.update_button.setText(self.tr("Update 1 item"))
        else:
            self.update_button.setText(
                self.tr("Update {count} items").format(count=count)
            )

    def set_arch_news_count(self, count: int) -> None:
        self.arch_news_button.setText(
            self.tr("Arch News")
            if count <= 0
            else self.tr("Arch News ({count})").format(count=count)
        )
        self.arch_news_button.setProperty("newsState", "unread" if count > 0 else "read")
        self._refresh_style(self.arch_news_button)

    def set_busy(self, busy: bool) -> None:
        self.check_button.setEnabled(not busy)
        self.preferences_button.setEnabled(not busy)
        self.github_button.setEnabled(not busy)
        if not busy:
            QToolTip.hideText()

    def _restore_persistent_status(self) -> None:
        self.status_label.setText(self._persistent_status_text)

    def eventFilter(self, watched, event) -> bool:  # type: ignore[override]
        if watched in {self, self.preferences_button}:
            if event.type() == QEvent.Type.ToolTip:
                help_event = event
                if isinstance(help_event, QHelpEvent):
                    self._maybe_show_preferences_busy_tooltip(help_event.globalPos())
                return True
            if event.type() == QEvent.Type.MouseMove:
                global_pos = watched.mapToGlobal(event.position().toPoint())  # type: ignore[attr-defined]
                self._maybe_show_preferences_busy_tooltip(global_pos)
            elif event.type() in {QEvent.Type.Leave, QEvent.Type.HoverLeave}:
                QToolTip.hideText()
        return super().eventFilter(watched, event)

    def _maybe_show_preferences_busy_tooltip(self, global_pos) -> None:  # noqa: ANN001
        if self.preferences_button.isEnabled():
            QToolTip.hideText()
            return
        local_pos = self.preferences_button.mapFromGlobal(global_pos)
        if self.preferences_button.rect().contains(local_pos):
            QToolTip.showText(
                global_pos,
                self._preferences_busy_tooltip,
                self.preferences_button,
            )
        else:
            QToolTip.hideText()

    def _refresh_style(self, widget: QWidget) -> None:
        widget.style().unpolish(widget)
        widget.style().polish(widget)
        widget.update()
