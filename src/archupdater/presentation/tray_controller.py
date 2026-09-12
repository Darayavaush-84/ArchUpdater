from __future__ import annotations

import time
from collections.abc import Callable

from PySide6.QtCore import QObject, QRect, QRectF, QSize, Qt, QTimer, Slot
from PySide6.QtGui import (
    QAction, QActionGroup, QColor, QFont, QIcon, QPainter, QPainterPath,
    QPalette, QPen, QPixmap,
)
from PySide6.QtWidgets import QApplication, QMenu, QStyle, QSystemTrayIcon, QWidget

from archupdater.application.update_session.protocol import BatchOutcome
from archupdater.domain.check_results import UpdateCheckResult
from archupdater.presentation.tray_status import TrayStatusModel
from archupdater.presentation.update_controller import UpdateController


class TrayController(QObject):
    UPDATES_AVAILABLE_DEBOUNCE_SECONDS = 600
    AUTO_CHECK_INTERVAL_OPTIONS = (6, 12, 24, 72, 168)

    def __init__(
        self,
        *,
        app: QApplication,
        window: QWidget,
        update_controller: UpdateController,
        enabled: bool,
        notifications_enabled: bool,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._app = app
        self._window = window
        self._update_controller = update_controller
        self._enabled = enabled
        self._notifications_enabled = notifications_enabled
        self._last_updates_signature: tuple[tuple[str, ...], float] | None = None
        self._update_started_in_background: bool | None = None
        self._force_next_updates_notification = False
        self._base_icon = self._build_icon()
        self._tray_status = TrayStatusModel(self.tr)
        self._check_action: QAction | None = None
        self._animation_angle = 0
        self._animation_timer = QTimer(self)
        self._animation_timer.setInterval(50)
        self._animation_timer.timeout.connect(self._advance_busy_icon)

        self._tray = QSystemTrayIcon(self._base_icon, self)
        self._sync_tooltip()
        self._menu = self._build_menu()
        self._tray.setContextMenu(self._menu)
        self._tray.activated.connect(self._on_tray_activated)
        self._tray.messageClicked.connect(self._on_message_clicked)

        self._update_controller.check_succeeded.connect(self._on_check_succeeded)
        self._update_controller.check_failed.connect(self._on_check_failed)
        self._update_controller.update_status_changed.connect(self._on_update_status_changed)
        self._update_controller.update_completed.connect(self._on_update_completed)
        self._update_controller.busy_changed.connect(self._on_busy_changed)

        self.apply_settings(enabled=enabled, notifications_enabled=notifications_enabled)

    def is_available(self) -> bool:
        return QSystemTrayIcon.isSystemTrayAvailable()

    def is_active(self) -> bool:
        return self._enabled and self.is_available()

    def apply_settings(self, *, enabled: bool, notifications_enabled: bool) -> None:
        self._enabled = enabled
        self._notifications_enabled = notifications_enabled
        self.retranslate()
        if self.is_active():
            self._tray.show()
            self._sync_tray_icon()
            return
        self._animation_timer.stop()
        self._tray.hide()

    def show_if_enabled(self) -> None:
        if self.is_active():
            self._tray.show()

    def retranslate(self) -> None:
        old_menu = self._menu
        self._menu = self._build_menu()
        self._tray.setContextMenu(self._menu)
        old_menu.deleteLater()
        self._sync_tooltip()

    def _build_menu(self) -> QMenu:
        menu = QMenu()
        menu.aboutToShow.connect(self._sync_menu_state)

        show_action = QAction(self.tr("Show ArchUpdater"), menu)
        show_action.triggered.connect(self._show_window)
        menu.addAction(show_action)

        check_action = QAction(self.tr("Check Now"), menu)
        check_action.triggered.connect(self._request_manual_check)
        menu.addAction(check_action)
        self._check_action = check_action

        self._auto_check_menu = menu.addMenu(self.tr("Automatic Checks"))
        self._auto_check_group = QActionGroup(self._auto_check_menu)
        self._auto_check_group.setExclusive(True)
        self._auto_check_actions: dict[int | None, QAction] = {}

        off_action = QAction(self.tr("Off"), self._auto_check_menu)
        off_action.setCheckable(True)
        off_action.triggered.connect(lambda checked=False: self._set_auto_check_schedule(None))
        self._auto_check_group.addAction(off_action)
        self._auto_check_menu.addAction(off_action)
        self._auto_check_actions[None] = off_action

        for hours in self.AUTO_CHECK_INTERVAL_OPTIONS:
            action = QAction(self._auto_check_interval_label(hours), self._auto_check_menu)
            action.setCheckable(True)
            action.triggered.connect(
                lambda checked=False, interval=hours: self._set_auto_check_schedule(interval)
            )
            self._auto_check_group.addAction(action)
            self._auto_check_menu.addAction(action)
            self._auto_check_actions[hours] = action

        menu.addSeparator()

        quit_action = QAction(self.tr("Quit"), menu)
        quit_action.triggered.connect(self._window.quit_application_from_tray)
        menu.addAction(quit_action)
        return menu

    def _auto_check_interval_label(self, hours: int) -> str:
        if hours == 6:
            return self.tr("Every 6 hours")
        if hours == 12:
            return self.tr("Every 12 hours")
        if hours == 24:
            return self.tr("Every 24 hours")
        if hours == 72:
            return self.tr("Every 3 days")
        if hours == 168:
            return self.tr("Every week")
        return self.tr("Every {hours} hours").format(hours=hours)

    def _build_icon(self) -> QIcon:
        icon = QIcon.fromTheme("system-software-update")
        if not icon.isNull():
            return icon
        return self._app.style().standardIcon(QStyle.StandardPixmap.SP_BrowserReload)

    def _should_notify(self) -> bool:
        if not self.is_active() or not self._notifications_enabled:
            return False

        return self._is_background_session()

    def _is_background_session(self) -> bool:
        return bool(self._window.should_show_background_notifications())

    def _is_debounced_updates_available(self, signature: tuple[str, ...]) -> bool:
        if self._last_updates_signature is None:
            return False
        last_signature, last_at = self._last_updates_signature
        return (
            last_signature == signature
            and (time.monotonic() - last_at) < self.UPDATES_AVAILABLE_DEBOUNCE_SECONDS
        )

    def _remember_updates_available(self, signature: tuple[str, ...]) -> None:
        self._last_updates_signature = (signature, time.monotonic())

    def _updates_signature(self, result: UpdateCheckResult) -> tuple[str, ...]:
        return self._tray_status.updates_signature(result)

    def _show_message(
        self,
        *,
        message: str,
        icon: QSystemTrayIcon.MessageIcon,
    ) -> bool:
        if not self._should_notify():
            return False
        self._tray.showMessage(self.tr("ArchUpdater"), message, icon, 10000)
        return True

    @Slot(object)
    def _on_check_succeeded(self, result: UpdateCheckResult) -> None:
        self._tray_status.apply_check_result(result)
        self._sync_tray_icon()
        self._sync_tooltip()
        signature = self._updates_signature(result)
        force_notification = self._force_next_updates_notification
        self._force_next_updates_notification = False
        count = self._tray_status.available_updates_count
        if count <= 0:
            return
        if not force_notification and self._is_debounced_updates_available(signature):
            return

        shown = self._show_message(
            message=self._tray_status.updates_available_message(),
            icon=QSystemTrayIcon.MessageIcon.Information,
        )
        if shown:
            self._remember_updates_available(signature)

    @Slot(str, object)
    def _on_check_failed(self, message: str, _logs: object) -> None:
        self._tray_status.apply_check_failure(message)
        self._force_next_updates_notification = False
        self._sync_tray_icon()
        self._sync_tooltip()
        self._show_message(
            message=self._tray_status.check_failed_message(),
            icon=QSystemTrayIcon.MessageIcon.Warning,
        )

    @Slot(str)
    def _on_update_status_changed(self, value: str) -> None:
        is_tracked_status = self._tray_status.mark_update_status(value)
        if is_tracked_status:
            self._sync_tooltip()
        if not is_tracked_status or self._update_started_in_background is not None:
            return
        self._update_started_in_background = self._is_background_session()

    @Slot(bool, str, str)
    def _on_update_completed(self, _success: bool, _message: str, outcome: str) -> None:
        if outcome in {
            BatchOutcome.SUCCESS.value,
            BatchOutcome.PARTIAL_SUCCESS.value,
        }:
            self._tray_status.mark_refresh_pending()
            self._sync_tray_icon()
            self._sync_tooltip()
            should_notify_completion = (
                self._update_started_in_background is True and self._should_notify()
            )
            self._update_started_in_background = None
            if not should_notify_completion:
                return
            self._show_message(
                message=(
                    self.tr("Some selected updates were skipped. Refreshing update status...")
                    if outcome == BatchOutcome.PARTIAL_SUCCESS.value
                    else self._tray_status.update_completed_message()
                ),
                icon=QSystemTrayIcon.MessageIcon.Information,
            )
            return

        if outcome == BatchOutcome.NO_CHANGES.value:
            self._update_started_in_background = None
            if self._should_notify():
                self._show_message(
                    message=self.tr("No selected updates were installed."),
                    icon=QSystemTrayIcon.MessageIcon.Information,
                )
            return

        self._update_started_in_background = None
        if not self._should_notify():
            return

        if outcome == BatchOutcome.AUTH_CANCELLED.value:
            self._show_message(
                message=self.tr("Update was cancelled before authorization."),
                icon=QSystemTrayIcon.MessageIcon.Warning,
            )
            return

        if outcome == BatchOutcome.CANCELLED.value:
            self._show_message(
                message=self.tr("The update was cancelled."),
                icon=QSystemTrayIcon.MessageIcon.Warning,
            )
            return

        self._show_message(
            message=self.tr("Selected updates failed. Open ArchUpdater."),
            icon=QSystemTrayIcon.MessageIcon.Critical,
        )

    @Slot(QSystemTrayIcon.ActivationReason)
    def _on_tray_activated(self, reason: QSystemTrayIcon.ActivationReason) -> None:
        if reason in {
            QSystemTrayIcon.ActivationReason.Trigger,
            QSystemTrayIcon.ActivationReason.DoubleClick,
            QSystemTrayIcon.ActivationReason.MiddleClick,
        }:
            self._show_window()

    @Slot()
    def _on_message_clicked(self) -> None:
        self._show_window()

    def _show_window(self) -> None:
        self._window.show_from_tray()

    @Slot()
    def _sync_menu_state(self) -> None:
        if self._check_action is not None:
            self._check_action.setEnabled(
                not self._update_controller.is_busy()
                and not self._tray_status.refresh_pending
            )
        enabled = bool(self._window.auto_check_enabled())
        interval = int(self._window.auto_check_interval_hours())
        selected_key = interval if enabled and interval in self._auto_check_actions else None
        action = self._auto_check_actions.get(selected_key)
        if action is not None:
            action.setChecked(True)

    def _set_auto_check_schedule(self, interval_hours: int | None) -> None:
        self._window.set_auto_check_schedule(interval_hours)

    @Slot()
    def _request_manual_check(self) -> None:
        if self._update_controller.is_busy() or self._tray_status.refresh_pending:
            return
        self._force_next_updates_notification = True
        if self._window.start_check_updates_from_tray():
            return
        self._force_next_updates_notification = False

    @Slot(bool)
    def _on_busy_changed(self, busy: bool) -> None:
        if busy and self._tray_status.busy_message is None:
            self._tray_status.mark_checking()
            self._sync_tooltip()
        if busy and self.is_active():
            if not self._animation_timer.isActive():
                self._animation_timer.start()
            self._advance_busy_icon()
            return

        self._tray_status.clear_busy_message()
        if self._tray_status.refresh_pending and self.is_active():
            if not self._animation_timer.isActive():
                self._animation_timer.start()
            self._advance_busy_icon()
            self._sync_tooltip()
            return

        self._animation_timer.stop()
        self._sync_tray_icon()
        self._sync_tooltip()

    def _advance_busy_icon(self) -> None:
        if not self.is_active():
            self._animation_timer.stop()
            self._sync_tray_icon()
            return

        if not self._update_controller.is_busy() and not self._tray_status.refresh_pending:
            self._animation_timer.stop()
            self._sync_tray_icon()
            return

        self._animation_angle = (self._animation_angle + 15) % 360
        self._tray.setIcon(self._busy_icon(self._animation_angle))

    def _sync_tray_icon(self) -> None:
        if (
            self.is_active()
            and (self._update_controller.is_busy() or self._tray_status.refresh_pending)
        ):
            self._tray.setIcon(self._busy_icon(self._animation_angle))
            return
        if self._tray_status.has_check_failure:
            self._tray.setIcon(self._warning_marked_icon(self._base_icon))
            return
        if self._tray_status.available_updates_count > 0:
            self._tray.setIcon(
                self._badged_icon(
                    self._base_icon,
                    self._tray_status.available_updates_count,
                )
            )
            return
        if self._tray_status.has_successful_check_result:
            self._tray.setIcon(self._ok_marked_icon(self._base_icon))
            return
        self._tray.setIcon(self._base_icon)

    def _sync_tooltip(self) -> None:
        self._tray.setToolTip(self._tray_status.tooltip(self._window.next_auto_check_at()))

    def _busy_icon(self, angle: int) -> QIcon:
        # Render geometry at each tray size: rotating a theme pixmap can clip
        # its edges and mix physical and logical pixels on scaled displays.
        icon = QIcon()
        color = self._app.palette().color(QPalette.ColorRole.WindowText)
        arc_rect = QRectF(-7, -7, 14, 14)
        arrow = QPainterPath()
        arrow.moveTo(6.9, -2.0)
        arrow.lineTo(4.3, -3.75)
        arrow.lineTo(7.4, -5.55)
        arrow.closeSubpath()

        for size in (16, 22, 24, 32, 44, 48, 64):
            canvas = QPixmap(size, size)
            canvas.fill(Qt.GlobalColor.transparent)
            painter = QPainter(canvas)
            painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
            painter.scale(size / 22, size / 22)
            painter.translate(11, 11)
            painter.rotate(angle)
            for _ in range(2):
                pen = QPen(color, 1.7)
                pen.setCapStyle(Qt.PenCapStyle.RoundCap)
                painter.setPen(pen)
                painter.setBrush(Qt.BrushStyle.NoBrush)
                painter.drawArc(arc_rect, 160 * 16, -130 * 16)
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(color)
                painter.drawPath(arrow)
                painter.rotate(180)
            painter.end()
            icon.addPixmap(canvas)
        return icon

    def _render_status_icon(
        self, icon: QIcon, draw_overlay: Callable[[QPainter], None]
    ) -> QIcon:
        if icon.isNull():
            return self._base_icon

        rendered = QIcon()
        for size in (16, 22, 24, 32, 44, 48, 64):
            # Keep the theme's small tray variant, requesting more physical
            # pixels through DPR instead of selecting a larger app icon.
            base_pixmap = icon.pixmap(QSize(22, 22), max(1.0, size / 22))
            if base_pixmap.isNull():
                continue
            canvas = QPixmap(size, size)
            canvas.fill(Qt.GlobalColor.transparent)
            painter = QPainter(canvas)
            painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
            painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
            painter.scale(size / 22, size / 22)
            painter.drawPixmap(QRectF(0, 0, 22, 22), base_pixmap, QRectF(base_pixmap.rect()))
            draw_overlay(painter)
            painter.end()
            rendered.addPixmap(canvas)
        return rendered if not rendered.isNull() else self._base_icon

    def _badged_icon(self, icon: QIcon, count: int) -> QIcon:
        badge_text = "99+" if count > 99 else str(count)

        def draw_badge(painter: QPainter) -> None:
            badge_rect = QRect(0, 0, 22, 22).adjusted(9, -1, -1, -8)
            font = QFont(self._app.font())
            font.setBold(True)
            font.setPixelSize(8 if len(badge_text) < 3 else 7)
            painter.setFont(font)

            # Keep the count integrated with the icon instead of using a red pill badge.
            painter.setPen(QColor(0, 0, 0, 170))
            painter.drawText(
                badge_rect.translated(0, 1),
                Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignTop,
                badge_text,
            )
            painter.setPen(QColor("#ffffff"))
            painter.drawText(
                badge_rect,
                Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignTop,
                badge_text,
            )

        return self._render_status_icon(icon, draw_badge)

    def _warning_marked_icon(self, icon: QIcon) -> QIcon:
        def draw_warning(painter: QPainter) -> None:
            marker_rect = QRect(0, 0, 22, 22).adjusted(12, 2, -1, -13)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor("#f0b429"))
            painter.drawEllipse(marker_rect)

            font = QFont(self._app.font())
            font.setBold(True)
            font.setPixelSize(8)
            painter.setFont(font)
            painter.setPen(QColor("#2f2410"))
            painter.drawText(marker_rect, Qt.AlignmentFlag.AlignCenter, "!")

        return self._render_status_icon(icon, draw_warning)

    def _ok_marked_icon(self, icon: QIcon) -> QIcon:
        def draw_ok(painter: QPainter) -> None:
            marker_rect = QRect(0, 0, 22, 22).adjusted(12, 2, -1, -13)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor("#39a86b"))
            painter.drawEllipse(marker_rect)

        return self._render_status_icon(icon, draw_ok)
