from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta
from typing import Protocol

from PySide6.QtCore import QCoreApplication, QTimer

from archupdater.presentation.tray_controller import TrayController
from archupdater.infrastructure.settings import AppSettings, SettingsService


class AutostartStatusService(Protocol):
    def is_enabled(self) -> bool: ...


class BackgroundBehaviorController:
    def __init__(
        self,
        *,
        settings: SettingsService,
        autostart_service: AutostartStatusService,
        auto_check_timer: QTimer,
    ) -> None:
        self._settings = settings
        self._autostart_service = autostart_service
        self._auto_check_timer = auto_check_timer

    def load_app_settings(self) -> AppSettings:
        return self._settings.load_app_settings(
            default_start_on_login=self._autostart_service.is_enabled()
        )

    def auto_check_enabled(self) -> bool:
        return self.load_app_settings().auto_check_enabled

    def auto_check_interval_hours(self) -> int:
        return self.load_app_settings().auto_check_interval_hours

    def apply_tray_settings(
        self,
        tray_controller: TrayController | None,
        app_settings: AppSettings,
    ) -> None:
        if tray_controller is None:
            return
        tray_controller.apply_settings(
            enabled=app_settings.systray_enabled,
            notifications_enabled=app_settings.systray_notifications_enabled,
        )

    def apply_auto_check_settings(
        self,
        app_settings: AppSettings,
        *,
        last_checked_at: datetime | None = None,
        defer_if_due: bool = False,
    ) -> None:
        if not app_settings.auto_check_enabled:
            self._auto_check_timer.stop()
            return

        delay_ms = self.auto_check_delay_ms(app_settings, last_checked_at=last_checked_at)
        if delay_ms is None:
            self._auto_check_timer.stop()
            return
        if delay_ms <= 0 and defer_if_due:
            delay_ms = self._auto_check_interval_ms(app_settings)
        self._auto_check_timer.start(max(1, delay_ms))

    def auto_check_delay_ms(
        self,
        app_settings: AppSettings,
        *,
        last_checked_at: datetime | None,
        now: datetime | None = None,
    ) -> int | None:
        if not app_settings.auto_check_enabled:
            return None
        interval_ms = self._auto_check_interval_ms(app_settings)
        if last_checked_at is None:
            return 0

        reference_time = now or datetime.now()
        elapsed_ms = int((reference_time - last_checked_at).total_seconds() * 1000)
        elapsed_ms = max(0, elapsed_ms)
        return max(0, interval_ms - elapsed_ms)

    def next_check_at(
        self,
        app_settings: AppSettings,
        *,
        last_checked_at: datetime | None,
        now: datetime | None = None,
    ) -> datetime | None:
        delay_ms = self.auto_check_delay_ms(
            app_settings,
            last_checked_at=last_checked_at,
            now=now,
        )
        if delay_ms is None:
            return None
        reference_time = now or datetime.now()
        return reference_time if delay_ms <= 0 else reference_time + timedelta(milliseconds=delay_ms)

    def set_auto_check_schedule(self, interval_hours: int | None) -> str | None:
        current_settings = self.load_app_settings()
        normalized_enabled = interval_hours is not None
        normalized_interval = (
            int(interval_hours)
            if interval_hours is not None
            else current_settings.auto_check_interval_hours
        )

        if (
            current_settings.auto_check_enabled == normalized_enabled
            and current_settings.auto_check_interval_hours == normalized_interval
        ):
            return None

        updated_settings = replace(
            current_settings,
            auto_check_enabled=normalized_enabled,
            auto_check_interval_hours=normalized_interval,
        )
        self._settings.save_app_settings(updated_settings)
        self.apply_auto_check_settings(updated_settings, defer_if_due=True)

        if normalized_enabled:
            return self._translate("Automatic checks set to every {hours} hours.").format(
                hours=normalized_interval
            )
        return self._translate("Automatic update checks disabled.")

    def _translate(self, text: str) -> str:
        return QCoreApplication.translate("MainWindow", text)

    def _auto_check_interval_ms(self, app_settings: AppSettings) -> int:
        return max(1, int(app_settings.auto_check_interval_hours)) * 60 * 60 * 1000
