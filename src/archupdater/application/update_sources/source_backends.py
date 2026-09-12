from __future__ import annotations

from collections.abc import Callable
from typing import Any

from archupdater.domain.check_results import CheckState, SourceCheckResult, UpdateCheckResult
from archupdater.domain.enums import PreflightSeverity, UpdateSource
from archupdater.domain.preflight import PreflightIssue
from archupdater.domain.update_plan import UpdatePlan
from archupdater.application.update_sources.source_backend import (
    BackendCheckResult,
    CheckProgress,
    PreflightContext,
    SourceBackendRegistry,
    Translate,
)
from archupdater.application.update_session.backend import UpdateBackend
from archupdater.application.update_session.step_backends import (
    AurBackend,
    FirmwareBackend,
    FlatpakBackend,
    PacmanBackend,
    PlasmaWidgetBackend,
)


ServiceProvider = Callable[[], Any]


class _BaseSourceBackend:
    source: UpdateSource
    check_percent: int
    _service_provider: ServiceProvider
    _install_backend: UpdateBackend

    def check_failure_result(self, exc: Exception, translate: Translate) -> BackendCheckResult:
        details = str(exc).strip() or translate("Unknown error.")
        return BackendCheckResult(
            warnings=[
                translate("{source} could not be checked: {details}").format(
                    source=self.failure_label(translate),
                    details=details,
                )
            ],
            state=CheckState.FAILED,
        )

    def install_backend(self) -> UpdateBackend:
        return self._install_backend

    def failure_label(self, translate: Translate) -> str:
        return translate("Updates")

    def _check_service(self) -> Any:
        return self._service_provider()

    def _tool_issue(
        self,
        context: PreflightContext,
        *,
        command: str,
        message: str,
    ) -> PreflightIssue | None:
        if context.command_available(command):
            return None
        return PreflightIssue(
            severity=PreflightSeverity.BLOCKING,
            title=context.translate("Required tool is missing"),
            message=message,
            details=[
                context.translate("Missing command: {command}").format(command=command)
            ],
        )

    def _pacman_lock_issue(self, context: PreflightContext) -> PreflightIssue | None:
        if not context.pacman_lock_path.exists():
            return None
        return PreflightIssue(
            severity=PreflightSeverity.BLOCKING,
            title=context.translate("Pacman is already running"),
            message=context.translate(
                "A pacman database lock is present. Close other package operations before updating."
            ),
            details=[str(context.pacman_lock_path)],
        )


class SystemSourceBackend(_BaseSourceBackend):
    source = UpdateSource.SYSTEM
    check_percent = 5

    def __init__(self, service_provider: ServiceProvider) -> None:
        self._service_provider = service_provider
        self._install_backend = PacmanBackend()

    def check_label(self, translate: Translate) -> str:
        return translate("Checking pacman updates...")

    def failure_label(self, translate: Translate) -> str:
        return translate("Pacman updates")

    def check_updates(
        self,
        *,
        progress_callback: CheckProgress | None = None,
        use_local_system_db: bool = False,
    ) -> BackendCheckResult:
        def report(label: str, percent: int) -> None:
            if progress_callback is not None:
                progress_callback(label, min(55, max(5, percent)))

        result = self._check_service().check_updates(
            progress_callback=report,
            use_local_db=use_local_system_db,
        )
        return _check_result_from(result)

    def check_failure_result(self, exc: Exception, translate: Translate) -> BackendCheckResult:
        raise exc

    def preflight_issues(
        self,
        plan: UpdatePlan,
        context: PreflightContext,
    ) -> list[PreflightIssue]:
        if not plan.update_items(UpdateSource.SYSTEM):
            return []

        issues = [
            issue
            for issue in (
                self._tool_issue(
                    context,
                    command="pacman",
                    message=context.translate("System package updates need pacman."),
                ),
                self._tool_issue(
                    context,
                    command="pacman-conf",
                    message=context.translate("System package updates need pacman-conf."),
                ),
                self._pacman_lock_issue(context),
            )
            if issue is not None
        ]
        if any(issue.severity is PreflightSeverity.BLOCKING for issue in issues):
            return issues
        issues.extend(self._pacman_configuration_issues(context))
        return issues

    def _pacman_configuration_issues(self, context: PreflightContext) -> list[PreflightIssue]:
        return_code, stdout, stderr = context.run_command(
            ["pacman-conf", "Architecture"],
            context.pacman_check_timeout_seconds,
        )
        details = context.command_details(stdout, stderr)
        if return_code == 0 and stdout.strip():
            return []
        return [
            PreflightIssue(
                severity=PreflightSeverity.BLOCKING,
                title=context.translate("Pacman configuration is not readable"),
                message=context.translate("Pacman architecture configuration could not be read."),
                details=details or [context.translate("Command failed: pacman-conf Architecture")],
            )
        ]


class AurSourceBackend(_BaseSourceBackend):
    source = UpdateSource.AUR
    check_percent = 68

    def __init__(self, service_provider: ServiceProvider) -> None:
        self._service_provider = service_provider
        self._install_backend = AurBackend()

    def check_label(self, translate: Translate) -> str:
        return translate("Checking AUR updates...")

    def failure_label(self, translate: Translate) -> str:
        return translate("AUR updates")

    def check_updates(
        self,
        *,
        progress_callback: CheckProgress | None = None,
        use_local_system_db: bool = False,
    ) -> BackendCheckResult:
        return _check_result_from(self._check_service().check_updates())

    def preflight_issues(
        self,
        plan: UpdatePlan,
        context: PreflightContext,
    ) -> list[PreflightIssue]:
        if not plan.update_items(UpdateSource.AUR):
            return []

        issues = [
            issue
            for issue in (
                self._tool_issue(
                    context,
                    command="pacman",
                    message=context.translate("AUR updates need pacman."),
                ),
                self._tool_issue(
                    context,
                    command="git",
                    message=context.translate("AUR updates need git."),
                ),
                self._tool_issue(
                    context,
                    command="makepkg",
                    message=context.translate("AUR updates need makepkg."),
                ),
                self._pacman_lock_issue(context),
            )
            if issue is not None
        ]
        return issues

class FlatpakSourceBackend(_BaseSourceBackend):
    source = UpdateSource.FLATPAK
    check_percent = 80

    def __init__(self, service_provider: ServiceProvider) -> None:
        self._service_provider = service_provider
        self._install_backend = FlatpakBackend()

    def check_label(self, translate: Translate) -> str:
        return translate("Checking Flatpak updates...")

    def failure_label(self, translate: Translate) -> str:
        return translate("Flatpak updates")

    def check_updates(
        self,
        *,
        progress_callback: CheckProgress | None = None,
        use_local_system_db: bool = False,
    ) -> BackendCheckResult:
        return _check_result_from(self._check_service().check_updates())

    def preflight_issues(
        self,
        plan: UpdatePlan,
        context: PreflightContext,
    ) -> list[PreflightIssue]:
        if not (plan.update_items(UpdateSource.FLATPAK) or plan.cleanup_items(UpdateSource.FLATPAK)):
            return []
        return [
            issue
            for issue in (
                self._tool_issue(
                    context,
                    command="flatpak",
                    message=context.translate("Flatpak updates need flatpak."),
                ),
            )
            if issue is not None
        ]


class PlasmaWidgetSourceBackend(_BaseSourceBackend):
    source = UpdateSource.PLASMA_WIDGET
    check_percent = 90

    def __init__(self, service_provider: ServiceProvider) -> None:
        self._service_provider = service_provider
        self._install_backend = PlasmaWidgetBackend()

    def check_label(self, translate: Translate) -> str:
        return translate("Checking KDE Store add-on updates...")

    def failure_label(self, translate: Translate) -> str:
        return translate("KDE Store add-on updates")

    def check_updates(
        self,
        *,
        progress_callback: CheckProgress | None = None,
        use_local_system_db: bool = False,
    ) -> BackendCheckResult:
        return _check_result_from(self._check_service().check_updates())

    def preflight_issues(
        self,
        plan: UpdatePlan,
        context: PreflightContext,
    ) -> list[PreflightIssue]:
        if not plan.update_items(UpdateSource.PLASMA_WIDGET):
            return []
        issue = self._tool_issue(
            context,
            command="kpackagetool6",
            message=context.translate("KDE Store add-on updates need kpackagetool6."),
        )
        return [] if issue is None else [issue]


class FirmwareSourceBackend(_BaseSourceBackend):
    source = UpdateSource.FIRMWARE
    check_percent = 96

    def __init__(self, service_provider: ServiceProvider) -> None:
        self._service_provider = service_provider
        self._install_backend = FirmwareBackend()

    def check_label(self, translate: Translate) -> str:
        return translate("Checking device firmware updates...")

    def failure_label(self, translate: Translate) -> str:
        return translate("Device firmware updates")

    def check_updates(
        self,
        *,
        progress_callback: CheckProgress | None = None,
        use_local_system_db: bool = False,
    ) -> BackendCheckResult:
        return _check_result_from(self._check_service().check_updates())

    def preflight_issues(
        self,
        plan: UpdatePlan,
        context: PreflightContext,
    ) -> list[PreflightIssue]:
        if not plan.update_items(UpdateSource.FIRMWARE):
            return []
        return [
            issue
            for issue in (
                self._tool_issue(
                    context,
                    command="fwupdmgr",
                    message=context.translate("Device firmware updates need fwupdmgr."),
                ),
            )
            if issue is not None
        ]


def build_source_backend_registry(
    *,
    pacman_service: ServiceProvider,
    aur_service: ServiceProvider,
    flatpak_service: ServiceProvider,
    plasma_widgets_service: ServiceProvider,
    firmware_service: ServiceProvider,
) -> SourceBackendRegistry:
    return SourceBackendRegistry(
        (
            SystemSourceBackend(pacman_service),
            AurSourceBackend(aur_service),
            FlatpakSourceBackend(flatpak_service),
            PlasmaWidgetSourceBackend(plasma_widgets_service),
            FirmwareSourceBackend(firmware_service),
        )
    )


def default_preflight_source_registry() -> SourceBackendRegistry:
    def unavailable() -> None:
        return None

    return build_source_backend_registry(
        pacman_service=unavailable,
        aur_service=unavailable,
        flatpak_service=unavailable,
        plasma_widgets_service=unavailable,
        firmware_service=unavailable,
    )


def _check_result_from(result: SourceCheckResult | UpdateCheckResult) -> BackendCheckResult:
    checked_at = result.checked_at if isinstance(result, UpdateCheckResult) else None
    return BackendCheckResult(
        packages=list(result.packages),
        logs=list(result.logs),
        warnings=list(result.warnings),
        checked_at=checked_at,
        state=CheckState.PARTIAL if result.warnings else CheckState.SUCCESS,
    )
