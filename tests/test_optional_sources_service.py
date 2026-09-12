from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from archupdater.domain.enums import UpdateSource
from archupdater.services.optional_sources import OptionalSourcesService


class OptionalSourcesServiceTests(unittest.TestCase):
    def _firmware_probe(self, payload: object):
        def probe(command: list[str], timeout: float) -> tuple[int, str, str]:
            self.assertEqual(command, ["fwupdmgr", "get-devices", "--json"])
            self.assertGreater(timeout, 0)
            return 0, json.dumps(payload), ""

        return probe

    def test_detects_single_aur_helper_as_installed_but_disabled_by_default(self) -> None:
        service = OptionalSourcesService(which=lambda name: "/usr/bin/paru" if name == "paru" else None)

        snapshot = service.snapshot()

        status = snapshot.status_for(UpdateSource.AUR)
        assert status is not None
        self.assertTrue(status.installed)
        self.assertFalse(status.active)
        self.assertEqual(status.removable_packages, [])
        self.assertEqual(status.installable_packages, [])
        self.assertIn("paru", status.status_text)
        self.assertIn(UpdateSource.SYSTEM, snapshot.selectable_sources)
        self.assertNotIn(UpdateSource.AUR, snapshot.selectable_sources)

    def test_detects_single_aur_helper_as_active_when_user_enabled(self) -> None:
        service = OptionalSourcesService(
            which=lambda name: "/usr/bin/paru" if name == "paru" else None,
            aur_enabled_provider=lambda: True,
        )

        snapshot = service.snapshot()

        status = snapshot.status_for(UpdateSource.AUR)
        assert status is not None
        self.assertTrue(status.installed)
        self.assertTrue(status.active)
        self.assertIn(UpdateSource.AUR, snapshot.selectable_sources)

    def test_aur_preference_change_requires_persistence_adapter(self) -> None:
        service = OptionalSourcesService()

        with self.assertRaisesRegex(RuntimeError, "persistence is unavailable"):
            service.set_aur_enabled(True)

    def test_aur_preference_change_uses_persistence_adapter(self) -> None:
        changes: list[bool] = []
        service = OptionalSourcesService(aur_enabled_setter=changes.append)

        service.set_aur_enabled(True)

        self.assertEqual(changes, [True])

    def test_reports_missing_flatpak_and_firmware(self) -> None:
        service = OptionalSourcesService(which=lambda _name: None)

        snapshot = service.snapshot()

        flatpak = snapshot.status_for(UpdateSource.FLATPAK)
        firmware = snapshot.status_for(UpdateSource.FIRMWARE)
        assert flatpak is not None and firmware is not None
        self.assertFalse(flatpak.active)
        self.assertEqual(flatpak.installable_packages, ["flatpak"])
        self.assertFalse(firmware.active)
        self.assertEqual(firmware.installable_packages, ["fwupd"])
        self.assertEqual(firmware.removable_packages, [])

    def test_reports_installed_firmware_backend_as_manageable(self) -> None:
        service = OptionalSourcesService(
            which=lambda name: "/usr/bin/fwupdmgr" if name == "fwupdmgr" else None,
            firmware_probe=self._firmware_probe(
                {
                    "Devices": [
                        {
                            "Name": "Framework Laptop 13 BIOS",
                            "Flags": ["internal", "updatable", "supported"],
                        }
                    ]
                }
            ),
        )

        snapshot = service.snapshot()

        firmware = snapshot.status_for(UpdateSource.FIRMWARE)
        assert firmware is not None
        self.assertTrue(firmware.installed)
        self.assertTrue(firmware.active)
        self.assertEqual(firmware.status_text, "Installed, ready to check device firmware")
        self.assertEqual(firmware.installable_packages, [])
        self.assertEqual(firmware.removable_packages, ["fwupd"])

    def test_installed_firmware_backend_stays_active_without_supported_devices(self) -> None:
        service = OptionalSourcesService(
            which=lambda name: "/usr/bin/fwupdmgr" if name == "fwupdmgr" else None,
            firmware_probe=self._firmware_probe(
                {
                    "Devices": [
                        {
                            "Name": "USB Mouse",
                            "Flags": ["internal"],
                        }
                    ]
                }
            ),
        )

        snapshot = service.snapshot()

        firmware = snapshot.status_for(UpdateSource.FIRMWARE)
        assert firmware is not None
        self.assertTrue(firmware.installed)
        self.assertTrue(firmware.active)
        self.assertEqual(firmware.status_text, "Installed, no compatible firmware devices detected")
        self.assertIn(UpdateSource.FIRMWARE, snapshot.active_sources)
        self.assertEqual(firmware.removable_packages, ["fwupd"])

    def test_installed_firmware_backend_stays_active_when_device_probe_fails(self) -> None:
        def failing_probe(_command: list[str], _timeout: float) -> tuple[int, str, str]:
            return 1, "", "failed"

        service = OptionalSourcesService(
            which=lambda name: "/usr/bin/fwupdmgr" if name == "fwupdmgr" else None,
            firmware_probe=failing_probe,
        )

        snapshot = service.snapshot()

        firmware = snapshot.status_for(UpdateSource.FIRMWARE)
        assert firmware is not None
        self.assertTrue(firmware.installed)
        self.assertTrue(firmware.active)
        self.assertEqual(firmware.status_text, "Installed, device support unavailable")
        self.assertEqual(firmware.removable_packages, ["fwupd"])

    def test_reports_plasma_widgets_installed_but_inactive_outside_plasma(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            service = OptionalSourcesService(
                which=lambda name: "/usr/bin/kpackagetool6" if name == "kpackagetool6" else None,
                home_dir=Path(tmp),
                env={"XDG_CURRENT_DESKTOP": "", "DESKTOP_SESSION": ""},
            )

            snapshot = service.snapshot()

        plasma = snapshot.status_for(UpdateSource.PLASMA_WIDGET)
        assert plasma is not None
        self.assertTrue(plasma.installed)
        self.assertFalse(plasma.active)
        self.assertEqual(plasma.status_text, "Installed but inactive")
        self.assertEqual(plasma.installable_packages, [])
        self.assertEqual(plasma.removable_packages, [])

    def test_local_plasma_widgets_activate_widgets_source_without_plasma_session(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / ".local" / "share" / "plasma" / "plasmoids" / "com.example.widget"
            root.mkdir(parents=True)
            service = OptionalSourcesService(
                which=lambda name: "/usr/bin/kpackagetool6" if name == "kpackagetool6" else None,
                home_dir=Path(tmp),
                env={"XDG_CURRENT_DESKTOP": "", "DESKTOP_SESSION": ""},
            )

            snapshot = service.snapshot()

        plasma = snapshot.status_for(UpdateSource.PLASMA_WIDGET)
        assert plasma is not None
        self.assertTrue(plasma.active)


if __name__ == "__main__":
    unittest.main()
