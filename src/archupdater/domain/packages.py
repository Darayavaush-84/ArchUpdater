from __future__ import annotations

from dataclasses import dataclass, field

from archupdater.domain.enums import UpdateSource
from archupdater.domain.package_metadata import (
    AurPackageMetadata,
    FirmwarePackageMetadata,
    FlatpakPackageMetadata,
    PackageSourceMetadata,
    PlasmaWidgetPackageMetadata,
    SystemPackageMetadata,
)


@dataclass(slots=True)
class PackageReleaseNote:
    version: str
    date: str | None = None
    description: str = ""


@dataclass(slots=True)
class PackageUpdate:
    name: str
    current_version: str
    new_version: str
    source: UpdateSource
    source_metadata: PackageSourceMetadata
    backend_id: str | None = None
    description: str = ""
    author: str | None = None
    homepage: str | None = None
    icon_name: str | None = None
    size: str | None = None
    download_size: str | None = None
    installed_size: str | None = None
    current_installed_size: str | None = None
    size_diff: str | None = None
    dependencies: list[str] = field(default_factory=list)
    optional_dependencies: list[str] = field(default_factory=list)
    release_notes: list[PackageReleaseNote] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    selected: bool = True
    selection_locked: bool = False
    selection_lock_reason: str | None = None
    blocked_by_config: bool = False
    blocked_reason: str | None = None
    skipped_by_pkgbuild_review: bool = False

    @property
    def id(self) -> str:
        return self.identity.cache_key

    @property
    def version_label(self) -> str:
        return self.versions.label

    @property
    def target_id(self) -> str:
        if isinstance(self.source_metadata, FlatpakPackageMetadata):
            return self.source_metadata.ref
        if isinstance(self.source_metadata, FirmwarePackageMetadata):
            return self.source_metadata.device_id
        if isinstance(self.source_metadata, PlasmaWidgetPackageMetadata):
            return self.source_metadata.content_id
        return self.backend_id or self.name

    @property
    def identity(self) -> PackageIdentity:
        installation_scope = (
            self.source_metadata.installation_scope
            if isinstance(self.source_metadata, FlatpakPackageMetadata)
            else None
        )
        return PackageIdentity(
            source=self.source,
            name=self.name,
            target_id=self.target_id,
            installation_scope=installation_scope,
        )

    @property
    def versions(self) -> PackageVersions:
        return PackageVersions(
            current=self.current_version,
            latest=self.new_version,
        )

    @property
    def repository_label(self) -> str | None:
        metadata = self.source_metadata
        if isinstance(
            metadata,
            (
                SystemPackageMetadata,
                AurPackageMetadata,
                FlatpakPackageMetadata,
                FirmwarePackageMetadata,
            ),
        ):
            return metadata.repository
        if isinstance(metadata, PlasmaWidgetPackageMetadata):
            return metadata.repository
        return None


@dataclass(frozen=True, slots=True)
class PackageIdentity:
    source: UpdateSource
    name: str
    target_id: str
    installation_scope: str | None = None

    @property
    def cache_key(self) -> str:
        scope = self.installation_scope or ""
        return f"{self.source.value}:{scope}:{self.target_id}"


@dataclass(frozen=True, slots=True)
class PackageVersions:
    current: str
    latest: str

    @property
    def label(self) -> str:
        return f"{self.current} -> {self.latest}"


@dataclass(slots=True)
class UpdateCounters:
    system: int = 0
    aur: int = 0
    flatpak: int = 0
    firmware: int = 0
    plasma_widgets: int = 0


def package_counter_snapshot(packages: list[PackageUpdate]) -> UpdateCounters:
    counters = UpdateCounters()
    for package in packages:
        if package.blocked_by_config:
            continue
        counter_field = package.source.counter_field
        setattr(counters, counter_field, getattr(counters, counter_field) + 1)
    return counters
