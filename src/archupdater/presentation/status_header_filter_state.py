from __future__ import annotations

from dataclasses import dataclass, field

from archupdater.domain.enums import UpdateSource
from archupdater.application.update_sources.descriptors import SOURCE_ORDER


def _all_sources() -> set[UpdateSource]:
    return set(SOURCE_ORDER)


def _zero_counters() -> dict[UpdateSource, int]:
    return {source: 0 for source in SOURCE_ORDER}


@dataclass(frozen=True, slots=True)
class SourceFilterToggle:
    active_source: UpdateSource | None
    changed: bool


@dataclass(slots=True)
class StatusHeaderFilterState:
    selectable_sources: set[UpdateSource] = field(default_factory=_all_sources)
    counter_values: dict[UpdateSource, int] = field(default_factory=_zero_counters)
    active_source_filter: UpdateSource | None = None

    @property
    def visible_sources(self) -> set[UpdateSource]:
        visible = set(self.selectable_sources)
        if self.counter_values.get(UpdateSource.FIRMWARE, 0) <= 0:
            visible.discard(UpdateSource.FIRMWARE)
        return visible

    def set_counter_values(self, values: dict[UpdateSource, int]) -> bool:
        self.counter_values = dict(values)
        return self.clear_invisible_active_filter()

    def set_selectable_sources(self, sources: set[UpdateSource]) -> bool:
        self.selectable_sources = set(sources)
        return self.clear_invisible_active_filter()

    def set_active_source_filter(self, source: UpdateSource | None) -> UpdateSource | None:
        self.active_source_filter = source if source in self.visible_sources else None
        return self.active_source_filter

    def toggle_source_filter(self, source: UpdateSource) -> SourceFilterToggle:
        if source not in self.visible_sources:
            return SourceFilterToggle(self.active_source_filter, changed=False)

        next_source = None if self.active_source_filter is source else source
        self.active_source_filter = next_source
        return SourceFilterToggle(next_source, changed=True)

    def clear_invisible_active_filter(self) -> bool:
        if (
            self.active_source_filter is not None
            and self.active_source_filter not in self.visible_sources
        ):
            self.active_source_filter = None
            return True
        return False
