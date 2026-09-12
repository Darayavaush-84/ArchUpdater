from __future__ import annotations

import sys
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from PySide6.QtCore import QEventLoop, QTimer, Qt
from support.network import FakeReachability, FakeNetworkInformation, FakeNetworkInformationApi
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QToolButton

from archupdater.domain.arch_news import ArchNewsItem
from archupdater.domain.check_results import CheckState, SourceCheckReport, UpdateCheckResult
from archupdater.domain.enums import OperationState, UpdateSource
from archupdater.domain.optional_sources import OptionalSourceStatus, OptionalSourcesSnapshot
from archupdater.domain.package_metadata import (
    AurPackageMetadata,
    FirmwarePackageMetadata,
    FlatpakPackageMetadata,
    PlasmaWidgetPackageMetadata,
    SystemPackageMetadata,
)
from archupdater.domain.progress import UpdateProgressSnapshot
from archupdater.presentation.main_window import MainWindow
from archupdater.presentation.arch_news_dialog import ArchNewsDialogResult
from archupdater.presentation.widgets.status_header import CounterCardWidget
from archupdater.application.update_session.protocol import BatchOutcome
from archupdater.services.pacman import PacmanServiceError
from archupdater.infrastructure.settings import AppSettings


class FakeSettingsService:
    def __init__(
        self,
        *,
        auto_check_enabled: bool = False,
        auto_check_interval_hours: int = 24,
        cleanup_unused_flatpak_runtimes: bool = False,
        cleanup_preference_set: bool = True,
    ) -> None:
        self.auto_check_enabled = auto_check_enabled
        self.auto_check_interval_hours = auto_check_interval_hours
        self.cleanup_unused_flatpak_runtimes = cleanup_unused_flatpak_runtimes
        self.cleanup_preference_set = cleanup_preference_set

    def load_app_settings(self, default_start_on_login: bool = False) -> AppSettings:
        return AppSettings(
            start_on_login=default_start_on_login,
            systray_enabled=False,
            systray_notifications_enabled=False,
            auto_check_enabled=self.auto_check_enabled,
            auto_check_interval_hours=self.auto_check_interval_hours,
            cleanup_unused_flatpak_runtimes=self.cleanup_unused_flatpak_runtimes,
        )

    def save_app_settings(self, app_settings: AppSettings) -> None:
        self.auto_check_enabled = app_settings.auto_check_enabled
        self.auto_check_interval_hours = app_settings.auto_check_interval_hours
        self.cleanup_unused_flatpak_runtimes = app_settings.cleanup_unused_flatpak_runtimes
        self.cleanup_preference_set = True
        return None

    def has_cleanup_unused_flatpak_runtimes_preference(self) -> bool:
        return self.cleanup_preference_set


class FakeStateCache:
    def __init__(self, *, unclean: bool = False) -> None:
        self.unclean = unclean
        self.read_arch_news_ids: set[str] = set()
        self.deleted_arch_news_ids: set[str] = set()
        self.arch_news_items: list[ArchNewsItem] = []

    def load_arch_news_items(self) -> list[ArchNewsItem]:
        return [
            item for item in self.arch_news_items if item.item_id not in self.deleted_arch_news_ids
        ]

    def store_arch_news_items(self, items: list[ArchNewsItem]) -> None:
        merged = {item.item_id: item for item in self.arch_news_items if item.item_id}
        for item in items:
            if item.item_id and item.item_id not in self.deleted_arch_news_ids:
                merged[item.item_id] = item
        self.arch_news_items = list(merged.values())

    def delete_arch_news_items(self, item_ids: set[str]) -> None:
        self.deleted_arch_news_ids.update(item_ids)
        self.arch_news_items = [
            item for item in self.arch_news_items if item.item_id not in self.deleted_arch_news_ids
        ]

    def has_unclean_update_session(self) -> bool:
        return self.unclean

    def mark_update_session_started(self) -> None:
        self.unclean = True

    def clear_update_session(self) -> None:
        self.unclean = False

    def load_read_arch_news_ids(self) -> set[str]:
        return set(self.read_arch_news_ids)

    def mark_arch_news_read(self, items: list[ArchNewsItem]) -> None:
        self.read_arch_news_ids.update(item.item_id for item in items)

    def load_deleted_arch_news_ids(self) -> set[str]:
        return set(self.deleted_arch_news_ids)


class FakeUpdateService:
    def __init__(
        self,
        result: UpdateCheckResult,
        *,
        snapshot: OptionalSourcesSnapshot | None = None,
    ) -> None:
        self._result = result
        self.check_calls = 0
        self.local_system_db_calls: list[bool] = []
        self._snapshot = snapshot or OptionalSourcesSnapshot(
            statuses={
                UpdateSource.AUR: OptionalSourceStatus(
                    source=UpdateSource.AUR,
                    installed=True,
                    active=True,
                    status_text="Installed",
                ),
                UpdateSource.FLATPAK: OptionalSourceStatus(
                    source=UpdateSource.FLATPAK,
                    installed=True,
                    active=True,
                    status_text="Installed",
                ),
                UpdateSource.PLASMA_WIDGET: OptionalSourceStatus(
                    source=UpdateSource.PLASMA_WIDGET,
                    installed=True,
                    active=True,
                    status_text="Installed",
                ),
                UpdateSource.FIRMWARE: OptionalSourceStatus(
                    source=UpdateSource.FIRMWARE,
                    installed=True,
                    active=True,
                    status_text="Installed",
                ),
            }
        )

    def check_updates(  # noqa: ANN001
        self,
        progress_callback=None,
        active_optional_sources=None,
        use_local_system_db=False,
        cancel_requested=None,
    ) -> UpdateCheckResult:
        self.check_calls += 1
        self.local_system_db_calls.append(use_local_system_db)
        if progress_callback is not None:
            progress_callback("Preparing", 10)
            progress_callback("Completed", 100)
        return self._result

    def can_restart_plasma_shell(self) -> bool:
        return False

    def restart_plasma_shell(self) -> bool:
        return False

    def optional_sources_snapshot(self) -> OptionalSourcesSnapshot:
        return self._snapshot


class FailingUpdateService(FakeUpdateService):
    def check_updates(  # noqa: ANN001
        self,
        progress_callback=None,
        active_optional_sources=None,
        use_local_system_db=False,
        cancel_requested=None,
    ) -> UpdateCheckResult:
        self.check_calls += 1
        self.local_system_db_calls.append(use_local_system_db)
        raise PacmanServiceError("checkupdates failed", logs=[])


class FailsAfterFirstCheckService(FakeUpdateService):
    def check_updates(  # noqa: ANN001
        self,
        progress_callback=None,
        active_optional_sources=None,
        use_local_system_db=False,
        cancel_requested=None,
    ) -> UpdateCheckResult:
        if self.check_calls == 0:
            return super().check_updates(
                progress_callback=progress_callback,
                active_optional_sources=active_optional_sources,
                use_local_system_db=use_local_system_db,
                cancel_requested=cancel_requested,
            )
        self.check_calls += 1
        self.local_system_db_calls.append(use_local_system_db)
        raise PacmanServiceError("post-update refresh failed", logs=[])








class MainWindowIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._app = QApplication.instance() or QApplication([])

    def setUp(self) -> None:
        self.window: MainWindow | None = None
        release_check = patch("archupdater.infrastructure.app_releases.AppReleaseChecker.check")
        release_check.start()
        self.addCleanup(release_check.stop)
        network = FakeNetworkInformation(FakeReachability.Online)
        network_patch = patch(
            "archupdater.presentation.check_schedule.QNetworkInformation",
            FakeNetworkInformationApi(network),
        )
        network_patch.start()
        self.addCleanup(network_patch.stop)

    def tearDown(self) -> None:
        if self.window is not None:
            self.window.update_controller.shutdown()
            self.window._allow_close = True
            self.window.close()
            self.window.deleteLater()
        self._process_events(50)

    def test_github_opens_releases_only_when_newer_version_was_detected(self) -> None:
        self.window = self._create_window(packages=[])
        checker = self.window._release_checker
        with patch("archupdater.presentation.main_window.window.QDesktopServices.openUrl") as open_url:
            self.window.action_bar.github_button.click()
            self.assertEqual(open_url.call_args.args[0].toString(),
                             "https://github.com/Darayavaush-84/ArchUpdater")
            checker.available_tag = "v1.1.0"
            checker.release_checked.emit(checker.available_tag)
            self.assertEqual(self.window.action_bar.github_button.text(), "Update")
            self.window.action_bar.github_button.click()
            self.assertEqual(open_url.call_args.args[0].toString(),
                             "https://github.com/Darayavaush-84/ArchUpdater/releases/latest")

    def test_first_scan_populates_list_without_auto_selecting_details(self) -> None:
        self.window = self._create_window(
            packages=[
                self._package("linux", UpdateSource.SYSTEM, repository="core"),
                self._package("flatseal", UpdateSource.FLATPAK, repository="flathub"),
            ]
        )

        self.assertEqual(self._visible_package_names(), ["flatseal", "linux"])
        self.assertEqual(self.window.package_updates_widget.tree.selectedItems(), [])
        self.assertEqual(self.window.details_panel._placeholder_title.text(), "Package Details")
        self.assertEqual(
            self.window.details_panel._details_placeholder.text(),
            "Select an update to view details",
        )

        first_item = self.window.package_updates_widget.tree.topLevelItem(0)
        self._click_tree_item(first_item)

        self.assertEqual(self.window.details_panel._detail_name.text(), "flatseal")
        self.assertEqual(self.window.details_panel._detail_repository.text(), "flathub")

    def test_kpi_click_filters_the_visible_list_in_main_window(self) -> None:
        self.window = self._create_window(
            packages=[
                self._package("linux", UpdateSource.SYSTEM, repository="core"),
                self._package("paru-bin", UpdateSource.AUR, repository="AUR"),
                self._package("flatseal", UpdateSource.FLATPAK, repository="flathub"),
            ]
        )

        flatpak_card = self._counter_card(UpdateSource.FLATPAK)
        self._click_widget(flatpak_card)

        self.assertEqual(self._visible_package_names(), ["flatseal"])
        self.assertEqual(
            self.window.package_updates_widget.title_label.text(),
            "Flatpak Updates",
        )

        self._click_widget(flatpak_card)

        self.assertEqual(
            self._visible_package_names(),
            ["flatseal", "linux", "paru-bin"],
        )
        self.assertEqual(
            self.window.package_updates_widget.title_label.text(),
            "All Updates",
        )

    def test_github_button_opens_project_repository(self) -> None:
        self.window = self._create_window(packages=[])

        with patch("archupdater.presentation.main_window.window.QDesktopServices.openUrl") as open_url:
            self.window.action_bar.github_button.click()

        self.assertEqual(open_url.call_count, 1)
        self.assertEqual(
            open_url.call_args.args[0].toString(),
            "https://github.com/Darayavaush-84/ArchUpdater",
        )

    def test_update_button_starts_when_flatpak_cleanup_preference_is_saved(self) -> None:
        settings = FakeSettingsService(
            cleanup_unused_flatpak_runtimes=True,
            cleanup_preference_set=True,
        )
        self.window = self._create_window(
            packages=[
                self._package(
                    "flatseal",
                    UpdateSource.FLATPAK,
                    repository="flathub",
                    installation_scope="user",
                )
            ],
            settings=settings,
        )
        started_plans = []
        self.window._preflight_coordinator.confirm = lambda _plan: True  # type: ignore[method-assign]
        self._wait_for_check(self.window)
        self.assertTrue(self.window.build_update_plan().has_any)
        self.assertFalse(self.window.update_controller.is_busy())
        self.window.refresh_selection_actions()
        self.assertTrue(self.window.action_bar.update_button.isEnabled())

        with patch.object(self.window.update_controller, "start_update", started_plans.append):
            self.window.action_bar.update_button.click()
            self._process_events(50)

        self.assertEqual(len(started_plans), 1)
        self.assertEqual(started_plans[0].cleanup_scopes(UpdateSource.FLATPAK), ["user"])

    def test_update_button_stays_disabled_until_post_update_refresh_finishes(self) -> None:
        self.window = self._create_window(
            packages=[
                self._package(
                    "flatseal",
                    UpdateSource.FLATPAK,
                    repository="flathub",
                    installation_scope="user",
                )
            ]
        )
        self._wait_for_check(self.window)

        with patch(
            "archupdater.presentation.update_completion_coordinator.QTimer.singleShot"
        ):
            self.window.apply_update_completed(
                True,
                "Selected updates completed.",
                BatchOutcome.SUCCESS.value,
            )

        self.assertTrue(self.window.has_post_update_refresh_pending())
        self.assertFalse(self.window.action_bar.update_button.isEnabled())

    def test_update_start_failure_closes_unfinished_progress_dialog(self) -> None:
        self.window = self._create_window(packages=[])
        self.window._handle_update_progress(
            UpdateProgressSnapshot(
                title="Installing Updates",
                subtitle="Starting the integrated update session.",
                steps=[],
                percent=0,
                present_dialog=True,
            )
        )
        self.assertIsNotNone(self.window._progress_presenter.dialog)

        self.window.handle_update_start_failure(OSError("disk full"))

        self.assertIsNone(self.window._progress_presenter.dialog)
        self.assertEqual(self.window._state.operation_state, OperationState.ERROR)

    def test_close_without_tray_is_blocked_while_operation_is_busy(self) -> None:
        self.window = self._create_window(packages=[])
        active_client = object()
        self.window.update_controller._update_client = active_client  # type: ignore[assignment]

        with patch("archupdater.presentation.main_window.window.QMessageBox.warning") as warning:
            closed = self.window.close()

        self.assertFalse(closed)
        self.assertTrue(self.window.isVisible())
        self.assertIs(self.window.update_controller._update_client, active_client)
        warning.assert_called_once()
        self.window.update_controller._update_client = None

    def test_close_with_tray_hides_busy_window_without_stopping_operation(self) -> None:
        self.window = self._create_window(packages=[])
        tray = type("TrayStub", (), {"is_active": lambda self: True})()
        self.window._tray_controller = tray  # type: ignore[assignment]
        active_client = object()
        self.window.update_controller._update_client = active_client  # type: ignore[assignment]

        with patch("archupdater.presentation.main_window.window.QMessageBox.warning") as warning:
            closed = self.window.close()

        self.assertFalse(closed)
        self.assertFalse(self.window.isVisible())
        self.assertIs(self.window.update_controller._update_client, active_client)
        warning.assert_not_called()
        self.window.update_controller._update_client = None
        self.window._tray_controller = None

    def test_quit_from_tray_is_blocked_while_operation_is_busy(self) -> None:
        self.window = self._create_window(packages=[])
        active_client = object()
        self.window.update_controller._update_client = active_client  # type: ignore[assignment]

        with patch("archupdater.presentation.main_window.window.QMessageBox.warning") as warning:
            self.window.quit_application_from_tray()

        self.assertFalse(self.window._allow_close)
        self.assertTrue(self.window.isVisible())
        self.assertIs(self.window.update_controller._update_client, active_client)
        warning.assert_called_once()
        self.window.update_controller._update_client = None

    def test_arch_news_button_is_available_and_marks_unread_news_after_dialog_accept(self) -> None:
        result = UpdateCheckResult(
            packages=[],
            checked_at=datetime.now(),
            logs=[],
            warnings=[],
            arch_news=[
                ArchNewsItem("news-1", "Unread news"),
                ArchNewsItem("news-2", "Read news", read=True),
            ],
        )
        state_cache = FakeStateCache()
        state_cache.read_arch_news_ids.add("news-2")
        self.window = MainWindow(
            service=FakeUpdateService(result),
            settings=FakeSettingsService(),
            state_cache=state_cache,
        )
        self.window.show()
        self._wait_for_check(self.window)
        self._process_events(50)

        self.assertFalse(self.window.action_bar.arch_news_button.isHidden())
        self.assertEqual(self.window.action_bar.arch_news_button.text(), "Arch News (1)")
        with patch.object(
            self.window,
            "_show_arch_news_dialog",
            return_value=ArchNewsDialogResult(accepted=True, deleted_read_ids=set()),
        ) as dialog:
            self.window._open_arch_news()

        self.assertEqual(state_cache.read_arch_news_ids, {"news-1", "news-2"})
        self.assertEqual(self.window.action_bar.arch_news_button.text(), "Arch News")
        self.assertEqual(dialog.call_args.kwargs["enable_ok"], True)

    def test_arch_news_dialog_receives_read_and_unread_items_even_without_unread_count(self) -> None:
        result = UpdateCheckResult(
            packages=[],
            checked_at=datetime.now(),
            logs=[],
            warnings=[],
            arch_news=[ArchNewsItem("news-2", "Read news", read=True)],
        )
        state_cache = FakeStateCache()
        state_cache.read_arch_news_ids.add("news-2")
        self.window = self._create_window(packages=[], result=result, state_cache=state_cache)

        with patch.object(
            self.window,
            "_show_arch_news_dialog",
            return_value=ArchNewsDialogResult(accepted=False, deleted_read_ids=set()),
        ) as dialog:
            self.window._open_arch_news()

        self.assertEqual(dialog.call_args.args[0], self.window._state.arch_news)
        self.assertEqual(dialog.call_args.kwargs["enable_ok"], False)

    def test_arch_news_history_loads_without_restoring_package_updates(self) -> None:
        service = FakeUpdateService(
            UpdateCheckResult(packages=[], checked_at=datetime.now(), logs=[], warnings=[])
        )
        state_cache = FakeStateCache()
        state_cache.arch_news_items = [ArchNewsItem("news-1", "Stored unread news")]

        self.window = MainWindow(
            service=service,
            settings=FakeSettingsService(),
            state_cache=state_cache,
        )

        self.assertEqual(self._visible_package_names(), [])
        self.assertEqual(self.window.header_widget.counter_labels["system"].text(), "0")
        self.assertEqual(self.window.action_bar.arch_news_button.text(), "Arch News (1)")

        self._process_events(50)
        self._wait_for_check(self.window)

        self.assertEqual(service.check_calls, 1)
        self.assertEqual(self._visible_package_names(), [])

    def test_arch_news_can_delete_selected_read_items_from_current_list(self) -> None:
        result = UpdateCheckResult(
            packages=[],
            checked_at=datetime.now(),
            logs=[],
            warnings=[],
            arch_news=[
                ArchNewsItem("news-1", "Unread news"),
                ArchNewsItem("news-2", "Read news", read=True),
                ArchNewsItem("news-3", "Another read news", read=True),
            ],
        )
        state_cache = FakeStateCache()
        state_cache.read_arch_news_ids.update({"news-2", "news-3"})
        self.window = self._create_window(packages=[], result=result, state_cache=state_cache)

        with patch.object(
            self.window,
            "_show_arch_news_dialog",
            return_value=ArchNewsDialogResult(accepted=False, deleted_read_ids={"news-2"}),
        ):
            self.window._open_arch_news()

        self.assertEqual([item.item_id for item in self.window._state.arch_news], ["news-1", "news-3"])
        self.assertEqual(state_cache.read_arch_news_ids, {"news-2", "news-3"})
        self.assertEqual(state_cache.deleted_arch_news_ids, {"news-2"})
        self.assertNotIn("news-2", [item.item_id for item in state_cache.arch_news_items])

    def test_no_updates_scan_shows_product_empty_state(self) -> None:
        self.window = self._create_window(packages=[])

        self.assertEqual(self.window.header_widget.system_status_label.text(), "Up to Date")
        self.assertEqual(self._visible_package_names(), [])
        self.assertFalse(self.window.action_bar.update_button.isEnabled())
        self.assertEqual(
            self.window.details_panel._placeholder_title.text(),
            "Your system is up to date.",
        )
        self.assertEqual(
            self.window.details_panel._details_placeholder.text(),
            "New updates will appear here after the next refresh.",
        )

    def test_failed_optional_check_shows_warnings_without_success_illustration(self) -> None:
        result = UpdateCheckResult(
            packages=[],
            checked_at=datetime.now(),
            logs=[],
            warnings=["Flatpak check failed"],
            source_reports=[SourceCheckReport(UpdateSource.FLATPAK, CheckState.FAILED)],
        )
        self.window = self._create_window(packages=[], result=result)

        self.assertEqual(
            self.window.header_widget.system_status_label.text(), "Checked with Warnings"
        )
        self.assertTrue(self.window.side_panel.isHidden())
        self.assertTrue(self.window.package_updates_widget.empty_illustration.isHidden())
        self.assertEqual(
            self.window.package_updates_widget.empty_title.text(), "Checked with Warnings"
        )

    def test_closing_details_restores_list_without_changing_update_selection(self) -> None:
        self.window = self._create_window(packages=[
            self._package("linux", UpdateSource.SYSTEM, repository="core"),
        ])
        self.assertTrue(self.window.side_panel.isHidden())
        item = self.window.package_updates_widget.tree.topLevelItem(0)
        checked = item.checkState(0)
        self._click_tree_item(item)
        self.assertTrue(self.window.side_panel.isVisible())

        self._click_widget(self.window.side_panel.findChild(QToolButton))

        self.assertTrue(self.window.side_panel.isHidden())
        self.assertEqual(item.checkState(0), checked)
        self.assertEqual(self.window.package_updates_widget.tree.selectedItems(), [])

    def test_check_failure_is_visible_in_main_content_without_success_illustration(self) -> None:
        self.window = self._create_window(packages=[])
        self.window._check_presenter.apply_fresh_check_failure_ui("Mirrors unavailable", [])

        self.assertTrue(self.window.side_panel.isHidden())
        self.assertTrue(self.window.package_updates_widget.empty_illustration.isHidden())
        self.assertEqual(
            self.window.package_updates_widget.empty_title.text(), "Update check failed"
        )
        self.assertEqual(
            self.window.package_updates_widget.empty_message.text(), "Mirrors unavailable"
        )

    def test_only_ignored_system_updates_keep_up_to_date_status_and_zero_kpi(self) -> None:
        self.window = self._create_window(
            packages=[
                self._package(
                    "linux",
                    UpdateSource.SYSTEM,
                    repository="core",
                    blocked_by_config=True,
                    blocked_reason="Blocked by pacman.conf",
                    selected=False,
                    selection_locked=True,
                )
            ]
        )

        self.assertEqual(self.window.header_widget.system_status_label.text(), "Up to Date")
        self.assertEqual(self.window.header_widget.counter_labels["system"].text(), "0")
        self.assertEqual(self._visible_package_names(), ["linux"])
        self.assertTrue(self.window.package_updates_widget.ignored_note_label.isVisible())

    def test_header_hides_optional_kpis_that_are_not_available(self) -> None:
        snapshot = OptionalSourcesSnapshot(
            statuses={
                UpdateSource.AUR: OptionalSourceStatus(
                    source=UpdateSource.AUR,
                    installed=True,
                    active=True,
                    status_text="Installed",
                ),
                UpdateSource.FLATPAK: OptionalSourceStatus(
                    source=UpdateSource.FLATPAK,
                    installed=False,
                    active=False,
                    status_text="Missing",
                ),
                UpdateSource.PLASMA_WIDGET: OptionalSourceStatus(
                    source=UpdateSource.PLASMA_WIDGET,
                    installed=False,
                    active=False,
                    status_text="Missing",
                ),
                UpdateSource.FIRMWARE: OptionalSourceStatus(
                    source=UpdateSource.FIRMWARE,
                    installed=False,
                    active=False,
                    status_text="Missing",
                ),
            }
        )
        self.window = self._create_window(
            packages=[self._package("linux", UpdateSource.SYSTEM, repository="core")],
            snapshot=snapshot,
        )

        self.assertTrue(self.window.header_widget._counter_cards[UpdateSource.SYSTEM].isVisible())
        self.assertTrue(self.window.header_widget._counter_cards[UpdateSource.AUR].isVisible())
        self.assertFalse(self.window.header_widget._counter_cards[UpdateSource.FLATPAK].isVisible())
        self.assertFalse(
            self.window.header_widget._counter_cards[UpdateSource.PLASMA_WIDGET].isVisible()
        )
        self.assertFalse(self.window.header_widget._counter_cards[UpdateSource.FIRMWARE].isVisible())

    def test_preferences_button_is_disabled_while_busy(self) -> None:
        self.window = self._create_window(packages=[])
        self.window._set_operation_state(
            OperationState.CHECKING,
            "Checking repositories and package metadata...",
        )

        self.assertFalse(self.window.action_bar.preferences_button.isEnabled())
        self.assertIn(
            "Preferences are not available while a scan or installation is running.",
            self.window.action_bar.preferences_button.toolTip(),
        )

    def test_failed_update_clears_selected_package_details(self) -> None:
        self.window = self._create_window(
            packages=[self._package("linux", UpdateSource.SYSTEM, repository="core")]
        )
        first_item = self.window.package_updates_widget.tree.topLevelItem(0)
        self._click_tree_item(first_item)

        self.window.apply_update_completed(False, "AUR update failed.", "failed")
        self._process_events(50)

        self.assertEqual(self.window.package_updates_widget.tree.selectedItems(), [])
        self.assertEqual(
            self.window.details_panel._details_placeholder.text(),
            "Select an update to view details",
        )

    def test_system_update_failure_shows_dedicated_warning(self) -> None:
        self.window = self._create_window(
            packages=[self._package("linux", UpdateSource.SYSTEM, repository="core")]
        )

        with patch("archupdater.presentation.main_window.window.QMessageBox.warning") as warning:
            self.window.apply_update_completed(
                False,
                "could not satisfy dependencies",
                BatchOutcome.SYSTEM_TRANSACTION_FAILED.value,
            )

        warning.assert_called_once()
        self.assertNotIn("could not satisfy dependencies", warning.call_args.args[2])
        self.assertIn("live activity log", warning.call_args.args[2])

    def test_post_update_refresh_failure_is_reported_as_error(self) -> None:
        result = UpdateCheckResult(
            packages=[self._package("linux", UpdateSource.SYSTEM, repository="core")],
            checked_at=datetime.now(),
            logs=[],
            warnings=[],
        )
        service = FailsAfterFirstCheckService(result)
        self.window = MainWindow(
            service=service,
            settings=FakeSettingsService(),
            state_cache=FakeStateCache(),
        )
        self.window.show()
        self._wait_for_check(self.window)
        self._process_events(50)

        with patch("archupdater.presentation.update_completion_coordinator.QTimer.singleShot") as timer:
            self.window.apply_update_completed(True, "Selected updates completed.", BatchOutcome.SUCCESS.value)

        timer.assert_called_once()
        self.window.apply_check_failure("post-update refresh failed", [])
        self._process_events(50)

        self.assertEqual(self.window._state.operation_state, OperationState.ERROR)
        self.assertEqual(self.window.header_widget.system_status_label.text(), "Error")
        self.assertEqual(
            self.window.action_bar.status_label.text(),
            "",
        )
        self.assertEqual(
            self.window.details_panel._details_placeholder.text(),
            "Details are unavailable because the last refresh did not complete.\n\n"
            "Error: post-update refresh failed",
        )
        self.assertEqual(self._visible_package_names(), [])

    def test_post_update_refresh_uses_local_system_database(self) -> None:
        package = self._package("bash", UpdateSource.SYSTEM, repository="core")
        result = UpdateCheckResult(
            packages=[],
            checked_at=datetime.now(),
            logs=[],
            warnings=[],
        )
        service = FakeUpdateService(result)
        self.window = MainWindow(
            service=service,
            settings=FakeSettingsService(),
            state_cache=FakeStateCache(),
        )
        self.window.show()
        self._wait_for_check(self.window)
        self._process_events(50)
        self.window._state.active_update_packages = [package]

        with patch("archupdater.presentation.update_completion_coordinator.QTimer.singleShot") as timer:
            self.window.apply_update_completed(True, "Selected updates completed.", BatchOutcome.SUCCESS.value)

        timer.call_args.args[1]()
        self._wait_for_check(self.window)
        self._process_events(50)

        self.assertEqual(service.local_system_db_calls, [False, True])

    def test_post_update_refresh_uses_normal_system_check_without_system_updates(self) -> None:
        result = UpdateCheckResult(
            packages=[],
            checked_at=datetime.now(),
            logs=[],
            warnings=[],
        )
        service = FakeUpdateService(result)
        self.window = MainWindow(
            service=service,
            settings=FakeSettingsService(),
            state_cache=FakeStateCache(),
        )
        self.window.show()
        self._wait_for_check(self.window)
        self._process_events(50)
        self.window._state.active_update_packages = [
            self._package("flatseal", UpdateSource.FLATPAK, repository="flathub")
        ]

        with patch("archupdater.presentation.update_completion_coordinator.QTimer.singleShot") as timer:
            self.window.apply_update_completed(True, "Selected updates completed.", BatchOutcome.SUCCESS.value)

        timer.call_args.args[1]()
        self._wait_for_check(self.window)
        self._process_events(50)

        self.assertEqual(service.local_system_db_calls, [False, False])

    def test_action_bar_does_not_repeat_checking_status_text(self) -> None:
        self.window = self._create_window(packages=[])

        self.window._set_operation_state(
            OperationState.CHECKING,
            "Checking repositories and package metadata...",
        )

        self.assertEqual(self.window.action_bar.status_label.text(), "")

    def test_unclean_update_session_notice_is_shown_on_startup(self) -> None:
        state_cache = FakeStateCache(unclean=True)
        result = UpdateCheckResult(
            packages=[],
            checked_at=datetime.now(),
            logs=[],
            warnings=[],
        )
        self.window = MainWindow(
            service=FakeUpdateService(result),
            settings=FakeSettingsService(),
            state_cache=state_cache,
        )

        self.assertFalse(self.window.action_bar.notice_label.isHidden())
        self.assertIn("did not finish cleanly", self.window.action_bar.notice_label.text())

    def test_startup_begins_empty_before_first_fresh_check_finishes(self) -> None:
        service = FakeUpdateService(
            UpdateCheckResult(packages=[], checked_at=datetime.now(), logs=[], warnings=[])
        )
        state_cache = FakeStateCache()

        self.window = MainWindow(
            service=service,
            settings=FakeSettingsService(),
            state_cache=state_cache,
        )

        self.assertEqual(self._visible_package_names(), [])
        self.assertEqual(self.window.header_widget.counter_labels["system"].text(), "0")

        self._process_events(50)
        self._wait_for_check(self.window)

        self.assertEqual(service.check_calls, 1)
        self.assertEqual(self._visible_package_names(), [])
        self.assertEqual(self.window.header_widget.counter_labels["system"].text(), "0")

    def test_startup_refresh_runs_even_when_automatic_checks_are_scheduled_later(self) -> None:
        service = FakeUpdateService(
            UpdateCheckResult(packages=[], checked_at=datetime.now(), logs=[], warnings=[])
        )

        self.window = MainWindow(
            service=service,
            settings=FakeSettingsService(auto_check_enabled=True, auto_check_interval_hours=168),
            state_cache=FakeStateCache(),
        )
        self._process_events(100)
        self._wait_for_check(self.window)

        self.assertEqual(service.check_calls, 1)
        self.assertEqual(self._visible_package_names(), [])

    def test_startup_refresh_failure_keeps_startup_screen_empty(self) -> None:
        service = FailingUpdateService(
            UpdateCheckResult(packages=[], checked_at=datetime.now(), logs=[])
        )

        self.window = MainWindow(
            service=service,
            settings=FakeSettingsService(auto_check_enabled=True, auto_check_interval_hours=168),
            state_cache=FakeStateCache(),
        )
        self._process_events(50)
        self._wait_for_check(self.window)

        self.assertEqual(self._visible_package_names(), [])
        self.assertFalse(self.window.action_bar.update_button.isEnabled())
        self.assertEqual(self.window.header_widget.system_status_label.text(), "Error")
        self.assertEqual(self.window.header_widget.last_checked_label.text(), "Last checked: Failed")
        self.assertEqual(self.window.action_bar.status_label.text(), "")
        self.assertIn("Error: checkupdates failed", self.window.details_panel._details_placeholder.text())

    def test_startup_refresh_waits_until_network_is_online(self) -> None:
        service = FakeUpdateService(
            UpdateCheckResult(packages=[], checked_at=datetime.now(), logs=[], warnings=[])
        )
        network_information = FakeNetworkInformation(FakeReachability.Disconnected)
        network_api = FakeNetworkInformationApi(network_information)

        with (
            patch("archupdater.presentation.check_schedule.QNetworkInformation", network_api),
            patch(
                "archupdater.presentation.main_window.update_flow.MainWindowUpdateFlowCoordinator.start_check_updates",
                return_value=True,
            ) as start_check,
        ):
            self.window = MainWindow(
                service=service,
                settings=FakeSettingsService(auto_check_enabled=True, auto_check_interval_hours=168),
                state_cache=FakeStateCache(),
            )
            self._process_events(80)

            start_check.assert_not_called()
            self.assertEqual(
                self.window.header_widget.system_status_label.text(),
                "Waiting for network...",
            )
            self.assertEqual(
                self.window.details_panel._details_placeholder.text(),
                "The startup scan will begin automatically when the network is online.",
            )

            network_information.set_reachability(FakeReachability.Online)
            self._process_events(50)
            start_check.assert_called_once_with()
            self.assertFalse(self.window._check_schedule.is_waiting_for_network())

    def _create_window(
        self,
        *,
        packages: list,
        snapshot: OptionalSourcesSnapshot | None = None,
        state_cache: FakeStateCache | None = None,
        result: UpdateCheckResult | None = None,
        settings: FakeSettingsService | None = None,
    ) -> MainWindow:
        result = result or UpdateCheckResult(
            packages=packages,
            checked_at=datetime.now(),
            logs=[],
            warnings=[],
        )
        window = MainWindow(
            service=FakeUpdateService(result, snapshot=snapshot),
            settings=settings or FakeSettingsService(),
            state_cache=state_cache or FakeStateCache(),
        )
        self.window = window
        window.show()
        self._wait_for_check(window)
        self._process_events(50)
        return window

    def _wait_for_check(self, window: MainWindow, timeout_s: float = 2.0) -> None:
        def finished() -> bool:
            return window._service.check_calls > 0 and not window.update_controller.is_busy()

        if finished():
            return
        loop = QEventLoop()
        poll = QTimer(loop)
        poll.setInterval(10)
        poll.timeout.connect(lambda: loop.quit() if finished() else None)
        timeout = QTimer(loop)
        timeout.setSingleShot(True)
        timeout.timeout.connect(loop.quit)
        poll.start()
        timeout.start(int(timeout_s * 1000))
        try:
            loop.exec()
        finally:
            poll.stop()
            timeout.stop()
        thread = window.update_controller._worker_thread
        self.assertTrue(
            finished(),
            "Initial check did not finish: "
            f"calls={window._service.check_calls}, "
            f"busy={window.update_controller.is_busy()}, "
            f"thread_running={thread.isRunning() if thread else False}, "
            f"waiting_for_network={window._check_schedule.is_waiting_for_network()}",
        )

    def _process_events(self, delay_ms: int) -> None:
        loop = QEventLoop()
        QTimer.singleShot(delay_ms, loop.quit)
        loop.exec()

    def _counter_card(self, source: UpdateSource) -> CounterCardWidget:
        for card in self.window.header_widget.findChildren(CounterCardWidget):
            if card.source is source:
                return card
        raise AssertionError(f"Counter card for source {source.value} not found")

    def _visible_package_names(self) -> list[str]:
        tree = self.window.package_updates_widget.tree
        return [
            tree.topLevelItem(index).text(0)
            for index in range(tree.topLevelItemCount())
            if not tree.topLevelItem(index).isHidden()
        ]

    def _click_widget(self, widget) -> None:
        QTest.mouseClick(widget, Qt.MouseButton.LeftButton, pos=widget.rect().center())
        self._process_events(20)

    def _click_tree_item(self, item) -> None:
        tree = self.window.package_updates_widget.tree
        rect = tree.visualItemRect(item)
        QTest.mouseClick(tree.viewport(), Qt.MouseButton.LeftButton, pos=rect.center())
        self._process_events(20)

    def _package(self, name: str, source: UpdateSource, *, repository: str, **extra) -> object:
        from archupdater.domain.packages import PackageUpdate

        target_id = extra.get("backend_id", name)
        package_kind = extra.pop("package_kind", None)
        plugin_id = extra.pop("plugin_id", None)
        installation_scope = extra.pop("installation_scope", "system")
        source_metadata = {
            UpdateSource.SYSTEM: SystemPackageMetadata(repository=repository),
            UpdateSource.AUR: AurPackageMetadata(repository=repository),
            UpdateSource.FLATPAK: FlatpakPackageMetadata(
                ref=target_id,
                repository=repository,
                installation_scope=installation_scope,
            ),
            UpdateSource.FIRMWARE: FirmwarePackageMetadata(
                device_id=target_id,
                repository=repository,
            ),
            UpdateSource.PLASMA_WIDGET: PlasmaWidgetPackageMetadata(
                content_id=target_id,
                repository=repository,
                package_kind=package_kind,
                plugin_id=plugin_id,
            ),
        }[source]
        return PackageUpdate(
            name=name,
            current_version="1.0",
            new_version="1.1",
            source=source,
            source_metadata=source_metadata,
            description=f"{name} description",
            **extra,
        )


if __name__ == "__main__":
    unittest.main()
