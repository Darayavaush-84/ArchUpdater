from __future__ import annotations

import gzip
import html
import platform
import re
import shutil
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from PySide6.QtCore import QCoreApplication

from archupdater.domain.check_results import SourceCheckResult
from archupdater.domain.command_log import CheckLogEntry
from archupdater.domain.enums import FlatpakRefKind, UpdateSource
from archupdater.domain.package_metadata import FlatpakPackageMetadata
from archupdater.domain.packages import PackageReleaseNote, PackageUpdate
from archupdater.services.command_runner import CommandRunner
from archupdater.services.io_limits import read_limited
from archupdater.domain.package_size import format_size_diff


@dataclass(slots=True)
class FlatpakUpdateService:
    runner: CommandRunner
    _release_cache: dict[tuple[str, str, str], dict[str, list[PackageReleaseNote]]] = field(
        default_factory=dict,
        init=False,
    )

    APPSTREAM_TIMEOUT_SECONDS = 180
    QUERY_TIMEOUT_SECONDS = 120
    INSTALLED_LIST_TIMEOUT_SECONDS = 120
    MAX_RELEASE_NOTES = 5
    MAX_APPSTREAM_BYTES = 64 * 1024 * 1024

    def check_updates(self) -> SourceCheckResult:
        if shutil.which("flatpak") is None:
            return SourceCheckResult()

        self._release_cache.clear()
        result = SourceCheckResult()
        for scope in ("system", "user"):
            result.logs.extend(self._sync_appstream(scope, result.warnings))
            for ref_kind in (FlatpakRefKind.APP, FlatpakRefKind.RUNTIME):
                packages, logs, warnings = self._check_scope(scope, ref_kind)
                result.packages.extend(packages)
                result.logs.extend(logs)
                result.warnings.extend(warnings)
        return result

    def _sync_appstream(self, scope: str, warnings: list[str]) -> list[CheckLogEntry]:
        sync_log = self.runner.run(
            ["flatpak", "update", f"--{scope}", "--appstream", "--noninteractive"],
            timeout_seconds=self.APPSTREAM_TIMEOUT_SECONDS,
        )
        if sync_log.exit_code != 0:
            warnings.append(
                QCoreApplication.translate(
                    "FlatpakUpdateService",
                    "Failed to synchronize Flatpak metadata for the {scope} installation.",
                ).format(scope=scope)
            )
        return [sync_log]

    def _check_scope(
        self,
        scope: str,
        ref_kind: FlatpakRefKind,
    ) -> tuple[list[PackageUpdate], list[CheckLogEntry], list[str]]:
        logs = []
        warnings: list[str] = []
        kind_flag = "--app" if ref_kind is FlatpakRefKind.APP else "--runtime"
        query_log = self.runner.run(
            [
                "flatpak",
                "remote-ls",
                f"--{scope}",
                kind_flag,
                "--updates",
                "--columns=application,name,version,branch,description,origin,ref,download-size,installed-size,runtime",
            ],
            timeout_seconds=self.QUERY_TIMEOUT_SECONDS,
        )
        logs.append(query_log)
        if query_log.exit_code != 0:
            warnings.append(
                QCoreApplication.translate(
                    "FlatpakUpdateService",
                    "Failed to check Flatpak {kind} updates for the {scope} installation.",
                ).format(scope=scope, kind=self._kind_label(ref_kind))
            )
            return [], logs, warnings

        installed_log = self.runner.run(
            [
                "flatpak",
                "list",
                f"--{scope}",
                kind_flag,
                "--columns=application,name,version,installation,ref,size,origin,branch,runtime",
            ],
            timeout_seconds=self.INSTALLED_LIST_TIMEOUT_SECONDS,
        )
        logs.append(installed_log)
        installed_versions = (
            self._parse_installed_versions(installed_log.stdout, ref_kind)
            if installed_log.exit_code == 0
            else {}
        )

        packages: list[PackageUpdate] = []
        unparsed_lines: list[str] = []
        for raw_line in query_log.stdout.splitlines():
            columns = [entry.strip() for entry in raw_line.split("\t")]
            if len(columns) < 9:
                line = raw_line.strip()
                if line:
                    unparsed_lines.append(line)
                continue
            columns = (columns + [""])[:10]

            (
                application,
                display_name,
                new_version,
                branch,
                description,
                origin,
                ref,
                download_size,
                installed_size,
                runtime_name,
            ) = columns[:10]
            installed = self._installed_metadata_for_update(
                installed_versions,
                ref_kind,
                ref=ref,
                application=application,
                name=display_name,
            )
            current_version = str(installed.get("version") or "")
            installation_name = str(installed.get("installation") or scope)
            current_installed_size = str(installed.get("installed_size") or "")
            installed_origin = str(installed.get("origin") or "")
            installed_branch = str(installed.get("branch") or "")
            installed_runtime = str(installed.get("runtime") or "")
            if not ref:
                ref = application or display_name
            package_name = display_name or application or ref
            if ref_kind is FlatpakRefKind.RUNTIME and runtime_name:
                package_name = display_name or runtime_name or ref
            resolved_remote = origin or installed_origin or None
            resolved_branch = branch or installed_branch or None
            resolved_runtime = runtime_name or installed_runtime or None
            resolved_scope = installation_name or scope
            packages.append(
                PackageUpdate(
                    name=package_name,
                    current_version=current_version or QCoreApplication.translate("FlatpakUpdateService", "Installed"),
                    new_version=new_version or branch or QCoreApplication.translate("FlatpakUpdateService", "Latest"),
                    source=UpdateSource.FLATPAK,
                    source_metadata=FlatpakPackageMetadata(
                        ref=ref,
                        ref_kind=ref_kind,
                        installation_scope=resolved_scope,
                        repository=(
                            f"{resolved_remote} ({resolved_scope})"
                            if resolved_remote
                            else resolved_scope
                        ),
                        remote=resolved_remote,
                        branch=resolved_branch,
                        runtime=resolved_runtime,
                    ),
                    backend_id=ref,
                    description=description,
                    size=download_size or installed_size or None,
                    download_size=download_size or None,
                    installed_size=installed_size or None,
                    current_installed_size=current_installed_size or None,
                    size_diff=format_size_diff(installed_size, current_installed_size),
                    release_notes=self._release_notes(
                        scope=resolved_scope,
                        remote=resolved_remote,
                        ref=ref,
                        application=application,
                    ),
                )
            )
        if unparsed_lines:
            warnings.append(
                QCoreApplication.translate(
                    "FlatpakUpdateService",
                    "Some Flatpak update lines could not be parsed: {lines}",
                ).format(lines="; ".join(unparsed_lines[:3]))
            )
        return packages, logs, warnings

    def _release_notes(
        self,
        *,
        scope: str,
        remote: str | None,
        ref: str,
        application: str,
    ) -> list[PackageReleaseNote]:
        if not remote:
            return []
        arch = self._ref_arch(ref)
        cache_key = (scope, remote, arch)
        if cache_key not in self._release_cache:
            self._release_cache[cache_key] = self._load_release_notes(scope, remote, arch)
        notes_by_component = self._release_cache[cache_key]
        component_id = self._component_id(ref, application)
        return list(notes_by_component.get(component_id, []))[: self.MAX_RELEASE_NOTES]

    def _load_release_notes(
        self,
        scope: str,
        remote: str,
        arch: str,
    ) -> dict[str, list[PackageReleaseNote]]:
        appstream_path = self._appstream_path(scope, remote, arch)
        if appstream_path is None:
            return {}
        try:
            raw_xml = self._read_appstream(appstream_path)
            root = ET.fromstring(raw_xml)
        except (OSError, ET.ParseError):
            return {}

        notes: dict[str, list[PackageReleaseNote]] = {}
        components = list(root.findall(".//{*}component"))
        if root.tag.endswith("component"):
            components.insert(0, root)
        for component in components:
            component_id = self._component_child_text(component, "id")
            if not component_id:
                continue
            releases = component.findall("./{*}releases/{*}release")
            component_notes: list[PackageReleaseNote] = []
            for release in releases[: self.MAX_RELEASE_NOTES]:
                version = str(release.attrib.get("version") or "").strip()
                if not version:
                    continue
                description = self._release_description(release)
                component_notes.append(
                    PackageReleaseNote(
                        version=version,
                        date=self._release_date(release),
                        description=description,
                    )
                )
            if component_notes:
                notes[component_id] = component_notes
        return notes

    def _appstream_path(self, scope: str, remote: str, arch: str) -> Path | None:
        root = self._appstream_root(scope)
        if root is None:
            return None
        base = root / remote / arch / "active"
        for name in ("appstream.xml.gz", "appstream.xml"):
            path = base / name
            if path.exists():
                return path
        return None

    def _appstream_root(self, scope: str) -> Path | None:
        if scope == "user":
            return Path.home() / ".local/share/flatpak/appstream"
        if scope == "system":
            return Path("/var/lib/flatpak/appstream")
        return None

    def _read_appstream(self, path: Path) -> bytes:
        if path.suffix == ".gz":
            with gzip.open(path, "rb") as handle:
                return self._read_limited_file(handle)
        with path.open("rb") as handle:
            return self._read_limited_file(handle)

    def _read_limited_file(self, handle) -> bytes:  # noqa: ANN001
        try:
            return read_limited(handle, self.MAX_APPSTREAM_BYTES)
        except ValueError as exc:
            raise OSError("Flatpak AppStream metadata is too large.") from exc

    def _component_id(self, ref: str, application: str) -> str:
        if application:
            return application
        parts = ref.split("/")
        if len(parts) >= 2:
            return parts[1]
        return ref

    def _ref_arch(self, ref: str) -> str:
        parts = ref.split("/")
        if len(parts) >= 3 and parts[2]:
            return parts[2]
        return platform.machine()

    def _component_child_text(self, component: ET.Element, name: str) -> str:
        child = component.find(f"{{*}}{name}")
        return (child.text or "").strip() if child is not None else ""

    def _release_description(self, release: ET.Element) -> str:
        description = release.find("{*}description")
        if description is None:
            return ""
        parts = [text.strip() for text in description.itertext() if text.strip()]
        text = html.unescape(" ".join(parts))
        return re.sub(r"\s+", " ", text).strip()

    def _release_date(self, release: ET.Element) -> str | None:
        date = str(release.attrib.get("date") or "").strip()
        if date:
            return date
        timestamp_text = str(release.attrib.get("timestamp") or "").strip()
        try:
            timestamp = int(timestamp_text)
        except ValueError:
            return None
        if timestamp <= 0:
            return None
        try:
            return datetime.fromtimestamp(timestamp, tz=timezone.utc).date().isoformat()
        except (OverflowError, OSError, ValueError):
            return None

    def _parse_installed_versions(
        self,
        raw_output: str,
        ref_kind: FlatpakRefKind,
    ) -> dict[str, dict[str, str]]:
        installed: dict[str, dict[str, str]] = {}
        for raw_line in raw_output.splitlines():
            (
                application,
                name,
                version,
                installation,
                ref,
                installed_size,
                origin,
                branch,
                runtime,
            ) = (raw_line.split("\t") + ["", "", "", "", "", "", "", "", ""])[:9]
            application = application.strip()
            name = name.strip()
            ref = ref.strip()
            lookup_keys = self._installed_lookup_keys(
                ref_kind,
                ref=ref,
                application=application,
                name=name,
            )
            if not lookup_keys:
                continue
            metadata = {
                "version": version.strip(),
                "installation": installation.strip() or "system",
                "installed_size": installed_size.strip(),
                "origin": origin.strip(),
                "branch": branch.strip(),
                "runtime": runtime.strip(),
            }
            for lookup_key in lookup_keys:
                installed.setdefault(lookup_key, metadata)
        return installed

    def _installed_metadata_for_update(
        self,
        installed_versions: dict[str, dict[str, str]],
        ref_kind: FlatpakRefKind,
        *,
        ref: str,
        application: str,
        name: str,
    ) -> dict[str, str]:
        for lookup_key in self._installed_lookup_keys(
            ref_kind,
            ref=ref,
            application=application,
            name=name,
        ):
            if lookup_key in installed_versions:
                return installed_versions[lookup_key]
        return {}

    def _installed_lookup_keys(
        self,
        ref_kind: FlatpakRefKind,
        *,
        ref: str,
        application: str,
        name: str,
    ) -> list[str]:
        keys = self._ref_lookup_keys(ref_kind, ref)
        keys.extend(key.strip() for key in (application, name) if key.strip())
        return list(dict.fromkeys(keys))

    def _ref_lookup_keys(self, ref_kind: FlatpakRefKind, ref: str) -> list[str]:
        normalized_ref = ref.strip()
        if not normalized_ref:
            return []

        keys = [normalized_ref]
        unprefixed_ref = normalized_ref
        for prefix in ("app/", "runtime/"):
            if normalized_ref.startswith(prefix):
                unprefixed_ref = normalized_ref[len(prefix) :]
                break

        if unprefixed_ref != normalized_ref:
            keys.append(unprefixed_ref)

        expected_prefix = f"{ref_kind.value}/"
        prefixed_ref = (
            normalized_ref
            if normalized_ref.startswith(expected_prefix)
            else f"{expected_prefix}{unprefixed_ref}"
        )
        keys.append(prefixed_ref)
        return list(dict.fromkeys(keys))

    def _kind_label(self, ref_kind: FlatpakRefKind) -> str:
        if ref_kind is FlatpakRefKind.RUNTIME:
            return QCoreApplication.translate("FlatpakUpdateService", "runtime")
        return QCoreApplication.translate("FlatpakUpdateService", "app")
