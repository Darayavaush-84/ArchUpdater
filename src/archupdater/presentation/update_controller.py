from __future__ import annotations

import threading

from PySide6.QtCore import QObject, QThread, Signal, Slot

from archupdater.domain.check_results import UpdateCheckResult
from archupdater.domain.enums import UpdateSource
from archupdater.domain.update_plan import UpdatePlan
from archupdater.presentation.integrated_batch_client import IntegratedBatchUpdateClient
from archupdater.presentation.update_progress_model import UpdateProgressModel
from archupdater.application.update_session.protocol import BatchEventType, BatchOutcome, BatchStep
from archupdater.application.updates import UpdateApplication
from archupdater.application.update_sources.check_coordinator import UpdateCheckCancelled


class UpdateCheckWorker(QObject):
    finished = Signal(object)
    failed = Signal(str, object)
    progress_changed = Signal(str, int)

    def __init__(
        self,
        service: UpdateApplication,
        *,
        active_optional_sources: set[UpdateSource] | None = None,
        use_local_system_db: bool = False,
    ) -> None:
        super().__init__()
        self._service = service
        self._active_optional_sources = active_optional_sources
        self._use_local_system_db = use_local_system_db
        self._cancel_requested = threading.Event()

    def cancel(self) -> None:
        self._cancel_requested.set()

    @Slot()
    def run(self) -> None:
        def report_progress(label: str, percent: int) -> None:
            if self._cancel_requested.is_set():
                raise UpdateCheckCancelled()
            self.progress_changed.emit(label, percent)

        try:
            result = self._service.check_updates(
                progress_callback=report_progress,
                active_optional_sources=self._active_optional_sources,
                use_local_system_db=self._use_local_system_db,
                cancel_requested=self._cancel_requested.is_set,
            )
            if self._cancel_requested.is_set():
                return
        except UpdateCheckCancelled:
            return
        except Exception as exc:  # pragma: no cover
            self.failed.emit(str(exc), getattr(exc, "logs", []))
            return

        self.finished.emit(result)


class UpdateController(QObject):
    WORKER_SHUTDOWN_TIMEOUT_MS = 3000

    check_succeeded = Signal(object)
    check_failed = Signal(str, object)
    check_progress_changed = Signal(str, int)
    update_status_changed = Signal(str)
    update_progress_changed = Signal(object)
    question_requested = Signal(object)
    aur_update_skipped = Signal(object)
    update_completed = Signal(bool, str, str)
    plasma_restart_recommended = Signal()
    busy_changed = Signal(bool)

    def __init__(self, service: UpdateApplication, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._service = service
        self._worker_thread: QThread | None = None
        self._worker: UpdateCheckWorker | None = None
        self._update_client: IntegratedBatchUpdateClient | None = None
        self._shutting_down = False
        self._progress_model = UpdateProgressModel(self.tr)
        self._active_update_has_plasma_widgets = False
        self._active_update_requires_restart_advisory = False
        self._active_optional_sources: set[UpdateSource] | None = None

    def set_active_optional_sources(self, sources: set[UpdateSource]) -> None:
        self._active_optional_sources = set(sources)

    def is_busy(self) -> bool:
        return self._worker_thread is not None or self._update_client is not None

    def active_update_requires_restart_advisory(self) -> bool:
        return self._active_update_requires_restart_advisory

    def shutdown(self) -> None:
        if self._shutting_down:
            return
        self._shutting_down = True

        if self._update_client is not None:
            client = self._update_client
            self._update_client = None
            self._disconnect_update_client(client)
            client.terminate()

        if self._worker_thread is not None:
            thread = self._worker_thread
            worker = self._worker
            if worker is not None:
                cancel = getattr(worker, "cancel", None)
                if callable(cancel):
                    cancel()
                self._disconnect_worker_signals(worker)
            thread.quit()
            if thread.wait(self.WORKER_SHUTDOWN_TIMEOUT_MS):
                self._cleanup_worker()

        self.busy_changed.emit(False)

    def start_check_updates(self, *, use_local_system_db: bool = False) -> bool:
        if self._shutting_down or self.is_busy():
            return False

        self._active_optional_sources = set(self._service.optional_sources_snapshot().active_sources)

        self._progress_model.reset_for_check()

        self._worker_thread = QThread(self)
        self._worker = UpdateCheckWorker(
            self._service,
            active_optional_sources=self._active_optional_sources,
            use_local_system_db=use_local_system_db,
        )
        self._worker.moveToThread(self._worker_thread)
        self._worker_thread.started.connect(self._worker.run)
        self._worker.progress_changed.connect(self.check_progress_changed)
        self._worker.finished.connect(self._handle_check_success)
        self._worker.failed.connect(self._handle_check_failure)
        self._worker.finished.connect(self._worker_thread.quit)
        self._worker.failed.connect(self._worker_thread.quit)
        self._worker_thread.finished.connect(self._cleanup_worker)
        self._worker_thread.start()
        self.busy_changed.emit(True)
        return True

    def start_update(self, plan: UpdatePlan) -> None:
        if self._shutting_down:
            raise RuntimeError(self.tr("The update controller is shutting down."))
        if self.is_busy():
            raise RuntimeError(self.tr("Another operation is already running."))

        self._initialize_progress(plan)
        self._active_update_requires_restart_advisory = False
        self._active_update_has_plasma_widgets = bool(
            plan.update_items(UpdateSource.PLASMA_WIDGET)
        )
        self._progress_model.reveal_dialog()
        self._emit_progress_snapshot(
            self.tr("Installing Updates"),
            self.tr("Starting the integrated update session."),
        )
        self.update_status_changed.emit("starting_integrated")

        client = IntegratedBatchUpdateClient(plan, parent=self)
        client.status_changed.connect(self._handle_update_status)
        client.log_received.connect(self._handle_update_log)
        client.progress_changed.connect(self._handle_runner_progress)
        client.question_requested.connect(self.question_requested)
        client.completed.connect(self._handle_update_completed)
        self._update_client = client
        try:
            client.start()
        except Exception:
            self._update_client = None
            client.deleteLater()
            raise
        self.busy_changed.emit(True)

    @Slot(object)
    def _handle_check_success(self, result: UpdateCheckResult) -> None:
        self.check_succeeded.emit(result)

    @Slot(str, object)
    def _handle_check_failure(self, message: str, logs: object) -> None:
        self.check_failed.emit(message, logs)

    def _cleanup_worker(self) -> None:
        if self._worker is not None:
            self._worker.deleteLater()
        if self._worker_thread is not None:
            self._worker_thread.deleteLater()
        self._worker = None
        self._worker_thread = None
        self.busy_changed.emit(self.is_busy())

    def submit_question_response(self, question_id: str, response: object) -> None:
        if self._update_client is not None:
            self._update_client.submit_question_response(question_id, response)

    def cancel_question(self, question_id: str) -> None:
        if self._update_client is not None:
            self._update_client.cancel_question(question_id)

    def append_external_log(self, message: str) -> None:
        if not message:
            return
        self._progress_model.append_console_lines(message)
        if self._progress_model.dialog_revealed:
            self.update_progress_changed.emit(
                self._progress_model.last_snapshot(
                    default_title=self.tr("Installing Updates"),
                    default_subtitle=self.tr("Running selected updates."),
                )
            )

    def _disconnect_update_client(self, client: IntegratedBatchUpdateClient) -> None:
        for signal, slot in (
            (client.status_changed, self._handle_update_status),
            (client.log_received, self._handle_update_log),
            (client.progress_changed, self._handle_runner_progress),
            (client.question_requested, self.question_requested),
            (client.completed, self._handle_update_completed),
        ):
            try:
                signal.disconnect(slot)
            except (RuntimeError, TypeError):
                pass

    def _disconnect_worker_signals(self, worker: UpdateCheckWorker) -> None:
        for signal, slot in (
            (worker.progress_changed, self.check_progress_changed),
            (worker.finished, self._handle_check_success),
            (worker.failed, self._handle_check_failure),
        ):
            try:
                signal.disconnect(slot)
            except (RuntimeError, TypeError):
                pass

    def _initialize_progress(self, plan: UpdatePlan) -> None:
        self._progress_model.initialize(plan)

    def _emit_progress_snapshot(
        self,
        title: str,
        subtitle: str,
        *,
        final_state: bool = False,
        success: bool | None = None,
    ) -> None:
        self.update_progress_changed.emit(
            self._progress_model.snapshot(
                title,
                subtitle,
                final_state=final_state,
                success=success,
            )
        )

    @Slot(str)
    def _handle_update_log(self, message: str) -> None:
        self.append_external_log(message)

    @Slot(object)
    def _handle_runner_progress(self, payload: object) -> None:
        if not isinstance(payload, dict):
            return
        event_type = str(payload.get("type") or "")
        if (
            event_type == BatchEventType.PROGRESS.value
            and payload.get("kind") == "aur_pkgbuild_review_skipped"
        ):
            self.aur_update_skipped.emit(payload)
            return
        if event_type != BatchEventType.STEP_COMPLETED.value:
            return
        step = str(payload.get("step") or "")
        success = payload.get("success") is True
        if (
            step in {BatchStep.SYSTEM.value, BatchStep.FIRMWARE.value}
            and payload.get("changed") is True
        ):
            self._active_update_requires_restart_advisory = True
        if not self._progress_model.handle_step_completed(
            step,
            success=success,
            incomplete=payload.get("incomplete") is True,
        ):
            return
        self.update_progress_changed.emit(
            self._progress_model.last_snapshot(
                default_title=self.tr("Installing Updates"),
                default_subtitle=self.tr("Running selected updates."),
            )
        )

    @Slot(str)
    def _handle_update_status(self, value: str) -> None:
        self.update_status_changed.emit(value)

        if value == "starting_integrated":
            self._emit_progress_snapshot(
                self.tr("Installing Updates"),
                self.tr("Starting the integrated update session."),
            )
            return

        progress_titles = self._progress_model.start_running_status(value)
        if progress_titles is None:
            return
        title, subtitle = progress_titles
        self._emit_progress_snapshot(title, subtitle)

    @Slot(bool, str, str)
    def _handle_update_completed(
        self,
        success: bool,
        message: str,
        outcome: str,
    ) -> None:
        self._update_client = None

        if outcome == BatchOutcome.SUCCESS.value:
            self._progress_model.complete_success()
            self._emit_progress_snapshot(
                self.tr("Updates completed"),
                message or self.tr("Selected updates completed successfully."),
                final_state=True,
                success=True,
            )
            if self._active_update_has_plasma_widgets:
                self.plasma_restart_recommended.emit()
        elif outcome == BatchOutcome.PARTIAL_SUCCESS.value:
            self._progress_model.complete_success()
            self._emit_progress_snapshot(
                self.tr("Updates completed with skipped items"),
                message or self.tr("Some selected updates were skipped."),
                final_state=True,
                success=True,
            )
            if self._active_update_has_plasma_widgets:
                self.plasma_restart_recommended.emit()
        elif outcome == BatchOutcome.NO_CHANGES.value:
            self._progress_model.complete_success(refresh_expected=False)
            self._emit_progress_snapshot(
                self.tr("No updates installed"),
                message or self.tr("No selected updates were installed."),
                final_state=True,
                success=True,
            )
        elif outcome == BatchOutcome.CANCELLED.value:
            self._progress_model.complete_cancelled()
            self._emit_progress_snapshot(
                self.tr("Update cancelled"),
                message or self.tr("The update was cancelled."),
                final_state=True,
                success=False,
            )
        elif outcome != BatchOutcome.AUTH_CANCELLED.value:
            self._progress_model.complete_failure()
            self._emit_progress_snapshot(
                self.tr("Update completed with issues")
                if self._progress_model.summary_completed
                else self.tr("Update failed"),
                message or self.tr("Selected updates failed."),
                final_state=True,
                success=False,
            )

        self._active_update_has_plasma_widgets = False
        self.update_completed.emit(success, message, outcome)
        self.busy_changed.emit(self.is_busy())
