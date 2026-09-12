from __future__ import annotations

import json
import re
import shutil
from dataclasses import dataclass
from typing import Callable, Iterator

from PySide6.QtCore import QCoreApplication

from archupdater.domain.check_results import SourceCheckResult
from archupdater.domain.enums import UpdateSource
from archupdater.domain.package_metadata import FirmwarePackageMetadata
from archupdater.domain.packages import PackageUpdate
from archupdater.services.command_runner import (
    CommandNotAvailableError,
    CommandRunner,
    CommandRunnerError,
)


FirmwareProbeFn = Callable[[list[str], float], tuple[int, str, str]]


@dataclass(slots=True)
class FirmwareDeviceSupportProbe:
    run: FirmwareProbeFn | None = None
    timeout_seconds: float = 4.0

    _SUPPORTED_FLAGS = frozenset({"supported", "updatable"})

    def detect_supported_devices(self) -> bool | None:
        exit_code, stdout, _stderr = self._run(
            ["fwupdmgr", "get-devices", "--json"],
            timeout_seconds=self.timeout_seconds,
        )
        if exit_code != 0 or not stdout.strip():
            return None

        try:
            payload = json.loads(stdout)
        except json.JSONDecodeError:
            return None

        return any(self._is_supported_device(device) for device in self._iter_devices(payload))

    def _run(
        self,
        command: list[str],
        *,
        timeout_seconds: float,
    ) -> tuple[int, str, str]:
        if self.run is not None:
            return self.run(command, timeout_seconds)

        try:
            completed = CommandRunner(
                default_timeout_seconds=timeout_seconds,
                max_output_bytes=2 * 1024 * 1024,
            ).run(
                command,
                timeout_seconds=timeout_seconds,
            )
        except CommandNotAvailableError as exc:
            return 127, "", str(exc)
        except CommandRunnerError as exc:
            return 1, "", str(exc)
        return completed.exit_code, completed.stdout, completed.stderr

    def _iter_devices(self, payload: object) -> Iterator[dict[str, object]]:
        roots: object
        if isinstance(payload, dict):
            roots = payload.get("Devices") or payload.get("devices") or []
        else:
            roots = payload

        if not isinstance(roots, list):
            return

        for item in roots:
            yield from self._walk_device_tree(item)

    def _walk_device_tree(self, item: object) -> Iterator[dict[str, object]]:
        if not isinstance(item, dict):
            return

        yield item
        for key in ("Children", "children", "ChildDevices", "child_devices"):
            children = item.get(key)
            if isinstance(children, list):
                for child in children:
                    yield from self._walk_device_tree(child)

    def _is_supported_device(self, device: dict[str, object]) -> bool:
        for key in ("Supported", "Updatable", "Updateable"):
            if device.get(key) is True:
                return True
        return bool(self._device_flags(device) & self._SUPPORTED_FLAGS)

    def _device_flags(self, device: dict[str, object]) -> set[str]:
        raw_flags = device.get("Flags") or device.get("flags") or []
        if isinstance(raw_flags, list):
            values = raw_flags
        elif isinstance(raw_flags, str):
            values = re.split(r"[\s,|]+", raw_flags)
        else:
            return set()
        return {
            str(flag).strip().casefold().replace("_", "-")
            for flag in values
            if str(flag).strip()
        }


@dataclass(slots=True)
class FirmwareUpdateService:
    runner: CommandRunner

    REFRESH_TIMEOUT_SECONDS = 180
    QUERY_TIMEOUT_SECONDS = 120
    GET_UPDATES_SUCCESS_EXIT_CODES = frozenset({0, 2})

    def check_updates(self) -> SourceCheckResult:
        if shutil.which("fwupdmgr") is None:
            return SourceCheckResult()

        result = SourceCheckResult()
        refresh_log = self.runner.run(
            ["fwupdmgr", "refresh", "--force"],
            timeout_seconds=self.REFRESH_TIMEOUT_SECONDS,
        )
        result.logs.append(refresh_log)
        if refresh_log.exit_code != 0:
            result.warnings.append(
                QCoreApplication.translate(
                    "FirmwareUpdateService",
                    "Failed to refresh firmware metadata.",
                )
            )

        updates_log = self.runner.run(
            ["fwupdmgr", "get-updates", "--json", "--no-authenticate"],
            timeout_seconds=self.QUERY_TIMEOUT_SECONDS,
        )
        result.logs.append(updates_log)
        if updates_log.exit_code not in self.GET_UPDATES_SUCCESS_EXIT_CODES:
            result.warnings.append(
                QCoreApplication.translate(
                    "FirmwareUpdateService",
                    "Failed to check firmware updates.",
                )
            )
            return result
        if updates_log.exit_code != 0 and not updates_log.stdout.strip():
            return result

        try:
            payload = json.loads(updates_log.stdout or "{}")
        except json.JSONDecodeError:
            result.warnings.append(
                QCoreApplication.translate(
                    "FirmwareUpdateService",
                    "Firmware update data could not be parsed.",
                )
            )
            return result

        for device in self._iter_devices(payload):
            release = self._first_release_with_version(device)
            if release is None:
                continue
            target_id = self._device_target_id(device)
            if not target_id:
                continue
            needs_reboot, needs_shutdown = self._restart_requirement(device, release)
            result.packages.append(
                PackageUpdate(
                    name=self._device_name(device),
                    current_version=str(device.get("Version") or ""),
                    new_version=str(release.get("Version") or ""),
                    source=UpdateSource.FIRMWARE,
                    source_metadata=FirmwarePackageMetadata(
                        device_id=target_id,
                        repository=str(release.get("RemoteId") or "LVFS"),
                        needs_reboot=needs_reboot,
                        needs_shutdown=needs_shutdown,
                    ),
                    backend_id=target_id,
                    description=str(release.get("Summary") or device.get("Summary") or ""),
                    size=self._format_bytes(release.get("Size")),
                    download_size=self._format_bytes(release.get("Size")),
                    warnings=self._device_warnings(
                        needs_reboot=needs_reboot,
                        needs_shutdown=needs_shutdown,
                    ),
                )
            )
        return result

    def _iter_devices(self, payload: object) -> Iterator[dict[str, object]]:
        roots: object
        if isinstance(payload, dict):
            roots = payload.get("Devices") or payload.get("devices") or []
        else:
            roots = payload
        if not isinstance(roots, list):
            return
        for item in roots:
            yield from self._walk_device_tree(item)

    def _walk_device_tree(self, item: object) -> Iterator[dict[str, object]]:
        if not isinstance(item, dict):
            return
        yield item
        for key in ("Children", "children", "ChildDevices", "child_devices"):
            children = item.get(key)
            if isinstance(children, list):
                for child in children:
                    yield from self._walk_device_tree(child)

    def _first_release_with_version(self, device: dict[str, object]) -> dict[str, object] | None:
        releases = device.get("Releases")
        if not isinstance(releases, list):
            return None
        for release in releases:
            if not isinstance(release, dict):
                continue
            version = str(release.get("Version") or "").strip()
            if version:
                return release
        return None

    def _device_target_id(self, device: dict[str, object]) -> str:
        for key in ("DeviceId", "Id", "GUID", "Guid"):
            value = device.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
        guids = device.get("Guids") or device.get("GUIDs")
        if isinstance(guids, list):
            for guid in guids:
                if isinstance(guid, str) and guid.strip():
                    return guid.strip()
        return ""

    def _device_name(self, device: dict[str, object]) -> str:
        vendor = str(device.get("Vendor") or "").strip()
        name = str(device.get("Name") or "").strip()
        return " ".join(part for part in (vendor, name) if part) or self._device_target_id(device)

    def _format_bytes(self, value: object) -> str | None:
        if not isinstance(value, int) or value <= 0:
            return None
        units = ["B", "KiB", "MiB", "GiB"]
        size = float(value)
        unit_index = 0
        while size >= 1024 and unit_index < len(units) - 1:
            size /= 1024
            unit_index += 1
        return f"{size:.2f} {units[unit_index]}"

    def _restart_requirement(
        self,
        device: dict[str, object],
        release: dict[str, object],
    ) -> tuple[bool, bool]:
        flags = self._device_flags(device) | self._device_flags(release)
        needs_shutdown = bool(
            device.get("NeedsShutdown") is True
            or release.get("NeedsShutdown") is True
            or "needs-shutdown" in flags
        )
        needs_reboot = bool(
            needs_shutdown
            or device.get("NeedsReboot") is True
            or release.get("NeedsReboot") is True
            or "needs-reboot" in flags
        )
        return needs_reboot, needs_shutdown

    def _device_warnings(
        self,
        *,
        needs_reboot: bool,
        needs_shutdown: bool,
    ) -> list[str]:
        warnings: list[str] = []
        if needs_shutdown:
            warnings.append(
                QCoreApplication.translate(
                    "FirmwareUpdateService",
                    "A full shutdown is required after installing this firmware update.",
                )
            )
        elif needs_reboot:
            warnings.append(
                QCoreApplication.translate(
                    "FirmwareUpdateService",
                    "A reboot may be required after installing this firmware update.",
                )
            )
        return warnings

    def _device_flags(self, device: dict[str, object]) -> set[str]:
        raw_flags = device.get("Flags") or device.get("flags") or []
        if isinstance(raw_flags, list):
            values = raw_flags
        elif isinstance(raw_flags, str):
            values = re.split(r"[\s,|]+", raw_flags)
        else:
            return set()
        return {
            str(flag).strip().casefold().replace("_", "-")
            for flag in values
            if str(flag).strip()
        }
