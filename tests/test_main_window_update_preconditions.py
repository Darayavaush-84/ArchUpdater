from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from PySide6.QtWidgets import QApplication

from archupdater.domain.enums import UpdateSource
from archupdater.domain.package_metadata import AurPackageMetadata
from archupdater.domain.packages import PackageUpdate
from archupdater.domain.update_plan import UpdatePlan, UpdatePlanItem
from archupdater.infrastructure.settings import AppSettings
from archupdater.presentation.main_window.state import MainWindowState
from archupdater.presentation.main_window.update_preconditions import MainWindowUpdatePreconditions


class _SettingsStub:
    def __init__(self) -> None:
        self.saved: list[AppSettings] = []

    def load_app_settings(self) -> AppSettings:
        return AppSettings()

    def save_app_settings(self, app_settings: AppSettings) -> None:
        self.saved.append(app_settings)

    def has_cleanup_unused_flatpak_runtimes_preference(self) -> bool:
        return True


class _ArchNewsCoordinatorStub:
    def confirm_before_update(self, _items, **_kwargs) -> bool:  # noqa: ANN001
        return True


class _PreflightCoordinatorStub:
    def confirm(self, _plan: UpdatePlan) -> bool:
        return True


class _WindowStub:
    def __init__(self) -> None:
        self._settings = _SettingsStub()
        self._background_behavior = self._settings
        self._arch_news_coordinator = _ArchNewsCoordinatorStub()
        self._preflight_coordinator = _PreflightCoordinatorStub()

    def tr(self, text: str) -> str:
        return text


class MainWindowUpdatePreconditionsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._app = QApplication.instance() or QApplication([])

    def test_aur_updates_are_preserved_for_batch_pkgbuild_review(self) -> None:
        state = MainWindowState(packages=[self._aur_package("spotify")])
        preconditions = MainWindowUpdatePreconditions(_WindowStub(), state)

        with (
            patch(
                "archupdater.presentation.main_window.update_preconditions.ask_flatpak_cleanup_scopes",
                return_value=[],
            ),
        ):
            result = preconditions.confirm(UpdatePlan(items=[UpdatePlanItem(UpdateSource.AUR, "spotify")]))

        self.assertIsNotNone(result)
        assert result is not None
        self.assertEqual(result.target_ids(UpdateSource.AUR), ["spotify"])
        self.assertEqual(state.active_update_packages[0].name, "spotify")

    def test_arch_news_cancel_still_cancels_update_plan_before_batch(self) -> None:
        state = MainWindowState(packages=[self._aur_package("spotify")])
        window = _WindowStub()
        window._arch_news_coordinator.confirm_before_update = (
            lambda _items, **_kwargs: False
        )
        preconditions = MainWindowUpdatePreconditions(window, state)

        result = preconditions.confirm(UpdatePlan(items=[UpdatePlanItem(UpdateSource.AUR, "spotify")]))

        self.assertIsNone(result)
        self.assertEqual(state.active_update_packages, [])

    def _aur_package(self, name: str) -> PackageUpdate:
        return PackageUpdate(
            name=name,
            current_version="1.0-1",
            new_version="1.1-1",
            source=UpdateSource.AUR,
            source_metadata=AurPackageMetadata(package_base=name),
            backend_id=name,
        )


if __name__ == "__main__":
    unittest.main()
