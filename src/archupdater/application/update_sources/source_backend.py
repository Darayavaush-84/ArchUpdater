from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Protocol

from archupdater.domain.command_log import CheckLogEntry
from archupdater.domain.check_results import CheckState
from archupdater.domain.enums import UpdateSource
from archupdater.domain.packages import PackageUpdate
from archupdater.domain.preflight import PreflightIssue
from archupdater.domain.update_plan import UpdatePlan
from archupdater.application.update_sources.descriptors import SOURCE_ORDER, UPDATE_STEP_ORDER, plan_has_source
from archupdater.application.update_session.backend import UpdateBackend


Translate = Callable[[str], str]
CheckProgress = Callable[[str, int], None]
CommandAvailable = Callable[[str], bool]
PreflightCommandRunner = Callable[[list[str], float], tuple[int, str, str]]
CommandDetails = Callable[[str, str], list[str]]


@dataclass(slots=True)
class BackendCheckResult:
    packages: list[PackageUpdate] = field(default_factory=list)
    logs: list[CheckLogEntry] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    checked_at: datetime | None = None
    state: CheckState = CheckState.SUCCESS


@dataclass(slots=True)
class PreflightContext:
    selected_packages: list[PackageUpdate]
    pacman_lock_path: Path
    pacman_check_timeout_seconds: float
    translate: Translate
    command_available: CommandAvailable
    run_command: PreflightCommandRunner
    command_details: CommandDetails


class SourceBackend(Protocol):
    source: UpdateSource
    check_percent: int

    def check_label(self, translate: Translate) -> str:
        pass

    def check_updates(
        self,
        *,
        progress_callback: CheckProgress | None = None,
        use_local_system_db: bool = False,
    ) -> BackendCheckResult:
        pass

    def check_failure_result(self, exc: Exception, translate: Translate) -> BackendCheckResult:
        pass

    def preflight_issues(
        self,
        plan: UpdatePlan,
        context: PreflightContext,
    ) -> list[PreflightIssue]:
        pass

    def install_backend(self) -> UpdateBackend:
        pass


@dataclass(frozen=True, slots=True)
class SourceBackendRegistry:
    backends: tuple[SourceBackend, ...]

    def enabled_for_check(self, active_optional_sources: set[UpdateSource]) -> list[SourceBackend]:
        by_source = {backend.source: backend for backend in self.backends}
        return [
            by_source[source]
            for source in SOURCE_ORDER
            if source in by_source
            and (source is UpdateSource.SYSTEM or source in active_optional_sources)
        ]

    def selected_for_plan(self, plan: UpdatePlan) -> list[SourceBackend]:
        by_source = {backend.source: backend for backend in self.backends}
        return [
            by_source[source]
            for source in UPDATE_STEP_ORDER
            if source in by_source and plan_has_source(plan, source)
        ]

    def preflight_issues(
        self,
        plan: UpdatePlan,
        context: PreflightContext,
    ) -> list[PreflightIssue]:
        issues: list[PreflightIssue] = []
        for backend in self.selected_for_plan(plan):
            issues.extend(backend.preflight_issues(plan, context))
        return issues

    def install_backends(self) -> list[UpdateBackend]:
        by_source = {backend.source: backend for backend in self.backends}
        return [
            by_source[source].install_backend()
            for source in UPDATE_STEP_ORDER
            if source in by_source
        ]
