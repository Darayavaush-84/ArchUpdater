from __future__ import annotations

import sys
import unittest
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from archupdater.domain.check_results import UpdateCheckResult
from archupdater.domain.enums import UpdateSource
from archupdater.domain.package_metadata import AurPackageMetadata, SystemPackageMetadata
from archupdater.domain.packages import PackageUpdate
from archupdater.presentation.tray_status import TrayStatusModel


def _package(
    name: str,
    source: UpdateSource,
    *,
    blocked_by_config: bool = False,
) -> PackageUpdate:
    metadata = SystemPackageMetadata() if source is UpdateSource.SYSTEM else AurPackageMetadata()
    return PackageUpdate(
        name=name,
        current_version="1",
        new_version="2",
        source=source,
        source_metadata=metadata,
        selected=not blocked_by_config,
        selection_locked=blocked_by_config,
        blocked_by_config=blocked_by_config,
        blocked_reason="Blocked by pacman.conf" if blocked_by_config else None,
    )


class TrayStatusModelTests(unittest.TestCase):
    def test_check_result_counts_only_actionable_updates(self) -> None:
        model = TrayStatusModel(lambda text: text)
        result = UpdateCheckResult(
            packages=[
                _package("linux", UpdateSource.SYSTEM),
                _package("paru-pkg", UpdateSource.AUR),
                _package("nvidia", UpdateSource.SYSTEM, blocked_by_config=True),
            ],
            checked_at=datetime.now(),
            logs=[],
        )

        model.apply_check_result(result)

        self.assertEqual(model.available_updates_count, 2)
        self.assertEqual(model.ignored_updates_count, 1)
        self.assertEqual(model.counters.system, 1)
        self.assertEqual(model.counters.aur, 1)
        self.assertEqual(
            model.updates_signature(result),
            ("aur::paru-pkg", "system::linux"),
        )

    def test_tooltip_includes_breakdown_ignored_and_next_check(self) -> None:
        model = TrayStatusModel(lambda text: text)
        model.apply_check_result(
            UpdateCheckResult(
                packages=[
                    _package("linux", UpdateSource.SYSTEM),
                    _package("paru-pkg", UpdateSource.AUR),
                    _package("nvidia", UpdateSource.SYSTEM, blocked_by_config=True),
                ],
                checked_at=datetime.now(),
                logs=[],
            )
        )

        tooltip = model.tooltip(datetime(2026, 6, 3, 10, 30))

        self.assertIn("ArchUpdater: 2 updates available", tooltip)
        self.assertIn("System: 1, AUR: 1", tooltip)
        self.assertIn("Ignored by pacman.conf: 1", tooltip)
        self.assertIn("Next check: 2026-06-03 10:30", tooltip)

    def test_failed_check_clears_stale_count_and_reports_failure(self) -> None:
        model = TrayStatusModel(lambda text: text)
        model.available_updates_count = 12
        model.has_successful_check_result = True

        model.apply_check_failure("network unavailable")

        self.assertEqual(model.available_updates_count, 0)
        self.assertFalse(model.has_successful_check_result)
        self.assertTrue(model.has_check_failure)
        self.assertEqual(
            model.tooltip(),
            "ArchUpdater: Last check failed\nnetwork unavailable",
        )

    def test_refresh_pending_tooltip_does_not_claim_up_to_date(self) -> None:
        model = TrayStatusModel(lambda text: text)
        model.has_successful_check_result = True

        model.mark_refresh_pending()

        self.assertEqual(model.tooltip(), "ArchUpdater: Refreshing update status...")

    def test_update_status_sets_busy_tooltip(self) -> None:
        model = TrayStatusModel(lambda text: text)

        self.assertTrue(model.mark_update_status("running_system"))

        self.assertEqual(
            model.tooltip(),
            "ArchUpdater: Installing system updates...",
        )


if __name__ == "__main__":
    unittest.main()
