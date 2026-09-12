from __future__ import annotations

from dataclasses import replace
from datetime import datetime

from PySide6.QtCore import QTimer, QUrl, Slot
from PySide6.QtGui import QCloseEvent, QDesktopServices, QShowEvent
from PySide6.QtNetwork import QNetworkInformation
from PySide6.QtWidgets import (
    QApplication,
    QMainWindow,
    QMessageBox,
    QStyle,
)

from archupdater import __version__
from archupdater.infrastructure.app_releases import AppReleaseChecker, GITHUB_URL, RELEASES_URL
from archupdater.domain.check_results import UpdateCheckResult
from archupdater.domain.enums import OperationState, UpdateSource
from archupdater.domain.optional_sources import OptionalSourcesSnapshot
from archupdater.domain.packages import PackageUpdate, UpdateCounters
from archupdater.domain.progress import UpdateProgressSnapshot
from archupdater.domain.update_plan import UpdatePlan
from archupdater.i18n.manager import TranslationManager
from archupdater.presentation.arch_news_coordinator import ArchNewsCoordinator
from archupdater.presentation.arch_news_dialog import ArchNewsDialogResult, show_arch_news_dialog
from archupdater.presentation.background_behavior import BackgroundBehaviorController
from archupdater.presentation.main_window.bindings import connect_main_window_signals
from archupdater.presentation.main_window.check_coordinator import MainWindowCheckCoordinator
from archupdater.presentation.main_window.check_presenter import MainWindowCheckPresenter
from archupdater.presentation.main_window.operation_presenter import MainWindowOperationPresenter
from archupdater.presentation.main_window.state import MainWindowState
from archupdater.presentation.main_window.update_flow import MainWindowUpdateFlowCoordinator
from archupdater.presentation.main_window.logic import source_texts, update_status_messages
from archupdater.presentation.package_details_presenter import PackageDetailsPresenter
from archupdater.presentation.plasma_restart_coordinator import PlasmaRestartCoordinator
from archupdater.presentation.preflight_coordinator import UpdatePreflightCoordinator
from archupdater.presentation.preferences_coordinator import PreferencesCoordinator
from archupdater.presentation.progress_controller import ProgressController
from archupdater.presentation.reboot_advisory import (
    critical_reboot_packages,
    firmware_reboot_devices,
    firmware_shutdown_devices,
)
from archupdater.presentation.tray_controller import TrayController
from archupdater.presentation.update_completion_coordinator import UpdateCompletionCoordinator
from archupdater.presentation.update_controller import UpdateController
from archupdater.presentation.main_window.update_preconditions import MainWindowUpdatePreconditions
from archupdater.presentation.update_progress_presenter import UpdateProgressPresenter
from archupdater.presentation.main_window.ui import build_main_window_ui
from archupdater.container import ApplicationContainer
from archupdater.application.updates import UpdateApplication
from archupdater.infrastructure.app_state_cache import AppStateCache
from archupdater.infrastructure.autostart import AutostartService
from archupdater.infrastructure.settings import AppSettings, SettingsService


class MainWindow(QMainWindow):
    STARTUP_NETWORK_RETRY_MS = 3000

    def __init__(
        self,
        service: UpdateApplication | None = None,
        settings: SettingsService | None = None,
        state_cache: AppStateCache | None = None,
        translation_manager: TranslationManager | None = None,
    ) -> None:
        super().__init__()
        self._settings = settings or SettingsService()
        self._service = service or ApplicationContainer(
            aur_enabled_provider=lambda: self._settings.load_app_settings().aur_updates_enabled,
            aur_enabled_setter=self._set_aur_updates_enabled,
        ).updates()
        self._state_cache = state_cache or AppStateCache()
        self._state = MainWindowState()
        self._translation_manager = translation_manager or TranslationManager(
            QApplication.instance()
        )
        self._autostart_service = AutostartService()
        self._update_controller = UpdateController(self._service, self)
        self._progress_presenter = UpdateProgressPresenter(self, self._update_controller)
        self._flow_coordinator = MainWindowUpdateFlowCoordinator(
            view=self,
            update_controller=self._update_controller,
        )
        self._progress_controller = ProgressController(self)
        self._preflight_coordinator = UpdatePreflightCoordinator(
            parent=self,
            service=self._service,
            packages=lambda: self._state.packages,
        )
        self._completion_coordinator = UpdateCompletionCoordinator(
            parent=self,
            state_cache=self._state_cache,
            clear_selection=lambda: self.package_updates_widget.clear_selection(),
            set_operation_state=self._set_operation_state,
            set_header_status=lambda value: self.header_widget.set_system_status(value),
            append_log=self._append_log,
            maybe_prompt_plasma_restart=self._maybe_prompt_plasma_restart,
            maybe_show_reboot_advisory=self._maybe_show_reboot_advisory,
            should_show_reboot_advisory_after_failure=(
                self._update_controller.active_update_requires_restart_advisory
            ),
            close_progress_dialog=self._progress_presenter.close_dialog,
            update_selection_actions=self._update_selection_actions,
            mark_post_update_refresh_pending=self._mark_post_update_refresh_pending,
            use_local_system_db_for_post_update_refresh=(
                self._post_update_refresh_can_use_local_system_db
            ),
            start_check_updates=lambda use_local_system_db: (
                self._flow_coordinator.start_check_updates(
                    use_local_system_db=use_local_system_db,
                )
            ),
            progress_dialog_parent=lambda: self._progress_presenter.dialog,
            translate=self.tr,
        )

        self._tray_controller: TrayController | None = None
        self._auto_check_timer = QTimer(self)
        self._auto_check_timer.setSingleShot(True)
        self._auto_check_timer.timeout.connect(self._run_scheduled_check)
        self._startup_network_retry_timer = QTimer(self)
        self._startup_network_retry_timer.setSingleShot(True)
        self._startup_network_retry_timer.timeout.connect(
            self._start_initial_check_when_network_ready
        )
        self._startup_network_signal_connected = False
        self._allow_close = False
        self._background_behavior = BackgroundBehaviorController(
            settings=self._settings,
            autostart_service=self._autostart_service,
            auto_check_timer=self._auto_check_timer,
        )
        self._plasma_restart_coordinator = PlasmaRestartCoordinator(
            service=self._service,
            settings=self._settings,
            autostart_service=self._autostart_service,
            append_log=self._append_log,
            is_interactive_foreground=self.is_interactive_foreground,
            ask_restart=self._ask_plasma_restart,
            warn_restart_failed=self._warn_plasma_restart_failed,
        )

        self.setWindowTitle(f"ArchUpdater v{__version__}")
        self.resize(1280, 820)
        self.setMinimumSize(960, 680)

        self._build_ui()
        self._release_checker = AppReleaseChecker(self)
        self._release_checker.release_checked.connect(self.action_bar.set_github_release)
        self._details_presenter = PackageDetailsPresenter(
            panel=self.details_panel,
            style=self.style(),
            translate=self.tr,
        )
        self._operation_presenter = MainWindowOperationPresenter(self, self._state)
        self._arch_news_coordinator = ArchNewsCoordinator(
            load_read_ids=self._state_cache.load_read_arch_news_ids,
            mark_read_in_cache=self._state_cache.mark_arch_news_read,
            delete_items_from_cache=self._state_cache.delete_arch_news_items,
            show_dialog=lambda items, **kwargs: self._show_arch_news_dialog(items, **kwargs),
            set_unread_count=self.action_bar.set_arch_news_count,
            set_notice_text=self.action_bar.set_notice_text,
            clear_notice_text=self._clear_startup_notice,
            translate=self.tr,
        )
        self._check_presenter = MainWindowCheckPresenter(self, self._state)
        self._check_coordinator = MainWindowCheckCoordinator(self._check_presenter)
        self._update_preconditions = MainWindowUpdatePreconditions(self, self._state)
        self._connect_signals()
        self._optional_sources_snapshot = self._load_optional_sources_snapshot()
        self.header_widget.set_optional_sources_snapshot(self._optional_sources_snapshot)
        self._update_controller.set_active_optional_sources(
            self._optional_sources_snapshot.active_sources
        )

        self._set_operation_state(OperationState.IDLE, self.tr("Ready to check for updates."))
        initial_counters = UpdateCounters()
        self.header_widget.set_counters(initial_counters)
        self._update_last_checked_label()
        self._update_next_check_label()
        self.header_widget.set_system_status(self.tr("Ready to scan"))
        self._show_package_details(None)
        self._load_arch_news_history()
        if self._state_cache.has_unclean_update_session():
            self._set_startup_notice(
                self.tr(
                    "The previous update session did not finish cleanly. A fresh scan is recommended."
                )
            )
            self._state.startup_notice_pending_visibility = True
        app_settings = self._background_behavior.load_app_settings()
        self._apply_background_behavior_settings(app_settings)
        self._auto_check_timer.stop()
        QTimer.singleShot(0, self._start_initial_check_when_network_ready)

    def _build_ui(self) -> None:
        ui = build_main_window_ui(self)
        self.header_widget = ui.header_widget
        self.package_updates_widget = ui.package_updates_widget
        self.details_panel = ui.details_panel
        self.side_panel = ui.side_panel
        self.action_bar = ui.action_bar
        ui.close_details_button.clicked.connect(self.package_updates_widget.clear_selection)

    def _connect_signals(self) -> None:
        connect_main_window_signals(self)

    def _open_preferences(self) -> None:
        PreferencesCoordinator(
            parent=self,
            settings=self._settings,
            autostart_service=self._autostart_service,
            translation_manager=self._translation_manager,
            update_service=self._service,
            load_app_settings=self._background_behavior.load_app_settings,
            current_optional_sources_snapshot=lambda: self._optional_sources_snapshot,
            apply_optional_sources_snapshot=self._apply_optional_sources_snapshot,
            apply_tray_settings=self._apply_tray_settings,
            apply_background_behavior_settings=self._apply_background_behavior_settings,
            start_check_updates=self._flow_coordinator.start_check_updates,
            translate=self.tr,
        ).open()

    def begin_check_ui(self) -> None:
        self._check_coordinator.begin_check_ui()
        self._release_checker.check()

    def show_no_updates_selected_message(self) -> None:
        QMessageBox.information(
            self,
            self.tr("No Updates Selected"),
            self.tr("There are no selected updates to install."),
        )

    def confirm_update_preconditions(self, plan: UpdatePlan) -> UpdatePlan | None:
        return self._update_preconditions.confirm(plan)

    def prepare_update_start_ui(self) -> None:
        self._state.plasma_restart_recommended = False
        self._state_cache.mark_update_session_started()
        self._set_operation_state(
            OperationState.UPDATING,
            self.tr("Starting integrated updater..."),
        )
        self.header_widget.set_system_status(self.tr("Starting updater"))

    def handle_update_start_failure(self, exc: Exception) -> None:
        self._state_cache.clear_update_session()
        self._progress_presenter.close_dialog()
        self._set_operation_state(OperationState.ERROR, str(exc))
        self.header_widget.set_system_status(self.tr("Error"))

    def apply_check_result(
        self,
        result: UpdateCheckResult,
        *,
        persist: bool = True,
    ) -> None:
        self._check_coordinator.apply_check_result(result, persist=persist)

    def apply_check_failure(self, message: str, logs: object) -> None:
        self._check_coordinator.apply_check_failure(message, logs)

    def apply_check_progress(self, label: str, percent: int) -> None:
        self._check_presenter.apply_check_progress(label, percent)

    def apply_update_status(self, value: str) -> None:
        messages = update_status_messages(value, translate=self.tr)
        if messages is not None:
            status_message, header_message = messages
            self._set_operation_state(OperationState.UPDATING, status_message)
            self.header_widget.set_system_status(header_message)
            return


    def apply_update_completed(self, success: bool, message: str, outcome: str) -> None:
        self._completion_coordinator.apply(success=success, message=message, outcome=outcome)

    @Slot(object)
    def _handle_update_progress(self, snapshot: UpdateProgressSnapshot) -> None:
        self._progress_presenter.apply_progress(snapshot)

    @Slot(object)
    def _handle_question_request(self, payload: object) -> None:
        self._progress_presenter.handle_question_request(payload)

    @Slot(object)
    def _handle_aur_update_skipped(self, payload: object) -> None:
        data = payload if isinstance(payload, dict) else {}
        target_id = str(data.get("target_id") or "")
        package_name = str(data.get("package_name") or target_id)
        reason = str(data.get("reason") or "").strip() or self.tr(
            "PKGBUILD review was cancelled."
        )
        matched = False
        for package in self._state.packages:
            if package.source is not UpdateSource.AUR or package.target_id != target_id:
                continue
            package.selected = False
            package.selection_locked = True
            package.selection_lock_reason = reason
            package.skipped_by_pkgbuild_review = True
            if reason not in package.warnings:
                package.warnings.append(reason)
            matched = True

        if matched:
            self._state.active_update_packages = [
                package
                for package in self._state.active_update_packages
                if package.source is not UpdateSource.AUR or package.target_id != target_id
            ]
            self._refresh_package_updates_view()
            self._update_selection_actions()

        self.action_bar.show_transient_message(
            self.tr("Skipped AUR update: {package}").format(package=package_name),
            5000,
        )

    @Slot(str, bool)
    def _on_package_selection_changed(self, _package_id: str, _selected: bool) -> None:
        self._update_selection_actions()

    @Slot()
    def _mark_plasma_restart_recommended(self) -> None:
        self._state.plasma_restart_recommended = True

    def _mark_post_update_refresh_pending(self) -> None:
        self._state.post_update_refresh_pending = True

    def has_post_update_refresh_pending(self) -> bool:
        return self._state.post_update_refresh_pending

    def _post_update_refresh_can_use_local_system_db(self) -> bool:
        return any(
            package.source is UpdateSource.SYSTEM
            for package in self._state.active_update_packages
        )

    @Slot(object)
    def _on_source_filter_changed(self, source: object) -> None:
        self._state.active_source_filter = source if isinstance(source, UpdateSource) else None
        self.header_widget.set_active_source_filter(self._state.active_source_filter)
        self.package_updates_widget.set_source_filter(self._state.active_source_filter)
        current_item = self.package_updates_widget.tree.currentItem()
        if current_item is None:
            self._show_package_details(None)

    @Slot(object)
    def _show_package_details(self, package: PackageUpdate | None) -> None:
        if not package:
            self._refresh_details_empty_state()
            return
        self._details_presenter.show_package(package)
        self.side_panel.show()

    def _update_last_checked_label(self) -> None:
        if self._state.last_checked_at is None:
            self.header_widget.set_last_checked(self.tr("Last checked: Never"))
            self._update_next_check_label()
            return

        self.header_widget.set_last_checked(
            self.tr("Last checked: {timestamp}").format(
                timestamp=self._state.last_checked_at.strftime("%Y-%m-%d %H:%M:%S")
            )
        )
        self._update_next_check_label()

    def _update_next_check_label(self) -> None:
        next_check_at = self._background_behavior.next_check_at(
            self._background_behavior.load_app_settings(),
            last_checked_at=self._state.last_checked_at,
        )
        if next_check_at is None:
            self.header_widget.set_next_check("")
            return
        self.header_widget.set_next_check(
            self.tr("Next check: {timestamp}").format(
                timestamp=next_check_at.strftime("%Y-%m-%d %H:%M:%S")
            )
        )

    def _set_operation_state(self, state: OperationState, message: str) -> None:
        self._operation_presenter.set_operation_state(state, message)

    def _refresh_details_empty_state(self) -> None:
        self._operation_presenter.refresh_details_empty_state()

    def _sync_side_panel_mode(self) -> None:
        has_selection = bool(self.package_updates_widget.tree.selectedItems())
        self.side_panel.setVisible(has_selection)
        if self._state.packages:
            return
        if self._state.operation_state is OperationState.ERROR:
            self.package_updates_widget.show_status_placeholder(
                self.tr("Update check failed"),
                self._state.check_failure_message,
            )
        elif self._state.operation_state is OperationState.CHECKING:
            self.package_updates_widget.show_status_placeholder(
                self.tr("Checking for updates..."), "",
            )
        elif self._state.operation_state is OperationState.WAITING_AUTH:
            self.package_updates_widget.show_status_placeholder(
                self.tr("Waiting for Authentication"), "",
            )
        elif self._state.operation_state is OperationState.COMPLETED:
            if self._state.check_warnings:
                self.package_updates_widget.show_status_placeholder(
                    self.tr("Checked with Warnings"),
                    "\n".join(self._state.check_warnings),
                )
            else:
                self.package_updates_widget.show_up_to_date()

    def _update_selection_actions(self) -> None:
        self._operation_presenter.update_selection_actions()

    def _refresh_package_updates_view(self) -> None:
        self.package_updates_widget.set_packages(
            self._state.packages,
            source_texts=source_texts(),
            system_tooltip=self.tr(
                "Pacman packages are selected and installed together as one full system upgrade."
            ),
        )
        self.package_updates_widget.set_source_filter(self._state.active_source_filter)
        self.header_widget.set_active_source_filter(self._state.active_source_filter)

    def refresh_selection_actions(self) -> None:
        self._update_selection_actions()

    def _build_update_plan(self) -> UpdatePlan:
        return self._operation_presenter.build_update_plan()

    def build_update_plan(self) -> UpdatePlan:
        return self._build_update_plan()

    def _apply_optional_sources_snapshot(self, snapshot: OptionalSourcesSnapshot) -> None:
        self._optional_sources_snapshot = snapshot
        self.header_widget.set_optional_sources_snapshot(snapshot)
        self._update_controller.set_active_optional_sources(snapshot.active_sources)
        if (
            self._state.active_source_filter is not None
            and self._state.active_source_filter not in snapshot.selectable_sources
        ):
            self._state.active_source_filter = None
            self.header_widget.set_active_source_filter(None)
            self.package_updates_widget.set_source_filter(None)
            self._show_package_details(None)

    def _load_optional_sources_snapshot(self) -> OptionalSourcesSnapshot:
        return self._service.optional_sources_snapshot()

    def _set_aur_updates_enabled(self, enabled: bool) -> None:
        current_settings = self._settings.load_app_settings()
        if current_settings.aur_updates_enabled == enabled:
            return
        self._settings.save_app_settings(
            replace(current_settings, aur_updates_enabled=enabled)
        )

    def _open_github(self) -> None:
        url = RELEASES_URL if self._release_checker.available_tag else GITHUB_URL
        QDesktopServices.openUrl(QUrl(url))

    def _open_arch_news(self) -> None:
        self._arch_news_coordinator.open_news(self._state.arch_news)

    def _maybe_prompt_plasma_restart(self) -> None:
        self._state.plasma_restart_recommended = self._plasma_restart_coordinator.maybe_prompt(
            self._state.plasma_restart_recommended
        )

    def _show_arch_news_dialog(
        self,
        items,
        *,
        intro: str,
        ok_text: str,
        cancel_text: str,
        include_cancel: bool,
        enable_ok: bool,
    ) -> ArchNewsDialogResult:
        return show_arch_news_dialog(
            self,
            items,
            intro=intro,
            ok_text=ok_text,
            cancel_text=cancel_text,
            include_cancel=include_cancel,
            enable_ok=enable_ok,
        )

    def _maybe_show_reboot_advisory(self) -> None:
        active_packages = self._state.active_update_packages
        packages = critical_reboot_packages(active_packages)
        shutdown_devices = firmware_shutdown_devices(active_packages)
        reboot_devices = firmware_reboot_devices(active_packages)
        self._state.active_update_packages = []
        if shutdown_devices:
            QMessageBox.information(
                self,
                self.tr("Shutdown Required"),
                self.tr(
                    "The updated firmware requires a full shutdown. Save your work and power the computer off completely before using it again.\n\nDevices: {devices}"
                ).format(devices=", ".join(shutdown_devices[:8])),
            )
            return
        if not packages and not reboot_devices:
            return
        affected = [*packages, *reboot_devices]
        QMessageBox.information(
            self,
            self.tr("Restart Recommended"),
            self.tr(
                "Some updated system components are already running. Restart when convenient to fully apply them.\n\nPackages: {packages}"
            ).format(packages=", ".join(affected[:8])),
        )

    def _ask_plasma_restart(self) -> bool:
        answer = QMessageBox.question(
            self,
            self.tr("Restart Plasma Shell"),
            self.tr(
                "KDE Store add-ons were updated. Restart plasmashell now to fully apply the changes?"
            ),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        return answer is QMessageBox.StandardButton.Yes

    def _warn_plasma_restart_failed(self) -> None:
        QMessageBox.warning(
            self,
            self.tr("Restart Failed"),
            self.tr("Plasma shell could not be restarted automatically."),
        )

    def set_tray_controller(self, tray_controller: TrayController) -> None:
        self._tray_controller = tray_controller

    def auto_check_enabled(self) -> bool:
        return self._background_behavior.auto_check_enabled()

    def auto_check_interval_hours(self) -> int:
        return self._background_behavior.auto_check_interval_hours()

    def next_auto_check_at(self) -> datetime | None:
        return self._background_behavior.next_check_at(
            self._background_behavior.load_app_settings(),
            last_checked_at=self._state.last_checked_at,
        )

    def set_auto_check_schedule(self, interval_hours: int | None) -> None:
        message = self._background_behavior.set_auto_check_schedule(interval_hours)
        if message is None:
            return
        self.action_bar.show_transient_message(message, 3000)

    def show_from_tray(self) -> None:
        if self.isMinimized():
            self.showNormal()
        else:
            self.show()
        self.raise_()
        self.activateWindow()

    def quit_application_from_tray(self) -> None:
        if self._update_controller.is_busy():
            self.show_from_tray()
            self._show_busy_exit_warning()
            return
        self._allow_close = True
        QApplication.instance().quit()

    def _show_busy_exit_warning(self) -> None:
        QMessageBox.warning(
            self,
            self.tr("Operation in progress"),
            self.tr(
                "ArchUpdater cannot quit while an update check or installation is running. "
                "Wait for the operation to finish."
            ),
        )

    def start_check_updates_from_tray(self) -> bool:
        return self._flow_coordinator.start_check_updates()

    def is_interactive_foreground(self) -> bool:
        return self.isVisible() and not self.isMinimized() and self.isActiveWindow()

    def should_show_background_notifications(self) -> bool:
        if self.isVisible() and not self.isMinimized():
            return False

        if self._progress_presenter.has_visible_dialog():
            return False

        return True

    def _append_log(self, message: str) -> None:
        if not message:
            return
        self._update_controller.append_external_log(message.rstrip())

    @property
    def update_controller(self) -> UpdateController:
        return self._update_controller

    def _apply_tray_settings(self, app_settings: AppSettings) -> None:
        self._background_behavior.apply_tray_settings(self._tray_controller, app_settings)

    def _apply_background_behavior_settings(self, app_settings: AppSettings) -> None:
        self._background_behavior.apply_auto_check_settings(
            app_settings,
            last_checked_at=self._state.last_checked_at,
        )
        self._update_next_check_label()

    def _defer_next_auto_check(self) -> None:
        self._background_behavior.apply_auto_check_settings(
            self._background_behavior.load_app_settings(),
            last_checked_at=self._state.last_checked_at,
            defer_if_due=True,
        )
        self._update_next_check_label()

    def _start_initial_check_when_network_ready(self) -> None:
        if self._update_controller.is_busy():
            return

        if self._network_is_ready_for_update_check():
            self._stop_startup_network_wait()
            self._flow_coordinator.start_check_updates()
            return

        self._show_waiting_for_network_state()
        self._ensure_startup_network_wait_connected()
        if not self._startup_network_retry_timer.isActive():
            self._startup_network_retry_timer.start(self.STARTUP_NETWORK_RETRY_MS)

    def _network_is_ready_for_update_check(self) -> bool:
        network_information = self._network_information_instance()
        if network_information is None:
            return True
        return (
            network_information.reachability()
            == QNetworkInformation.Reachability.Online
        )

    def _network_information_instance(self):  # noqa: ANN202
        try:
            if not QNetworkInformation.loadDefaultBackend():
                return None
            return QNetworkInformation.instance()
        except RuntimeError:
            return None

    def _show_waiting_for_network_state(self) -> None:
        self.header_widget.set_system_status(self.tr("Waiting for network..."))
        self.header_widget.set_last_checked(self.tr("Last checked: Waiting for network"))
        self.header_widget.set_next_check("")
        self.action_bar.clear_status_text()
        self.details_panel.show_placeholder(
            title=self.tr("Waiting for network..."),
            text=self.tr("The startup scan will begin automatically when the network is online."),
            icon=QStyle.StandardPixmap.SP_BrowserReload,
        )
        self.side_panel.hide()
        self.package_updates_widget.show_status_placeholder(
            self.tr("Waiting for network..."),
            self.tr("The startup scan will begin automatically when the network is online."),
        )

    def _ensure_startup_network_wait_connected(self) -> None:
        if self._startup_network_signal_connected:
            return
        network_information = self._network_information_instance()
        if network_information is None:
            return
        try:
            network_information.reachabilityChanged.connect(
                self._handle_startup_network_reachability_changed
            )
        except (RuntimeError, TypeError):
            return
        self._startup_network_signal_connected = True

    def _stop_startup_network_wait(self) -> None:
        self._startup_network_retry_timer.stop()
        if not self._startup_network_signal_connected:
            return
        network_information = self._network_information_instance()
        if network_information is not None:
            try:
                network_information.reachabilityChanged.disconnect(
                    self._handle_startup_network_reachability_changed
                )
            except (RuntimeError, TypeError):
                pass
        self._startup_network_signal_connected = False

    @Slot(object)
    def _handle_startup_network_reachability_changed(self, _reachability: object) -> None:
        if self._network_is_ready_for_update_check():
            self._start_initial_check_when_network_ready()

    def _run_scheduled_check(self) -> None:
        if self._update_controller.is_busy():
            self._defer_next_auto_check()
            return
        if not self._flow_coordinator.start_check_updates():
            self._defer_next_auto_check()

    def _load_arch_news_history(self) -> None:
        self._state.arch_news = self._state_cache.load_arch_news_items()
        self._arch_news_coordinator.apply_read_state(self._state.arch_news)

    def _set_startup_notice(self, text: str) -> None:
        self.action_bar.set_notice_text(text)

    def _clear_startup_notice(self) -> None:
        self._state.startup_notice_pending_visibility = False
        self.action_bar.clear_notice_text()

    def closeEvent(self, event: QCloseEvent) -> None:
        if (
            not self._allow_close
            and self._tray_controller is not None
            and self._tray_controller.is_active()
        ):
            self.hide()
            event.ignore()
            return

        if self._update_controller.is_busy():
            self._allow_close = False
            self._show_busy_exit_warning()
            event.ignore()
            return

        self._update_controller.shutdown()
        super().closeEvent(event)

    def showEvent(self, event: QShowEvent) -> None:
        super().showEvent(event)
        if self._state.startup_notice_pending_visibility:
            self._state.startup_notice_pending_visibility = False
