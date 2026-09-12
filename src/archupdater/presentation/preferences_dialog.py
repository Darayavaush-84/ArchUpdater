from __future__ import annotations

from PySide6.QtCore import Signal, QT_TRANSLATE_NOOP
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFrame,
    QFormLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from archupdater.i18n.manager import TranslationManager
from archupdater.domain.optional_sources import OptionalSourcesSnapshot
from archupdater.presentation.optional_sources_dialog import OptionalSourcesDialog
from archupdater.infrastructure.settings import AppSettings
from archupdater.application.updates import UpdateApplication


class PreferencesDialog(QDialog):
    optional_sources_snapshot_changed = Signal(object)
    AUTO_CHECK_INTERVAL_OPTIONS = (6, 12, 24, 72, 168)
    PLASMA_RESTART_OPTIONS = (
        ("ask", QT_TRANSLATE_NOOP("PreferencesDialog", "Ask every time")),
        ("auto", QT_TRANSLATE_NOOP("PreferencesDialog", "Restart automatically")),
        ("never", QT_TRANSLATE_NOOP("PreferencesDialog", "Do not restart automatically")),
    )
    def __init__(
        self,
        app_settings: AppSettings,
        translation_manager: TranslationManager,
        update_service: UpdateApplication | None = None,
        optional_sources_snapshot: OptionalSourcesSnapshot | None = None,
        parent: QDialog | None = None,
    ) -> None:
        super().__init__(parent)
        self._app_settings = app_settings
        self._translation_manager = translation_manager
        self._update_service = update_service
        self._optional_sources_modified = False
        self._optional_sources_snapshot = optional_sources_snapshot
        self.setWindowTitle(self.tr("Preferences"))
        self.setModal(True)
        self.setMinimumWidth(720)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(16)

        title = QLabel(self.tr("Preferences"))
        title.setObjectName("sectionTitle")
        layout.addWidget(title)

        description = QLabel(
            self.tr("Adjust language, startup behavior, tray integration, and automatic checks.")
        )
        description.setWordWrap(True)
        description.setObjectName("mutedText")
        layout.addWidget(description)

        layout.addWidget(self._build_general_page())

        self.buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Cancel | QDialogButtonBox.StandardButton.Save
        )
        save_button = self.buttons.button(QDialogButtonBox.StandardButton.Save)
        cancel_button = self.buttons.button(QDialogButtonBox.StandardButton.Cancel)
        if save_button is not None:
            save_button.setText(self.tr("Save"))
            save_button.setProperty("actionKind", "primary")
            save_button.setProperty("uiRole", "dialogFooter")
            save_button.setProperty("density", "compact")
        if cancel_button is not None:
            cancel_button.setText(self.tr("Cancel"))
            cancel_button.setProperty("actionKind", "neutral")
            cancel_button.setProperty("uiRole", "dialogFooter")
            cancel_button.setProperty("density", "compact")
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        layout.addWidget(self.buttons)
        self.adjustSize()

    def _build_general_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(16)
        layout.addWidget(self._build_language_card())
        layout.addWidget(self._build_behavior_card())
        if self._update_service is not None and self._optional_sources_snapshot is not None:
            layout.addWidget(self._build_update_sources_card())
        layout.addStretch(1)
        return page

    def _build_language_card(self) -> QFrame:
        card = QFrame()
        card.setObjectName("card")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        caption = QLabel(self.tr("Language"))
        caption.setObjectName("sectionCaption")
        layout.addWidget(caption)

        description = QLabel(
            self.tr(
                "Use the system language or choose a language manually for ArchUpdater."
            )
        )
        description.setObjectName("mutedText")
        description.setWordWrap(True)
        layout.addWidget(description)

        form = QFormLayout()
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        form.setHorizontalSpacing(18)
        form.setVerticalSpacing(12)
        self.language_combo = QComboBox()
        self.language_combo.setSizePolicy(
            QSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        )
        self.language_combo.setMinimumHeight(36)
        for option in self._translation_manager.available_language_options():
            self.language_combo.addItem(option.label, option.code)

        current_preference = self._app_settings.language_preference
        current_index = self.language_combo.findData(current_preference)
        if current_index >= 0:
            self.language_combo.setCurrentIndex(current_index)

        form.addRow(self.tr("Application language"), self.language_combo)
        layout.addLayout(form)
        return card

    def _build_update_sources_card(self) -> QFrame:
        card = QFrame()
        card.setObjectName("card")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        caption = QLabel(self.tr("Update Sources"))
        caption.setObjectName("sectionCaption")
        layout.addWidget(caption)

        description = QLabel(
            self.tr(
                "Manage installed AUR helpers, Flatpak support, and firmware tools used by ArchUpdater."
            )
        )
        description.setObjectName("mutedText")
        description.setWordWrap(True)
        layout.addWidget(description)

        self.manage_sources_button = QPushButton(self.tr("Manage Update Sources"))
        self.manage_sources_button.setProperty("actionKind", "neutral")
        self.manage_sources_button.setProperty("density", "compact")
        self.manage_sources_button.clicked.connect(self._open_optional_sources_dialog)
        layout.addWidget(self.manage_sources_button, 0)
        return card

    def _build_behavior_card(self) -> QFrame:
        card = QFrame()
        card.setObjectName("card")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        caption = QLabel(self.tr("Startup and Background"))
        caption.setObjectName("sectionCaption")
        layout.addWidget(caption)

        description = QLabel(
            self.tr(
                "Choose how ArchUpdater starts, stays available in the system tray, and checks for updates automatically while it is running."
            )
        )
        description.setObjectName("mutedText")
        description.setWordWrap(True)
        layout.addWidget(description)

        form = QFormLayout()
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        form.setHorizontalSpacing(18)
        form.setVerticalSpacing(12)

        self.start_on_login_checkbox = QCheckBox(
            self.tr("Start ArchUpdater automatically when you sign in")
        )
        self.start_on_login_checkbox.setChecked(self._app_settings.start_on_login)
        form.addRow(self.tr("Startup"), self.start_on_login_checkbox)

        self.systray_enabled_checkbox = QCheckBox(
            self.tr("Keep ArchUpdater available in the system tray")
        )
        self.systray_enabled_checkbox.setChecked(self._app_settings.systray_enabled)
        form.addRow(self.tr("System tray"), self.systray_enabled_checkbox)

        self.systray_notifications_checkbox = QCheckBox(
            self.tr("Show tray notifications for background events")
        )
        self.systray_notifications_checkbox.setChecked(
            self._app_settings.systray_notifications_enabled
        )
        form.addRow(self.tr("Notifications"), self.systray_notifications_checkbox)

        self.auto_check_checkbox = QCheckBox(
            self.tr("Check for updates automatically")
        )
        self.auto_check_checkbox.setChecked(self._app_settings.auto_check_enabled)
        form.addRow(self.tr("Automatic checks"), self.auto_check_checkbox)

        self.auto_check_interval_combo = QComboBox()
        self.auto_check_interval_combo.setSizePolicy(
            QSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        )
        self.auto_check_interval_combo.setMinimumHeight(36)
        for hours in self.AUTO_CHECK_INTERVAL_OPTIONS:
            self.auto_check_interval_combo.addItem(self._auto_check_interval_label(hours), hours)
        current_interval_index = self.auto_check_interval_combo.findData(
            self._app_settings.auto_check_interval_hours
        )
        if current_interval_index >= 0:
            self.auto_check_interval_combo.setCurrentIndex(current_interval_index)
        self.auto_check_interval_combo.setEnabled(self._app_settings.auto_check_enabled)
        self.auto_check_checkbox.toggled.connect(self.auto_check_interval_combo.setEnabled)
        form.addRow(self.tr("Check interval"), self.auto_check_interval_combo)

        self.cleanup_unused_flatpak_checkbox = QCheckBox(
            self.tr("Remove unused Flatpak runtimes after Flatpak updates")
        )
        self.cleanup_unused_flatpak_checkbox.setChecked(
            self._app_settings.cleanup_unused_flatpak_runtimes
        )
        form.addRow(self.tr("Flatpak cleanup"), self.cleanup_unused_flatpak_checkbox)

        self.plasma_restart_combo = QComboBox()
        self.plasma_restart_combo.setSizePolicy(
            QSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        )
        self.plasma_restart_combo.setMinimumHeight(36)
        for mode, label in self.PLASMA_RESTART_OPTIONS:
            self.plasma_restart_combo.addItem(self.tr(label), mode)
        current_restart_index = self.plasma_restart_combo.findData(
            self._app_settings.plasma_restart_mode
        )
        if current_restart_index >= 0:
            self.plasma_restart_combo.setCurrentIndex(current_restart_index)
        form.addRow(self.tr("Add-on restart"), self.plasma_restart_combo)

        plasma_restart_note = QLabel(
            self.tr(
                "Some KDE Store add-ons require restarting plasmashell before their updates are fully applied."
            )
        )
        plasma_restart_note.setObjectName("mutedText")
        plasma_restart_note.setWordWrap(True)
        layout.addWidget(plasma_restart_note)

        layout.addLayout(form)
        return card

    def selected_language_preference(self) -> str:
        return str(self.language_combo.currentData())

    def selected_start_on_login_enabled(self) -> bool:
        return self.start_on_login_checkbox.isChecked()

    def selected_systray_enabled(self) -> bool:
        return self.systray_enabled_checkbox.isChecked()

    def selected_systray_notifications_enabled(self) -> bool:
        return self.systray_notifications_checkbox.isChecked()

    def selected_auto_check_enabled(self) -> bool:
        return self.auto_check_checkbox.isChecked()

    def selected_auto_check_interval_hours(self) -> int:
        return int(self.auto_check_interval_combo.currentData())

    def selected_cleanup_unused_flatpak_runtimes(self) -> bool:
        return self.cleanup_unused_flatpak_checkbox.isChecked()

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

    def selected_plasma_restart_mode(self) -> str:
        return str(self.plasma_restart_combo.currentData())

    def selected_app_settings(self) -> AppSettings:
        return AppSettings(
            language_preference=self.selected_language_preference(),
            start_on_login=self.selected_start_on_login_enabled(),
            systray_enabled=self.selected_systray_enabled(),
            systray_notifications_enabled=self.selected_systray_notifications_enabled(),
            auto_check_enabled=self.selected_auto_check_enabled(),
            auto_check_interval_hours=self.selected_auto_check_interval_hours(),
            plasma_restart_mode=self.selected_plasma_restart_mode(),
            cleanup_unused_flatpak_runtimes=self.selected_cleanup_unused_flatpak_runtimes(),
            aur_updates_enabled=self._app_settings.aur_updates_enabled,
        )

    def optional_sources_modified(self) -> bool:
        return self._optional_sources_modified

    def optional_sources_snapshot(self) -> OptionalSourcesSnapshot | None:
        return self._optional_sources_snapshot

    def _open_optional_sources_dialog(self) -> None:
        if self._update_service is None or self._optional_sources_snapshot is None:
            return
        dialog = OptionalSourcesDialog(
            self._update_service,
            self._optional_sources_snapshot,
            self,
        )
        dialog.exec()
        if not dialog.modified():
            return
        self._optional_sources_modified = True
        self._optional_sources_snapshot = dialog.snapshot()
        self.optional_sources_snapshot_changed.emit(self._optional_sources_snapshot)
