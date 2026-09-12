from __future__ import annotations

import re
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Pattern

from PySide6.QtCore import QCoreApplication

from archupdater.services.checkupdates_workspace import CheckupdatesDbWorkspace
from archupdater.domain.check_results import UpdateCheckResult
from archupdater.domain.command_log import CheckLogEntry, CommandLogEntry
from archupdater.domain.enums import UpdateSource
from archupdater.domain.package_metadata import SystemPackageMetadata
from archupdater.domain.packages import PackageUpdate
from archupdater.services.command_runner import (
    CommandNotAvailableError,
    CommandRunner,
    CommandRunnerError,
)
from archupdater.domain.package_size import format_size_diff
from archupdater.domain.errors import BackendError


class PacmanServiceError(BackendError):
    def __init__(self, message: str, *, logs: list[CheckLogEntry] | None = None) -> None:
        super().__init__(message)
        self.logs = logs or []


@dataclass(slots=True)
class PacmanUpdateService:
    runner: CommandRunner
    checkupdates_workspace: CheckupdatesDbWorkspace = field(
        default_factory=CheckupdatesDbWorkspace
    )

    PACMAN_UPDATE_LINE_RE = re.compile(
        r"^(?P<name>[A-Za-z0-9@._+-]+)\s+"
        r"(?P<current_version>\S+)\s+->\s+"
        r"(?P<new_version>\S+?)(?P<ignored>\s+\[ignored\])?$"
    )
    QUERY_TIMEOUT_SECONDS = 60
    INFO_TIMEOUT_SECONDS = 120
    IGNORE_TIMEOUT_SECONDS = 20
    LIST_METADATA_KEYS = frozenset(
        {
            "Licenses",
            "Groups",
            "Provides",
            "Conflicts With",
            "Replaces",
            "Depends On",
            "Optional Deps",
            "Required By",
        }
    )

    def check_updates(
        self,
        progress_callback: Callable[[str, int], None] | None = None,
        *,
        use_local_db: bool = False,
    ) -> UpdateCheckResult:
        logs = []
        metadata_db_path: Path | None = None
        try:
            self._report_progress(
                progress_callback,
                QCoreApplication.translate("PacmanUpdateService", "Querying updates"),
                40,
            )
            query_log, preparation_logs, metadata_db_path = self._query_updates(
                use_local_db=use_local_db
            )
            logs.extend(preparation_logs)
            logs.append(query_log)

            no_updates = (
                query_log.exit_code in (0, 1, 2)
                and not query_log.stdout.strip()
                and not query_log.stderr.strip()
            )
            if query_log.exit_code != 0 and not no_updates:
                stderr = query_log.stderr.strip() or query_log.stdout.strip()
                fallback_details = (
                    QCoreApplication.translate(
                        "PacmanUpdateService",
                        "pacman returned a non-zero exit code.",
                    )
                    if use_local_db
                    else QCoreApplication.translate(
                        "PacmanUpdateService",
                        "checkupdates returned a non-zero exit code.",
                    )
                )
                raise PacmanServiceError(
                    QCoreApplication.translate(
                        "PacmanUpdateService",
                        "Failed to query updates: {details}",
                    ).format(details=stderr or fallback_details),
                    logs=logs,
                )

            packages, unparsed_lines = self._parse_update_output(query_log.stdout)
            warnings = []
            if unparsed_lines:
                warnings.append(
                    QCoreApplication.translate(
                        "PacmanUpdateService",
                        "Some pacman update lines could not be parsed: {lines}",
                    ).format(lines="; ".join(unparsed_lines[:3]))
                )
            ignore_patterns, ignore_log = self._load_ignore_patterns()
            logs.append(ignore_log)
            for package in packages:
                self._apply_selection_policy(package, ignore_patterns=ignore_patterns)
            if packages:
                self._load_metadata(
                    packages,
                    logs=logs,
                    ignore_patterns=ignore_patterns,
                    database_path=metadata_db_path,
                    progress_callback=progress_callback,
                )

            return UpdateCheckResult(
                packages=packages,
                checked_at=query_log.started_at,
                logs=logs,
                warnings=warnings,
            )
        except CommandNotAvailableError as exc:
            raise PacmanServiceError(
                QCoreApplication.translate(
                    "PacmanUpdateService",
                    "A required pacman command is not available: {details}",
                ).format(details=exc)
            ) from exc
        except CommandRunnerError as exc:
            raise PacmanServiceError(str(exc), logs=logs) from exc
        finally:
            if metadata_db_path is not None:
                self._cleanup_checkupdates_db_path(metadata_db_path)

    def _query_updates(
        self,
        *,
        use_local_db: bool = False,
    ) -> tuple[CommandLogEntry, list[CommandLogEntry], Path | None]:
        if use_local_db:
            return (
                self.runner.run(
                    ["pacman", "-Qu"],
                    timeout_seconds=self.QUERY_TIMEOUT_SECONDS,
                ),
                [],
                None,
            )

        if not self._has_command("checkupdates"):
            raise PacmanServiceError(
                QCoreApplication.translate(
                    "PacmanUpdateService",
                    "Update discovery requires `checkupdates` from pacman-contrib.",
                )
            )

        checkupdates_db_path = self._fresh_checkupdates_db_path()
        try:
            refresh_log = self.runner.run(
                ["checkupdates"],
                timeout_seconds=self.QUERY_TIMEOUT_SECONDS,
                extra_env={"CHECKUPDATES_DB": str(checkupdates_db_path)},
            )
            if refresh_log.exit_code not in {0, 2}:
                return refresh_log, [], checkupdates_db_path
            query_log = self.runner.run(
                [
                    "pacman",
                    "-Qu",
                    "--dbpath",
                    str(checkupdates_db_path),
                    "--color",
                    "never",
                ],
                timeout_seconds=self.QUERY_TIMEOUT_SECONDS,
            )
            return query_log, [refresh_log], checkupdates_db_path
        except BaseException:
            self._cleanup_checkupdates_db_path(checkupdates_db_path)
            raise

    def _fresh_checkupdates_db_path(self) -> Path:
        return self.checkupdates_workspace.create_run_path()

    def _cleanup_checkupdates_db_path(self, path: Path) -> None:
        self.checkupdates_workspace.cleanup_run_path(path)

    def _load_metadata(
        self,
        packages: list[PackageUpdate],
        *,
        logs: list[CheckLogEntry],
        ignore_patterns: list[Pattern[str]],
        database_path: Path | None = None,
        progress_callback: Callable[[str, int], None] | None = None,
    ) -> None:
        self._report_progress(
            progress_callback,
            QCoreApplication.translate("PacmanUpdateService", "Loading metadata"),
            90,
        )

        names = [package.name for package in packages]
        database_arguments = (
            ["--dbpath", str(database_path), "--color", "never"]
            if database_path is not None
            else []
        )
        remote_log = self.runner.run(
            ["pacman", "-Si", *database_arguments, *names],
            timeout_seconds=self.INFO_TIMEOUT_SECONDS,
        )
        logs.append(remote_log)
        if remote_log.stdout.strip():
            self._apply_remote_metadata(packages, remote_log.stdout)

        local_log = self.runner.run(
            ["pacman", "-Qi", *database_arguments, *names],
            timeout_seconds=self.INFO_TIMEOUT_SECONDS,
        )
        logs.append(local_log)
        if local_log.stdout.strip():
            self._apply_local_metadata(packages, local_log.stdout)

        for package in packages:
            self._apply_selection_policy(package, ignore_patterns=ignore_patterns)

    def _has_command(self, name: str) -> bool:
        return shutil.which(name) is not None

    def _report_progress(
        self,
        progress_callback: Callable[[str, int], None] | None,
        label: str,
        percent: int,
    ) -> None:
        if progress_callback is not None:
            progress_callback(label, percent)

    def _parse_update_output(self, raw_output: str) -> tuple[list[PackageUpdate], list[str]]:
        packages: list[PackageUpdate] = []
        unparsed_lines: list[str] = []
        for raw_line in raw_output.splitlines():
            line = raw_line.strip()
            if not line:
                continue

            match = self.PACMAN_UPDATE_LINE_RE.match(line)
            if not match:
                unparsed_lines.append(line)
                continue

            package = PackageUpdate(
                name=match.group("name"),
                current_version=match.group("current_version"),
                new_version=match.group("new_version"),
                source=UpdateSource.SYSTEM,
                source_metadata=SystemPackageMetadata(),
            )
            if match.group("ignored"):
                self._mark_blocked_by_pacman_config(package)
            packages.append(package)
        return packages, unparsed_lines

    def _apply_remote_metadata(self, packages: list[PackageUpdate], raw_output: str) -> None:
        metadata_by_name = {
            section.get("Name", ""): section
            for section in self._parse_sections(raw_output)
            if section.get("Name")
        }
        for package in packages:
            metadata = metadata_by_name.get(package.name)
            if not metadata:
                continue
            source_metadata = self._system_metadata(package)
            package.description = metadata.get("Description", "")
            source_metadata.repository = metadata.get("Repository") or source_metadata.repository
            package.download_size = metadata.get("Download Size")
            package.installed_size = metadata.get("Installed Size")
            package.size = package.download_size or package.installed_size
            package.homepage = metadata.get("URL") or package.homepage
            source_metadata.architecture = metadata.get("Architecture")
            source_metadata.packager = metadata.get("Packager")
            source_metadata.build_date = metadata.get("Build Date")
            source_metadata.licenses = self._split_metadata_list(metadata.get("Licenses"))
            source_metadata.groups = self._split_metadata_list(metadata.get("Groups"))
            source_metadata.provides = self._split_metadata_list(metadata.get("Provides"))
            source_metadata.conflicts = self._split_metadata_list(metadata.get("Conflicts With"))
            source_metadata.replaces = self._split_metadata_list(metadata.get("Replaces"))
            package.dependencies = self._split_metadata_list(metadata.get("Depends On"))
            package.optional_dependencies = self._split_metadata_list(metadata.get("Optional Deps"))

    def _apply_local_metadata(self, packages: list[PackageUpdate], raw_output: str) -> None:
        metadata_by_name = {
            section.get("Name", ""): section
            for section in self._parse_sections(raw_output)
            if section.get("Name")
        }
        for package in packages:
            metadata = metadata_by_name.get(package.name)
            if not metadata:
                continue
            source_metadata = self._system_metadata(package)
            package.current_installed_size = metadata.get("Installed Size")
            source_metadata.install_date = metadata.get("Install Date")
            source_metadata.install_reason = metadata.get("Install Reason")
            source_metadata.required_by = self._split_metadata_list(metadata.get("Required By"))
            package.size_diff = format_size_diff(
                package.installed_size,
                package.current_installed_size,
            )

    def _apply_selection_policy(
        self,
        package: PackageUpdate,
        *,
        ignore_patterns: list[Pattern[str]] | None = None,
    ) -> None:
        reported_ignored = package.blocked_by_config
        package.selection_locked = False
        package.selection_lock_reason = None
        package.blocked_by_config = False
        package.blocked_reason = None

        if reported_ignored or self._matches_ignore_patterns(
            package.name,
            ignore_patterns or [],
        ):
            self._mark_blocked_by_pacman_config(package)
            return

        package.selected = True

    def _mark_blocked_by_pacman_config(self, package: PackageUpdate) -> None:
        package.selected = False
        package.selection_locked = True
        package.blocked_by_config = True
        package.blocked_reason = QCoreApplication.translate(
            "PacmanUpdateService",
            "Blocked by pacman.conf",
        )
        package.selection_lock_reason = package.blocked_reason

    def _load_ignore_patterns(self) -> tuple[list[Pattern[str]], object]:
        ignore_log = self.runner.run(
            ["pacman-conf", "IgnorePkg"],
            timeout_seconds=self.IGNORE_TIMEOUT_SECONDS,
        )
        if ignore_log.exit_code != 0 or not ignore_log.stdout.strip():
            return [], ignore_log

        patterns: list[Pattern[str]] = []
        for token in ignore_log.stdout.strip().split():
            base = token.split("=", 1)[0].split("<", 1)[0].split(">", 1)[0].strip()
            if not base:
                continue
            escaped = re.escape(base)
            escaped = escaped.replace(r"\*", ".*").replace(r"\?", ".")
            patterns.append(re.compile(f"^{escaped}$"))
        return patterns, ignore_log

    def _matches_ignore_patterns(self, package_name: str, patterns: list[Pattern[str]]) -> bool:
        return any(pattern.match(package_name) for pattern in patterns)

    def _system_metadata(self, package: PackageUpdate) -> SystemPackageMetadata:
        metadata = package.source_metadata
        if not isinstance(metadata, SystemPackageMetadata):
            raise TypeError("System package metadata expected.")
        return metadata

    def _parse_sections(self, raw_output: str) -> list[dict[str, str]]:
        sections: list[dict[str, str]] = []
        current: dict[str, str] = {}
        current_key: str | None = None

        for line in raw_output.splitlines():
            if not line.strip():
                if current:
                    sections.append(current)
                    current = {}
                    current_key = None
                continue

            match = re.match(r"^([A-Za-z][A-Za-z ]+?)\s*:\s*(.*)$", line)
            if match:
                current_key = match.group(1).strip()
                current[current_key] = match.group(2).strip()
                continue

            if current_key:
                separator = "  " if current_key in self.LIST_METADATA_KEYS else " "
                current[current_key] = (
                    f"{current[current_key]}{separator}{line.strip()}".strip()
                )

        if current:
            sections.append(current)

        return sections

    def _split_metadata_list(self, value: str | None) -> list[str]:
        if not value:
            return []
        stripped = value.strip()
        if not stripped or stripped.lower() == "none":
            return []
        return [
            item.strip()
            for item in re.split(r"\s{2,}|,\s*", stripped)
            if item.strip() and item.strip().lower() != "none"
        ]
