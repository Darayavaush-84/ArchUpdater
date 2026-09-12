from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol

from archupdater.domain.check_results import (
    ArchNewsCheckState,
    SourceCheckReport,
    UpdateCheckResult,
)
from archupdater.domain.command_log import CheckLogEntry
from archupdater.domain.enums import UpdateSource
from archupdater.domain.optional_sources import OptionalSourcesSnapshot
from archupdater.domain.packages import PackageUpdate
from archupdater.application.update_sources.source_backend import BackendCheckResult, SourceBackend, SourceBackendRegistry


Translate = Callable[[str], str]
CheckProgress = Callable[[str, int], None]
CancelRequested = Callable[[], bool]
OptionalSourcesProvider = Callable[[], OptionalSourcesSnapshot]


class ArchNewsProvider(Protocol):
    def fetch(self) -> Any: ...


@dataclass(slots=True)
class UpdateCheckCoordinator:
    source_registry: SourceBackendRegistry
    arch_news_provider: ArchNewsProvider
    optional_sources_provider: OptionalSourcesProvider
    translate: Translate

    def check_updates(
        self,
        *,
        progress_callback: CheckProgress | None = None,
        active_optional_sources: set[UpdateSource] | None = None,
        use_local_system_db: bool = False,
        cancel_requested: CancelRequested | None = None,
    ) -> UpdateCheckResult:
        packages: list[PackageUpdate] = []
        logs: list[CheckLogEntry] = []
        warnings: list[str] = []
        source_reports: list[SourceCheckReport] = []
        checked_at = datetime.now()

        def report(label: str, percent: int) -> None:
            if progress_callback is not None:
                progress_callback(label, percent)

        def ensure_not_cancelled() -> None:
            if cancel_requested is not None and cancel_requested():
                raise UpdateCheckCancelled()

        active_sources = (
            set(active_optional_sources)
            if active_optional_sources is not None
            else self.optional_sources_provider().active_sources
        )
        for backend in self.source_registry.enabled_for_check(active_sources):
            ensure_not_cancelled()
            report(backend.check_label(self.translate), backend.check_percent)
            backend_result = self._run_source_check(
                backend,
                report,
                use_local_system_db=use_local_system_db,
            )
            self._extend_collected_result(backend_result, packages, logs, warnings)
            source_reports.append(
                SourceCheckReport(
                    source=backend.source,
                    state=backend_result.state,
                    warnings=tuple(backend_result.warnings),
                )
            )
            if backend_result.checked_at is not None:
                checked_at = backend_result.checked_at

        ensure_not_cancelled()
        report(self.translate("Checking Arch Linux news..."), 98)
        news_result = self.arch_news_provider.fetch()
        ensure_not_cancelled()
        if news_result.warning:
            warnings.append(news_result.warning)
        news_state = (
            ArchNewsCheckState.FAILED
            if news_result.warning
            else ArchNewsCheckState.LOADED
        )

        report(self.translate("Completed"), 100)
        return UpdateCheckResult(
            packages=packages,
            checked_at=checked_at,
            logs=logs,
            warnings=warnings,
            arch_news=news_result.items,
            source_reports=source_reports,
            arch_news_state=news_state,
        )

    def _run_source_check(
        self,
        backend: SourceBackend,
        progress_callback: CheckProgress | None = None,
        *,
        use_local_system_db: bool = False,
    ) -> BackendCheckResult:
        try:
            return backend.check_updates(
                progress_callback=progress_callback,
                use_local_system_db=use_local_system_db,
            )
        except UpdateCheckCancelled:
            raise
        except Exception as exc:
            return backend.check_failure_result(exc, self.translate)

    def _extend_collected_result(
        self,
        result: BackendCheckResult,
        packages: list[PackageUpdate],
        logs: list[CheckLogEntry],
        warnings: list[str],
    ) -> None:
        packages.extend(result.packages)
        logs.extend(result.logs)
        warnings.extend(result.warnings)


class UpdateCheckCancelled(RuntimeError):
    pass
