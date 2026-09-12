from __future__ import annotations

from typing import Any


def connect_main_window_signals(window: Any) -> None:
    window.action_bar.check_requested.connect(window._flow_coordinator.start_check_updates)
    window.action_bar.update_requested.connect(window._flow_coordinator.start_update)
    window.action_bar.arch_news_requested.connect(window._open_arch_news)
    window.action_bar.preferences_requested.connect(window._open_preferences)
    window.action_bar.github_requested.connect(window._open_github)

    window.package_updates_widget.current_package_changed.connect(window._show_package_details)
    window.package_updates_widget.package_selection_changed.connect(
        window._on_package_selection_changed
    )
    window.header_widget.source_filter_changed.connect(window._on_source_filter_changed)

    window._update_controller.check_succeeded.connect(
        window._flow_coordinator.handle_check_success
    )
    window._update_controller.check_failed.connect(
        window._flow_coordinator.handle_check_failure
    )
    window._update_controller.check_progress_changed.connect(
        window._flow_coordinator.handle_check_progress
    )
    window._update_controller.update_status_changed.connect(
        window._flow_coordinator.handle_update_status
    )
    window._update_controller.update_progress_changed.connect(window._handle_update_progress)
    window._update_controller.question_requested.connect(window._handle_question_request)
    window._update_controller.aur_update_skipped.connect(window._handle_aur_update_skipped)
    window._update_controller.plasma_restart_recommended.connect(
        window._mark_plasma_restart_recommended
    )
    window._update_controller.update_completed.connect(
        window._flow_coordinator.handle_update_completed
    )
    window._update_controller.busy_changed.connect(window._flow_coordinator.handle_busy_changed)

    window._progress_controller.progress_changed.connect(window.header_widget.set_progress)
