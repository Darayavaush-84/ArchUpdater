from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol

from archupdater.application.use_cases import (
    CheckUpdates,
    PrepareUpdateInstallation,
    ReadOptionalSources,
    RunPreflightChecks,
)
from archupdater.domain.check_results import UpdateCheckResult
from archupdater.domain.aur import AurPkgbuildReview, AurVcsSource
from archupdater.domain.enums import UpdateSource
from archupdater.domain.optional_sources import OptionalSourcesSnapshot
from archupdater.domain.packages import PackageUpdate
from archupdater.domain.preflight import PreflightIssue
from archupdater.domain.update_plan import UpdatePlan, UpdatePlanItem
from archupdater.application.update_session.backend import UpdateBackend


class PlasmaShellControl(Protocol):
    def can_restart_shell(self) -> bool: ...

    def restart_shell(self) -> bool: ...


class PlasmaWidgetsUpdateResult(Protocol):
    success: bool
    message: str


class PlasmaWidgetsUpdateRunner(Protocol):
    def update_widgets(
        self,
        targets: list[UpdatePlanItem],
        *,
        log_callback: Callable[[str], None],
    ) -> PlasmaWidgetsUpdateResult: ...


@dataclass(slots=True)
class UpdateApplication:
    check_updates_use_case: CheckUpdates
    installation_use_case: PrepareUpdateInstallation
    preflight_use_case: RunPreflightChecks
    optional_sources_reader: ReadOptionalSources
    plasma_shell_service: PlasmaShellControl
    plasma_widgets_update_service: PlasmaWidgetsUpdateRunner

    def check_updates(
        self,
        progress_callback: Callable[[str, int], None] | None = None,
        active_optional_sources: set[UpdateSource] | None = None,
        use_local_system_db: bool = False,
        cancel_requested: Callable[[], bool] | None = None,
    ) -> UpdateCheckResult:
        return self.check_updates_use_case.run(
            progress_callback=progress_callback,
            active_optional_sources=active_optional_sources,
            use_local_system_db=use_local_system_db,
            cancel_requested=cancel_requested,
        )

    def optional_sources_snapshot(self) -> OptionalSourcesSnapshot:
        return self.optional_sources_reader.snapshot()

    def set_aur_updates_enabled(self, enabled: bool) -> None:
        self.optional_sources_reader.set_aur_enabled(enabled)

    def install_backends(self) -> list[UpdateBackend]:
        return self.installation_use_case.install_backends()

    def check_update_preflight(
        self,
        plan: UpdatePlan,
        packages: list[PackageUpdate],
    ) -> list[PreflightIssue]:
        return self.preflight_use_case.run(plan, packages)

    def aur_pkgbuild_review(
        self,
        package_name: str,
        package_base: str | None = None,
        *,
        lock_vcs_sources: bool = False,
    ) -> AurPkgbuildReview:
        return self.installation_use_case.aur_pkgbuild_review(
            package_name,
            package_base,
            lock_vcs_sources=lock_vcs_sources,
        )

    def aur_missing_build_dependencies(self, review: AurPkgbuildReview) -> list[str]:
        return self.installation_use_case.aur_missing_build_dependencies(review)

    def discard_aur_pkgbuild_review(self, review: AurPkgbuildReview) -> None:
        self.installation_use_case.discard_aur_pkgbuild_review(review)

    def record_aur_vcs_install(
        self,
        package_name: str,
        version: str,
        sources: tuple[AurVcsSource, ...],
    ) -> None:
        self.installation_use_case.record_aur_vcs_install(package_name, version, sources)

    def can_restart_plasma_shell(self) -> bool:
        return self.plasma_shell_service.can_restart_shell()

    def restart_plasma_shell(self) -> bool:
        return self.plasma_shell_service.restart_shell()
