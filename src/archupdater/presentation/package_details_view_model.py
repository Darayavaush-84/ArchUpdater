from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

from archupdater.domain.package_metadata import (
    AurPackageMetadata,
    FlatpakPackageMetadata,
    PlasmaWidgetPackageMetadata,
    SystemPackageMetadata,
)
from archupdater.domain.packages import PackageUpdate
from archupdater.domain.kde_addons import kde_addon_type_label


Translate = Callable[[str], str]


@dataclass(frozen=True, slots=True)
class PackageDetailsMetric:
    key: str
    value: str


@dataclass(frozen=True, slots=True)
class PackageDetailsRow:
    key: str
    value: str
    hide_when_empty: bool = False


@dataclass(frozen=True, slots=True)
class PackageDetailsChipSection:
    key: str
    values: list[str] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class PackageDetailsViewModel:
    name: str
    source_text: str
    description: str
    homepage: str | None
    metrics: list[PackageDetailsMetric]
    rows: list[PackageDetailsRow]
    chip_sections: list[PackageDetailsChipSection]


def build_package_details_view_model(
    package: PackageUpdate,
    *,
    source_text: str,
    unavailable_text: str,
    no_description_text: str,
) -> PackageDetailsViewModel:
    source_metadata = package.source_metadata
    repository = package.repository_label or unavailable_text
    system_metadata = (
        source_metadata
        if isinstance(source_metadata, (SystemPackageMetadata, AurPackageMetadata))
        else None
    )
    aur_metadata = source_metadata if isinstance(source_metadata, AurPackageMetadata) else None
    flatpak_metadata = source_metadata if isinstance(source_metadata, FlatpakPackageMetadata) else None
    widget_metadata = (
        source_metadata if isinstance(source_metadata, PlasmaWidgetPackageMetadata) else None
    )
    return PackageDetailsViewModel(
        name=package.name,
        source_text=source_text,
        description=package.description or no_description_text,
        homepage=package.homepage,
        metrics=[
            PackageDetailsMetric("current", package.current_version or unavailable_text),
            PackageDetailsMetric("new", package.new_version or unavailable_text),
            PackageDetailsMetric("size_diff", package.size_diff or unavailable_text),
            PackageDetailsMetric("download", package.download_size or package.size or unavailable_text),
            PackageDetailsMetric("installed", package.installed_size or unavailable_text),
            PackageDetailsMetric("repository", repository),
        ],
        rows=[
            PackageDetailsRow("source", source_text),
            PackageDetailsRow("author", package.author or unavailable_text),
            PackageDetailsRow("size", package.size or unavailable_text),
            PackageDetailsRow("repository", repository),
            PackageDetailsRow("kind", _package_kind(package), True),
            PackageDetailsRow(
                "scope",
                (flatpak_metadata.installation_scope if flatpak_metadata else "") or "",
                True,
            ),
            PackageDetailsRow("remote", (flatpak_metadata.remote if flatpak_metadata else "") or "", True),
            PackageDetailsRow("branch", (flatpak_metadata.branch if flatpak_metadata else "") or "", True),
            PackageDetailsRow("runtime", (flatpak_metadata.runtime if flatpak_metadata else "") or "", True),
            PackageDetailsRow(
                "plugin",
                (widget_metadata.plugin_id if widget_metadata else "") or "",
                True,
            ),
            PackageDetailsRow("current_installed_size", package.current_installed_size or "", True),
            PackageDetailsRow(
                "architecture",
                (system_metadata.architecture if system_metadata else "") or "",
                True,
            ),
            PackageDetailsRow("packager", (system_metadata.packager if system_metadata else "") or "", True),
            PackageDetailsRow("build_date", (system_metadata.build_date if system_metadata else "") or "", True),
            PackageDetailsRow(
                "install_date",
                (system_metadata.install_date if system_metadata else "") or "",
                True,
            ),
            PackageDetailsRow(
                "install_reason",
                (system_metadata.install_reason if system_metadata else "") or "",
                True,
            ),
            PackageDetailsRow("maintainer", (aur_metadata.maintainer if aur_metadata else "") or "", True),
            PackageDetailsRow("votes", (aur_metadata.votes if aur_metadata else "") or "", True),
            PackageDetailsRow("popularity", (aur_metadata.popularity if aur_metadata else "") or "", True),
            PackageDetailsRow("out_of_date", (aur_metadata.out_of_date if aur_metadata else "") or "", True),
            PackageDetailsRow(
                "first_submitted",
                (aur_metadata.first_submitted if aur_metadata else "") or "",
                True,
            ),
            PackageDetailsRow(
                "last_modified",
                (aur_metadata.last_modified if aur_metadata else "") or "",
                True,
            ),
            PackageDetailsRow(
                "licenses",
                ", ".join(system_metadata.licenses) if system_metadata else "",
                True,
            ),
            PackageDetailsRow(
                "groups",
                ", ".join(system_metadata.groups) if system_metadata else "",
                True,
            ),
            PackageDetailsRow(
                "provides",
                ", ".join(system_metadata.provides) if system_metadata else "",
                True,
            ),
            PackageDetailsRow(
                "conflicts",
                ", ".join(system_metadata.conflicts) if system_metadata else "",
                True,
            ),
            PackageDetailsRow(
                "replaces",
                ", ".join(system_metadata.replaces) if system_metadata else "",
                True,
            ),
            PackageDetailsRow(
                "required_by",
                ", ".join(system_metadata.required_by) if system_metadata else "",
                True,
            ),
        ],
        chip_sections=[
            PackageDetailsChipSection("dependencies", _clean_values(package.dependencies)),
            PackageDetailsChipSection(
                "optional_dependencies",
                _clean_values(package.optional_dependencies),
            ),
            PackageDetailsChipSection(
                "make_dependencies",
                _clean_values(aur_metadata.make_dependencies if aur_metadata else []),
            ),
            PackageDetailsChipSection(
                "check_dependencies",
                _clean_values(aur_metadata.check_dependencies if aur_metadata else []),
            ),
            PackageDetailsChipSection(
                "release_notes",
                [
                    _release_note_text(note.version, note.date, note.description)
                    for note in package.release_notes
                ],
            ),
            PackageDetailsChipSection("warnings", _clean_values(package.warnings)),
        ],
    )


def _flatpak_kind(package: PackageUpdate) -> str:
    metadata = package.source_metadata
    if not isinstance(metadata, FlatpakPackageMetadata) or metadata.ref_kind is None:
        return ""
    return metadata.ref_kind.value.title()


def _package_kind(package: PackageUpdate) -> str:
    metadata = package.source_metadata
    if isinstance(metadata, PlasmaWidgetPackageMetadata):
        return kde_addon_type_label(metadata.package_kind, lambda text: text)
    return _flatpak_kind(package)


def _clean_values(values: list[str]) -> list[str]:
    return [value.strip() for value in values if value.strip()]


def _release_note_text(version: str, date: str | None, description: str) -> str:
    head = f"{version} · {date}" if date else version
    return f"{head}\n{description}" if description else head
