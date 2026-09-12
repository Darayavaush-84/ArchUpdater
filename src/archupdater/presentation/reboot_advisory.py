from __future__ import annotations

from archupdater.domain.package_metadata import FirmwarePackageMetadata, SystemPackageMetadata
from archupdater.domain.packages import PackageUpdate


def critical_reboot_packages(packages: list[PackageUpdate]) -> list[str]:
    prefixes = ("linux", "nvidia", "mesa", "systemd", "glibc", "linux-firmware")
    exact = {"amd-ucode", "intel-ucode"}
    names: list[str] = []
    for package in packages:
        if not isinstance(package.source_metadata, SystemPackageMetadata):
            continue
        name = package.name
        if name in exact or any(name == prefix or name.startswith(f"{prefix}-") for prefix in prefixes):
            names.append(name)
    return names


def firmware_shutdown_devices(packages: list[PackageUpdate]) -> list[str]:
    return [
        package.name
        for package in packages
        if isinstance(package.source_metadata, FirmwarePackageMetadata)
        and package.source_metadata.needs_shutdown
    ]


def firmware_reboot_devices(packages: list[PackageUpdate]) -> list[str]:
    return [
        package.name
        for package in packages
        if isinstance(package.source_metadata, FirmwarePackageMetadata)
        and package.source_metadata.needs_reboot
        and not package.source_metadata.needs_shutdown
    ]
