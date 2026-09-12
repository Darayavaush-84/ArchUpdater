from __future__ import annotations

from dataclasses import dataclass, field

from archupdater.domain.enums import UpdateSource


@dataclass(slots=True)
class OptionalSourceStatus:
    source: UpdateSource
    installed: bool
    active: bool
    status_text: str
    installable_packages: list[str] = field(default_factory=list)
    removable_packages: list[str] = field(default_factory=list)


@dataclass(slots=True)
class OptionalSourcesSnapshot:
    statuses: dict[UpdateSource, OptionalSourceStatus] = field(default_factory=dict)

    def status_for(self, source: UpdateSource) -> OptionalSourceStatus | None:
        return self.statuses.get(source)

    @property
    def active_sources(self) -> set[UpdateSource]:
        return {
            source
            for source, status in self.statuses.items()
            if status.active
        }

    @property
    def selectable_sources(self) -> set[UpdateSource]:
        return {UpdateSource.SYSTEM, *self.active_sources}
