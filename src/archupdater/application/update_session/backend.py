from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Protocol

from archupdater.domain.update_plan import UpdatePlan
from archupdater.application.update_session.plan import BatchPlanInspector
from archupdater.application.helper_protocol import HelperRequest


Translate = Callable[[str], str]
PrintLine = Callable[[str], None]
EmitLog = Callable[[str], None]
EmitProgress = Callable[[dict[str, object]], None]
RequestQuestion = Callable[[dict[str, object]], object | None]
CommandAvailable = Callable[[str], bool]


@dataclass(frozen=True, slots=True)
class CommandRunResult:
    success: bool
    message: str = ""
    payload: dict[str, object] | None = None


class RunCommand(Protocol):
    def __call__(
        self,
        command: list[str],
        *,
        failure_message: str,
        extra_env: dict[str, str] | None = None,
        success_codes: frozenset[int] = frozenset({0}),
    ) -> CommandRunResult:
        pass


class RunPrivileged(Protocol):
    def __call__(
        self,
        request: HelperRequest,
        *,
        failure_message: str,
    ) -> CommandRunResult:
        pass


class SummarizeItems(Protocol):
    def __call__(self, items: list[str], *, limit: int = 4) -> str:
        pass


@dataclass(slots=True)
class BackendRunContext:
    plan: UpdatePlan
    service: Any
    plan_inspector: BatchPlanInspector
    translate: Translate
    print_line: PrintLine
    emit_log: EmitLog
    emit_progress: EmitProgress
    request_question: RequestQuestion
    run_command: RunCommand
    run_privileged: RunPrivileged
    summarize_items: SummarizeItems
    command_available: CommandAvailable


@dataclass(frozen=True, slots=True)
class BackendRunResult:
    success: bool
    message: str = ""
    changed: bool = False
    incomplete: bool = False


class UpdateBackend(Protocol):
    step_key: str
    exit_code: int
    outcome: str

    def should_run(self, plan: UpdatePlan) -> bool:
        pass

    def label(self, context: BackendRunContext) -> str:
        pass

    def start_message(self, context: BackendRunContext) -> str:
        pass

    def run(self, context: BackendRunContext) -> BackendRunResult:
        pass
