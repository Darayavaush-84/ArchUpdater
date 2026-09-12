from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

from PySide6.QtCore import QCoreApplication

from archupdater.application.preflight import UpdatePreflightService
from archupdater.application.update_sources.source_backend import SourceBackendRegistry
from archupdater.application.update_sources.source_backends import build_source_backend_registry
from archupdater.application.updates import UpdateApplication
from archupdater.application.use_cases import (
    CheckUpdates,
    PrepareUpdateInstallation,
    ReadOptionalSources,
    RunPreflightChecks,
)
from archupdater.domain.optional_sources import OptionalSourcesSnapshot
from archupdater.infrastructure.widget_match_cache import WidgetMatchCache
from archupdater.services.arch_news import ArchNewsService
from archupdater.services.aur import AurUpdateService
from archupdater.services.command_runner import CommandRunner
from archupdater.services.firmware import FirmwareUpdateService
from archupdater.services.flatpak import FlatpakUpdateService
from archupdater.services.optional_sources import OptionalSourcesService
from archupdater.services.pacman import PacmanUpdateService
from archupdater.services.plasma_shell import PlasmaShellService
from archupdater.services.plasma_widgets import PlasmaWidgetsUpdateService
from archupdater.services.plasma_widgets_store import PlasmaWidgetsStoreClient
from archupdater.services.plasma_widgets_update import (
    PlasmaWidgetsUpdateService as PlasmaWidgetsInstallerService,
)
from archupdater.services.preflight import SystemPreflightEnvironment


@dataclass(slots=True)
class ApplicationContainer:
    aur_enabled_provider: Callable[[], bool] = lambda: False
    aur_enabled_setter: Callable[[bool], None] | None = None
    runner: CommandRunner = field(
        default_factory=lambda: CommandRunner(default_env={"LC_ALL": "C.UTF-8"})
    )
    pacman_updates: PacmanUpdateService = field(init=False)
    aur_updates: AurUpdateService = field(init=False)
    flatpak_updates: FlatpakUpdateService = field(init=False)
    firmware_updates: FirmwareUpdateService = field(init=False)
    plasma_widget_checks: PlasmaWidgetsUpdateService = field(init=False)
    plasma_widget_installer: PlasmaWidgetsInstallerService = field(init=False)
    plasma_widgets_store: PlasmaWidgetsStoreClient = field(init=False)
    widget_match_cache: WidgetMatchCache = field(init=False)
    plasma_shell: PlasmaShellService = field(init=False)
    optional_sources: OptionalSourcesService = field(init=False)
    arch_news: ArchNewsService = field(init=False)
    preflight: UpdatePreflightService = field(init=False)

    def __post_init__(self) -> None:
        self.pacman_updates = PacmanUpdateService(runner=self.runner)
        self.aur_updates = AurUpdateService(runner=self.runner)
        self.flatpak_updates = FlatpakUpdateService(runner=self.runner)
        self.firmware_updates = FirmwareUpdateService(runner=self.runner)
        self.plasma_widgets_store = PlasmaWidgetsStoreClient()
        self.widget_match_cache = WidgetMatchCache()
        self.plasma_widget_checks = PlasmaWidgetsUpdateService(
            store_client=self.plasma_widgets_store,
            match_cache=self.widget_match_cache,
        )
        self.plasma_widget_installer = PlasmaWidgetsInstallerService(
            runner=self.runner,
            store_client=self.plasma_widgets_store,
            match_cache=self.widget_match_cache,
        )
        self.plasma_shell = PlasmaShellService(runner=self.runner)
        self.optional_sources = OptionalSourcesService(
            aur_enabled_provider=self.aur_enabled_provider,
            aur_enabled_setter=self.aur_enabled_setter,
        )
        self.arch_news = ArchNewsService()

        def preflight_translate(text: str) -> str:
            return QCoreApplication.translate("UpdatePreflightService", text)

        self.preflight = UpdatePreflightService(
            environment=SystemPreflightEnvironment(translate=preflight_translate),
            translate=preflight_translate,
        )

    def updates(self) -> UpdateApplication:
        return UpdateApplication(
            check_updates_use_case=CheckUpdates(
                translate=lambda text: QCoreApplication.translate("UpdateService", text),
                source_registry_provider=self.source_backend_registry,
                arch_news_provider=self.arch_news,
                optional_sources_provider=self.optional_sources_snapshot,
            ),
            installation_use_case=PrepareUpdateInstallation(
                source_registry_provider=self.source_backend_registry,
                aur_service_provider=lambda: self.aur_updates,
            ),
            preflight_use_case=RunPreflightChecks(
                preflight_service=self.preflight,
                source_registry_provider=self.source_backend_registry,
            ),
            optional_sources_reader=ReadOptionalSources(self.optional_sources),
            plasma_shell_service=self.plasma_shell,
            plasma_widgets_update_service=self.plasma_widget_installer,
        )

    def optional_sources_snapshot(self) -> OptionalSourcesSnapshot:
        return self.optional_sources.snapshot()

    def source_backend_registry(self) -> SourceBackendRegistry:
        return build_source_backend_registry(
            pacman_service=lambda: self.pacman_updates,
            aur_service=lambda: self.aur_updates,
            flatpak_service=lambda: self.flatpak_updates,
            plasma_widgets_service=lambda: self.plasma_widget_checks,
            firmware_service=lambda: self.firmware_updates,
        )
