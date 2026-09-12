from __future__ import annotations

from dataclasses import dataclass

from archupdater.domain.enums import UpdateSource
from archupdater.domain.package_metadata import FlatpakPackageMetadata
from archupdater.domain.packages import PackageUpdate
from archupdater.domain.update_plan import UpdatePlan, UpdatePlanAction


@dataclass(frozen=True, slots=True)
class PackageSelectionKey:
    source: UpdateSource
    scope: str
    target_id: str

    @classmethod
    def from_package(cls, package: PackageUpdate) -> PackageSelectionKey:
        scope = (
            package.source_metadata.installation_scope
            if isinstance(package.source_metadata, FlatpakPackageMetadata)
            else ""
        )
        return cls(
            source=package.source,
            scope=scope,
            target_id=package.target_id,
        )


def selection_keys_for_plan(plan: UpdatePlan) -> set[PackageSelectionKey]:
    keys: set[PackageSelectionKey] = set()
    for item in plan.items:
        if item.action is UpdatePlanAction.CLEANUP:
            continue
        scope = item.installation_scope or ""
        if item.source is UpdateSource.FLATPAK:
            scope = scope or "system"
        keys.add(PackageSelectionKey(item.source, scope, item.target_id))
    return keys


def package_is_selected_by_plan(
    package: PackageUpdate,
    keys: set[PackageSelectionKey],
) -> bool:
    package_key = PackageSelectionKey.from_package(package)
    return package_key in keys


def selected_packages_for_plan(
    plan: UpdatePlan,
    packages: list[PackageUpdate],
) -> list[PackageUpdate]:
    keys = selection_keys_for_plan(plan)
    return [package for package in packages if package_is_selected_by_plan(package, keys)]
