from __future__ import annotations

import io
import json
import stat
import struct
import sys
import tarfile
import tempfile
import unittest
import warnings
import zipfile
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from archupdater.services.plasma_widget_archive import PlasmaWidgetArchiveHandler


class PlasmaWidgetArchiveHandlerTests(unittest.TestCase):
    def _handler(self) -> PlasmaWidgetArchiveHandler:
        return PlasmaWidgetArchiveHandler(
            translate=lambda text: text,
            max_archive_entries=100,
            max_extracted_bytes=1024 * 1024,
        )

    def test_safe_download_filename_removes_path_components(self) -> None:
        handler = self._handler()

        self.assertEqual(handler.safe_download_filename("../widget.plasmoid"), "widget.plasmoid")
        self.assertEqual(handler.safe_download_filename("/tmp/widget.plasmoid"), "widget.plasmoid")
        self.assertEqual(handler.safe_download_filename(".."), "download.archive")
        self.assertEqual(handler.safe_download_filename("widget\nspoof.zip"), "download.archive")

    def test_extract_archive_rejects_path_traversal(self) -> None:
        handler = self._handler()
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
                handler.extract_archive(archive_path, extract_dir)

            self.assertFalse((root / "escape.txt").exists())

    def test_extract_zip_preserves_executable_bits_without_special_bits(self) -> None:
        handler = self._handler()
        archive_bytes = io.BytesIO()
        directory_info = zipfile.ZipInfo("widget/")
        directory_info.create_system = 3
        directory_info.external_attr = (
            stat.S_IFDIR | stat.S_ISUID | stat.S_ISGID | stat.S_ISVTX | 0o755
        ) << 16
        info = zipfile.ZipInfo("widget/run.sh")
        info.create_system = 3
        info.external_attr = (
            stat.S_IFREG | stat.S_ISUID | stat.S_ISGID | stat.S_ISVTX | 0o755
        ) << 16
        with zipfile.ZipFile(archive_bytes, "w") as archive:
            archive.writestr(directory_info, b"")
            archive.writestr(info, "#!/bin/sh\n")

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            archive_path = root / "payload.zip"
            extract_dir = root / "extract"
            archive_path.write_bytes(archive_bytes.getvalue())
            extract_dir.mkdir()

            handler.extract_archive(archive_path, extract_dir)

            mode = stat.S_IMODE((extract_dir / "widget" / "run.sh").stat().st_mode)
            self.assertEqual(mode, 0o755)
            directory_mode = stat.S_IMODE((extract_dir / "widget").stat().st_mode)
            self.assertEqual(directory_mode, 0o755)

    def test_extract_tar_preserves_executable_bits_without_special_bits(self) -> None:
        handler = self._handler()
        archive_bytes = io.BytesIO()
        with tarfile.open(fileobj=archive_bytes, mode="w") as archive:
            directory_info = tarfile.TarInfo("widget")
            directory_info.type = tarfile.DIRTYPE
            directory_info.mode = stat.S_ISUID | stat.S_ISGID | stat.S_ISVTX | 0o755
            archive.addfile(directory_info)
            info = tarfile.TarInfo("widget/run.sh")
            content = b"#!/bin/sh\n"
            info.size = len(content)
            info.mode = stat.S_ISUID | stat.S_ISGID | stat.S_ISVTX | 0o755
            archive.addfile(info, io.BytesIO(content))

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            archive_path = root / "payload.tar"
            extract_dir = root / "extract"
            archive_path.write_bytes(archive_bytes.getvalue())
            extract_dir.mkdir()

            handler.extract_archive(archive_path, extract_dir)

            mode = stat.S_IMODE((extract_dir / "widget" / "run.sh").stat().st_mode)
            self.assertEqual(mode, 0o755)
            directory_mode = stat.S_IMODE((extract_dir / "widget").stat().st_mode)
            self.assertEqual(directory_mode, 0o755)

    def test_extract_archive_rejects_duplicate_member_paths(self) -> None:
        handler = self._handler()
        archive_bytes = io.BytesIO()
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", UserWarning)
            with zipfile.ZipFile(archive_bytes, "w") as archive:
                archive.writestr("metadata.json", "first")
                archive.writestr("metadata.json", "second")

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            archive_path = root / "payload.zip"
            extract_dir = root / "extract"
            archive_path.write_bytes(archive_bytes.getvalue())
            extract_dir.mkdir()

            with self.assertRaisesRegex(OSError, "incomplete or incompatible"):
                handler.extract_archive(archive_path, extract_dir)

    def test_zip_entry_limit_is_checked_before_zipfile_allocates_entries(self) -> None:
        handler = self._handler()
        archive_bytes = io.BytesIO()
        with zipfile.ZipFile(archive_bytes, "w") as archive:
            for index in range(101):
                archive.writestr(f"empty-{index}", b"")

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            archive_path = root / "many.zip"
            archive_path.write_bytes(archive_bytes.getvalue())
            extract_dir = root / "extract"
            extract_dir.mkdir()

            with (
                patch.object(
                    zipfile,
                    "ZipFile",
                    side_effect=AssertionError("ZipFile must not be opened"),
                ),
                self.assertRaisesRegex(OSError, "incomplete or incompatible"),
            ):
                handler.extract_archive(archive_path, extract_dir)
            self.assertEqual(list(extract_dir.iterdir()), [])

    def test_zip_preflight_rejects_forged_entry_count_before_opening(self) -> None:
        handler = self._handler()
        archive_bytes = io.BytesIO()
        with zipfile.ZipFile(archive_bytes, "w") as archive:
            archive.writestr("one", b"")
            archive.writestr("two", b"")
        payload = bytearray(archive_bytes.getvalue())
        eocd_offset = payload.rfind(b"PK\x05\x06")
        struct.pack_into("<HH", payload, eocd_offset + 8, 1, 1)

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            archive_path = root / "forged.zip"
            archive_path.write_bytes(payload)
            extract_dir = root / "extract"
            extract_dir.mkdir()

            with (
                patch.object(
                    zipfile,
                    "ZipFile",
                    side_effect=AssertionError("ZipFile must not be opened"),
                ),
                self.assertRaisesRegex(OSError, "incomplete or incompatible"),
            ):
                handler.extract_archive(archive_path, extract_dir)

    def test_tar_extraction_never_materializes_all_members(self) -> None:
        handler = self._handler()
        archive_bytes = io.BytesIO()
        with tarfile.open(fileobj=archive_bytes, mode="w") as archive:
            info = tarfile.TarInfo("metadata.json")
            content = b"{}"
            info.size = len(content)
            archive.addfile(info, io.BytesIO(content))

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            archive_path = root / "payload.tar"
            archive_path.write_bytes(archive_bytes.getvalue())
            extract_dir = root / "extract"
            extract_dir.mkdir()

            original_getmembers = tarfile.TarFile.getmembers
            tarfile.TarFile.getmembers = lambda _self: (_ for _ in ()).throw(  # type: ignore[method-assign]
                AssertionError("getmembers must not be called")
            )
            try:
                handler.extract_archive(archive_path, extract_dir)
            finally:
                tarfile.TarFile.getmembers = original_getmembers  # type: ignore[method-assign]

            self.assertEqual((extract_dir / "metadata.json").read_text(), "{}")

    def test_extract_archive_removes_group_and_world_write_bits(self) -> None:
        handler = self._handler()
        archive_bytes = io.BytesIO()
        info = zipfile.ZipInfo("metadata.json")
        info.create_system = 3
        info.external_attr = (stat.S_IFREG | 0o777) << 16
        with zipfile.ZipFile(archive_bytes, "w") as archive:
            archive.writestr(info, "{}")

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            archive_path = root / "payload.zip"
            extract_dir = root / "extract"
            archive_path.write_bytes(archive_bytes.getvalue())
            extract_dir.mkdir()

            handler.extract_archive(archive_path, extract_dir)

            mode = stat.S_IMODE((extract_dir / "metadata.json").stat().st_mode)
            self.assertEqual(mode, 0o755)

    def test_find_metadata_path_prefers_matching_plugin_id(self) -> None:
        handler = self._handler()

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for plugin_id in ("first", "second"):
                package_dir = root / plugin_id
                package_dir.mkdir()
                (package_dir / "metadata.json").write_text(
                    json.dumps({"KPlugin": {"Id": plugin_id}}),
                    encoding="utf-8",
                )

            chosen = handler.find_metadata_path(
                root,
                plugin_id="second",
                package_kind="",
            )

        self.assertEqual(chosen.name, "metadata.json")
        self.assertEqual(chosen.parent.name, "second")


if __name__ == "__main__":
    unittest.main()
