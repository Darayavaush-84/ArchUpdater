from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from archupdater.domain.enums import UpdateSource
from archupdater.domain.package_metadata import PlasmaWidgetPackageMetadata
from archupdater.services.plasma_widgets import PlasmaWidgetsUpdateService
from archupdater.services.plasma_widgets_store import StoreWidgetSummary
from archupdater.services.plasma_widgets_store import StoreWidgetDetail


class _CacheStub:
    def __init__(self, values: dict[tuple[str, str], str] | None = None) -> None:
        self.values = values or {}

    def resolve(self, package_kind: str, plugin_id: str | None) -> str | None:
        if plugin_id is None:
            return None
        return self.values.get((package_kind, plugin_id))

    def remember(self, package_kind: str, plugin_id: str | None, content_id: str) -> None:
        if plugin_id is None:
            return
        self.values[(package_kind, plugin_id)] = content_id


class PlasmaWidgetsUpdateServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.home_dir = Path(self._tmp.name)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _write_widget(
        self,
        relative_dir: str,
        *,
        plugin_id: str,
        name: str,
        version: str,
        description: str = "",
    ) -> Path:
        package_dir = self.home_dir / relative_dir / plugin_id
        package_dir.mkdir(parents=True, exist_ok=True)
        metadata = {
            "KPlugin": {
                "Id": plugin_id,
                "Name": name,
                "Version": version,
                "Description": description,
            }
        }
        (package_dir / "metadata.json").write_text(json.dumps(metadata), encoding="utf-8")
        return package_dir

    def test_check_updates_uses_registry_match_and_preserves_widget_metadata(self) -> None:
        package_dir = self._write_widget(
            ".local/share/plasma/plasmoids",
            plugin_id="com.example.widget",
            name="Example Widget",
            version="1.2.3",
            description="Local description",
        )
        registry_dir = self.home_dir / ".local/share/knewstuff3"
        registry_dir.mkdir(parents=True, exist_ok=True)
        registry_dir.joinpath("plasmoids.knsregistry").write_text(
            (
                "<hotnewstuffregistry>"
                "<stuff>"
                f"<installedfile>{package_dir.as_posix()}/</installedfile>"
                "<id>5555</id>"
                "</stuff>"
                "</hotnewstuffregistry>"
            ),
            encoding="utf-8",
        )

        service = PlasmaWidgetsUpdateService(
            home_dir=self.home_dir,
            store_fetcher=lambda: [
                StoreWidgetSummary(
                    content_id="5555",
                    name="Example Widget",
                    version="1.3.0",
                    summary="Store summary",
                    type_label="Plasma/Applet",
                    author="example-author",
                    detail_url="https://store.kde.org/p/5555",
                )
            ],
        )

        result = service.check_updates()

        self.assertEqual(len(result.packages), 1)
        package = result.packages[0]
        self.assertEqual(package.source, UpdateSource.PLASMA_WIDGET)
        self.assertEqual(package.name, "Example Widget")
        self.assertEqual(package.current_version, "1.2.3")
        self.assertEqual(package.new_version, "1.3.0")
        metadata = package.source_metadata
        self.assertIsInstance(metadata, PlasmaWidgetPackageMetadata)
        self.assertEqual(metadata.repository, "KDE Store")
        self.assertTrue(package.selected)
        self.assertFalse(package.selection_locked)
        self.assertEqual(package.backend_id, "5555")
        self.assertEqual(metadata.plugin_id, "com.example.widget")
        self.assertEqual(metadata.package_kind, "Plasma/Applet")
        self.assertEqual(package.author, "example-author")
        self.assertEqual(package.homepage, "https://store.kde.org/p/5555")
        self.assertEqual(
            package.warnings,
            ["Some KDE Store add-ons may require restarting plasmashell after updating."],
        )

    def test_default_store_check_fetches_only_known_content_ids(self) -> None:
        self._write_widget(
            ".local/share/plasma/plasmoids",
            plugin_id="com.example.widget",
            name="Example Widget",
            version="1.0",
        )
        id_map_path = self.home_dir / "plasma_widgets_id_map.txt"
        id_map_path.write_text("5555 com.example.widget\n", encoding="utf-8")
        fetched: list[str] = []

        class _Store:
            def fetch_listing(self):  # noqa: ANN201
                raise AssertionError("the full KDE Store listing must not be fetched")

            def fetch_details(self, content_id: str) -> StoreWidgetDetail:
                fetched.append(content_id)
                return StoreWidgetDetail(
                    content_id=content_id,
                    name="Example Widget",
                    version="1.1",
                    summary="Update",
                    type_label="Plasma/Applet",
                    author="author",
                    detail_url="https://store.kde.org/p/5555",
                    downloads=[],
                )

        service = PlasmaWidgetsUpdateService(
            home_dir=self.home_dir,
            id_map_path=id_map_path,
            store_client=_Store(),  # type: ignore[arg-type]
        )

        result = service.check_updates()

        self.assertEqual(fetched, ["5555"])
        self.assertEqual([package.backend_id for package in result.packages], ["5555"])

    def test_check_updates_uses_id_map_fallback_without_registry(self) -> None:
        self._write_widget(
            ".local/share/kwin/scripts",
            plugin_id="org.example.script",
            name="Missing Registry Script",
            version="2.0",
        )
        id_map_path = self.home_dir / "plasma_widgets_id_map.txt"
        id_map_path.write_text("9988 org.example.script\n", encoding="utf-8")

        service = PlasmaWidgetsUpdateService(
            home_dir=self.home_dir,
            id_map_path=id_map_path,
            store_fetcher=lambda: [
                StoreWidgetSummary(
                    content_id="9988",
                    name="Different Store Name",
                    version="2.1",
                    summary="KWin script update",
                    type_label="KWin/Script",
                    author="script-author",
                    detail_url="https://store.kde.org/p/9988",
                )
            ],
        )

        result = service.check_updates()

        self.assertEqual([package.name for package in result.packages], ["Missing Registry Script"])
        self.assertEqual(result.packages[0].new_version, "2.1")

    def test_id_map_loader_skips_ignored_entries(self) -> None:
        id_map_path = self.home_dir / "plasma_widgets_id_map.txt"
        id_map_path.write_text(
            "1000 org.example.addon\n"
            "1001 org.example.addon #Ignored, not a unique ID\n",
            encoding="utf-8",
        )
        service = PlasmaWidgetsUpdateService(home_dir=self.home_dir, id_map_path=id_map_path)

        self.assertEqual(service._load_id_map(), {"org.example.addon": "1000"})

    def test_check_updates_returns_warning_when_store_fetch_fails(self) -> None:
        self._write_widget(
            ".local/share/plasma/plasmoids",
            plugin_id="com.example.widget",
            name="Example Widget",
            version="1.0",
        )

        def fail_fetch() -> list[StoreWidgetSummary]:
            raise OSError("network down")

        service = PlasmaWidgetsUpdateService(
            home_dir=self.home_dir,
            store_fetcher=fail_fetch,
        )

        result = service.check_updates()

        self.assertEqual(result.packages, [])
        self.assertEqual(result.warnings, ["KDE Store is temporarily unavailable. Try again later."])

    def test_check_updates_uses_cached_match_before_name_fallback(self) -> None:
        self._write_widget(
            ".local/share/kwin/scripts",
            plugin_id="org.example.script",
            name="Local Script",
            version="2.0",
        )

        service = PlasmaWidgetsUpdateService(
            home_dir=self.home_dir,
            match_cache=_CacheStub({("KWin/Script", "org.example.script"): "9988"}),  # type: ignore[arg-type]
            store_fetcher=lambda: [
                StoreWidgetSummary(
                    content_id="9988",
                    name="Different Store Name",
                    version="2.1",
                    summary="KWin script update",
                    type_label="KWin/Script",
                    author="script-author",
                    detail_url="https://store.kde.org/p/9988",
                )
            ],
        )

        result = service.check_updates()

        self.assertEqual([package.backend_id for package in result.packages], ["9988"])

    def test_check_updates_does_not_match_store_entries_by_name_only(self) -> None:
        self._write_widget(
            ".local/share/kwin/effects",
            plugin_id="org.example.effect",
            name="Shared Name",
            version="1.0",
        )

        service = PlasmaWidgetsUpdateService(
            home_dir=self.home_dir,
            store_fetcher=lambda: [
                StoreWidgetSummary(
                    content_id="1111",
                    name="Shared Name",
                    version="2.0",
                    summary="Wrong type",
                    type_label="Plasma/Applet",
                    author="author",
                    detail_url="https://store.kde.org/p/1111",
                ),
                StoreWidgetSummary(
                    content_id="2222",
                    name="Shared Name",
                    version="2.0",
                    summary="Right type",
                    type_label="KWin/Effect",
                    author="author",
                    detail_url="https://store.kde.org/p/2222",
                ),
            ],
        )

        result = service.check_updates()

        self.assertEqual(result.packages, [])

    def test_check_updates_ignores_id_map_entry_with_wrong_addon_type(self) -> None:
        self._write_widget(
            ".local/share/plasma/plasmoids",
            plugin_id="org.example.widget",
            name="Widget Name",
            version="1.0",
        )
        id_map_path = self.home_dir / "plasma_widgets_id_map.txt"
        id_map_path.write_text("1111 org.example.widget\n", encoding="utf-8")

        service = PlasmaWidgetsUpdateService(
            home_dir=self.home_dir,
            id_map_path=id_map_path,
            store_fetcher=lambda: [
                StoreWidgetSummary(
                    content_id="1111",
                    name="Widget Name",
                    version="2.0",
                    summary="Wrong type",
                    type_label="KWin/Script",
                    author="author",
                    detail_url="https://store.kde.org/p/1111",
                )
            ],
        )

        result = service.check_updates()

        self.assertEqual(result.packages, [])

    def test_version_compare_handles_suffixes_and_prereleases(self) -> None:
        service = PlasmaWidgetsUpdateService(home_dir=self.home_dir)

        self.assertTrue(service._is_remote_version_newer("1.2.0", "1.2.1"))
        self.assertTrue(service._is_remote_version_newer("1.2-rc1", "1.2"))
        self.assertFalse(service._is_remote_version_newer("1.2", "1.2-beta1"))
        self.assertFalse(service._is_remote_version_newer("1.0", "1.0beta"))
        self.assertFalse(service._is_remote_version_newer("1.0", "1.0rc1"))
        self.assertTrue(service._is_remote_version_newer("v2.0", "2.0.1"))
        self.assertTrue(service._is_remote_version_newer("2.0", "v2.0.1"))
        self.assertFalse(service._is_remote_version_newer("2.0.1", "v2.0"))
        self.assertFalse(service._is_remote_version_newer("kde-store", "newer"))


if __name__ == "__main__":
    unittest.main()
