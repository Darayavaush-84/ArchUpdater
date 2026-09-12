from __future__ import annotations

import shutil
from pathlib import Path

from PySide6.QtCore import QCoreApplication

from archupdater.domain.aur import AurPkgbuildReview, AurVcsSource
from archupdater.domain.check_results import SourceCheckResult
from archupdater.domain.command_log import CheckLogEntry
from archupdater.domain.packages import PackageUpdate
from archupdater.services import aur_metadata
from archupdater.services.aur_errors import AurBuildError as AurBuildError
from archupdater.services.aur_errors import AurPkgbuildFetchError as AurPkgbuildFetchError
from archupdater.services.aur_review import AurReviewManager
from archupdater.services.aur_rpc import AurRpcClient
from archupdater.services.aur_vcs import AurVcsTracker
from archupdater.services.aur_vcs_state import AurVcsStateStore
from archupdater.services.command_runner import CommandRunner


class AurUpdateService:
    """Coordinate AUR checks; collaborators own metadata, reviews and VCS state."""

    def __init__(
        self,
        runner: CommandRunner,
        vcs_state_path: Path | None = None,
        *,
        rpc: AurRpcClient | None = None,
        vcs: AurVcsTracker | None = None,
        reviews: AurReviewManager | None = None,
    ) -> None:
        self.runner = runner
        self.rpc = rpc if rpc is not None else AurRpcClient()
        self.vcs = (
            vcs if vcs is not None else AurVcsTracker(runner, AurVcsStateStore(vcs_state_path))
        )
        self.reviews = (
            reviews if reviews is not None else AurReviewManager(runner, self.rpc, self.vcs)
        )

    QUERY_TIMEOUT_SECONDS = 120
    INFO_TIMEOUT_SECONDS = 120
    LOCAL_INFO_TIMEOUT_SECONDS = 120

    def check_updates(self) -> SourceCheckResult:
        helper = self.detect_helper()
        if helper is None:
            return SourceCheckResult()

        result = SourceCheckResult()
        command = [helper, "-Qua"]
        if helper == "pikaur":
            command.append("--noconfirm")

        query_log = self.runner.run(command, timeout_seconds=self.QUERY_TIMEOUT_SECONDS)
        result.logs.append(query_log)

        no_updates = (query_log.exit_code == 0 and not query_log.stdout.strip()) or (
            query_log.exit_code == 1
            and not query_log.stdout.strip()
            and not query_log.stderr.strip()
        )
        if no_updates:
            return result

        if query_log.exit_code != 0:
            details = query_log.stderr.strip() or query_log.stdout.strip() or helper
            result.warnings.append(
                QCoreApplication.translate(
                    "AurUpdateService",
                    "Failed to check AUR updates: {details}",
                ).format(details=details)
            )
            return result

        result.packages, unparsed_lines = aur_metadata.parse_update_output(query_log.stdout)
        if unparsed_lines:
            result.warnings.append(
                QCoreApplication.translate(
                    "AurUpdateService",
                    "Some AUR update lines could not be parsed: {lines}",
                ).format(lines="; ".join(unparsed_lines[:3]))
            )
        if not result.packages:
            return result

        info_command = [helper, "-Si", "--aur", *[package.name for package in result.packages]]
        if helper == "pikaur":
            info_command.append("--noconfirm")
        info_log = self.runner.run(info_command, timeout_seconds=self.INFO_TIMEOUT_SECONDS)
        result.logs.append(info_log)
        if info_log.stdout.strip():
            aur_metadata.apply_metadata(result.packages, info_log.stdout)

        local_info_log = self.runner.run(
            ["pacman", "-Qi", *[package.name for package in result.packages]],
            timeout_seconds=self.LOCAL_INFO_TIMEOUT_SECONDS,
        )
        result.logs.append(local_info_log)
        local_output = self._complete_local_metadata_output(
            result.packages,
            initial_output=local_info_log.stdout,
            logs=result.logs,
        )
        if local_output.strip():
            aur_metadata.apply_local_metadata(result.packages, local_output)

        result.packages = self.vcs.filter_stale_updates(
            result.packages,
            local_output=local_output,
            logs=result.logs,
        )
        if not result.packages:
            return result

        aur_metadata.apply_aur_rpc_metadata(
            result.packages, self.rpc.fetch_metadata(result.packages)
        )
        unresolved = [
            package.name
            for package in result.packages
            if not (aur_metadata.aur_metadata(package).package_base or "").strip()
        ]
        if unresolved:
            result.warnings.append(
                QCoreApplication.translate(
                    "AurUpdateService",
                    "AUR package base metadata could not be resolved: {packages}",
                ).format(packages=", ".join(unresolved[:8]))
            )
            unresolved_names = set(unresolved)
            result.packages = [
                package for package in result.packages if package.name not in unresolved_names
            ]
        return result

    def detect_helper(self) -> str | None:
        for candidate in ("paru", "yay", "pikaur"):
            if shutil.which(candidate):
                return candidate
        return None

    def _complete_local_metadata_output(
        self,
        packages: list[PackageUpdate],
        *,
        initial_output: str,
        logs: list[CheckLogEntry],
    ) -> str:
        output_parts = [initial_output] if initial_output.strip() else []
        found_names = {
            section.get("Name", "")
            for section in aur_metadata.parse_sections(initial_output)
            if section.get("Name")
        }
        missing_names = [package.name for package in packages if package.name not in found_names]
        for name in missing_names:
            info_log = self.runner.run(
                ["pacman", "-Qi", name],
                timeout_seconds=self.LOCAL_INFO_TIMEOUT_SECONDS,
            )
            logs.append(info_log)
            if info_log.stdout.strip():
                output_parts.append(info_log.stdout)
        return "\n\n".join(output_parts)

    def fetch_pkgbuild_review(
        self, package_name: str, package_base: str | None = None, *, lock_vcs_sources: bool = False
    ) -> AurPkgbuildReview:
        return self.reviews.prepare(package_name, package_base, lock_vcs_sources=lock_vcs_sources)

    def missing_build_dependencies(self, review: AurPkgbuildReview) -> list[str]:
        return self.reviews.missing_build_dependencies(review)

    def discard_pkgbuild_review(self, review: AurPkgbuildReview) -> None:
        self.reviews.discard(review)

    def record_vcs_install(
        self, package_name: str, version: str, sources: tuple[AurVcsSource, ...]
    ) -> None:
        self.vcs.store.record_install(package_name, version, sources)
