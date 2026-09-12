from __future__ import annotations

import json
import os
import stat
import struct
import tarfile
import zipfile
import unicodedata
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from packaging.version import InvalidVersion, Version

from archupdater.services.plasma_widgets_store import PlasmaWidgetUserVisibleError


Translate = Callable[[str], str]


@dataclass(slots=True)
class PlasmaWidgetArchiveHandler:
    translate: Translate
    max_archive_entries: int
    max_extracted_bytes: int
    MAX_METADATA_BYTES = 1024 * 1024
    COPY_CHUNK_BYTES = 64 * 1024

    def safe_download_filename(self, value: str | None) -> str:
        raw_name = str(value or "").replace("\\", "/").strip()
        filename = Path(raw_name).name
        if (
            not filename
            or filename in {".", ".."}
            or len(filename) > 255
            or any(
                unicodedata.category(character) in {"Cc", "Cf", "Cs"}
                for character in filename
            )
        ):
            return "download.archive"
        if Path(filename).is_absolute() or ".." in Path(filename).parts:
            return "download.archive"
        return filename

    def extract_archive(self, archive_path: Path, extract_dir: Path) -> None:
        if zipfile.is_zipfile(archive_path):
            self._validate_zip_directory_entry_count(archive_path)
            with zipfile.ZipFile(archive_path) as archive:
                self._extract_zip_safely(archive, extract_dir)
            return
        if tarfile.is_tarfile(archive_path):
            with tarfile.open(archive_path) as archive:
                self._extract_tar_safely(archive, extract_dir)
            return
        raise PlasmaWidgetUserVisibleError(
            self._t("The downloaded KDE Store add-on package is incomplete or incompatible."),
            self._t("The downloaded KDE Store add-on archive could not be extracted."),
        )

    def find_metadata_path(
        self,
        extract_dir: Path,
        *,
        plugin_id: str | None,
        package_kind: str,
        expected_version: str | None = None,
    ) -> Path:
        candidates = sorted(extract_dir.rglob("metadata.json"))
        if not candidates:
            raise PlasmaWidgetUserVisibleError(
                self._t("The downloaded KDE Store add-on package is incomplete or incompatible."),
                self._t(
                    "The downloaded KDE Store add-on archive does not contain metadata.json."
                ),
            )

        if plugin_id:
            for candidate in candidates:
                payload = self.read_json(candidate)
                plugin = payload.get("KPlugin")
                if isinstance(plugin, dict) and str(plugin.get("Id") or "").strip() == plugin_id:
                    self._validate_metadata(payload, package_kind, expected_version)
                    return candidate
            raise PlasmaWidgetUserVisibleError(
                self._t("The downloaded KDE Store add-on package is incomplete or incompatible."),
                self._t(
                    "The downloaded KDE Store add-on metadata does not match the installed add-on."
                ),
            )

        if len(candidates) == 1:
            payload = self.read_json(candidates[0])
            self._validate_metadata(payload, package_kind, expected_version)
            return candidates[0]

        kind_matches: list[Path] = []
        if package_kind:
            for candidate in candidates:
                payload = self.read_json(candidate)
                if str(payload.get("KPackageStructure") or "").strip() == package_kind:
                    kind_matches.append(candidate)
            if len(kind_matches) == 1:
                self._validate_metadata(
                    self.read_json(kind_matches[0]),
                    package_kind,
                    expected_version,
                )
                return kind_matches[0]

        raise PlasmaWidgetUserVisibleError(
            self._t("The downloaded KDE Store add-on package is incomplete or incompatible."),
            "Archive contains multiple metadata.json files and ArchUpdater could not choose one safely.",
        )

    def read_json(self, path: Path) -> dict[str, object]:
        try:
            if path.stat().st_size > self.MAX_METADATA_BYTES:
                raise ValueError("metadata.json exceeds the safety limit")
            payload = json.loads(path.read_bytes().decode("utf-8"))
        except (OSError, UnicodeDecodeError, ValueError, json.JSONDecodeError) as exc:
            raise PlasmaWidgetUserVisibleError(
                self._t("The downloaded KDE Store add-on package is incomplete or incompatible."),
                self._t("Failed to read KDE Store add-on metadata from {path}.").format(
                    path=path.name
                ),
            ) from exc
        if not isinstance(payload, dict):
            raise PlasmaWidgetUserVisibleError(
                self._t("The downloaded KDE Store add-on package is incomplete or incompatible."),
                self._t("The downloaded KDE Store add-on metadata is invalid."),
            )
        return payload

    def _validate_metadata(
        self,
        payload: dict[str, object],
        package_kind: str,
        expected_version: str | None,
    ) -> None:
        plugin = payload.get("KPlugin")
        if not isinstance(plugin, dict):
            raise PlasmaWidgetUserVisibleError(
                self._t("The downloaded KDE Store add-on package is incomplete or incompatible."),
                self._t("The downloaded KDE Store add-on metadata is invalid."),
            )

        expected_kind = str(package_kind or "").strip()
        actual_kind = str(payload.get("KPackageStructure") or "").strip()
        if expected_kind and actual_kind != expected_kind:
            raise PlasmaWidgetUserVisibleError(
                self._t("The downloaded KDE Store add-on package is incomplete or incompatible."),
                self._t(
                    "The downloaded KDE Store add-on type does not match the installed add-on."
                ),
            )

        expected = self._normalize_version(expected_version)
        actual = self._normalize_version(plugin.get("Version"))
        if expected and not self._versions_match(actual, expected):
            raise PlasmaWidgetUserVisibleError(
                self._t("The downloaded KDE Store add-on package is incomplete or incompatible."),
                self._t(
                    "The downloaded KDE Store add-on version does not match the advertised update."
                ),
            )

    def _normalize_version(self, value: object) -> str:
        return str(value or "").strip().removeprefix("v").removeprefix("V").strip()

    def _versions_match(self, first: str, second: str) -> bool:
        try:
            return Version(first) == Version(second)
        except InvalidVersion:
            return first == second

    def incompatible_archive_error(self, technical_message: str) -> PlasmaWidgetUserVisibleError:
        return PlasmaWidgetUserVisibleError(
            self._t("The downloaded KDE Store add-on package is incomplete or incompatible."),
            technical_message,
        )

    def _extract_zip_safely(
        self,
        archive: zipfile.ZipFile,
        extract_dir: Path,
    ) -> None:
        total_size = 0
        directory_modes: dict[Path, int] = {}
        extracted_targets: set[Path] = set()
        for index, info in enumerate(archive.filelist, start=1):
            self._validate_archive_entry_count(index)
            target_path = self._validated_archive_target(extract_dir, info.filename)
            self._register_archive_target(target_path, extracted_targets)
            mode = info.external_attr >> 16
            if stat.S_ISLNK(mode):
                raise self.incompatible_archive_error("Archive contains a symbolic link.")
            file_type = stat.S_IFMT(mode)
            if info.create_system == 3 and file_type not in {0, stat.S_IFREG, stat.S_IFDIR}:
                raise self.incompatible_archive_error("Archive contains a special file.")
            if info.is_dir():
                target_path.mkdir(parents=True, exist_ok=True)
                if info.create_system == 3:
                    directory_modes[target_path] = mode
                continue

            self._validate_extracted_size(total_size + max(0, info.file_size))
            target_path.parent.mkdir(parents=True, exist_ok=True)
            with archive.open(info) as source, target_path.open("xb") as destination:
                total_size = self._copy_member_limited(source, destination, total_size)
            if info.create_system == 3:
                self._restore_safe_mode(target_path, mode)
        self._restore_directory_modes(directory_modes)

    def _extract_tar_safely(
        self,
        archive: tarfile.TarFile,
        extract_dir: Path,
    ) -> None:
        total_size = 0
        directory_modes: dict[Path, int] = {}
        extracted_targets: set[Path] = set()
        for index, member in enumerate(archive, start=1):
            self._validate_archive_entry_count(index)
            target_path = self._validated_archive_target(extract_dir, member.name)
            self._register_archive_target(target_path, extracted_targets)
            if member.issym() or member.islnk():
                raise self.incompatible_archive_error("Archive contains a link.")
            if member.isdir():
                target_path.mkdir(parents=True, exist_ok=True)
                directory_modes[target_path] = member.mode
                continue
            if not member.isfile():
                raise self.incompatible_archive_error("Archive contains a special file.")

            self._validate_extracted_size(total_size + max(0, member.size))
            target_path.parent.mkdir(parents=True, exist_ok=True)
            source = archive.extractfile(member)
            if source is None:
                raise self.incompatible_archive_error("Archive member could not be read.")
            with source, target_path.open("xb") as destination:
                total_size = self._copy_member_limited(source, destination, total_size)
            self._restore_safe_mode(target_path, member.mode)
        self._restore_directory_modes(directory_modes)

    def _validate_zip_directory_entry_count(self, archive_path: Path) -> None:
        # The stdlib builds every ZipInfo while opening a ZIP. Inspect the small
        # end-of-central-directory record first so a file with millions of empty
        # members is rejected before those objects are allocated.
        max_tail_bytes = 22 + 0xFFFF
        with archive_path.open("rb") as handle:
            handle.seek(0, 2)
            file_size = handle.tell()
            handle.seek(max(0, file_size - max_tail_bytes))
            tail = handle.read(max_tail_bytes)
        marker = b"PK\x05\x06"
        offset = tail.rfind(marker)
        if offset < 0 or len(tail) - offset < 22:
            raise self.incompatible_archive_error("ZIP central directory is incomplete.")
        (
            _signature,
            disk_number,
            central_disk,
            entries_on_disk,
            total_entries,
            central_size,
            central_offset,
            comment_size,
        ) = struct.unpack_from("<4s4H2LH", tail, offset)
        if offset + 22 + comment_size != len(tail):
            raise self.incompatible_archive_error("ZIP end record is inconsistent.")
        if disk_number != 0 or central_disk != 0 or entries_on_disk != total_entries:
            raise self.incompatible_archive_error("Multi-disk ZIP archives are not supported.")
        if total_entries == 0xFFFF:
            raise self.incompatible_archive_error("ZIP64 archives are not supported.")
        self._validate_archive_entry_count(total_entries)
        eocd_offset = file_size - len(tail) + offset
        if central_offset + central_size != eocd_offset:
            raise self.incompatible_archive_error("ZIP central directory bounds are invalid.")
        self._validate_zip_central_directory(
            archive_path,
            central_offset=central_offset,
            central_size=central_size,
            total_entries=total_entries,
        )

    def _validate_zip_central_directory(
        self,
        archive_path: Path,
        *,
        central_offset: int,
        central_size: int,
        total_entries: int,
    ) -> None:
        remaining = central_size
        with archive_path.open("rb") as handle:
            handle.seek(central_offset)
            for _index in range(total_entries):
                header = handle.read(46)
                if len(header) != 46 or header[:4] != b"PK\x01\x02":
                    raise self.incompatible_archive_error(
                        "ZIP central directory entry is invalid."
                    )
                filename_size, extra_size, entry_comment_size = struct.unpack_from(
                    "<3H", header, 28
                )
                record_size = 46 + filename_size + extra_size + entry_comment_size
                if record_size > remaining:
                    raise self.incompatible_archive_error(
                        "ZIP central directory entry exceeds its declared bounds."
                    )
                handle.seek(record_size - 46, 1)
                remaining -= record_size
        if remaining != 0:
            raise self.incompatible_archive_error(
                "ZIP central directory contains undeclared entries."
            )

    def _restore_safe_mode(self, path: Path, archive_mode: int) -> None:
        safe_mode = stat.S_IMODE(archive_mode) & 0o755
        safe_mode |= 0o500 if path.is_dir() else 0o400
        path.chmod(safe_mode)

    def _restore_directory_modes(self, directory_modes: dict[Path, int]) -> None:
        for path in sorted(directory_modes, key=lambda item: len(item.parts), reverse=True):
            self._restore_safe_mode(path, directory_modes[path])

    def _validated_archive_target(self, extract_dir: Path, member_name: str) -> Path:
        normalized_name = member_name.replace("\\", "/")
        if not normalized_name or normalized_name.endswith("/.."):
            raise self.incompatible_archive_error("Archive member path is invalid.")

        relative_path = Path(normalized_name)
        if relative_path.is_absolute() or ".." in relative_path.parts:
            raise self.incompatible_archive_error(
                "Archive member path escapes the target directory."
            )

        extract_root = extract_dir.resolve()
        target_path = (extract_dir / relative_path).resolve()
        if os.path.commonpath([str(extract_root), str(target_path)]) != str(extract_root):
            raise self.incompatible_archive_error(
                "Archive member path escapes the target directory."
            )
        return target_path

    def _register_archive_target(
        self,
        target_path: Path,
        extracted_targets: set[Path],
    ) -> None:
        if target_path in extracted_targets:
            raise self.incompatible_archive_error("Archive contains duplicate member paths.")
        extracted_targets.add(target_path)

    def _copy_member_limited(self, source, destination, total_size: int) -> int:  # noqa: ANN001
        while chunk := source.read(self.COPY_CHUNK_BYTES):
            total_size += len(chunk)
            self._validate_extracted_size(total_size)
            destination.write(chunk)
        return total_size

    def _validate_archive_entry_count(self, count: int) -> None:
        if count > self.max_archive_entries:
            raise self.incompatible_archive_error(
                f"Archive contains more than {self.max_archive_entries} entries."
            )

    def _validate_extracted_size(self, total_size: int) -> None:
        if total_size > self.max_extracted_bytes:
            raise self.incompatible_archive_error(
                f"Archive expands to more than {self.max_extracted_bytes} bytes."
            )

    def _t(self, text: str) -> str:
        return self.translate(text)
