from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from archupdater.domain.enums import PreflightSeverity, UpdateSource
from archupdater.domain.package_metadata import (
    AurPackageMetadata,
    FlatpakPackageMetadata,
    SystemPackageMetadata,
)
from archupdater.domain.packages import PackageUpdate
from archupdater.domain.update_plan import UpdatePlan, UpdatePlanAction, UpdatePlanItem
from archupdater.application.preflight import UpdatePreflightService
from support.environment import FakePreflightEnvironment


class PreflightServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self._directory = tempfile.TemporaryDirectory()
        self.addCleanup(self._directory.cleanup)
        self.root = Path(self._directory.name)
        self.helper = self.root / "archupdater-helper"
        self.helper.touch()
        self.environment = FakePreflightEnvironment()

    def _service(
        self,
        *,
        command_runner=None,
        **kwargs,
    ) -> UpdatePreflightService:
        kwargs.setdefault("privileged_helper_path", self.helper)
        kwargs.setdefault("pacman_lock_path", self.root / "db.lck")
        self.environment.command_runner = command_runner
        return UpdatePreflightService(
            environment=self.environment,
            **kwargs,
        )

    def _plan(self, *items: UpdatePlanItem) -> UpdatePlan:
        return UpdatePlan(items=list(items))

    def _update_item(self, source: UpdateSource, target_id: str) -> UpdatePlanItem:
        return UpdatePlanItem(source, target_id)

    def _flatpak_item(self, ref: str, scope: str = "system") -> UpdatePlanItem:
        return UpdatePlanItem(UpdateSource.FLATPAK, ref, installation_scope=scope)

    def _flatpak_cleanup_item(self, scope: str) -> UpdatePlanItem:
        return UpdatePlanItem(
            UpdateSource.FLATPAK,
            scope,
            action=UpdatePlanAction.CLEANUP,
            installation_scope=scope,
        )

    def test_pacman_lock_blocks_system_update(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            lock_path = Path(tmp) / "db.lck"
            lock_path.write_text("", encoding="utf-8")
            service = self._service(pacman_lock_path=lock_path)

            issues = service.check(self._plan(self._update_item(UpdateSource.SYSTEM, "linux")), [])

        self.assertEqual(len(issues), 1)
        self.assertEqual(issues[0].severity, PreflightSeverity.BLOCKING)
        self.assertIn("lock", issues[0].message.lower())

    def test_missing_flatpak_blocks_flatpak_update(self) -> None:
        service = self._service()

        with patch.object(self.environment, "command_available", return_value=False):
            issues = service.check(self._plan(self._flatpak_cleanup_item("user")), [])

        self.assertEqual(issues[0].severity, PreflightSeverity.BLOCKING)
        self.assertIn("flatpak", issues[0].message.lower())

    def test_missing_kpackagetool_blocks_plasma_widget_update(self) -> None:
        service = self._service()

        def which(command: str) -> str | None:
            return None if command == "kpackagetool6" else f"/usr/bin/{command}"

        with patch.object(self.environment, "command_available", side_effect=which):
            issues = service.check(
                self._plan(
                    UpdatePlanItem(
                        UpdateSource.PLASMA_WIDGET,
                        "123",
                        package_name="Widget",
                        package_kind="Plasma/Applet",
                    )
                ),
                [],
            )

        self.assertEqual(issues[0].severity, PreflightSeverity.BLOCKING)
        self.assertIn("kpackagetool6", issues[0].details[0])

    def test_missing_checkupdates_does_not_block_existing_system_update_plan(self) -> None:
        def which(command: str) -> str | None:
            return None if command == "checkupdates" else f"/usr/bin/{command}"

        def command_runner(command: list[str], _timeout: float) -> tuple[int, str, str]:
            if command == ["pacman-conf", "Architecture"]:
                return 0, "x86_64\n", ""
            raise AssertionError(f"unexpected command: {command}")

        service = self._service(
            pacman_lock_path=Path("/not-present"),
            command_runner=command_runner,
        )

        with (
            patch.object(self.environment, "command_available", side_effect=which),
        ):
            issues = service.check(self._plan(self._update_item(UpdateSource.SYSTEM, "linux")), [])

        self.assertEqual(issues, [])

    def test_missing_pkexec_or_helper_blocks_aur_only_update_plan(self) -> None:
        service = self._service(
            pacman_lock_path=Path("/not-present"),
            privileged_helper_path=Path("/missing/archupdater-helper"),
        )

        def which(command: str) -> str | None:
            return None if command == "pkexec" else f"/usr/bin/{command}"

        with (
            patch.object(self.environment, "command_available", side_effect=which),
        ):
            issues = service.check(self._plan(self._update_item(UpdateSource.AUR, "example")), [])

        self.assertEqual(issues[0].severity, PreflightSeverity.BLOCKING)
        self.assertIn("ArchUpdater helper", issues[0].message)
        self.assertIn("Missing command: pkexec", issues[0].details)
        self.assertTrue(any("archupdater-helper" in detail for detail in issues[0].details))

    def test_preflight_allows_valid_local_pacman_database_state(self) -> None:
        def command_runner(command: list[str], _timeout: float) -> tuple[int, str, str]:
            if command == ["pacman-conf", "Architecture"]:
                return 0, "x86_64\nx86_64_v4\n", ""
            raise AssertionError(f"unexpected command: {command}")

        service = self._service(
            pacman_lock_path=Path("/not-present"),
            command_runner=command_runner,
        )

        issues = service.check(self._plan(self._update_item(UpdateSource.SYSTEM, "linux")), [])

        self.assertEqual(issues, [])

    def test_preflight_does_not_block_system_update_on_stale_local_databases(self) -> None:
        def command_runner(command: list[str], _timeout: float) -> tuple[int, str, str]:
            if command == ["pacman-conf", "Architecture"]:
                return 0, "x86_64\nx86_64_v4\n", ""
            raise AssertionError(f"unexpected command: {command}")

        service = self._service(
            pacman_lock_path=Path("/not-present"),
            command_runner=command_runner,
        )

        issues = service.check(self._plan(self._update_item(UpdateSource.SYSTEM, "linux")), [])

        self.assertEqual(issues, [])

    def test_preflight_does_not_block_combined_system_and_aur_update_on_stale_local_databases(self) -> None:
        def command_runner(command: list[str], _timeout: float) -> tuple[int, str, str]:
            if command == ["pacman-conf", "Architecture"]:
                return 0, "x86_64\nx86_64_v4\n", ""
            raise AssertionError(f"unexpected command: {command}")

        service = self._service(
            pacman_lock_path=Path("/not-present"),
            command_runner=command_runner,
        )

        issues = service.check(
            self._plan(
                self._update_item(UpdateSource.SYSTEM, "linux"),
                self._update_item(UpdateSource.AUR, "example"),
            ),
            [],
        )

        self.assertEqual(issues, [])

    def test_preflight_allows_aur_when_pacman_databases_have_signature_warnings(self) -> None:
        def command_runner(command: list[str], _timeout: float) -> tuple[int, str, str]:
            raise AssertionError(f"unexpected command: {command}")

        def which(command: str) -> str | None:
            return (
                f"/usr/bin/{command}"
                if command in {"pacman", "git", "makepkg", "pkexec"}
                else None
            )

        service = self._service(
            pacman_lock_path=Path("/not-present"),
            command_runner=command_runner,
        )

        with (
            patch.object(self.environment, "command_available", side_effect=which),
        ):
            issues = service.check(self._plan(self._update_item(UpdateSource.AUR, "example")), [])

        self.assertEqual(issues, [])

    def test_aur_preflight_does_not_require_an_aur_helper(self) -> None:
        def command_runner(command: list[str], _timeout: float) -> tuple[int, str, str]:
            if command == ["pacman", "-Qu"]:
                return 0, "", ""
            raise AssertionError(f"unexpected command: {command}")

        service = self._service(
            pacman_lock_path=Path("/not-present"),
            command_runner=command_runner,
        )

        def which(command: str) -> str | None:
            return (
                f"/usr/bin/{command}"
                if command in {"pacman", "git", "makepkg", "pkexec"}
                else None
            )

        with (
            patch.object(self.environment, "command_available", side_effect=which),
        ):
            issues = service.check(self._plan(self._update_item(UpdateSource.AUR, "example")), [])

        self.assertEqual(issues, [])

    def test_aur_disk_warning_checks_build_and_pacman_caches(self) -> None:
        checked_paths: list[str] = []
        service = self._service(
            pacman_lock_path=Path("/not-present"),
            minimum_free_bytes=1024,
        )
        package = PackageUpdate(
            "aur-big",
            "1",
            "2",
            UpdateSource.AUR,
            AurPackageMetadata(),
            download_size="2 GiB",
        )

        def which(command: str) -> str | None:
            return (
                f"/usr/bin/{command}"
                if command in {"pacman", "git", "makepkg", "pkexec"}
                else None
            )

        def disk_space(path: Path):
            checked_paths.append(str(path))
            return path, 512 * 1024**2

        with (
            patch.object(self.environment, "command_available", side_effect=which),
            patch.object(self.environment, "disk_space", side_effect=disk_space),
        ):
            issues = service.check(self._plan(self._update_item(UpdateSource.AUR, "aur-big")), [package])

        self.assertTrue(any(issue.severity is PreflightSeverity.WARNING for issue in issues))
        self.assertTrue(any("pacman" in path for path in checked_paths))
        self.assertIn("/tmp", checked_paths)

    def test_user_flatpak_plan_does_not_check_system_flatpak_storage(self) -> None:
        checked_paths: list[str] = []
        service = self._service(minimum_free_bytes=1)

        def disk_space(path: Path):
            checked_paths.append(str(path))
            return path, 100 * 1024**3

        with (
            patch.object(self.environment, "command_available", return_value=True),
            patch.object(self.environment, "disk_space", side_effect=disk_space),
        ):
            issues = service.check(
                self._plan(self._flatpak_item("app/org.example.App/x86_64/stable", "user")),
                [],
            )

        self.assertEqual(issues, [])
        self.assertTrue(any(".local/share/flatpak" in path for path in checked_paths))
        self.assertNotIn("/var/lib/flatpak", checked_paths)

    def test_system_flatpak_plan_does_not_check_user_flatpak_storage(self) -> None:
        checked_paths: list[str] = []
        service = self._service(minimum_free_bytes=1)

        def disk_space(path: Path):
            checked_paths.append(str(path))
            return path, 100 * 1024**3

        with (
            patch.object(self.environment, "command_available", return_value=True),
            patch.object(self.environment, "disk_space", side_effect=disk_space),
        ):
            issues = service.check(
                self._plan(self._flatpak_item("app/org.example.App/x86_64/stable", "system")),
                [],
            )

        self.assertEqual(issues, [])
        self.assertIn("/var/lib/flatpak", checked_paths)
        self.assertFalse(any(".local/share/flatpak" in path for path in checked_paths))

    def test_disk_warning_uses_selected_download_estimate(self) -> None:
        service = self._service(
            pacman_lock_path=Path("/not-present"),
            minimum_free_bytes=1024,
        )
        package = PackageUpdate(
            "big-flatpak",
            "1",
            "2",
            UpdateSource.FLATPAK,
            FlatpakPackageMetadata(
                ref="app/org.example.Big/x86_64/stable",
                installation_scope="user",
            ),
            backend_id="app/org.example.Big/x86_64/stable",
            download_size="3 GiB",
        )

        with (
            patch.object(self.environment, "command_available", return_value=True),
            patch.object(self.environment, "disk_space") as disk_usage,
        ):
            disk_usage.side_effect = lambda path: (path, 2 * 1024**3)
            issues = service.check(
                self._plan(self._flatpak_item("app/org.example.Big/x86_64/stable", "user")),
                [package],
            )

        self.assertGreaterEqual(len(issues), 1)
        self.assertEqual(issues[0].severity, PreflightSeverity.WARNING)
        self.assertIn("3 GiB", issues[0].message)

    def test_selected_package_matching_keeps_sources_separate(self) -> None:
        service = self._service()
        system_package = PackageUpdate(
            "shared-name",
            "1",
            "2",
            UpdateSource.SYSTEM,
            SystemPackageMetadata(),
            backend_id="shared-id",
            download_size="1 GiB",
        )
        aur_package = PackageUpdate(
            "shared-aur",
            "1",
            "2",
            UpdateSource.AUR,
            AurPackageMetadata(),
            backend_id="shared-id",
            download_size="9 GiB",
        )

        selected = service._selected_packages(
            self._plan(self._update_item(UpdateSource.SYSTEM, "shared-id")),
            [system_package, aur_package],
        )

        self.assertEqual(selected, [system_package])


if __name__ == "__main__":
    unittest.main()
