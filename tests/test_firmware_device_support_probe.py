from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from archupdater.services.firmware import FirmwareDeviceSupportProbe


class FirmwareDeviceSupportProbeTests(unittest.TestCase):
    def test_detects_supported_device_in_nested_fwupd_payload(self) -> None:
        payload = {
            "Devices": [
                {
                    "Name": "USB Controller",
                    "Children": [
                        {
                            "Name": "Laptop BIOS",
                            "flags": "internal|updatable",
                        }
                    ],
                }
            ]
        }

        def run(command: list[str], timeout: float) -> tuple[int, str, str]:
            self.assertEqual(command, ["fwupdmgr", "get-devices", "--json"])
            self.assertGreater(timeout, 0)
            return 0, json.dumps(payload), ""

        probe = FirmwareDeviceSupportProbe(run=run)

        self.assertTrue(probe.detect_supported_devices())

    def test_reports_false_when_fwupd_payload_has_no_supported_devices(self) -> None:
        probe = FirmwareDeviceSupportProbe(
            run=lambda _command, _timeout: (
                0,
                json.dumps({"Devices": [{"Name": "USB Mouse", "Flags": ["internal"]}]}),
                "",
            )
        )

        self.assertFalse(probe.detect_supported_devices())

    def test_reports_none_when_fwupd_probe_fails_or_returns_invalid_json(self) -> None:
        failed_probe = FirmwareDeviceSupportProbe(run=lambda _command, _timeout: (1, "", "failed"))
        invalid_probe = FirmwareDeviceSupportProbe(
            run=lambda _command, _timeout: (0, "not-json", "")
        )

        self.assertIsNone(failed_probe.detect_supported_devices())
        self.assertIsNone(invalid_probe.detect_supported_devices())

    def test_boolean_fwupd_capabilities_count_as_supported(self) -> None:
        probe = FirmwareDeviceSupportProbe(
            run=lambda _command, _timeout: (
                0,
                json.dumps({"devices": [{"Name": "Dock", "Updateable": True}]}),
                "",
            )
        )

        self.assertTrue(probe.detect_supported_devices())


if __name__ == "__main__":
    unittest.main()
