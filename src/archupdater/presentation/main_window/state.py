from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from archupdater.domain.arch_news import ArchNewsItem
from archupdater.domain.check_results import ArchNewsCheckState
from archupdater.domain.enums import OperationState, UpdateSource
from archupdater.domain.packages import PackageUpdate


@dataclass(slots=True)
class MainWindowState:
    packages: list[PackageUpdate] = field(default_factory=list)
    arch_news: list[ArchNewsItem] = field(default_factory=list)
    arch_news_state: ArchNewsCheckState = ArchNewsCheckState.LOADED
    check_warnings: list[str] = field(default_factory=list)
    active_update_packages: list[PackageUpdate] = field(default_factory=list)
    last_checked_at: datetime | None = None
    check_failure_message: str = ""
    operation_state: OperationState = OperationState.IDLE
    active_source_filter: UpdateSource | None = None
    plasma_restart_recommended: bool = False
    startup_notice_pending_visibility: bool = False
    post_update_refresh_pending: bool = False
