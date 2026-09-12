from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from archupdater.domain.check_results import SourceCheckResult
from archupdater.domain.check_results import ArchNewsCheckState, CheckState
from archupdater.domain.enums import UpdateSource
from archupdater.container import ApplicationContainer
from archupdater.application.update_sources.check_coordinator import UpdateCheckCancelled
from archupdater.services.optional_sources import OptionalSourcesService
from archupdater.services.pacman import PacmanServiceError


class _FailingPacman:
    def check_updates(self, progress_callback=None, *, use_local_db=False):  # noqa: ANN001
        raise PacmanServiceError("pacman temp db failed", logs=["pacman-log"])


class _CleanPacman:
    def __init__(self) -> None:
        self.use_local_db_calls: list[bool] = []

    def check_updates(self, progress_callback=None, *, use_local_db=False):  # noqa: ANN001
        from datetime import datetime

        from archupdater.domain.check_results import UpdateCheckResult

        self.use_local_db_calls.append(use_local_db)
        return UpdateCheckResult(packages=[], checked_at=datetime.now(), logs=[])


class _OptionalBackend:
    def __init__(self, name: str) -> None:
        self.name = name
        self.calls = 0

    def check_updates(self) -> SourceCheckResult:
        self.calls += 1
        return SourceCheckResult(warnings=[f"{self.name}-warning"])


class _CrashingBackend:
    def __init__(self, message: str) -> None:
        self.message = message

    def check_updates(self) -> SourceCheckResult:
        raise RuntimeError(self.message)


class _NewsFailure:
    def fetch(self):  # noqa: ANN201
        return type("NewsResult", (), {"items": [], "warning": "news unavailable"})()


class _NewsSuccess:
    def fetch(self):  # noqa: ANN201
        return type("NewsResult", (), {"items": [], "warning": None})()


class UpdateServiceTests(unittest.TestCase):
    def _container(self) -> ApplicationContainer:
        container = ApplicationContainer()
        container.arch_news = _NewsSuccess()  # type: ignore[assignment]
        return container

    def test_system_backend_failure_stops_refresh(self) -> None:
        container = self._container()
        service = container.updates()
        container.pacman_updates = _FailingPacman()
        container.aur_updates = _OptionalBackend("aur")
        container.flatpak_updates = _OptionalBackend("flatpak")
        container.plasma_widget_checks = _OptionalBackend("widgets")
        container.firmware_updates = _OptionalBackend("firmware")

        with self.assertRaises(PacmanServiceError) as context:
            service.check_updates()

        self.assertEqual(str(context.exception), "pacman temp db failed")
        self.assertEqual(context.exception.logs, ["pacman-log"])
        self.assertEqual(container.aur_updates.calls, 0)
        self.assertEqual(container.flatpak_updates.calls, 0)
        self.assertEqual(container.plasma_widget_checks.calls, 0)
        self.assertEqual(container.firmware_updates.calls, 0)

    def test_cancellation_before_first_backend_does_not_start_a_check(self) -> None:
        container = self._container()
        service = container.updates()
        pacman = _CleanPacman()
        container.pacman_updates = pacman

        with self.assertRaises(UpdateCheckCancelled):
            service.check_updates(cancel_requested=lambda: True)

        self.assertEqual(pacman.use_local_db_calls, [])

    def test_skips_optional_backends_that_are_not_active(self) -> None:
        container = self._container()
        service = container.updates()
        container.pacman_updates = _CleanPacman()
        container.aur_updates = _OptionalBackend("aur")
        container.flatpak_updates = _OptionalBackend("flatpak")
        container.plasma_widget_checks = _OptionalBackend("widgets")
        container.firmware_updates = _OptionalBackend("firmware")

        result = service.check_updates(active_optional_sources={UpdateSource.FLATPAK})

        self.assertIn("flatpak-warning", result.warnings)
        self.assertNotIn("aur-warning", result.warnings)
        self.assertNotIn("widgets-warning", result.warnings)
        self.assertNotIn("firmware-warning", result.warnings)
        self.assertEqual(container.aur_updates.calls, 0)
        self.assertEqual(container.flatpak_updates.calls, 1)
        self.assertEqual(container.plasma_widget_checks.calls, 0)
        self.assertEqual(container.firmware_updates.calls, 0)

    def test_default_check_skips_aur_when_helper_exists_but_user_has_not_enabled_it(self) -> None:
        container = self._container()
        service = container.updates()
        container.optional_sources = OptionalSourcesService(
            which=lambda name: "/usr/bin/paru" if name == "paru" else None
        )
        container.pacman_updates = _CleanPacman()
        container.aur_updates = _OptionalBackend("aur")

        result = service.check_updates()

        self.assertNotIn("aur-warning", result.warnings)
        self.assertEqual(container.aur_updates.calls, 0)

    def test_can_use_local_pacman_database_for_system_refresh(self) -> None:
        container = self._container()
        service = container.updates()
        pacman = _CleanPacman()
        container.pacman_updates = pacman
        container.aur_updates = _OptionalBackend("aur")
        container.flatpak_updates = _OptionalBackend("flatpak")
        container.plasma_widget_checks = _OptionalBackend("widgets")
        container.firmware_updates = _OptionalBackend("firmware")

        service.check_updates(use_local_system_db=True)

        self.assertEqual(pacman.use_local_db_calls, [True])

    def test_optional_backend_exception_becomes_warning_and_does_not_stop_refresh(self) -> None:
        container = self._container()
        service = container.updates()
        container.pacman_updates = _CleanPacman()
        container.aur_updates = _CrashingBackend("aur crashed")
        container.flatpak_updates = _OptionalBackend("flatpak")
        container.plasma_widget_checks = _OptionalBackend("widgets")
        container.firmware_updates = _OptionalBackend("firmware")

        result = service.check_updates(
            active_optional_sources={
                UpdateSource.AUR,
                UpdateSource.FLATPAK,
                UpdateSource.PLASMA_WIDGET,
                UpdateSource.FIRMWARE,
            }
        )

        self.assertIn("AUR updates could not be checked: aur crashed", result.warnings)
        self.assertIn("flatpak-warning", result.warnings)
        self.assertIn("widgets-warning", result.warnings)
        self.assertIn("firmware-warning", result.warnings)

    def test_result_reports_failed_source_and_failed_news_separately(self) -> None:
        container = ApplicationContainer()
        container.arch_news = _NewsFailure()  # type: ignore[assignment]
        service = container.updates()
        container.pacman_updates = _CleanPacman()
        container.aur_updates = _CrashingBackend("rpc down")

        result = service.check_updates(active_optional_sources={UpdateSource.AUR})

        reports = {report.source: report for report in result.source_reports}
        self.assertEqual(reports[UpdateSource.SYSTEM].state, CheckState.SUCCESS)
        self.assertEqual(reports[UpdateSource.AUR].state, CheckState.FAILED)
        self.assertEqual(result.arch_news_state, ArchNewsCheckState.FAILED)

if __name__ == "__main__":
    unittest.main()
