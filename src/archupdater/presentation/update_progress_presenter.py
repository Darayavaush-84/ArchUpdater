from __future__ import annotations

from PySide6.QtWidgets import QWidget

from archupdater.domain.progress import UpdateProgressSnapshot
from archupdater.presentation.update_controller import UpdateController
from archupdater.presentation.update_interaction_dialogs import handle_question_request
from archupdater.presentation.update_progress_dialog import UpdateProgressDialog


class UpdateProgressPresenter:
    def __init__(self, parent: QWidget, update_controller: UpdateController) -> None:
        self._parent = parent
        self._update_controller = update_controller
        self._dialog: UpdateProgressDialog | None = None

    @property
    def dialog(self) -> UpdateProgressDialog | None:
        return self._dialog

    def has_visible_dialog(self) -> bool:
        return self._dialog is not None and self._dialog.isVisible()

    def apply_progress(self, snapshot: UpdateProgressSnapshot) -> None:
        present_dialog = snapshot.present_dialog
        if not present_dialog:
            return
        if present_dialog and self._dialog is None:
            self._dialog = UpdateProgressDialog(self._parent)
            self._dialog.finished.connect(self._on_dialog_finished)

        if self._dialog is None:
            return

        self._dialog.apply_snapshot(snapshot)
        if present_dialog and not self._dialog.isVisible():
            self._dialog.show()
            self._dialog.raise_()
            self._dialog.activateWindow()

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
