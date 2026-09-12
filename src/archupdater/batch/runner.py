from __future__ import annotations

import shlex
import shutil
from collections.abc import Callable

from PySide6.QtCore import QCoreApplication

from archupdater.batch.events import EventWriter
from archupdater.batch.privileged_helper import BatchPrivilegedHelperInvoker
from archupdater.application.helper_protocol import HelperRequest
from archupdater.domain.aur import AurInstallTarget
from archupdater.domain.enums import UpdateSource
from archupdater.domain.update_plan import UpdatePlan
from archupdater.application.update_session.plan import BatchPlanInspector
from archupdater.services.batch_process import BatchProcessRunner
from archupdater.application.update_session.protocol import (
    BatchEventType,
    BatchOutcome,
    BatchStepResult,
)
from archupdater.application.update_session.errors import BatchAuthenticationCancelled, BatchCancelled
from archupdater.application.update_session.execution_gateway import ExecutionGateway
from archupdater.domain.process_result import CommandProcessResult
from archupdater.services.session_log import SessionLog
from archupdater.application.update_session.messages import UpdateSessionMessages
from archupdater.services.update_diagnostics import (
    command_failure_diagnostic,
)
from archupdater.application.update_session.backend import (
    BackendRunContext,
    BackendRunResult,
    CommandRunResult,
    UpdateBackend,
)
from archupdater.container import ApplicationContainer
from archupdater.application.update_session.interaction import BatchInteractionController
from archupdater.application.update_session.reporting import BatchSessionReporter


class BatchRunner:
    def __init__(self, plan: UpdatePlan, events: EventWriter) -> None:
        self._plan = plan
        self._events = events
        self._container = ApplicationContainer()
        self._service = self._container.updates()
        self._step_results: dict[str, str] = {}
        self._plan_inspector = BatchPlanInspector(
            plan,
            translate=self._t,
        )
        self._backends = self._service.install_backends()
        self._session_messages = UpdateSessionMessages(self._t)
        self._session_log = SessionLog.create()
        self._interaction = BatchInteractionController.from_event_writer(self._events)
        self._process_runner = BatchProcessRunner(
            print_line=self._print_line,
            emit_log=lambda message: self._events.emit(BatchEventType.LOG.value, message=message),
            translate=self._t,
        )
        self._privileged_helper = BatchPrivilegedHelperInvoker(
            translate=self._t,
            print_line=self._print_line,
            emit_log=self._emit_log,
            auth_purpose="update-session",
            request_question=self._request_question,
            aur_targets=[
                AurInstallTarget(
                    package_name=item.package_name or item.target_id,
                    package_base=item.package_base or item.package_name or item.target_id,
                    version=(item.expected_version or "").strip(),
                    current_version=(item.current_version or "").strip(),
                    dynamic_version=item.dynamic_version,
                )
                for item in plan.update_items(UpdateSource.AUR)
            ],
        )

    def _reporter(self) -> BatchSessionReporter:
        return BatchSessionReporter(
            plan_inspector=self._plan_inspector,
            session_messages=self._session_messages,
            translate=self._t,
            print_line=self._print_line,
        )

    def run(self) -> int:
        session_changed = False
        session_incomplete = False
        ran_step = False
        first_independent_failure: tuple[str, int] | None = None
        session_log_path = self._session_log.path
        self._events.emit(
            BatchEventType.BATCH_STARTED.value,
            message=self._t("ArchUpdater batch started."),
            session_log=str(session_log_path) if session_log_path is not None else "",
        )
        if session_log_path is not None:
            self._print_line(
                self._t("Session log: {path}").format(path=session_log_path)
            )
        self._print_banner()
        try:
            try:
                auth_result = self._authorize_privileged_session()
                if auth_result is not None and not auth_result.success:
                    # No update step can have started before the privileged
                    # session is authorized.  Report this as an authorization
                    # cancellation/failure so the UI closes the progress
                    # dialog and re-scans instead of treating planned steps
                    # as installed.
                    return self._fail(
                        auth_result.message,
                        exit_code=1,
                        outcome=BatchOutcome.AUTH_CANCELLED.value,
                    )

                for should_run, run_step, exit_code, outcome in self._update_steps():
                    if not should_run:
                        continue
                    ran_step = True
                    result = run_step()
                    if not result.success:
                        if outcome == BatchOutcome.SYSTEM_TRANSACTION_FAILED.value:
                            return self._fail(
                                result.message,
                                exit_code=exit_code,
                                outcome=outcome,
                            )
                        if first_independent_failure is None:
                            first_independent_failure = (result.message, exit_code)
                        session_changed = session_changed or result.changed
                        session_incomplete = True
                        continue
                    session_changed = session_changed or result.changed
                    session_incomplete = session_incomplete or result.incomplete
            except BatchAuthenticationCancelled as exc:
                message = str(exc) or self._session_messages.authentication_cancelled()
                return self._fail(
                    message,
                    exit_code=130,
                    outcome=BatchOutcome.AUTH_CANCELLED.value,
                )
            except (KeyboardInterrupt, BatchCancelled):
                return self._fail(
                    self._t("The update batch was interrupted."),
                    exit_code=130,
                    outcome=BatchOutcome.CANCELLED.value,
                )

            if first_independent_failure is not None and not session_changed:
                message = self._session_messages.independent_steps_failed()
                self._print_summary(success=False)
                self._print_footer(success=False, message=message)
                self._events.emit(
                    BatchEventType.BATCH_COMPLETED.value,
                    success=False,
                    message=message,
                    outcome=BatchOutcome.FAILED.value,
                    completed=self._summary_completed_steps(),
                    incomplete=self._summary_incomplete_steps(),
                    failed=self._summary_failed_steps(),
                    not_executed=self._summary_not_executed_steps(),
                )
                return first_independent_failure[1]
            if not ran_step or not session_changed:
                message = self._session_messages.no_selected_updates_installed()
                completion_outcome = BatchOutcome.NO_CHANGES.value
            elif session_incomplete and session_changed:
                message = self._session_messages.selected_updates_partially_completed()
                completion_outcome = BatchOutcome.PARTIAL_SUCCESS.value
            elif session_incomplete:
                message = self._session_messages.no_selected_updates_installed()
                completion_outcome = BatchOutcome.NO_CHANGES.value
            else:
                message = self._session_messages.selected_updates_completed()
                completion_outcome = BatchOutcome.SUCCESS.value
            self._print_summary(success=True)
            self._print_footer(
                success=True,
                message=message,
                refresh_expected=completion_outcome != BatchOutcome.NO_CHANGES.value,
            )
            self._events.emit(
                BatchEventType.BATCH_COMPLETED.value,
                success=True,
                message=message,
                outcome=completion_outcome,
                completed=self._summary_completed_steps(),
                incomplete=self._summary_incomplete_steps(),
                failed=self._summary_failed_steps(),
                not_executed=self._summary_not_executed_steps(),
            )
            return 0
        finally:
            self._privileged_helper.close()

    def _update_steps(self) -> list[tuple[bool, Callable[[], BackendRunResult], int, str]]:
        return [
            (
                backend.should_run(self._plan),
                lambda backend=backend: self._run_backend_step(backend),
                backend.exit_code,
                backend.outcome,
            )
            for backend in self._all_backends()
        ]

    def _all_backends(self) -> list[UpdateBackend]:
        return list(self._backends)

    def _backend_context(self) -> BackendRunContext:
        return BackendRunContext(
            plan=self._plan,
            service=self._service,
            plan_inspector=self._plan_inspector,
            translate=self._t,
            print_line=self._print_line,
            emit_log=self._emit_log,
            emit_progress=self._emit_progress,
            request_question=self._request_question,
            run_command=self._run_command,
            run_privileged=self._run_privileged,
            summarize_items=self._summarize_items,
            command_available=self._command_available,
        )

    def _run_backend_step(self, backend: UpdateBackend) -> BackendRunResult:
        context = self._backend_context()
        self._start_step(
            backend.step_key,
            backend.label(context),
            backend.start_message(context),
        )
        try:
            result = backend.run(context)
        except (KeyboardInterrupt, BatchCancelled) as exc:
            result = BackendRunResult(
                False,
                self._t("The update step was interrupted before it completed."),
                changed=bool(getattr(exc, "changed", False)),
                incomplete=True,
            )
            self._finish_step(backend.step_key, result)
            raise
        self._finish_step(backend.step_key, result)
        return result

    def _command_available(self, command: str) -> bool:
        return shutil.which(command) is not None

    def _run_command(
        self,
        command: list[str],
        *,
        failure_message: str,
        extra_env: dict[str, str] | None = None,
        success_codes: frozenset[int] = frozenset({0}),
    ) -> CommandRunResult:
        return self._execution_gateway().run_command(
            command,
            failure_message=failure_message,
            extra_env=extra_env,
            success_codes=success_codes,
        )

    def _run_privileged(
        self,
        request: HelperRequest,
        *,
        failure_message: str,
    ) -> CommandRunResult:
        return self._privileged_helper.run(request, failure_message=failure_message)

    def _authorize_privileged_session(self) -> CommandRunResult | None:
        if not self._plan_inspector.requires_privileged_auth():
            return None
        return self._privileged_helper.authorize()

    def _command_failure_message(
        self,
        *,
        failure_message: str,
        return_code: int,
        output: str,
    ) -> str:
        return command_failure_diagnostic(
            failure_message=failure_message,
            return_code=return_code,
            output=output,
        ).render(self._t)

    def _execution_gateway(self) -> ExecutionGateway:
        return ExecutionGateway(
            translate=self._t,
            command_available=self._command_available,
            print_command=self._print_command,
            run_process=self._run_process,
            command_failure_message=lambda failure_message, return_code, output: (
                self._command_failure_message(
                    failure_message=failure_message,
                    return_code=return_code,
                    output=output,
                )
            ),
        )

    def _run_process(
        self,
        command: list[str],
        *,
        extra_env: dict[str, str] | None = None,
    ) -> CommandProcessResult:
        return self._process_runner.run_process(command, extra_env=extra_env)

    def _start_step(self, step: str, label: str, message: str) -> None:
        self._print_step_header(step, label)
        self._print_line(message)
        self._events.emit(BatchEventType.STEP_STARTED.value, step=step, message=message)

    def _finish_step(self, step: str, result: BackendRunResult) -> None:
        self._record_step_result(
            step,
            (
                BatchStepResult.INCOMPLETE.value
                if result.incomplete
                else BatchStepResult.FAILED.value
                if not result.success
                else BatchStepResult.COMPLETED.value
            ),
        )
        if result.success:
            final_message = result.message or self._t("{step} completed successfully.").format(
                step=step
            )
            self._print_line(final_message)
        else:
            final_message = result.message or self._t("{step} failed.").format(step=step)
            self._print_line(final_message)
        self._events.emit(
            BatchEventType.STEP_COMPLETED.value,
            step=step,
            success=result.success,
            incomplete=result.incomplete,
            changed=result.changed,
            message=final_message,
        )

    def _fail(
        self,
        message: str,
        *,
        exit_code: int,
        outcome: str = BatchOutcome.FAILED.value,
    ) -> int:
        if message:
            self._print_line(self._session_messages.no_further_steps().strip())
        self._print_summary(success=False)
        self._print_footer(success=False, message=message)
        self._events.emit(
            BatchEventType.BATCH_COMPLETED.value,
            success=False,
            message=message,
            outcome=outcome,
            completed=self._summary_completed_steps(),
            incomplete=self._summary_incomplete_steps(),
            failed=self._summary_failed_steps(),
            not_executed=self._summary_not_executed_steps(),
        )
        return exit_code

    def _print_banner(self) -> None:
        self._reporter().print_banner()

    def _print_step_header(self, step: str, label: str) -> None:
        self._reporter().print_step_header(step, label)

    def _print_footer(
        self,
        *,
        success: bool,
        message: str,
        refresh_expected: bool = True,
    ) -> None:
        self._reporter().print_footer(
            success=success,
            message=message,
            refresh_expected=refresh_expected,
        )

    def _print_summary(self, *, success: bool) -> None:
        self._reporter().print_summary(success=success, step_results=self._step_results)

    def _record_step_result(self, step: str, result: str) -> None:
        self._step_results[step] = result

    def _summary_completed_steps(self) -> list[str]:
        return self._reporter().completed_steps(self._step_results)

    def _summary_failed_steps(self) -> list[str]:
        return self._reporter().failed_steps(self._step_results)

    def _summary_incomplete_steps(self) -> list[str]:
        return self._reporter().incomplete_steps(self._step_results)

    def _summary_not_executed_steps(self) -> list[str]:
        return self._reporter().not_executed_steps(self._step_results)

    def _print_command(self, command: list[str]) -> None:
        rendered = self._display_command(command)
        message = self._t("Command: {command}").format(command=rendered)
        self._print_line(message)
        self._events.emit(BatchEventType.LOG.value, message=message)
        self._events.emit(BatchEventType.COMMAND_STARTED.value, command=message)

    def _emit_log(self, message: str) -> None:
        self._events.emit(BatchEventType.LOG.value, message=message)

    def _emit_progress(self, payload: dict[str, object]) -> None:
        self._events.emit(BatchEventType.PROGRESS.value, **payload)

    def _display_command(self, command: list[str]) -> str:
        return shlex.join(command)

    def _request_question(self, payload: dict[str, object]) -> object | None:
        return self._interaction.request_question(payload)

    def _print_line(self, text: str) -> None:
        print(text, flush=True)
        session_log = getattr(self, "_session_log", None)
        if session_log is not None:
            session_log.write_line(text)

    def _summarize_items(self, items: list[str], *, limit: int = 4) -> str:
        return self._plan_inspector.summarize_items(items, limit=limit)

    def _t(self, text: str) -> str:
        return QCoreApplication.translate("BatchUpdateRunner", text)
