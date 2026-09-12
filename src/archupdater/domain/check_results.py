from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum

from archupdater.domain.arch_news import ArchNewsItem
from archupdater.domain.command_log import CheckLogEntry
from archupdater.domain.packages import PackageUpdate, UpdateCounters, package_counter_snapshot
from archupdater.domain.enums import UpdateSource


class CheckState(str, Enum):
    SUCCESS = "success"
    PARTIAL = "partial"
    FAILED = "failed"


class ArchNewsCheckState(str, Enum):
    LOADED = "loaded"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class SourceCheckReport:
    source: UpdateSource
    state: CheckState
    warnings: tuple[str, ...] = ()


@dataclass(slots=True)
class SourceCheckResult:
    packages: list[PackageUpdate] = field(default_factory=list)
    logs: list[CheckLogEntry] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


@dataclass(slots=True)
class UpdateCheckResult:
    packages: list[PackageUpdate]
    checked_at: datetime
    logs: list[CheckLogEntry]
    warnings: list[str] = field(default_factory=list)
    arch_news: list[ArchNewsItem] = field(default_factory=list)
    source_reports: list[SourceCheckReport] = field(default_factory=list)
    arch_news_state: ArchNewsCheckState = ArchNewsCheckState.LOADED

    @property
    def actionable_packages(self) -> list[PackageUpdate]:
        return [package for package in self.packages if not package.blocked_by_config]

    @property
    def actionable_count(self) -> int:
        return len(self.actionable_packages)

    @property
    def ignored_count(self) -> int:
        return len([package for package in self.packages if package.blocked_by_config])

    @property
    def counters(self) -> UpdateCounters:
        return package_counter_snapshot(self.packages)
