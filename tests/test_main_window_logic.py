from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from archupdater.domain.enums import OperationState, UpdateSource
from archupdater.domain.package_metadata import (
    AurPackageMetadata,
    FirmwarePackageMetadata,
    FlatpakPackageMetadata,
    PlasmaWidgetPackageMetadata,
    SystemPackageMetadata,
)
from archupdater.domain.packages import PackageUpdate
from archupdater.presentation.main_window.logic import (
    build_update_plan,
    check_completion_message,
    details_placeholder_text,
    system_status_summary,
    update_status_messages,
)


class MainWindowLogicTests(unittest.TestCase):
    def test_build_update_plan_groups_selected_packages_by_backend(self) -> None:
        packages = [
            PackageUpdate(
                "linux",
                "1",
                "2",
                UpdateSource.SYSTEM,
                SystemPackageMetadata(),
            ),
            PackageUpdate(
                "paru-pkg",
                "1",
                "2",
                UpdateSource.AUR,
                AurPackageMetadata(),
                selected=True,
            ),
            PackageUpdate(
                "Flatseal",
                "1",
                "2",
                UpdateSource.FLATPAK,
                FlatpakPackageMetadata(
                    ref="com.github.tchx84.Flatseal",
                    installation_scope="user",
                ),
                backend_id="com.github.tchx84.Flatseal",
                selected=True,
            ),
            PackageUpdate(
                "BIOS",
                "1",
                "2",
                UpdateSource.FIRMWARE,
                FirmwarePackageMetadata(device_id="device-1"),
                backend_id="device-1",
                selected=False,
            ),
            PackageUpdate(
                "Example Widget",
                "1.0",
                "1.1",
                UpdateSource.PLASMA_WIDGET,
                PlasmaWidgetPackageMetadata(
                    content_id="5555",
                    package_kind="Plasma/Applet",
                    plugin_id="com.example.widget",
                ),
                backend_id="5555",
                selected=True,
            ),
        ]

        plan = build_update_plan(packages)

        self.assertEqual(plan.target_ids(UpdateSource.SYSTEM), ["linux"])
        self.assertEqual(plan.target_ids(UpdateSource.AUR), ["paru-pkg"])
        self.assertEqual(
            [
                (item.target_id, item.installation_scope)
                for item in plan.update_items(UpdateSource.FLATPAK)
            ],
            [("com.github.tchx84.Flatseal", "user")],
        )
        self.assertEqual(plan.target_ids(UpdateSource.FIRMWARE), [])
        self.assertEqual(
            [
                (item.target_id, item.package_kind, item.plugin_id)
                for item in plan.update_items(UpdateSource.PLASMA_WIDGET)
            ],
            [("5555", "Plasma/Applet", "com.example.widget")],
        )

    def test_system_status_summary_reports_warning_state_without_updates(self) -> None:
        self.assertEqual(
            system_status_summary(0, has_warnings=True),
            "Checked with Warnings",
        )

    def test_build_update_plan_cannot_encode_a_partial_pacman_transaction(self) -> None:
        packages = [
            PackageUpdate(
                "linux",
                "1",
                "2",
                UpdateSource.SYSTEM,
                SystemPackageMetadata(repository="core"),
                selected=True,
            ),
            PackageUpdate(
                "glibc",
                "1",
                "2",
                UpdateSource.SYSTEM,
                SystemPackageMetadata(repository="core"),
                selected=False,
            ),
            PackageUpdate(
                "linux-lts",
                "1",
                "2",
                UpdateSource.SYSTEM,
                SystemPackageMetadata(repository="core"),
                selected=False,
                selection_locked=True,
                blocked_by_config=True,
                blocked_reason="Blocked by pacman.conf",
            ),
        ]

        plan = build_update_plan(packages)

        self.assertEqual(plan.target_ids(UpdateSource.SYSTEM), ["linux", "glibc"])

    def test_check_completion_message_prefers_warnings_over_up_to_date(self) -> None:
        self.assertEqual(
            check_completion_message(package_count=0, warning_count=1),
            "Refresh completed with warnings.",
        )

    def test_details_placeholder_depends_on_state_and_packages(self) -> None:
        self.assertEqual(
            details_placeholder_text(
                current_state=OperationState.CHECKING,
                has_packages=False,
            ),
            "Checking for updates...",
        )
        self.assertEqual(
            details_placeholder_text(
                current_state=OperationState.COMPLETED,
                has_packages=False,
            ),
            "Your system is up to date.\nNew updates will appear here after the next refresh.",
        )
        self.assertEqual(
            details_placeholder_text(
                current_state=OperationState.ERROR,
                has_packages=True,
            ),
            "Select an update to view details",
        )
        self.assertEqual(
            details_placeholder_text(
                current_state=OperationState.ERROR,
                has_packages=False,
                failure_message="refresh failed",
            ),
            "Details are unavailable because the last refresh did not complete.\n\n"
            "Error: refresh failed",
        )

    def test_update_status_messages_maps_known_runner_statuses(self) -> None:
        self.assertEqual(
            update_status_messages("running_system", translate=lambda value: value),
            ("Running pacman update...", "Updating pacman packages"),
        )
        self.assertIsNone(update_status_messages("custom-status", translate=lambda value: value))


if __name__ == "__main__":
    unittest.main()
