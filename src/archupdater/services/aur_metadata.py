from __future__ import annotations

import re
from datetime import datetime, timezone

from PySide6.QtCore import QCoreApplication

from archupdater.domain.enums import UpdateSource
from archupdater.domain.package_metadata import AurPackageMetadata
from archupdater.domain.package_size import format_size_diff
from archupdater.domain.packages import PackageUpdate

ANSI_ESCAPE_RE = re.compile(r"\x1b\[[0-9;?]*[ -/]*[@-~]")
UPDATE_LINE_RE = re.compile(
    r"^(?:(?P<repository>[A-Za-z0-9@._+-]+)/)?"
    r"(?P<name>[A-Za-z0-9@._+-]+)\s+"
    r"(?P<current_version>\S+)\s+->\s+"
    r"(?P<new_version>\S+)$"
)
LIST_METADATA_KEYS = frozenset(
    {
        "Licenses",
        "Groups",
        "Provides",
        "Conflicts With",
        "Replaces",
        "Depends On",
        "Optional Deps",
        "Required By",
        "Make Deps",
        "Check Deps",
    }
)


def parse_update_lines(raw_output: str) -> list[PackageUpdate]:
    packages, _unparsed_lines = parse_update_output(raw_output)
    return packages


def parse_update_output(raw_output: str) -> tuple[list[PackageUpdate], list[str]]:
    packages: list[PackageUpdate] = []
    unparsed_lines: list[str] = []
    for raw_line in raw_output.splitlines():
        line = ANSI_ESCAPE_RE.sub("", raw_line).strip()
        if not line:
            continue

        match = UPDATE_LINE_RE.match(line)
        if not match:
            unparsed_lines.append(line)
            continue

        name = match.group("name")
        current_version = match.group("current_version")
        new_version = match.group("new_version")
        packages.append(
            PackageUpdate(
                name=name,
                current_version=current_version,
                new_version=new_version,
                source=UpdateSource.AUR,
                source_metadata=AurPackageMetadata(
                    repository=QCoreApplication.translate("AurUpdateService", "AUR"),
                    dynamic_version=new_version == "latest-commit",
                ),
                backend_id=name,
            )
        )
    return packages, unparsed_lines


def apply_metadata(packages: list[PackageUpdate], raw_output: str) -> None:
    metadata_by_name = {
        section.get("Name", ""): section
        for section in parse_sections(raw_output)
        if section.get("Name")
    }
    for package in packages:
        metadata = metadata_by_name.get(package.name)
        if not metadata:
            continue
        source_metadata = aur_metadata(package)
        package.description = metadata.get("Description", "")
        source_metadata.repository = metadata.get("Repository") or source_metadata.repository
        source_metadata.package_base = metadata.get("Package Base") or source_metadata.package_base
        package.download_size = metadata.get("Download Size")
        package.installed_size = metadata.get("Installed Size")
        package.size = package.download_size or package.installed_size
        package.homepage = metadata.get("URL") or package.homepage
        source_metadata.architecture = metadata.get("Architecture")
        source_metadata.packager = metadata.get("Packager")
        source_metadata.build_date = metadata.get("Build Date")
        source_metadata.licenses = split_metadata_list(metadata.get("Licenses"))
        source_metadata.groups = split_metadata_list(metadata.get("Groups"))
        source_metadata.provides = split_metadata_list(metadata.get("Provides"))
        source_metadata.conflicts = split_metadata_list(metadata.get("Conflicts With"))
        source_metadata.replaces = split_metadata_list(metadata.get("Replaces"))
        package.dependencies = split_metadata_list(metadata.get("Depends On"))
        package.optional_dependencies = split_metadata_list(metadata.get("Optional Deps"))
        source_metadata.make_dependencies = split_metadata_list(metadata.get("Make Deps"))
        source_metadata.check_dependencies = split_metadata_list(metadata.get("Check Deps"))


def apply_local_metadata(packages: list[PackageUpdate], raw_output: str) -> None:
    local_metadata_by_name = {
        section.get("Name", ""): section
        for section in parse_sections(raw_output)
        if section.get("Name")
    }
    for package in packages:
        metadata = local_metadata_by_name.get(package.name)
        if not metadata:
            continue
        source_metadata = aur_metadata(package)
        package.current_installed_size = metadata.get("Installed Size")
        source_metadata.install_date = metadata.get("Install Date")
        source_metadata.install_reason = metadata.get("Install Reason")
        source_metadata.required_by = split_metadata_list(metadata.get("Required By"))
        package.size_diff = format_size_diff(
            package.installed_size,
            package.current_installed_size,
        )


def apply_aur_rpc_metadata(
    packages: list[PackageUpdate],
    metadata_by_name: dict[str, dict[str, object]],
) -> None:
    for package in packages:
        metadata = metadata_by_name.get(package.name)
        if not metadata:
            continue
        source_metadata = aur_metadata(package)
        source_metadata.maintainer = optional_str(metadata.get("Maintainer"))
        source_metadata.package_base = (
            optional_str(metadata.get("PackageBase")) or source_metadata.package_base
        )
        source_metadata.votes = optional_str(metadata.get("NumVotes"))
        source_metadata.popularity = optional_str(metadata.get("Popularity"))
        source_metadata.out_of_date = (
            format_timestamp(metadata.get("OutOfDate")) if metadata.get("OutOfDate") else "No"
        )
        source_metadata.first_submitted = format_timestamp(metadata.get("FirstSubmitted"))
        source_metadata.last_modified = format_timestamp(metadata.get("LastModified"))
        package.homepage = optional_str(metadata.get("URL")) or package.homepage
        source_metadata.licenses = merge_metadata_list(
            source_metadata.licenses,
            metadata.get("License"),
        )
        package.dependencies = merge_metadata_list(package.dependencies, metadata.get("Depends"))
        package.optional_dependencies = merge_metadata_list(
            package.optional_dependencies,
            metadata.get("OptDepends"),
        )
        source_metadata.make_dependencies = merge_metadata_list(
            source_metadata.make_dependencies,
            metadata.get("MakeDepends"),
        )
        source_metadata.check_dependencies = merge_metadata_list(
            source_metadata.check_dependencies,
            metadata.get("CheckDepends"),
        )
        source_metadata.provides = merge_metadata_list(
            source_metadata.provides,
            metadata.get("Provides"),
        )
        source_metadata.conflicts = merge_metadata_list(
            source_metadata.conflicts,
            metadata.get("Conflicts"),
        )
        source_metadata.replaces = merge_metadata_list(
            source_metadata.replaces,
            metadata.get("Replaces"),
        )


def aur_metadata(package: PackageUpdate) -> AurPackageMetadata:
    metadata = package.source_metadata
    if not isinstance(metadata, AurPackageMetadata):
        raise TypeError("AUR package metadata expected.")
    return metadata


def parse_sections(raw_output: str) -> list[dict[str, str]]:
    sections: list[dict[str, str]] = []
    current: dict[str, str] = {}
    current_key: str | None = None

    for line in raw_output.splitlines():
        if not line.strip():
            if current:
                sections.append(current)
                current = {}
                current_key = None
            continue

        match = re.match(r"^([A-Za-z][A-Za-z ]+?)\s*:\s*(.*)$", line)
        if match:
            current_key = match.group(1).strip()
            current[current_key] = match.group(2).strip()
            continue

        if current_key:
            separator = "  " if current_key in LIST_METADATA_KEYS else " "
            current[current_key] = f"{current[current_key]}{separator}{line.strip()}".strip()

    if current:
        sections.append(current)

    return sections


def split_metadata_list(value: str | None) -> list[str]:
    if not value:
        return []
    stripped = value.strip()
    if not stripped or stripped.lower() == "none":
        return []
    return [
        item.strip()
        for item in re.split(r"\s{2,}|,\s*", stripped)
        if item.strip() and item.strip().lower() != "none"
    ]


def merge_metadata_list(current: list[str], value: object) -> list[str]:
    if isinstance(value, list):
        incoming = [str(item).strip() for item in value if str(item).strip()]
    else:
        incoming = split_metadata_list(str(value) if value is not None else None)
    merged = list(current)
    for item in incoming:
        if item not in merged:
            merged.append(item)
    return merged


def optional_str(value: object) -> str | None:
    text = str(value).strip() if value is not None else ""
    return text or None


def format_timestamp(value: object) -> str | None:
    try:
        timestamp = int(str(value))
    except (TypeError, ValueError):
        return None
    if timestamp <= 0:
        return None
    try:
        return datetime.fromtimestamp(timestamp, tz=timezone.utc).date().isoformat()
    except (OverflowError, ValueError, OSError):
        return None
