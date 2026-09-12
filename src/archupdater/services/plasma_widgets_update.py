from __future__ import annotations

import tempfile
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from packaging.version import InvalidVersion, Version
from PySide6.QtCore import QCoreApplication

from archupdater import __version__
from archupdater.domain.command_log import CommandLogEntry
from archupdater.domain.update_plan import UpdatePlanItem
from archupdater.services.command_runner import CommandRunner
from archupdater.services.io_limits import read_limited
from archupdater.services.plasma_widget_archive import PlasmaWidgetArchiveHandler
from archupdater.services.plasma_widgets_store import (
    PlasmaWidgetUserVisibleError,
    PlasmaWidgetsStoreClient,
)
from archupdater.services.widget_matching import MemoryWidgetMatchCache, WidgetMatchCache

LogCallback = Callable[[str], None]
DownloadCallback = Callable[[str], bytes]


@dataclass(frozen=True, slots=True)
class PlasmaWidgetUpdateResult:
    success: bool
    message: str
    changed: bool = False
    incomplete: bool = False


@dataclass(slots=True)
class PlasmaWidgetsUpdateService:
    runner: CommandRunner = field(
        default_factory=lambda: CommandRunner(default_env={"LC_ALL": "C.UTF-8"})
    )
    store_client: PlasmaWidgetsStoreClient = field(default_factory=PlasmaWidgetsStoreClient)
    match_cache: WidgetMatchCache = field(default_factory=MemoryWidgetMatchCache)
    downloader: DownloadCallback | None = None
    KPACKAGE_UPDATE_TIMEOUT_SECONDS = 180
    DOWNLOAD_CHUNK_BYTES = 64 * 1024
    MAX_DOWNLOAD_BYTES = 64 * 1024 * 1024
    MAX_ARCHIVE_ENTRIES = 2000
    MAX_EXTRACTED_BYTES = 256 * 1024 * 1024

    def update_widgets(
        self,
        targets: list[UpdatePlanItem],
        *,
        log_callback: LogCallback,
    ) -> PlasmaWidgetUpdateResult:
        updated_names: list[str] = []
        failed_names: list[str] = []

        for target in targets:
            target_name = target.package_name or target.target_id
            try:
                self._update_single_widget(target, log_callback=log_callback)
            except Exception as exc:
                failed_names.append(target_name)
                log_callback(
                    self._translate("KDE Store add-on update failed for {name}: {error}").format(
                        name=target_name, error=self._user_message(exc)
                    )
                )
                technical_message = self._technical_message(exc)
                if technical_message and technical_message != self._user_message(exc):
                    log_callback(
                        self._translate("Details: {details}").format(details=technical_message)
                    )
                continue
            updated_names.append(target_name)

        if not updated_names:
            return PlasmaWidgetUpdateResult(
                success=False,
                message=self._translate("KDE Store add-on update failed."),
                changed=False,
            )

        if failed_names:
            return PlasmaWidgetUpdateResult(
                success=False,
                message=self._translate(
                    "Updated {updated} KDE Store add-ons. Failed: {failed}."
                ).format(
                    updated=len(updated_names),
                    failed=", ".join(failed_names),
                ),
                changed=True,
                incomplete=True,
            )

        return PlasmaWidgetUpdateResult(
            success=True,
            message=self._translate(
                "KDE Store add-on updates completed successfully. Some add-ons may require restarting plasmashell."
            ),
            changed=True,
        )

    def _update_single_widget(
        self,
        target: UpdatePlanItem,
        *,
        log_callback: LogCallback,
    ) -> None:
        log_callback(
            self._translate("Fetching KDE Store metadata for {name}...").format(
                name=target.package_name or target.target_id
            )
        )
        details = self.store_client.fetch_details(target.target_id)
        if details.content_id != target.target_id:
            raise self._incompatible_archive_error(
                "KDE Store content id does not match the selected update."
            )
        expected_version = str(target.expected_version or "").strip()
        if not expected_version:
            raise self._incompatible_archive_error(
                "The selected KDE Store update has no expected version."
            )
        if not self._versions_match(details.version, expected_version):
            raise self._incompatible_archive_error(
                "KDE Store version changed after the update was selected."
            )
        download = self.store_client.choose_download(details)
        effective_kind = str(target.package_kind or "").strip()
        if not effective_kind:
            raise self._incompatible_archive_error(
                "The selected KDE Store update has no package type."
            )
        if details.type_label and details.type_label != target.package_kind:
            raise self._incompatible_archive_error(
                "KDE Store add-on type does not match the locally installed package type."
            )
        log_callback(self._translate("KDE Store type: {kind}.").format(kind=effective_kind))
        log_callback(
            self._translate("Selected download: {file}.").format(
                file=download.name or download.url.rsplit("/", 1)[-1] or download.url
            )
        )

        with tempfile.TemporaryDirectory(prefix="archupdater-widget-") as temp_dir_name:
            temp_dir = Path(temp_dir_name)
            archive_handler = self._archive_handler()
            archive_name = archive_handler.safe_download_filename(download.name)
            archive_path = temp_dir / archive_name
            extract_dir = temp_dir / "extracted"
            extract_dir.mkdir(parents=True, exist_ok=True)

            log_callback(
                self._translate("Downloading {name} {version}...").format(
                    name=target.package_name or target.target_id,
                    version=details.version,
                )
            )
            archive_path.write_bytes(self._download(download.url))

            archive_handler.extract_archive(archive_path, extract_dir)
            log_callback(self._translate("Archive extracted successfully."))
            metadata_path = archive_handler.find_metadata_path(
                extract_dir,
                plugin_id=target.plugin_id,
                package_kind=target.package_kind,
                expected_version=expected_version or details.version,
            )
            package_root = metadata_path.parent
            log_callback(
                self._translate("Installing from extracted package: {path}").format(
                    path=package_root.name
                )
            )
            command = [
                "kpackagetool6",
                "-t",
                effective_kind,
                "-u",
                str(package_root),
            ]
            log_callback(f"$ {' '.join(command)}")
            log_entry = self.runner.run(
                command,
                timeout_seconds=self.KPACKAGE_UPDATE_TIMEOUT_SECONDS,
            )
            self._emit_log_entry(log_entry, log_callback)
            if log_entry.exit_code != 0:
                raise OSError(
                    self._translate("kpackagetool6 exited with code {code}.").format(
                        code=log_entry.exit_code
                    )
                )
            self.match_cache.remember(
                effective_kind,
                target.plugin_id,
                details.content_id,
            )

    def _download(self, url: str) -> bytes:
        safe_url = self._validated_download_url(url)
        if self.downloader is not None:
            try:
                return self._validate_download_size(self.downloader(safe_url))
            except PlasmaWidgetUserVisibleError:
                raise
            except Exception as exc:  # pragma: no cover - test doubles may raise arbitrary errors
                raise PlasmaWidgetUserVisibleError(
                    self._translate("KDE Store is temporarily unavailable. Try again later."),
                    str(exc),
                ) from exc

        request = urllib.request.Request(
            safe_url,
            headers={
                "User-Agent": f"ArchUpdater/{__version__}",
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=60) as response:
                final_url = str(getattr(response, "geturl", lambda: safe_url)() or "")
                self._validated_download_url(final_url)
                content_length = response.headers.get("Content-Length")
                size = 0
                if content_length:
                    try:
                        size = int(content_length)
                    except ValueError:
                        size = 0
                if size > self.MAX_DOWNLOAD_BYTES:
                    raise self._incompatible_archive_error(
                        f"Download is larger than {self.MAX_DOWNLOAD_BYTES} bytes."
                    )
                return self._read_limited_response(response)
        except PlasmaWidgetUserVisibleError:
            raise
        except urllib.error.HTTPError as exc:
            if exc.code == 429:
                raise PlasmaWidgetUserVisibleError(
                    self._translate(
                        "KDE Store is temporarily limiting requests. Try again in a few minutes."
                    ),
                    f"HTTP {exc.code} while downloading widget archive.",
                ) from exc
            raise PlasmaWidgetUserVisibleError(
                self._translate("KDE Store is temporarily unavailable. Try again later."),
                f"HTTP {exc.code} while downloading widget archive.",
            ) from exc
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise PlasmaWidgetUserVisibleError(
                self._translate("KDE Store is temporarily unavailable. Try again later."),
                f"Failed to download widget archive: {exc}",
            ) from exc

    def _validated_download_url(self, url: str) -> str:
        text = str(url or "").strip()
        parsed = urllib.parse.urlsplit(text)
        if parsed.scheme.lower() != "https" or not parsed.netloc:
            raise self._incompatible_archive_error(
                "KDE Store download URL must use HTTPS."
            )
        return text

    def _versions_match(self, first: object, second: object) -> bool:
        first_text = str(first or "").strip().removeprefix("v").removeprefix("V").strip()
        second_text = str(second or "").strip().removeprefix("v").removeprefix("V").strip()
        if not first_text or not second_text:
            return first_text == second_text
        try:
            return Version(first_text) == Version(second_text)
        except InvalidVersion:
            return first_text == second_text

    def _read_limited_response(self, response) -> bytes:  # noqa: ANN001
        try:
            return read_limited(
                response,
                self.MAX_DOWNLOAD_BYTES,
                chunk_size=self.DOWNLOAD_CHUNK_BYTES,
            )
        except ValueError as exc:
            raise self._incompatible_archive_error(
                f"Download is larger than {self.MAX_DOWNLOAD_BYTES} bytes."
            ) from exc

    def _validate_download_size(self, payload: bytes | bytearray) -> bytes:
        if len(payload) > self.MAX_DOWNLOAD_BYTES:
            raise self._incompatible_archive_error(
                f"Download is larger than {self.MAX_DOWNLOAD_BYTES} bytes."
            )
        return bytes(payload)

    def _incompatible_archive_error(self, technical_message: str) -> PlasmaWidgetUserVisibleError:
        return self._archive_handler().incompatible_archive_error(technical_message)

    def _archive_handler(self) -> PlasmaWidgetArchiveHandler:
        return PlasmaWidgetArchiveHandler(
            translate=self._translate,
            max_archive_entries=self.MAX_ARCHIVE_ENTRIES,
            max_extracted_bytes=self.MAX_EXTRACTED_BYTES,
        )

    def _emit_log_entry(self, log_entry: CommandLogEntry, log_callback: LogCallback) -> None:
        if log_entry.stdout.strip():
            for line in log_entry.stdout.splitlines():
                text = line.strip()
                if text:
                    log_callback(text)
        if log_entry.stderr.strip():
            for line in log_entry.stderr.splitlines():
                text = line.strip()
                if text:
                    log_callback(text)

    def _translate(self, text: str) -> str:
        return QCoreApplication.translate("PlasmaWidgetsUpdateService", text)

    def _user_message(self, exc: Exception) -> str:
        if isinstance(exc, PlasmaWidgetUserVisibleError):
            return exc.user_message
        details = str(exc).casefold()
        if "429" in details or "too many api requests" in details:
            return self._translate(
                "KDE Store is temporarily limiting requests. Try again in a few minutes."
            )
        if any(
            token in details
            for token in ("timed out", "connection", "network", "urlopen", "unavailable")
        ):
            return self._translate("KDE Store is temporarily unavailable. Try again later.")
        return str(exc) or self._translate("KDE Store add-on update failed.")

    def _technical_message(self, exc: Exception) -> str:
        if isinstance(exc, PlasmaWidgetUserVisibleError):
            return exc.technical_message
        return str(exc)
