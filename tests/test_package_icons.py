from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from archupdater.domain.enums import UpdateSource
from archupdater.domain.package_metadata import (
    FirmwarePackageMetadata,
    FlatpakPackageMetadata,
    SystemPackageMetadata,
)
from archupdater.domain.packages import PackageUpdate
from archupdater.presentation.package_icons import PackageIconResolver


class PackageIconResolverTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _system(self, name: str) -> PackageUpdate:
        return PackageUpdate(name, "1", "2", UpdateSource.SYSTEM, SystemPackageMetadata())

    def _flatpak(self, name: str, ref: str, repository: str) -> PackageUpdate:
        return PackageUpdate(
            name,
            "1",
            "2",
            UpdateSource.FLATPAK,
            FlatpakPackageMetadata(ref=ref, repository=repository),
            backend_id=ref,
        )

    def _firmware(self, name: str) -> PackageUpdate:
        return PackageUpdate(
            name,
            "1",
            "2",
            UpdateSource.FIRMWARE,
            FirmwarePackageMetadata(device_id=name),
        )

    def test_resolves_icon_from_appstream_catalog(self) -> None:
        icon_path = (
            self.root
            / "catalog"
            / "archlinux-arch-extra"
            / "64x64"
            / "python_abc123.png"
        )
        icon_path.parent.mkdir(parents=True)
        icon_path.write_bytes(b"not a real png, but enough for path resolution")
        resolver = PackageIconResolver(appstream_icon_roots=(self.root / "catalog",))

        resolved = resolver.icon_path_for(self._system("python"))

        self.assertEqual(resolved, icon_path)

    def test_resolves_icon_from_legacy_app_info_catalog(self) -> None:
        icon_path = (
            self.root
            / "app-info"
            / "archlinux-arch-core"
            / "128x128"
            / "linux_kernel.png"
        )
        icon_path.parent.mkdir(parents=True)
        icon_path.write_bytes(b"not a real png, but enough for path resolution")
        resolver = PackageIconResolver(appstream_icon_roots=(self.root / "app-info",))

        resolved = resolver.icon_path_for(self._system("linux"))

        self.assertEqual(resolved, icon_path)

    def test_resolves_flatpak_appstream_icon(self) -> None:
        icon_path = (
            self.root
            / "flathub"
            / "x86_64"
            / "active"
            / "icons"
            / "64x64"
            / "org.example.App.png"
        )
        icon_path.parent.mkdir(parents=True)
        icon_path.write_bytes(b"not a real png, but enough for path resolution")
        resolver = PackageIconResolver(flatpak_appstream_roots=(self.root,))

        resolved = resolver.icon_path_for(
            self._flatpak(
                "Example",
                "app/org.example.App/x86_64/stable",
                "flathub (system)",
            )
        )

        self.assertEqual(resolved, icon_path)

    def test_resolves_desktop_entry_theme_icon(self) -> None:
        desktop_root = self.root / "applications"
        theme_root = self.root / "icons"
        desktop_root.mkdir()
        (desktop_root / "example.desktop").write_text(
            "[Desktop Entry]\nName=Example\nIcon=example-icon\n",
            encoding="utf-8",
        )
        icon_path = theme_root / "hicolor" / "64x64" / "apps" / "example-icon.svg"
        icon_path.parent.mkdir(parents=True)
        icon_path.write_text("<svg />", encoding="utf-8")
        resolver = PackageIconResolver(
            desktop_entry_roots=(desktop_root,),
            icon_theme_roots=(theme_root,),
        )

        resolved = resolver.icon_path_for(self._system("example"))

        self.assertEqual(resolved, icon_path)

    def test_resolves_language_family_icon_for_python_packages(self) -> None:
        theme_root = self.root / "icons"
        icon_path = theme_root / "custom" / "apps" / "16" / "python.svg"
        icon_path.parent.mkdir(parents=True)
        icon_path.write_text("<svg />", encoding="utf-8")
        resolver = PackageIconResolver(icon_theme_roots=(theme_root,))

        resolved = resolver.icon_path_for(self._system("python-orjson"))

        self.assertEqual(resolved, icon_path)

    def test_resolves_desktop_family_icon_for_kde_packages(self) -> None:
        theme_root = self.root / "icons"
        icon_path = theme_root / "custom" / "48x48" / "apps" / "kde.svg"
        icon_path.parent.mkdir(parents=True)
        icon_path.write_text("<svg />", encoding="utf-8")
        resolver = PackageIconResolver(icon_theme_roots=(theme_root,))

        resolved = resolver.icon_path_for(self._system("breeze-icons"))

        self.assertEqual(resolved, icon_path)

    def test_resolves_container_family_icon_for_sandbox_packages(self) -> None:
        theme_root = self.root / "icons"
        icon_path = theme_root / "custom" / "64x64" / "apps" / "application-x-executable.svg"
        icon_path.parent.mkdir(parents=True)
        icon_path.write_text("<svg />", encoding="utf-8")
        resolver = PackageIconResolver(
            appstream_icon_roots=(self.root / "catalog",),
            icon_theme_roots=(theme_root,),
            desktop_entry_roots=(self.root / "applications",),
            flatpak_appstream_roots=(self.root / "flatpak",),
        )

        resolved = resolver.icon_path_for(self._system("bubblewrap"))

        self.assertEqual(resolved, icon_path)

    def test_resolves_font_family_icon_for_font_packages(self) -> None:
        theme_root = self.root / "icons"
        icon_path = theme_root / "custom" / "mimetypes" / "48" / "font-x-generic.svg"
        icon_path.parent.mkdir(parents=True)
        icon_path.write_text("<svg />", encoding="utf-8")
        resolver = PackageIconResolver(
            appstream_icon_roots=(self.root / "catalog",),
            icon_theme_roots=(theme_root,),
            desktop_entry_roots=(self.root / "applications",),
            flatpak_appstream_roots=(self.root / "flatpak",),
        )

        resolved = resolver.icon_path_for(self._system("ttf-fira-code"))

        self.assertEqual(resolved, icon_path)

    def test_resolves_firmware_source_icon_without_package_hint(self) -> None:
        theme_root = self.root / "icons"
        icon_path = theme_root / "custom" / "devices" / "64" / "drive-removable-media.svg"
        icon_path.parent.mkdir(parents=True)
        icon_path.write_text("<svg />", encoding="utf-8")
        resolver = PackageIconResolver(
            appstream_icon_roots=(self.root / "catalog",),
            icon_theme_roots=(theme_root,),
            desktop_entry_roots=(self.root / "applications",),
            flatpak_appstream_roots=(self.root / "flatpak",),
        )

        resolved = resolver.icon_path_for(self._firmware("UEFI Device Firmware"))

        self.assertEqual(resolved, icon_path)

    def test_returns_none_when_no_system_icon_exists(self) -> None:
        resolver = PackageIconResolver(
            appstream_icon_roots=(self.root / "catalog",),
            icon_theme_roots=(self.root / "icons",),
            desktop_entry_roots=(self.root / "applications",),
            flatpak_appstream_roots=(self.root / "flatpak",),
        )

        resolved = resolver.icon_path_for(self._system("missing"))

        self.assertIsNone(resolved)


if __name__ == "__main__":
    unittest.main()
