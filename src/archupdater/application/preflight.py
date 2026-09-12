from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Protocol

from archupdater.domain.enums import PreflightSeverity, UpdateSource
from archupdater.domain.packages import PackageUpdate
from archupdater.domain.preflight import PreflightIssue
from archupdater.domain.update_plan import UpdatePlan
from archupdater.domain.package_size import parse_size_to_bytes
from archupdater.application.package_selection import selected_packages_for_plan
from archupdater.application.update_sources.source_backend import PreflightContext, SourceBackendRegistry
from archupdater.application.update_sources.source_backends import default_preflight_source_registry

PreflightCommandRunner = Callable[[list[str], float], tuple[int, str, str]]
Translate = Callable[[str], str]
PreflightDiskSpace = tuple[Path, int]


class PreflightEnvironment(Protocol):
    def command_available(self, command: str) -> bool:
        pass

    def run_command(self, command: list[str], timeout_seconds: float) -> tuple[int, str, str]:
        pass

    def command_details(self, stdout: str, stderr: str) -> list[str]:
        pass

    def disk_space(self, path: Path) -> PreflightDiskSpace | None:
        pass

    def home_dir(self) -> Path:
        pass


@dataclass(slots=True)
class UpdatePreflightService:
    environment: PreflightEnvironment
    pacman_lock_path: Path = Path("/var/lib/pacman/db.lck")
    minimum_free_bytes: int = 1024 * 1024 * 1024
    pacman_check_timeout_seconds: float = 20
    privileged_helper_path: Path = Path("/usr/lib/archupdater/archupdater-helper")
    translate: Translate = lambda text: text

    def check(
        self,
        plan: UpdatePlan,
        packages: list[PackageUpdate],
        *,
        source_registry: SourceBackendRegistry | None = None,
    ) -> list[PreflightIssue]:
        issues: list[PreflightIssue] = []
        selected = self._selected_packages(plan, packages)
        registry = source_registry or default_preflight_source_registry()
        context = self._preflight_context(selected)
        issues.extend(registry.preflight_issues(plan, context))
        issues.extend(self._privileged_helper_issues(plan, context))
        issues.extend(self._disk_issues(plan, selected))
        return issues

    def _preflight_context(self, selected_packages: list[PackageUpdate]) -> PreflightContext:
        return PreflightContext(
            selected_packages=selected_packages,
            pacman_lock_path=self.pacman_lock_path,
            pacman_check_timeout_seconds=self.pacman_check_timeout_seconds,
            translate=self._t,
            command_available=self.environment.command_available,
            run_command=self.environment.run_command,
            command_details=self.environment.command_details,
        )

    def _privileged_helper_issues(
        self,
        plan: UpdatePlan,
        context: PreflightContext,
    ) -> list[PreflightIssue]:
        if not self._plan_needs_privileged_helper(plan):
            return []
        missing_details: list[str] = []
        if not context.command_available("pkexec"):
            missing_details.append(self._t("Missing command: pkexec"))
        if not self.privileged_helper_path.exists():
            missing_details.append(
                self._t("Missing helper: {path}").format(path=self.privileged_helper_path)
            )
        if not missing_details:
            return []
        return [
            PreflightIssue(
                severity=PreflightSeverity.BLOCKING,
                title=self._t("Required tool is missing"),
                message=self._t("Privileged update steps need the ArchUpdater helper."),
                details=missing_details,
            )
        ]

    def _plan_needs_privileged_helper(self, plan: UpdatePlan) -> bool:
        if (
            plan.target_ids(UpdateSource.SYSTEM)
            or plan.target_ids(UpdateSource.AUR)
            or plan.target_ids(UpdateSource.FIRMWARE)
        ):
            return True
        return False

    def _disk_issues(
        self,
        plan: UpdatePlan,
        selected_packages: list[PackageUpdate],
    ) -> list[PreflightIssue]:
        paths: list[Path] = []
        has_system = bool(plan.target_ids(UpdateSource.SYSTEM))
        has_aur = bool(plan.target_ids(UpdateSource.AUR))
        has_firmware = bool(plan.target_ids(UpdateSource.FIRMWARE))
        flatpak_scopes = {
            item.installation_scope or "system"
            for item in plan.update_items(UpdateSource.FLATPAK)
        }
        flatpak_scopes.update(plan.cleanup_scopes(UpdateSource.FLATPAK))
        if has_system or has_aur or has_firmware or "system" in flatpak_scopes:
            paths.append(Path("/"))
        if has_system or has_aur:
            paths.append(Path("/var/cache/pacman/pkg"))
        if has_aur:
            paths.extend(self._aur_cache_paths())
        if "system" in flatpak_scopes:
            paths.append(Path("/var/lib/flatpak"))
        if "user" in flatpak_scopes:
            paths.append(self.environment.home_dir() / ".local/share/flatpak")
        if plan.update_items(UpdateSource.PLASMA_WIDGET):
            paths.append(Path("/tmp"))
            paths.append(self.environment.home_dir() / ".local/share")

        issues: list[PreflightIssue] = []
        seen: set[Path] = set()
        estimated_download = self._estimated_download_text(selected_packages)
        for path in paths:
            disk_space = self.environment.disk_space(path)
            if disk_space is None:
                continue
            existing_path, free_bytes = disk_space
            if existing_path in seen:
                continue
            seen.add(existing_path)
            if free_bytes >= self.minimum_free_bytes:
                required_bytes = self._estimated_download_bytes(selected_packages)
                if required_bytes is None or free_bytes >= required_bytes + self.minimum_free_bytes:
                    continue
            message = self._t("Free disk space is low on {path}.").format(path=existing_path)
            if estimated_download:
                message = self._t("{message} Selected downloads report about {size}.").format(
                    message=message,
                    size=estimated_download,
                )
            issues.append(
                PreflightIssue(
                    severity=PreflightSeverity.WARNING,
                    title=self._t("Low disk space"),
                    message=message,
                    details=[
                        self._t("Available: {size}").format(size=self._format_bytes(free_bytes)),
                    ],
                )
            )
        return issues

    def _aur_cache_paths(self) -> list[Path]:
        return [Path("/tmp")]

    def _selected_packages(
        self,
        plan: UpdatePlan,
        packages: list[PackageUpdate],
    ) -> list[PackageUpdate]:
        return selected_packages_for_plan(plan, packages)

    def _estimated_download_text(self, packages: list[PackageUpdate]) -> str | None:
        values = [package.download_size or package.size for package in packages]
        values = [value for value in values if value]
        if not values:
            return None
        return ", ".join(values[:4]) + ("..." if len(values) > 4 else "")

    def _estimated_download_bytes(self, packages: list[PackageUpdate]) -> int | None:
        values = [
            parse_size_to_bytes(package.download_size or package.size)
            for package in packages
        ]
        byte_values = [value for value in values if value is not None]
        if not byte_values:
            return None
        return sum(byte_values)

    def _format_bytes(self, value: int) -> str:
        size = float(value)
        units = ("B", "KiB", "MiB", "GiB", "TiB")
        index = 0
        while size >= 1024 and index < len(units) - 1:
            size /= 1024
            index += 1
        return f"{size:.1f} {units[index]}"

    def _t(self, text: str) -> str:
        return self.translate(text)
