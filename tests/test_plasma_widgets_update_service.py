from __future__ import annotations

import io
import json
import tarfile
import sys
import tempfile
import zipfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from support.commands import CommandResponse, FakeCommandRunner
from archupdater.domain.enums import UpdateSource
from archupdater.domain.update_plan import UpdatePlanItem
from archupdater.services.plasma_widgets_store import StoreWidgetDetail, StoreWidgetDownload
from archupdater.services.plasma_widgets_update import PlasmaWidgetsUpdateService




class _StoreClient:
    def __init__(self, detail: StoreWidgetDetail) -> None:
        self.detail = detail
        self.requested_ids: list[str] = []

    def fetch_details(self, content_id: str) -> StoreWidgetDetail:
        self.requested_ids.append(content_id)
        return self.detail

    def choose_download(self, detail: StoreWidgetDetail) -> StoreWidgetDownload:
        return detail.downloads[0]


class _FlakyStoreClient(_StoreClient):
    def fetch_details(self, content_id: str) -> StoreWidgetDetail:
        self.requested_ids.append(content_id)
        if content_id == "6666":
            raise OSError("store unavailable")
        return self.detail


class _CacheStub:
    def __init__(self) -> None:
        self.saved: list[tuple[str, str | None, str]] = []

    def remember(self, package_kind: str, plugin_id: str | None, content_id: str) -> None:
        self.saved.append((package_kind, plugin_id, content_id))


class _ResponseWithoutLength:
    headers: dict[str, str] = {}

    def __init__(self, payload: bytes, *, final_url: str = "https://example.test/widget") -> None:
        self._payload = io.BytesIO(payload)
        self._final_url = final_url

    def __enter__(self) -> _ResponseWithoutLength:
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def read(self, size: int = -1) -> bytes:
        return self._payload.read(size)

    def geturl(self) -> str:
        return self._final_url


class PlasmaWidgetsUpdateServiceTests(unittest.TestCase):
    def _make_archive(
        self,
        *,
        plugin_id: str,
        version: str,
        package_kind: str = "Plasma/Applet",
    ) -> bytes:
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w") as archive:
            archive.writestr(
                f"{plugin_id}/metadata.json",
                json.dumps(
                    {
                        "KPlugin": {
                            "Id": plugin_id,
                            "Name": "Example Widget",
                            "Version": version,
                        },
                        "KPackageStructure": package_kind,
                    }
                ),
            )
        return buffer.getvalue()

    def _make_tar_archive(self, filename: str, content: bytes) -> bytes:
        buffer = io.BytesIO()
        with tarfile.open(fileobj=buffer, mode="w:gz") as archive:
            info = tarfile.TarInfo(filename)
            info.size = len(content)
            archive.addfile(info, io.BytesIO(content))
        return buffer.getvalue()

    def test_update_widgets_validates_archive_and_runs_kpackagetool(self) -> None:
        detail = StoreWidgetDetail(
            content_id="5555",
            name="Example Widget",
            version="1.3.0",
            summary="Store summary",
            type_label="Plasma/Applet",
            author="example-author",
            detail_url="https://store.kde.org/p/5555",
            downloads=[
                StoreWidgetDownload(
                    url="https://example.test/widget", name="widget.plasmoid", version="1.3.0"
                )
            ],
        )
        store_client = _StoreClient(detail)
        runner = FakeCommandRunner([CommandResponse(stdout="updated\n")])
        cache = _CacheStub()
        service = PlasmaWidgetsUpdateService(
            runner=runner,  # type: ignore[arg-type]
            store_client=store_client,
            match_cache=cache,  # type: ignore[arg-type]
            downloader=lambda _url: self._make_archive(
                plugin_id="com.example.widget", version="1.3.0"
            ),
        )
        messages: list[str] = []

        result = service.update_widgets(
            [
                UpdatePlanItem(
                    source=UpdateSource.PLASMA_WIDGET,
                    target_id="5555",
                    package_name="Example Widget",
                    package_kind="Plasma/Applet",
                    plugin_id="com.example.widget",
                    expected_version="1.3.0",
                )
            ],
            log_callback=messages.append,
        )

        self.assertTrue(result.success)
        self.assertIn("completed successfully", result.message)
        self.assertEqual(store_client.requested_ids, ["5555"])
        self.assertEqual(runner.commands[0][:4], ["kpackagetool6", "-t", "Plasma/Applet", "-u"])
        self.assertTrue(any("Downloading Example Widget 1.3.0" in message for message in messages))
        self.assertTrue(any("KDE Store type: Plasma/Applet." in message for message in messages))
        self.assertTrue(
            any("Selected download: widget.plasmoid." in message for message in messages)
        )
        self.assertTrue(any("Archive extracted successfully." in message for message in messages))
        self.assertEqual(cache.saved, [("Plasma/Applet", "com.example.widget", "5555")])

    def test_update_widgets_reports_partial_success(self) -> None:
        detail = StoreWidgetDetail(
            content_id="5555",
            name="Example Widget",
            version="1.3.0",
            summary="Store summary",
            type_label="Plasma/Applet",
            author="example-author",
            detail_url="https://store.kde.org/p/5555",
            downloads=[
                StoreWidgetDownload(
                    url="https://example.test/widget", name="widget.plasmoid", version="1.3.0"
                )
            ],
        )
        runner = FakeCommandRunner([CommandResponse(stdout="updated\n")])
        service = PlasmaWidgetsUpdateService(
            runner=runner,  # type: ignore[arg-type]
            store_client=_FlakyStoreClient(detail),
            downloader=lambda _url: self._make_archive(
                plugin_id="com.example.widget",
                version="1.3.0",
            ),
        )
        messages: list[str] = []

        result = service.update_widgets(
            [
                UpdatePlanItem(
                    source=UpdateSource.PLASMA_WIDGET,
                    target_id="5555",
                    package_name="Example Widget",
                    package_kind="Plasma/Applet",
                    plugin_id="com.example.widget",
                    expected_version="1.3.0",
                ),
                UpdatePlanItem(
                    source=UpdateSource.PLASMA_WIDGET,
                    target_id="6666",
                    package_name="Broken Widget",
                    package_kind="Plasma/Applet",
                    plugin_id="com.example.missing",
                    expected_version="1.3.0",
                ),
            ],
            log_callback=messages.append,
        )

        self.assertFalse(result.success)
        self.assertIn("Failed: Broken Widget", result.message)
        self.assertTrue(any("Broken Widget" in message for message in messages))
        self.assertTrue(
            any(
                "KDE Store is temporarily unavailable. Try again later." in message
                for message in messages
            )
        )

    def test_update_widgets_rejects_store_detail_type_mismatch(self) -> None:
        detail = StoreWidgetDetail(
            content_id="5555",
            name="Example Widget",
            version="1.3.0",
            summary="Store summary",
            type_label="KWin/Script",
            author="example-author",
            detail_url="https://store.kde.org/p/5555",
            downloads=[
                StoreWidgetDownload(
                    url="https://example.test/widget",
                    name="widget.plasmoid",
                    version="1.3.0",
                )
            ],
        )
        runner = FakeCommandRunner([CommandResponse(stdout="updated\n")])
        service = PlasmaWidgetsUpdateService(
            runner=runner,  # type: ignore[arg-type]
            store_client=_StoreClient(detail),
            downloader=lambda _url: self._make_archive(
                plugin_id="com.example.widget",
                version="1.0.0",
                package_kind="Plasma/Applet",
            ),
        )

        result = service.update_widgets(
            [
                UpdatePlanItem(
                    source=UpdateSource.PLASMA_WIDGET,
                    target_id="5555",
                    package_name="Example Widget",
                    package_kind="Plasma/Applet",
                    plugin_id="com.example.widget",
                    expected_version="1.3.0",
                )
            ],
            log_callback=lambda _message: None,
        )

        self.assertFalse(result.success)
        self.assertEqual(runner.commands, [])

    def test_update_widgets_rejects_store_version_that_changed_after_selection(self) -> None:
        detail = StoreWidgetDetail(
            content_id="5555",
            name="Example Widget",
            version="1.4.0",
            summary="Store summary",
            type_label="Plasma/Applet",
            author="example-author",
            detail_url="https://store.kde.org/p/5555",
            downloads=[
                StoreWidgetDownload(
                    url="https://example.test/widget",
                    name="widget.plasmoid",
                    version="1.4.0",
                )
            ],
        )
        runner = FakeCommandRunner([CommandResponse(stdout="updated\n")])
        downloads: list[str] = []
        service = PlasmaWidgetsUpdateService(
            runner=runner,  # type: ignore[arg-type]
            store_client=_StoreClient(detail),
            downloader=lambda url: downloads.append(url) or b"unused",
        )

        result = service.update_widgets(
            [
                UpdatePlanItem(
                    source=UpdateSource.PLASMA_WIDGET,
                    target_id="5555",
                    package_name="Example Widget",
                    package_kind="Plasma/Applet",
                    plugin_id="com.example.widget",
                    expected_version="1.3.0",
                )
            ],
            log_callback=lambda _message: None,
        )

        self.assertFalse(result.success)
        self.assertEqual(downloads, [])
        self.assertEqual(runner.commands, [])

    def test_update_widgets_rejects_store_content_id_mismatch(self) -> None:
        detail = StoreWidgetDetail(
            content_id="9999",
            name="Example Widget",
            version="1.3.0",
            summary="Store summary",
            type_label="Plasma/Applet",
            author="example-author",
            detail_url="https://store.kde.org/p/9999",
            downloads=[
                StoreWidgetDownload(
                    url="https://example.test/widget",
                    name="widget.plasmoid",
                    version="1.3.0",
                )
            ],
        )
        runner = FakeCommandRunner([CommandResponse(stdout="updated\n")])
        downloads: list[str] = []
        service = PlasmaWidgetsUpdateService(
            runner=runner,  # type: ignore[arg-type]
            store_client=_StoreClient(detail),
            downloader=lambda url: downloads.append(url) or b"unused",
        )

        result = service.update_widgets(
            [
                UpdatePlanItem(
                    source=UpdateSource.PLASMA_WIDGET,
                    target_id="5555",
                    package_name="Example Widget",
                    package_kind="Plasma/Applet",
                    plugin_id="com.example.widget",
                    expected_version="1.3.0",
                )
            ],
            log_callback=lambda _message: None,
        )

        self.assertFalse(result.success)
        self.assertEqual(downloads, [])
        self.assertEqual(runner.commands, [])

    def test_update_widgets_rejects_archive_metadata_version_mismatch(self) -> None:
        detail = StoreWidgetDetail(
            content_id="5555",
            name="Example Widget",
            version="1.3.0",
            summary="Store summary",
            type_label="Plasma/Applet",
            author="example-author",
            detail_url="https://store.kde.org/p/5555",
            downloads=[
                StoreWidgetDownload(
                    url="https://example.test/widget",
                    name="widget.plasmoid",
                    version="1.3.0",
                )
            ],
        )
        runner = FakeCommandRunner([CommandResponse(stdout="updated\n")])
        service = PlasmaWidgetsUpdateService(
            runner=runner,  # type: ignore[arg-type]
            store_client=_StoreClient(detail),
            downloader=lambda _url: self._make_archive(
                plugin_id="com.example.widget",
                version="1.0.0",
            ),
        )

        result = service.update_widgets(
            [
                UpdatePlanItem(
                    source=UpdateSource.PLASMA_WIDGET,
                    target_id="5555",
                    package_name="Example Widget",
                    package_kind="Plasma/Applet",
                    plugin_id="com.example.widget",
                    expected_version="1.3.0",
                )
            ],
            log_callback=lambda _message: None,
        )

        self.assertFalse(result.success)
        self.assertEqual(runner.commands, [])

    def test_extract_archive_rejects_zip_path_traversal(self) -> None:
        service = PlasmaWidgetsUpdateService()
        archive_bytes = io.BytesIO()
        with zipfile.ZipFile(archive_bytes, "w") as archive:
            archive.writestr("../escape.txt", "boom")

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            archive_path = root / "payload.zip"
            extract_dir = root / "extract"
            archive_path.write_bytes(archive_bytes.getvalue())
            extract_dir.mkdir()

            with self.assertRaisesRegex(OSError, "incomplete or incompatible"):
                service._archive_handler().extract_archive(archive_path, extract_dir)

            self.assertFalse((root / "escape.txt").exists())

    def test_extract_archive_rejects_tar_path_traversal(self) -> None:
        service = PlasmaWidgetsUpdateService()
        archive_bytes = self._make_tar_archive("../escape.txt", b"boom")

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            archive_path = root / "payload.tar.gz"
            extract_dir = root / "extract"
            archive_path.write_bytes(archive_bytes)
            extract_dir.mkdir()

            with self.assertRaisesRegex(OSError, "incomplete or incompatible"):
                service._archive_handler().extract_archive(archive_path, extract_dir)

            self.assertFalse((root / "escape.txt").exists())

    def test_download_rejects_payloads_over_size_limit(self) -> None:
        service = PlasmaWidgetsUpdateService(downloader=lambda _url: b"too large")

        with (
            patch.object(PlasmaWidgetsUpdateService, "MAX_DOWNLOAD_BYTES", 3),
            self.assertRaisesRegex(OSError, "incomplete or incompatible"),
        ):
            service._download("https://example.test/widget")

    def test_download_rejects_non_https_urls_before_calling_downloader(self) -> None:
        calls: list[str] = []
        service = PlasmaWidgetsUpdateService(downloader=lambda url: calls.append(url) or b"")

        with self.assertRaisesRegex(OSError, "incomplete or incompatible"):
            service._download("file:///etc/passwd")
        with self.assertRaisesRegex(OSError, "incomplete or incompatible"):
            service._download("http://example.test/widget")

        self.assertEqual(calls, [])

    def test_download_filename_cannot_escape_temporary_directory(self) -> None:
        service = PlasmaWidgetsUpdateService()

        handler = service._archive_handler()
        self.assertEqual(handler.safe_download_filename("../escape.plasmoid"), "escape.plasmoid")
        self.assertEqual(handler.safe_download_filename("/tmp/escape.plasmoid"), "escape.plasmoid")
        self.assertEqual(handler.safe_download_filename(".."), "download.archive")
        self.assertEqual(handler.safe_download_filename(""), "download.archive")

    def test_download_accepts_responses_without_content_length(self) -> None:
        service = PlasmaWidgetsUpdateService()

        with patch(
            "urllib.request.urlopen",
            return_value=_ResponseWithoutLength(b"widget archive"),
        ):
            payload = service._download("https://example.test/widget")

        self.assertEqual(payload, b"widget archive")

    def test_download_rejects_https_redirect_to_http(self) -> None:
        service = PlasmaWidgetsUpdateService()

        with (
            patch(
                "urllib.request.urlopen",
                return_value=_ResponseWithoutLength(
                    b"widget archive",
                    final_url="http://example.test/widget",
                ),
            ),
            self.assertRaisesRegex(OSError, "incomplete or incompatible"),
        ):
            service._download("https://example.test/widget")

    def test_extract_archive_rejects_zip_that_expands_over_size_limit(self) -> None:
        service = PlasmaWidgetsUpdateService()
        archive_bytes = io.BytesIO()
        with zipfile.ZipFile(archive_bytes, "w") as archive:
            archive.writestr("widget/metadata.json", "{}")

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            archive_path = root / "payload.zip"
            extract_dir = root / "extract"
            archive_path.write_bytes(archive_bytes.getvalue())
            extract_dir.mkdir()

            with (
                patch.object(PlasmaWidgetsUpdateService, "MAX_EXTRACTED_BYTES", 1),
                self.assertRaisesRegex(OSError, "incomplete or incompatible"),
            ):
                service._archive_handler().extract_archive(archive_path, extract_dir)

    def test_find_metadata_path_rejects_ambiguous_multiple_metadata_files(self) -> None:
        service = PlasmaWidgetsUpdateService()

        with tempfile.TemporaryDirectory() as tmp:
            extract_dir = Path(tmp)
            for plugin_id in ("one", "two"):
                package_dir = extract_dir / plugin_id
                package_dir.mkdir()
                (package_dir / "metadata.json").write_text(
                    json.dumps(
                        {
                            "KPlugin": {"Id": plugin_id, "Version": "1.0.0"},
                            "KPackageStructure": "Plasma/Applet",
                        }
                    ),
                    encoding="utf-8",
                )

            with self.assertRaisesRegex(OSError, "incomplete or incompatible") as captured:
                service._archive_handler().find_metadata_path(
                    extract_dir,
                    plugin_id="missing",
                    package_kind="Plasma/Applet",
                )
            self.assertIn("does not match the installed add-on", captured.exception.technical_message)

    def test_find_metadata_path_uses_unique_package_kind_match_without_plugin_id(self) -> None:
        service = PlasmaWidgetsUpdateService()

        with tempfile.TemporaryDirectory() as tmp:
            extract_dir = Path(tmp)
            first = extract_dir / "first"
            second = extract_dir / "second"
            first.mkdir()
            second.mkdir()
            (first / "metadata.json").write_text(
                json.dumps(
                    {
                        "KPlugin": {"Id": "first", "Version": "1.0.0"},
                        "KPackageStructure": "KWin/Script",
                    }
                ),
                encoding="utf-8",
            )
            (second / "metadata.json").write_text(
                json.dumps(
                    {
                        "KPlugin": {"Id": "second", "Version": "1.0.0"},
                        "KPackageStructure": "Plasma/Applet",
                    }
                ),
                encoding="utf-8",
            )

            chosen = service._archive_handler().find_metadata_path(
                extract_dir,
                plugin_id=None,
                package_kind="Plasma/Applet",
            )

            self.assertEqual(chosen, second / "metadata.json")

    def test_find_metadata_path_rejects_single_metadata_with_wrong_plugin_id(self) -> None:
        service = PlasmaWidgetsUpdateService()

        with tempfile.TemporaryDirectory() as tmp:
            extract_dir = Path(tmp)
            package_dir = extract_dir / "wrong"
            package_dir.mkdir()
            (package_dir / "metadata.json").write_text(
                json.dumps(
                    {
                        "KPlugin": {"Id": "wrong", "Version": "1.0.0"},
                        "KPackageStructure": "Plasma/Applet",
                    }
                ),
                encoding="utf-8",
            )

            with self.assertRaisesRegex(OSError, "incomplete or incompatible"):
                service._archive_handler().find_metadata_path(
                    extract_dir,
                    plugin_id="expected",
                    package_kind="Plasma/Applet",
                )

    def test_find_metadata_path_rejects_matching_plugin_with_wrong_package_kind(self) -> None:
        service = PlasmaWidgetsUpdateService()

        with tempfile.TemporaryDirectory() as tmp:
            extract_dir = Path(tmp)
            package_dir = extract_dir / "com.example.widget"
            package_dir.mkdir()
            (package_dir / "metadata.json").write_text(
                json.dumps(
                    {
                        "KPlugin": {"Id": "com.example.widget", "Version": "1.0.0"},
                        "KPackageStructure": "KWin/Script",
                    }
                ),
                encoding="utf-8",
            )

            with self.assertRaisesRegex(OSError, "incomplete or incompatible"):
                service._archive_handler().find_metadata_path(
                    extract_dir,
                    plugin_id="com.example.widget",
                    package_kind="Plasma/Applet",
                )


if __name__ == "__main__":
    unittest.main()
