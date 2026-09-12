from __future__ import annotations

from dataclasses import replace
from typing import Any

from PySide6.QtCore import QCoreApplication

from archupdater.domain.check_results import ArchNewsCheckState, UpdateCheckResult
from archupdater.domain.enums import OperationState
from archupdater.domain.packages import UpdateCounters
from archupdater.presentation.main_window.logic import (
    check_completion_message,
    source_texts,
    system_status_summary,
)
from archupdater.presentation.main_window.state import MainWindowState


class MainWindowCheckPresenter:
    def __init__(self, window: Any, state: MainWindowState) -> None:
        self._window = window
        self._state = state

    def tr(self, text: str) -> str:
        return QCoreApplication.translate("MainWindowCheckPresenter", text)

    def set_check_operation_state(self, state: OperationState, message: str) -> None:
        self._window._set_operation_state(state, message)

    def has_post_update_refresh_pending(self) -> bool:
        return self._state.post_update_refresh_pending

    def show_post_update_refreshing_state(self) -> None:
        self._state.packages = []
        self._state.last_checked_at = None
        self._state.check_failure_message = ""
        self._state.check_warnings = []
        self._window.package_updates_widget.clear_packages()
        self._window._show_package_details(None)
        self._window.header_widget.set_counters(UpdateCounters())
        self._window.header_widget.set_system_status(self.tr("Refreshing package status..."))
        self._window.header_widget.set_last_checked(self.tr("Last checked: In progress"))
        self._window.header_widget.set_next_check("")
        self._window.action_bar.set_update_selection(0)

    def reset_for_fresh_check(self) -> None:
        self._state.packages = []
        self._state.last_checked_at = None
        self._state.check_failure_message = ""
        self._state.check_warnings = []
        self._window.package_updates_widget.clear_packages()
        self._window._show_package_details(None)
        self._window.header_widget.set_counters(UpdateCounters())
        self._window.header_widget.set_system_status(self.tr("Checking for updates..."))
        self._window.header_widget.set_last_checked(self.tr("Last checked: In progress"))
        self._window.header_widget.set_next_check("")
        self._window.action_bar.set_update_selection(0)

    def apply_successful_check_result_ui(self, result: UpdateCheckResult) -> None:
        window = self._window
        self._state.post_update_refresh_pending = False
        self._state.check_failure_message = ""
        self._state.check_warnings = list(result.warnings)
        window._apply_optional_sources_snapshot(window._load_optional_sources_snapshot())
        self._state.packages = [replace(package) for package in result.packages]
        deleted_news_ids = window._state_cache.load_deleted_arch_news_ids()
        self._state.arch_news_state = result.arch_news_state
        if result.arch_news_state is ArchNewsCheckState.LOADED:
            self._state.arch_news = [
                replace(item) for item in result.arch_news if item.item_id not in deleted_news_ids
            ]
        window._arch_news_coordinator.apply_read_state(self._state.arch_news)
        window.action_bar.set_arch_news_count(
            len(window._arch_news_coordinator.unread_items(self._state.arch_news))
        )
        self._state.last_checked_at = result.checked_at
        window.package_updates_widget.set_packages(
            self._state.packages,
            source_texts=source_texts(),
            system_tooltip=self.tr(
                "Pacman packages are selected and installed together as one full system upgrade."
            ),
        )
        window.package_updates_widget.set_source_filter(self._state.active_source_filter)
        window.header_widget.set_active_source_filter(self._state.active_source_filter)
        window.header_widget.set_optional_sources_snapshot(window._optional_sources_snapshot)
        window.header_widget.set_counters(result.counters)
        window.header_widget.set_system_status(
            system_status_summary(
                result.actionable_count,
                has_warnings=bool(result.warnings),
            )
        )
        window._update_last_checked_label()
        state_message = check_completion_message(
            package_count=result.actionable_count,
            warning_count=len(result.warnings),
        )
        window._set_operation_state(OperationState.COMPLETED, state_message)
        if result.warnings:
            window.action_bar.set_status_text(
                self.tr("Check warnings: {warnings}").format(warnings="; ".join(result.warnings))
            )
        window._update_selection_actions()

    def persist_successful_check_result(self) -> None:
        window = self._window
        if self._state.arch_news:
            window._state_cache.store_arch_news_items(self._state.arch_news)
        window._state_cache.clear_update_session()
        if not self._state.startup_notice_pending_visibility:
            window._clear_startup_notice()
            window._arch_news_coordinator.show_notice(self._state.arch_news)
        window._apply_background_behavior_settings(window._background_behavior.load_app_settings())

    def apply_fresh_check_failure_ui(self, message: str, _logs: object) -> None:
        window = self._window
        self._state.post_update_refresh_pending = False
        window._apply_optional_sources_snapshot(window._load_optional_sources_snapshot())
        self._state.packages = []
        self._state.last_checked_at = None
        self._state.check_failure_message = message.strip()
        self._state.check_warnings = []
        window.package_updates_widget.clear_packages()
        window.header_widget.set_counters(UpdateCounters())
        window.header_widget.set_optional_sources_snapshot(window._optional_sources_snapshot)
        window.header_widget.set_system_status(self.tr("Error"))
        window.header_widget.set_last_checked(self.tr("Last checked: Failed"))
        window._update_next_check_label()
        window.action_bar.set_update_selection(0)

        window._set_operation_state(OperationState.ERROR, message)
        window.action_bar.clear_status_text()
        window._show_package_details(None)
        window._defer_next_auto_check()

    def apply_check_progress(self, label: str, percent: int) -> None:
        self._window._progress_controller.set_check_progress(label, percent)
