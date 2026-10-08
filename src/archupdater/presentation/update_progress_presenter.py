from __future__ import annotations

from dataclasses import replace
import logging

from PySide6.QtWidgets import QWidget

from archupdater.domain.progress import UpdateProgressSnapshot
from archupdater.infrastructure.settings import SettingsService
from archupdater.infrastructure.last_update import LastUpdateStore
from archupdater.presentation.update_controller import UpdateController
from archupdater.presentation.update_interaction_dialogs import handle_question_request
from archupdater.presentation.update_progress_dialog import UpdateProgressDialog


class UpdateProgressPresenter:
    def __init__(
        self, parent: QWidget, update_controller: UpdateController,
        *, settings: SettingsService | None = None,
        last_update_store: LastUpdateStore | None = None,
    ) -> None:
        self._parent = parent
        self._update_controller = update_controller
        self._settings = settings or SettingsService()
        self._dialog: UpdateProgressDialog | None = None
        self._last_update_store = last_update_store or LastUpdateStore()
        self._last_update = self._last_update_store.load()
        self._history_dialog: UpdateProgressDialog | None = None
        self._displayed_update = None

    @property
    def dialog(self) -> UpdateProgressDialog | None:
        return self._dialog

    def has_visible_dialog(self) -> bool:
        return any(
            dialog is not None and dialog.isVisible()
            for dialog in (self._dialog, self._history_dialog)
        )

    def has_last_update(self) -> bool:
        return self._last_update is not None

    def show_last_update(self) -> None:
        if self._last_update is None:
            return
        if self._history_dialog is not None and self._displayed_update is not self._last_update:
            self._history_dialog.close()
        if self._history_dialog is None:
            self._history_dialog = UpdateProgressDialog(
                self._parent, completed_at=self._last_update.completed_at,
            )
            self._history_dialog.apply_snapshot(self._last_update.snapshot)
            self._displayed_update = self._last_update
            self._history_dialog.finished.connect(self._on_history_dialog_finished)
        self._history_dialog.show()
        self._history_dialog.raise_()
        self._history_dialog.activateWindow()

    def _on_history_dialog_finished(self, _result: int) -> None:
        if self._history_dialog is not None:
            self._history_dialog.deleteLater()
            self._history_dialog = None
            self._displayed_update = None

    def apply_progress(self, snapshot: UpdateProgressSnapshot) -> None:
        if snapshot.final_state:
            try:
                self._last_update = self._last_update_store.save(snapshot)
            except (OSError, ValueError):
                logging.getLogger(__name__).warning("Could not save the last update", exc_info=True)
        present_dialog = snapshot.present_dialog
        if not present_dialog:
            return
        if present_dialog and self._dialog is None:
            self._dialog = UpdateProgressDialog(self._parent)
            self._dialog.auto_close_checkbox.setChecked(
                self._settings.load_app_settings().auto_close_after_success
            )
            self._dialog.auto_close_checkbox.toggled.connect(self._save_auto_close_preference)
            self._dialog.finished.connect(self._on_dialog_finished)

        if self._dialog is None:
            return

        self._dialog.apply_snapshot(snapshot)
        if present_dialog and not self._dialog.isVisible():
            self._dialog.show()
            self._dialog.raise_()
            self._dialog.activateWindow()

    def _save_auto_close_preference(self, enabled: bool) -> None:
        self._settings.save_app_settings(replace(
            self._settings.load_app_settings(), auto_close_after_success=enabled,
        ))

    def handle_question_request(self, payload: object) -> None:
        dialog = self._dialog
        if dialog is not None:
            dialog.set_waiting_for_response(True)
        try:
            handle_question_request(
                parent=dialog or self._parent,
                payload=payload,
                submit_response=self._update_controller.submit_question_response,
                cancel_question=self._update_controller.cancel_question,
            )
        finally:
            if dialog is not None and self._dialog is dialog:
                dialog.set_waiting_for_response(False)

    def close_dialog(self) -> None:
        if self._dialog is None:
            return
        self._dialog.deleteLater()
        self._dialog = None

    def _on_dialog_finished(self, _result: int) -> None:
        self.close_dialog()
