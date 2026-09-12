from __future__ import annotations

from typing import Protocol

from PySide6.QtCore import QCoreApplication

from archupdater.infrastructure.settings import SettingsService


class PlasmaRestartService(Protocol):
    def can_restart_plasma_shell(self) -> bool: ...

    def restart_plasma_shell(self) -> bool: ...


class AutostartStatusService(Protocol):
    def is_enabled(self) -> bool: ...


class PlasmaRestartCoordinator:
    def __init__(
        self,
        *,
        service: PlasmaRestartService,
        settings: SettingsService,
        autostart_service: AutostartStatusService,
        append_log,
        is_interactive_foreground,
        ask_restart,
        warn_restart_failed,
    ) -> None:
        self._service = service
        self._settings = settings
        self._autostart_service = autostart_service
        self._append_log = append_log
        self._is_interactive_foreground = is_interactive_foreground
        self._ask_restart = ask_restart
        self._warn_restart_failed = warn_restart_failed

    def maybe_prompt(self, recommended: bool) -> bool:
        if not recommended:
            return False

        manual_message = self._translate(
            "KDE Store add-ons were updated. Restart plasmashell manually to fully apply the changes."
        )

        if not self._service.can_restart_plasma_shell():
            self._append_log(manual_message)
            return False

        restart_mode = self._settings.load_app_settings(
            default_start_on_login=self._autostart_service.is_enabled()
        ).plasma_restart_mode

        if restart_mode == "never":
            self._append_log(manual_message)
            return False

        if restart_mode == "auto":
            if self._service.restart_plasma_shell():
                self._append_log(self._translate("Plasma shell restart requested successfully."))
                return False
            self._append_log(self._translate("Plasma shell could not be restarted automatically."))
            if self._is_interactive_foreground():
                self._warn_restart_failed()
            return False

        if not self._is_interactive_foreground():
            self._append_log(manual_message)
            return False

        if not self._ask_restart():
            self._append_log(manual_message)
            return False

        if self._service.restart_plasma_shell():
            self._append_log(self._translate("Plasma shell restart requested successfully."))
            return False

        self._append_log(self._translate("Plasma shell could not be restarted automatically."))
        self._warn_restart_failed()
        return False

    def _translate(self, text: str) -> str:
        return QCoreApplication.translate("MainWindow", text)
