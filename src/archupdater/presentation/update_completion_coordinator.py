from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QMessageBox, QWidget

from archupdater.domain.enums import OperationState
from archupdater.infrastructure.app_state_cache import AppStateCache
from archupdater.application.update_session.protocol import BatchOutcome


Translate = Callable[[str], str]


class UpdateCompletionCoordinator:
    def __init__(
        self,
        *,
        parent: QWidget,
        state_cache: AppStateCache,
        clear_selection: Callable[[], None],
        set_operation_state: Callable[[OperationState, str], None],
        set_header_status: Callable[[str], None],
        append_log: Callable[[str], None],
        maybe_prompt_plasma_restart: Callable[[], None],
        maybe_show_reboot_advisory: Callable[[], None],
        should_show_reboot_advisory_after_failure: Callable[[], bool],
        close_progress_dialog: Callable[[], None],
        update_selection_actions: Callable[[], None],
        mark_post_update_refresh_pending: Callable[[], None],
        use_local_system_db_for_post_update_refresh: Callable[[], bool],
        start_check_updates: Callable[[bool], object],
        progress_dialog_parent: Callable[[], QWidget | None],
        translate: Translate,
    ) -> None:
        self._parent = parent
        self._state_cache = state_cache
        self._clear_selection = clear_selection
        self._set_operation_state = set_operation_state
        self._set_header_status = set_header_status
        self._append_log = append_log
        self._maybe_prompt_plasma_restart = maybe_prompt_plasma_restart
        self._maybe_show_reboot_advisory = maybe_show_reboot_advisory
        self._should_show_reboot_advisory_after_failure = (
            should_show_reboot_advisory_after_failure
        )
        self._close_progress_dialog = close_progress_dialog
        self._update_selection_actions = update_selection_actions
        self._mark_post_update_refresh_pending = mark_post_update_refresh_pending
        self._use_local_system_db_for_post_update_refresh = (
            use_local_system_db_for_post_update_refresh
        )
        self._start_check_updates = start_check_updates
        self._progress_dialog_parent = progress_dialog_parent
        self._t = translate

    def apply(self, *, success: bool, message: str, outcome: str) -> None:
        if outcome == BatchOutcome.SUCCESS.value:
            self._apply_success(message)
            return
        if outcome == BatchOutcome.PARTIAL_SUCCESS.value:
            self._apply_partial_success(message)
            return
        if outcome == BatchOutcome.NO_CHANGES.value:
            self._apply_no_changes(message)
            return
        if outcome == BatchOutcome.AUTH_CANCELLED.value:
            self._apply_auth_cancelled(message)
            return
        if outcome == BatchOutcome.CANCELLED.value:
            self._apply_cancelled(message)
            return
        self._apply_failure(message, outcome)

    def _apply_success(self, message: str) -> None:
        self._state_cache.clear_update_session()
        use_local_system_db = self._use_local_system_db_for_post_update_refresh()
        self._mark_post_update_refresh_pending()
        self._set_operation_state(
            OperationState.COMPLETED,
            message or self._t("System update completed."),
        )
        self._set_header_status(self._t("Updates installed"))
        self._append_log(message or self._t("System update completed successfully."))
        self._maybe_prompt_plasma_restart()
        self._maybe_show_reboot_advisory()
        QTimer.singleShot(1600, lambda: self._start_check_updates(use_local_system_db))

    def _apply_partial_success(self, message: str) -> None:
        self._state_cache.clear_update_session()
        final_message = message or self._t("Some selected updates were skipped.")
        use_local_system_db = self._use_local_system_db_for_post_update_refresh()
        self._mark_post_update_refresh_pending()
        self._set_operation_state(OperationState.COMPLETED, final_message)
        self._set_header_status(self._t("Updates installed with skipped items"))
        self._append_log(final_message)
        self._maybe_prompt_plasma_restart()
        self._maybe_show_reboot_advisory()
        QTimer.singleShot(1600, lambda: self._start_check_updates(use_local_system_db))

    def _apply_no_changes(self, message: str) -> None:
        self._state_cache.clear_update_session()
        self._clear_selection()
        final_message = message or self._t("No selected updates were installed.")
        self._set_operation_state(OperationState.IDLE, final_message)
        self._set_header_status(self._t("No updates installed"))
        self._append_log(final_message)
        self._update_selection_actions()

    def _apply_auth_cancelled(self, message: str) -> None:
        self._state_cache.clear_update_session()
        self._clear_selection()
        self._set_operation_state(OperationState.IDLE, message)
        self._set_header_status(self._t("Authentication cancelled"))
        self._append_log(message)
        self._close_progress_dialog()
        self._update_selection_actions()
        # Authorization was cancelled before the transaction started.  The
        # cached scan is therefore still valid as a source of candidates, but
        # it must not be presented as an installation result.  Re-scan so the
        # main window reflects the actual package state (including Flatpak).
        QTimer.singleShot(0, lambda: self._start_check_updates(False))

    def _apply_failure(self, message: str, outcome: str) -> None:
        self._clear_selection()
        use_local_system_db = self._use_local_system_db_for_post_update_refresh()
        self._mark_post_update_refresh_pending()
        self._set_operation_state(
            OperationState.ERROR,
            message or self._t("System update failed."),
        )
        self._state_cache.clear_update_session()
        self._set_header_status(self._t("Update failed"))
        self._append_log(message or self._t("System update failed."))
        if outcome == BatchOutcome.SYSTEM_TRANSACTION_FAILED.value:
            self._show_system_transaction_error()
        if self._should_show_reboot_advisory_after_failure():
            self._maybe_show_reboot_advisory()
        self._update_selection_actions()
        QTimer.singleShot(0, lambda: self._start_check_updates(use_local_system_db))

    def _apply_cancelled(self, message: str) -> None:
        self._clear_selection()
        final_message = message or self._t("The update was cancelled.")
        use_local_system_db = self._use_local_system_db_for_post_update_refresh()
        self._mark_post_update_refresh_pending()
        self._set_operation_state(OperationState.IDLE, final_message)
        self._state_cache.clear_update_session()
        self._set_header_status(self._t("Update cancelled"))
        self._append_log(final_message)
        if self._should_show_reboot_advisory_after_failure():
            self._maybe_show_reboot_advisory()
        self._update_selection_actions()
        QTimer.singleShot(0, lambda: self._start_check_updates(use_local_system_db))

    def _show_system_transaction_error(self) -> None:
        QMessageBox.warning(
            self._progress_dialog_parent() or self._parent,
            self._t("The system upgrade could not be completed"),
            self._t(
                "Pacman could not complete the full system transaction.\n\n"
                "There may be a dependency, mirror, signature, or package conflict.\n\n"
                "Review the live activity log before trying again."
            ),
        )
