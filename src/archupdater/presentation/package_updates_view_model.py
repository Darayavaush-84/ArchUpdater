from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from archupdater.domain.enums import UpdateSource
from archupdater.domain.package_metadata import FlatpakPackageMetadata, PlasmaWidgetPackageMetadata
from archupdater.domain.packages import PackageUpdate
from archupdater.application.update_sources.descriptors import source_filter_title as _source_filter_title
from archupdater.domain.kde_addons import kde_addon_type_label


Translate = Callable[[str], str]


@dataclass(frozen=True, slots=True)
class PackageUpdateRowView:
    package_id: str
    name: str
    source: UpdateSource
    source_text: str
    version_text: str
    current_version: str
    new_version: str
    checked: bool
    selection_locked: bool
    blocked_by_config: bool
    blocked_reason: str
    skipped_by_pkgbuild_review: bool
    tooltip: str
    haystack: str


def build_package_update_row_view(
    package: PackageUpdate,
    *,
    source_text: str,
    system_tooltip: str,
    translate: Translate | None = None,
) -> PackageUpdateRowView:
    t = translate or (lambda text: text)
    tooltip = ""
    if package.selection_locked:
        tooltip = package.blocked_reason or package.selection_lock_reason or system_tooltip
    elif package.source is UpdateSource.SYSTEM:
        tooltip = system_tooltip
    if package.skipped_by_pkgbuild_review:
        tooltip = package.selection_lock_reason or tooltip

    display_source_text = source_text
    addon_type = ""
    source_metadata = package.source_metadata
    if isinstance(source_metadata, PlasmaWidgetPackageMetadata):
        addon_type = kde_addon_type_label(source_metadata.package_kind, t)
        if addon_type:
            display_source_text = f"{source_text} - {addon_type}"
    elif isinstance(source_metadata, FlatpakPackageMetadata):
        flatpak_type = source_metadata.ref_kind.value.title() if source_metadata.ref_kind else ""
        if flatpak_type:
            display_source_text = f"{source_text} - {flatpak_type}"

    haystack = " ".join(
        part
        for part in (
            package.name,
            display_source_text,
            source_metadata.package_kind if isinstance(source_metadata, PlasmaWidgetPackageMetadata) else "",
            addon_type,
            package.version_label,
            package.description,
            package.repository_label or "",
            package.current_version,
            package.new_version,
        )
        if part
    ).lower()
    return PackageUpdateRowView(
        package_id=package.id,
        name=package.name,
        source=package.source,
        source_text=display_source_text,
        version_text=package.version_label,
        current_version=package.current_version,
        new_version=package.new_version,
        checked=package.selected,
        selection_locked=package.selection_locked,
        blocked_by_config=package.blocked_by_config,
        blocked_reason=package.blocked_reason or "",
        skipped_by_pkgbuild_review=package.skipped_by_pkgbuild_review,
        tooltip=tooltip,
        haystack=haystack,
    )


def package_matches_filter(
    row: PackageUpdateRowView,
    *,
    query: str,
    source_filter: UpdateSource | None,
) -> bool:
    source_matches = source_filter is None or row.source is source_filter
    return source_matches and (not query or query in row.haystack)


def source_filter_title(
    source: UpdateSource | None,
    *,
    translate: Translate,
) -> str:
    return _source_filter_title(source, translate=translate)
