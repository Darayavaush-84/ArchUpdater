from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

from archupdater.domain.enums import UpdateSource
from archupdater.domain.package_metadata import (
    AurPackageMetadata,
    FlatpakPackageMetadata,
    PlasmaWidgetPackageMetadata,
)
from archupdater.domain.packages import PackageUpdate


class UpdatePlanAction(str, Enum):
    UPDATE = "update"
    CLEANUP = "cleanup"


@dataclass(frozen=True, slots=True)
class UpdatePlanItem:
    source: UpdateSource
    target_id: str
    action: UpdatePlanAction = UpdatePlanAction.UPDATE
    installation_scope: str | None = None
    package_name: str | None = None
    package_kind: str | None = None
    plugin_id: str | None = None
    package_base: str | None = None
    expected_version: str | None = None
    current_version: str | None = None
    dynamic_version: bool = False

    @classmethod
    def from_package(cls, package: PackageUpdate) -> UpdatePlanItem:
        metadata = package.source_metadata
        if isinstance(metadata, AurPackageMetadata):
            return cls(
                source=package.source,
                target_id=package.target_id,
                package_name=package.name,
                package_base=metadata.package_base,
                expected_version=package.new_version,
                current_version=package.current_version,
                dynamic_version=metadata.dynamic_version,
            )
        if isinstance(metadata, FlatpakPackageMetadata):
            return cls(
                source=package.source,
                target_id=package.target_id,
                installation_scope=metadata.installation_scope or "system",
                expected_version=package.new_version,
            )
        if isinstance(metadata, PlasmaWidgetPackageMetadata):
            return cls(
                source=package.source,
                target_id=package.target_id,
                package_name=package.name,
                package_kind=metadata.package_kind or "Plasma/Applet",
                plugin_id=metadata.plugin_id,
                expected_version=package.new_version,
            )
        return cls(
            source=package.source,
            target_id=package.target_id,
            expected_version=package.new_version,
        )


@dataclass(slots=True)
class UpdatePlan:
    items: list[UpdatePlanItem] = field(default_factory=list)

    @property
    def has_any(self) -> bool:
        return bool(self.items)

    def has_source(self, source: UpdateSource) -> bool:
        return any(item.source is source for item in self.items)

    def update_items(self, source: UpdateSource | None = None) -> list[UpdatePlanItem]:
        return [
            item
            for item in self.items
            if item.action is UpdatePlanAction.UPDATE
            and (source is None or item.source is source)
        ]

    def cleanup_items(self, source: UpdateSource | None = None) -> list[UpdatePlanItem]:
        return [
            item
            for item in self.items
            if item.action is UpdatePlanAction.CLEANUP
            and (source is None or item.source is source)
        ]

    def target_ids(self, source: UpdateSource) -> list[str]:
        return [item.target_id for item in self.update_items(source)]

    def flatpak_refs(self, installation_scope: str | None = None) -> list[str]:
        refs: list[str] = []
        for item in self.update_items(UpdateSource.FLATPAK):
            scope = item.installation_scope or "system"
            if installation_scope is None or scope == installation_scope:
                refs.append(item.target_id)
        return refs

    def cleanup_scopes(self, source: UpdateSource) -> list[str]:
        return [
            item.installation_scope or item.target_id
            for item in self.cleanup_items(source)
        ]
