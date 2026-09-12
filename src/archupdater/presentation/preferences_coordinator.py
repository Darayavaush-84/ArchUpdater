from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace

from PySide6.QtWidgets import QMessageBox, QWidget

from archupdater.domain.optional_sources import OptionalSourcesSnapshot
from archupdater.i18n.manager import TranslationManager
from archupdater.presentation.preferences_dialog import PreferencesDialog
from archupdater.infrastructure.autostart import AutostartService
from archupdater.infrastructure.settings import AppSettings, SettingsService
from archupdater.application.updates import UpdateApplication


class PreferencesCoordinator:
    def __init__(
        self,
        *,
        parent: QWidget,
        settings: SettingsService,
        autostart_service: AutostartService,
        translation_manager: TranslationManager,
        update_service: UpdateApplication,
        load_app_settings: Callable[[], AppSettings],
        current_optional_sources_snapshot: Callable[[], OptionalSourcesSnapshot],
        apply_optional_sources_snapshot: Callable[[OptionalSourcesSnapshot], None],
        apply_tray_settings: Callable[[AppSettings], None],
        apply_background_behavior_settings: Callable[[AppSettings], None],
        start_check_updates: Callable[[], object],
        translate: Callable[[str], str],
    ) -> None:
        self._parent = parent
        self._settings = settings
        self._autostart_service = autostart_service
        self._translation_manager = translation_manager
        self._update_service = update_service
        self._load_app_settings = load_app_settings
        self._current_optional_sources_snapshot = current_optional_sources_snapshot
        self._apply_optional_sources_snapshot = apply_optional_sources_snapshot
        self._apply_tray_settings = apply_tray_settings
        self._apply_background_behavior_settings = apply_background_behavior_settings
        self._start_check_updates = start_check_updates
        self._t = translate

    def open(self) -> None:
        current_settings = self._load_app_settings()
        dialog = PreferencesDialog(
            current_settings,
            self._translation_manager,
            update_service=self._update_service,
            optional_sources_snapshot=self._current_optional_sources_snapshot(),
            parent=self._parent,
        )
        accepted = dialog.exec() == PreferencesDialog.DialogCode.Accepted
        optional_sources_modified = dialog.optional_sources_modified()
        optional_sources_snapshot = dialog.optional_sources_snapshot()

        if optional_sources_modified and optional_sources_snapshot is not None:
            self._apply_optional_sources_snapshot(optional_sources_snapshot)

        if not accepted:
            if optional_sources_modified:
                self._start_check_updates()
            return

        settings_after_optional_sources = (
            self._load_app_settings() if optional_sources_modified else current_settings
        )
        selected_settings = dialog.selected_app_settings()
        updated_settings = self._updated_settings(settings_after_optional_sources, selected_settings)
        messages = self._apply_side_effectful_preferences(
            settings_after_optional_sources,
            selected_settings,
            updated_settings,
        )

        if updated_settings != current_settings:
            self._settings.save_app_settings(updated_settings)
            self._apply_tray_settings(updated_settings)
            self._apply_background_behavior_settings(updated_settings)

        if messages:
            QMessageBox.information(
                self._parent,
                self._t("Preferences Saved"),
                "\n\n".join(messages),
            )

        if optional_sources_modified:
            self._start_check_updates()

    def _updated_settings(
        self,
        current_settings: AppSettings,
        selected_settings: AppSettings,
    ) -> AppSettings:
        return replace(
            selected_settings,
            start_on_login=current_settings.start_on_login,
            aur_updates_enabled=current_settings.aur_updates_enabled,
        )

    def _apply_side_effectful_preferences(
        self,
        current_settings: AppSettings,
        selected_settings: AppSettings,
        updated_settings: AppSettings,
    ) -> list[str]:
        messages: list[str] = []
        if selected_settings.language_preference != current_settings.language_preference:
            effective_code = self._translation_manager.resolve_language(
                selected_settings.language_preference
            )
            messages.append(
                self._t(
                    "Language preference saved as {language}. Restart ArchUpdater to apply the new language."
                ).format(language=self._translation_manager.display_name(effective_code))
            )

        if selected_settings.start_on_login != current_settings.start_on_login:
            try:
                self._autostart_service.set_enabled(selected_settings.start_on_login)
            except OSError as exc:
                QMessageBox.warning(
                    self._parent,
                    self._t("Startup Preference Failed"),
                    self._t("Could not update the startup preference: {error}").format(
                        error=str(exc)
                    ),
                )
            else:
                updated_settings.start_on_login = selected_settings.start_on_login
                messages.append(
                    self._t("ArchUpdater will start automatically when you sign in.")
                    if selected_settings.start_on_login
                    else self._t("ArchUpdater will no longer start automatically when you sign in.")
                )
        return messages
