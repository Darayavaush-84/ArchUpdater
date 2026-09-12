from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol

from archupdater.domain.check_results import UpdateCheckResult
from archupdater.domain.aur import AurPkgbuildReview, AurVcsSource
from archupdater.domain.enums import UpdateSource
from archupdater.domain.optional_sources import OptionalSourcesSnapshot
from archupdater.domain.packages import PackageUpdate
from archupdater.domain.preflight import PreflightIssue
from archupdater.domain.update_plan import UpdatePlan
from archupdater.application.preflight import UpdatePreflightService
from archupdater.application.update_sources.source_backend import SourceBackendRegistry
from archupdater.application.update_session.backend import UpdateBackend
from archupdater.application.update_sources.check_coordinator import (
    CheckProgress,
    UpdateCheckCoordinator,
)


Translate = Callable[[str], str]
SourceRegistryProvider = Callable[[], SourceBackendRegistry]
OptionalSourcesProvider = Callable[[], OptionalSourcesSnapshot]


class ArchNewsProvider(Protocol):
    def fetch(self) -> object: ...


class AurHelperDetector(Protocol):
    def fetch_pkgbuild_review(
        self,
        package_name: str,
        package_base: str | None = None,
        *,
        lock_vcs_sources: bool = False,
    ) -> AurPkgbuildReview: ...

    def missing_build_dependencies(self, review: AurPkgbuildReview) -> list[str]: ...

    def discard_pkgbuild_review(self, review: AurPkgbuildReview) -> None: ...

    def record_vcs_install(
        self,
        package_name: str,
        version: str,
        sources: tuple[AurVcsSource, ...],
    ) -> None: ...


class OptionalSourcesReader(Protocol):
    def snapshot(self) -> OptionalSourcesSnapshot: ...

    def set_aur_enabled(self, enabled: bool) -> None: ...


@dataclass(slots=True)
class CheckUpdates:
    source_registry_provider: SourceRegistryProvider
    arch_news_provider: ArchNewsProvider
    optional_sources_provider: OptionalSourcesProvider
    translate: Translate = lambda text: text

    def run(
        self,
        *,
        progress_callback: CheckProgress | None = None,
        active_optional_sources: set[UpdateSource] | None = None,
        use_local_system_db: bool = False,
        cancel_requested: Callable[[], bool] | None = None,
    ) -> UpdateCheckResult:
        return self.coordinator().check_updates(
            progress_callback=progress_callback,
            active_optional_sources=active_optional_sources,
            use_local_system_db=use_local_system_db,
            cancel_requested=cancel_requested,
        )

    def coordinator(self) -> UpdateCheckCoordinator:
        return UpdateCheckCoordinator(
            source_registry=self.source_registry_provider(),
            arch_news_provider=self.arch_news_provider,
            optional_sources_provider=self.optional_sources_provider,
            translate=self.translate,
        )


@dataclass(slots=True)
class PrepareUpdateInstallation:
    source_registry_provider: SourceRegistryProvider
    aur_service_provider: Callable[[], AurHelperDetector]

    def install_backends(self) -> list[UpdateBackend]:
        return self.source_registry_provider().install_backends()

    def aur_pkgbuild_review(
        self,
        package_name: str,
        package_base: str | None = None,
        *,
        lock_vcs_sources: bool = False,
    ) -> AurPkgbuildReview:
        return self.aur_service_provider().fetch_pkgbuild_review(
            package_name,
            package_base,
            lock_vcs_sources=lock_vcs_sources,
        )

    def aur_missing_build_dependencies(self, review: AurPkgbuildReview) -> list[str]:
        return self.aur_service_provider().missing_build_dependencies(review)

    def discard_aur_pkgbuild_review(self, review: AurPkgbuildReview) -> None:
        self.aur_service_provider().discard_pkgbuild_review(review)

    def record_aur_vcs_install(
        self,
        package_name: str,
        version: str,
        sources: tuple[AurVcsSource, ...],
    ) -> None:
        self.aur_service_provider().record_vcs_install(package_name, version, sources)


@dataclass(slots=True)
class RunPreflightChecks:
    preflight_service: UpdatePreflightService
    source_registry_provider: SourceRegistryProvider

    def run(
        self,
        plan: UpdatePlan,
        packages: list[PackageUpdate],
    ) -> list[PreflightIssue]:
        return self.preflight_service.check(
            plan,
            packages,
            source_registry=self.source_registry_provider(),
        )


@dataclass(slots=True)
class ReadOptionalSources:
    optional_sources_service: OptionalSourcesReader

    def snapshot(self) -> OptionalSourcesSnapshot:
        return self.optional_sources_service.snapshot()

    def set_aur_enabled(self, enabled: bool) -> None:
        self.optional_sources_service.set_aur_enabled(enabled)
