from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from PySide6.QtCore import QSettings

from archupdater.i18n.manager import SYSTEM_LANGUAGE


AUTO_CHECK_INTERVAL_OPTIONS = frozenset({6, 12, 24, 72, 168})


@dataclass(slots=True)
class AppSettings:
    language_preference: str = SYSTEM_LANGUAGE
    start_on_login: bool = False
    systray_enabled: bool = True
    systray_notifications_enabled: bool = True
    auto_check_enabled: bool = False
    auto_check_interval_hours: int = 24
    plasma_restart_mode: str = "ask"
    cleanup_unused_flatpak_runtimes: bool = False
    aur_updates_enabled: bool = False


@dataclass(frozen=True, slots=True)
class SettingSpec:
    attribute: str
    key: str
    default: object
    coerce: Callable[[object], object]


class SettingsService:
    LANGUAGE_KEY = "ui/language"
    START_ON_LOGIN_KEY = "system/start_on_login"
    SYSTRAY_ENABLED_KEY = "ui/systray_enabled"
    SYSTRAY_NOTIFICATIONS_ENABLED_KEY = "ui/systray_notifications_enabled"
    AUTO_CHECK_ENABLED_KEY = "updates/auto_check_enabled"
    AUTO_CHECK_INTERVAL_HOURS_KEY = "updates/auto_check_interval_hours"
    PLASMA_RESTART_MODE_KEY = "ui/plasma_restart_mode"
    CLEANUP_UNUSED_FLATPAK_RUNTIMES_KEY = "updates/cleanup_unused_flatpak_runtimes"
    AUR_UPDATES_ENABLED_KEY = "updates/aur_updates_enabled"

    def __init__(self) -> None:
        self._settings = QSettings()

    def language_preference(self) -> str:
        return self.load_app_settings().language_preference

    def load_app_settings(self, default_start_on_login: bool = False) -> AppSettings:
        values = {
            spec.attribute: spec.coerce(self._settings.value(spec.key, spec.default))
            for spec in self._setting_specs(default_start_on_login)
        }
        return AppSettings(**values)

    def save_app_settings(self, app_settings: AppSettings) -> None:
        for spec in self._setting_specs(app_settings.start_on_login):
            value = spec.coerce(getattr(app_settings, spec.attribute))
            self._settings.setValue(spec.key, value)
        self._settings.sync()

    def has_cleanup_unused_flatpak_runtimes_preference(self) -> bool:
        return self._settings.contains(self.CLEANUP_UNUSED_FLATPAK_RUNTIMES_KEY)

    def _setting_specs(self, default_start_on_login: bool) -> tuple[SettingSpec, ...]:
        return (
            SettingSpec(
                "language_preference",
                self.LANGUAGE_KEY,
                SYSTEM_LANGUAGE,
                self._coerce_language,
            ),
            SettingSpec(
                "start_on_login",
                self.START_ON_LOGIN_KEY,
                default_start_on_login,
                self._coerce_bool,
            ),
            SettingSpec("systray_enabled", self.SYSTRAY_ENABLED_KEY, True, self._coerce_bool),
            SettingSpec(
                "systray_notifications_enabled",
                self.SYSTRAY_NOTIFICATIONS_ENABLED_KEY,
                True,
                self._coerce_bool,
            ),
            SettingSpec(
                "auto_check_enabled",
                self.AUTO_CHECK_ENABLED_KEY,
                False,
                self._coerce_bool,
            ),
            SettingSpec(
                "auto_check_interval_hours",
                self.AUTO_CHECK_INTERVAL_HOURS_KEY,
                24,
                self._coerce_auto_check_interval,
            ),
            SettingSpec(
                "plasma_restart_mode",
                self.PLASMA_RESTART_MODE_KEY,
                "ask",
                self._coerce_restart_mode,
            ),
            SettingSpec(
                "cleanup_unused_flatpak_runtimes",
                self.CLEANUP_UNUSED_FLATPAK_RUNTIMES_KEY,
                False,
                self._coerce_bool,
            ),
            SettingSpec(
                "aur_updates_enabled",
                self.AUR_UPDATES_ENABLED_KEY,
                False,
                self._coerce_bool,
            ),
        )

    def _coerce_language(self, value: object) -> str:
        return str(value or SYSTEM_LANGUAGE)

    def _coerce_bool(self, value: object) -> bool:
        if isinstance(value, bool):
            return value
        return str(value).strip().lower() in {"1", "true", "yes", "on"}

    def _coerce_int(self, value: object, default: int) -> int:
        try:
            return int(value)
        except (TypeError, ValueError):
            return default

    def _coerce_auto_check_interval(self, value: object) -> int:
        interval = self._coerce_int(value, 24)
        return interval if interval in AUTO_CHECK_INTERVAL_OPTIONS else 24

    def _coerce_restart_mode(self, value: object) -> str:
        normalized = str(value).strip().lower()
        if normalized in {"ask", "auto", "never"}:
            return normalized
        return "ask"
