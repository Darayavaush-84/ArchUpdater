from __future__ import annotations

from dataclasses import dataclass, field

from archupdater.domain.enums import FlatpakRefKind


@dataclass(slots=True)
class SystemPackageMetadata:
    repository: str | None = None
    architecture: str | None = None
    packager: str | None = None
    build_date: str | None = None
    install_date: str | None = None
    install_reason: str | None = None
    licenses: list[str] = field(default_factory=list)
    groups: list[str] = field(default_factory=list)
    provides: list[str] = field(default_factory=list)
    conflicts: list[str] = field(default_factory=list)
    replaces: list[str] = field(default_factory=list)
    required_by: list[str] = field(default_factory=list)


@dataclass(slots=True)
class AurPackageMetadata:
    repository: str | None = "AUR"
    package_base: str | None = None
    architecture: str | None = None
    packager: str | None = None
    build_date: str | None = None
    install_date: str | None = None
    install_reason: str | None = None
    maintainer: str | None = None
    votes: str | None = None
    popularity: str | None = None
    out_of_date: str | None = None
    first_submitted: str | None = None
    last_modified: str | None = None
    licenses: list[str] = field(default_factory=list)
    groups: list[str] = field(default_factory=list)
    provides: list[str] = field(default_factory=list)
    conflicts: list[str] = field(default_factory=list)
    replaces: list[str] = field(default_factory=list)
    required_by: list[str] = field(default_factory=list)
    make_dependencies: list[str] = field(default_factory=list)
    check_dependencies: list[str] = field(default_factory=list)
    dynamic_version: bool = False


@dataclass(slots=True)
class FlatpakPackageMetadata:
    ref: str
    ref_kind: FlatpakRefKind | None = None
    installation_scope: str = "system"
    repository: str | None = None
    remote: str | None = None
    branch: str | None = None
    runtime: str | None = None


@dataclass(slots=True)
class FirmwarePackageMetadata:
    device_id: str
    repository: str | None = None
    needs_reboot: bool = False
    needs_shutdown: bool = False


@dataclass(slots=True)
class PlasmaWidgetPackageMetadata:
    content_id: str
    repository: str | None = "KDE Store"
    package_kind: str | None = None
    plugin_id: str | None = None


PackageSourceMetadata = (
    SystemPackageMetadata
    | AurPackageMetadata
    | FlatpakPackageMetadata
    | FirmwarePackageMetadata
    | PlasmaWidgetPackageMetadata
)
