from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime

from archupdater.application.update_session.protocol import (
    BatchStep,
    step_from_running_status,
)
from archupdater.application.update_sources.descriptors import (
    SOURCE_ORDER,
    source_descriptors,
)
from archupdater.domain.check_results import UpdateCheckResult
from archupdater.domain.enums import UpdateSource
from archupdater.domain.packages import UpdateCounters


Translate = Callable[[str], str]


@dataclass(slots=True)
class TrayStatusModel:
    translate: Translate
    available_updates_count: int = 0
    counters: UpdateCounters = field(default_factory=UpdateCounters)
    ignored_updates_count: int = 0
    has_successful_check_result: bool = False
    check_failure_message: str | None = None
    busy_message: str | None = None
    refresh_pending: bool = False

    @property
    def has_check_failure(self) -> bool:
        return self.check_failure_message is not None

    @property
    def shows_busy_status(self) -> bool:
        return self.busy_message is not None or self.refresh_pending

    def apply_check_result(self, result: UpdateCheckResult) -> None:
        self.available_updates_count = result.actionable_count
        self.counters = result.counters
        self.ignored_updates_count = result.ignored_count
        self.has_successful_check_result = True
        self.check_failure_message = None
        self.busy_message = None
        self.refresh_pending = False

    def apply_check_failure(self, message: str) -> None:
        self.available_updates_count = 0
        self.counters = UpdateCounters()
        self.ignored_updates_count = 0
        self.has_successful_check_result = False
        self.check_failure_message = message.strip() or self.translate("Unknown error.")
        self.busy_message = None
        self.refresh_pending = False

    def mark_checking(self) -> None:
        self.busy_message = self.translate("Checking for updates...")
        self.refresh_pending = False
        self.check_failure_message = None

    def mark_update_status(self, value: str) -> bool:
        message = self._update_busy_message(value)
        if message is None:
            return False
        self.busy_message = message
        self.refresh_pending = False
        self.check_failure_message = None
        return True

    def mark_refresh_pending(self) -> None:
        self.busy_message = None
        self.refresh_pending = True
        self.check_failure_message = None

    def clear_busy_message(self) -> None:
        self.busy_message = None

    def updates_signature(self, result: UpdateCheckResult) -> tuple[str, ...]:
        return tuple(sorted(package.id for package in result.actionable_packages))

    def updates_available_message(self) -> str:
        count = self.available_updates_count
        if count == 1:
            message = self.translate("1 update is ready to install.")
        else:
            message = self.translate("{count} updates are ready to install.").format(
                count=count
            )
        if self.ignored_updates_count > 0:
            message = (
                message
                + " "
                + self.translate("{count} ignored by pacman.conf.").format(
                    count=self.ignored_updates_count
                )
            )
        return message

    def check_failed_message(self) -> str:
        return self.translate("Update check failed. Open ArchUpdater.")

    def update_completed_message(self) -> str:
        return self.translate("Selected updates completed. Refreshing update status...")

    def tooltip(self, next_check_at: datetime | None = None) -> str:
        lines = [self._primary_tooltip_line()]

        breakdown = self._counter_breakdown()
        if breakdown:
            lines.append(breakdown)
        if self.ignored_updates_count > 0:
            lines.append(
                self.translate("Ignored by pacman.conf: {count}").format(
                    count=self.ignored_updates_count
                )
            )
        if self.check_failure_message:
            lines.append(self.check_failure_message)
        if next_check_at is not None and not self.shows_busy_status:
            lines.append(
                self.translate("Next check: {time}").format(
                    time=next_check_at.strftime("%Y-%m-%d %H:%M")
                )
            )
        return "\n".join(lines)

    def _primary_tooltip_line(self) -> str:
        if self.refresh_pending:
            return self.translate("ArchUpdater: Refreshing update status...")
        if self.busy_message is not None:
            return self.translate("ArchUpdater: {status}").format(status=self.busy_message)
        if self.check_failure_message is not None:
            return self.translate("ArchUpdater: Last check failed")
        if self.available_updates_count <= 0 and self.has_successful_check_result:
            return self.translate("ArchUpdater: Up to date")
        if self.available_updates_count <= 0:
            return self.translate("ArchUpdater")
        if self.available_updates_count == 1:
            return self.translate("ArchUpdater: 1 update available")
        return self.translate("ArchUpdater: {count} updates available").format(
            count=self.available_updates_count
        )

    def _counter_breakdown(self) -> str:
        values = self._counter_values()
        parts: list[str] = []
        descriptors = source_descriptors(self.translate)
        for source in SOURCE_ORDER:
            count = values[source]
            if count <= 0:
                continue
            parts.append(f"{descriptors[source].counter_title}: {count}")
        return ", ".join(parts)

    def _counter_values(self) -> dict[UpdateSource, int]:
        return {
            UpdateSource.SYSTEM: self.counters.system,
            UpdateSource.AUR: self.counters.aur,
            UpdateSource.FLATPAK: self.counters.flatpak,
            UpdateSource.PLASMA_WIDGET: self.counters.plasma_widgets,
            UpdateSource.FIRMWARE: self.counters.firmware,
        }

    def _update_busy_message(self, value: str) -> str | None:
        if value == "starting_integrated":
            return self.translate("Starting update session...")
        if value == "waiting_authentication":
            return self.translate("Waiting for authentication...")

        step = step_from_running_status(value)
        if step is None:
            return None

        messages = {
            BatchStep.SYSTEM: self.translate("Installing system updates..."),
            BatchStep.AUR: self.translate("Installing AUR updates..."),
            BatchStep.FLATPAK: self.translate("Installing Flatpak updates..."),
            BatchStep.FIRMWARE: self.translate("Installing firmware updates..."),
            BatchStep.PLASMA_WIDGET: self.translate("Installing KDE Store add-ons..."),
        }
        return messages[step]
