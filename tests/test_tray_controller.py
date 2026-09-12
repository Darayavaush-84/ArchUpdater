from __future__ import annotations

import sys
import types
import unittest
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from PySide6.QtWidgets import QApplication, QSystemTrayIcon

from archupdater.application.update_session.protocol import BatchOutcome
from archupdater.domain.check_results import UpdateCheckResult
from archupdater.domain.enums import UpdateSource
from archupdater.domain.package_metadata import SystemPackageMetadata
from archupdater.domain.packages import PackageUpdate
from archupdater.presentation.tray_controller import TrayController
from archupdater.presentation.tray_status import TrayStatusModel


def _package(
    name: str,
    *,
    blocked_by_config: bool = False,
) -> PackageUpdate:
    return PackageUpdate(
        name=name,
        current_version="1",
        new_version="2",
        source=UpdateSource.SYSTEM,
        source_metadata=SystemPackageMetadata(),
        selected=not blocked_by_config,
        selection_locked=blocked_by_config,
        blocked_by_config=blocked_by_config,
        blocked_reason="Blocked by pacman.conf" if blocked_by_config else None,
    )


class TrayControllerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._app = QApplication.instance() or QApplication([])

    def test_sync_tooltip_uses_update_count(self) -> None:
        controller = TrayController.__new__(TrayController)
        tooltips: list[str] = []
        controller._tray = types.SimpleNamespace(setToolTip=tooltips.append)
        controller._tray_status = TrayStatusModel(lambda text: text)
        controller._tray_status.available_updates_count = 3
        controller._window = types.SimpleNamespace(next_auto_check_at=lambda: None)

        controller._sync_tooltip()

        self.assertEqual(tooltips[-1], "ArchUpdater: 3 updates available")

    def test_notification_uses_qt_tray_api_and_reports_only_an_actual_show_call(self) -> None:
        controller = TrayController.__new__(TrayController)
        shown: list[tuple[object, ...]] = []
        controller._tray = types.SimpleNamespace(
            showMessage=lambda *args: shown.append(args)
        )
        controller._should_notify = lambda: True  # type: ignore[assignment]
        controller.tr = lambda text: text  # type: ignore[assignment]

        result = controller._show_message(
            message="Updates available",
            icon=QSystemTrayIcon.MessageIcon.Information,
        )

        self.assertTrue(result)
        self.assertEqual(len(shown), 1)
        self.assertEqual(shown[0][0:2], ("ArchUpdater", "Updates available"))

    def test_sync_tray_icon_uses_badged_icon_when_updates_exist(self) -> None:
        controller = TrayController.__new__(TrayController)
        icons: list[object] = []
        base_icon = object()
        badged_icon = object()
        controller._tray = types.SimpleNamespace(setIcon=icons.append)
        controller._base_icon = base_icon
        controller._tray_status = TrayStatusModel(lambda text: text)
        controller._tray_status.available_updates_count = 5
        controller._tray_status.has_successful_check_result = True
        controller._update_controller = types.SimpleNamespace(is_busy=lambda: False)
        controller.is_active = lambda: True  # type: ignore[assignment]
        controller._badged_icon = lambda icon, count: badged_icon  # type: ignore[assignment]

        controller._sync_tray_icon()

        self.assertIs(icons[-1], badged_icon)

    def test_sync_tray_icon_uses_green_marker_when_up_to_date(self) -> None:
        controller = TrayController.__new__(TrayController)
        icons: list[object] = []
        base_icon = object()
        ok_icon = object()
        controller._tray = types.SimpleNamespace(setIcon=icons.append)
        controller._base_icon = base_icon
        controller._tray_status = TrayStatusModel(lambda text: text)
        controller._tray_status.has_successful_check_result = True
        controller._update_controller = types.SimpleNamespace(is_busy=lambda: False)
        controller.is_active = lambda: True  # type: ignore[assignment]
        controller._ok_marked_icon = lambda icon: ok_icon  # type: ignore[assignment]

        controller._sync_tray_icon()

        self.assertIs(icons[-1], ok_icon)

    def test_sync_tray_icon_uses_warning_marker_after_failed_check(self) -> None:
        controller = TrayController.__new__(TrayController)
        icons: list[object] = []
        base_icon = object()
        warning_icon = object()
        controller._tray = types.SimpleNamespace(setIcon=icons.append)
        controller._base_icon = base_icon
        controller._tray_status = TrayStatusModel(lambda text: text)
        controller._tray_status.apply_check_failure("network unavailable")
        controller._update_controller = types.SimpleNamespace(is_busy=lambda: False)
        controller.is_active = lambda: True  # type: ignore[assignment]
        controller._warning_marked_icon = lambda icon: warning_icon  # type: ignore[assignment]

        controller._sync_tray_icon()

        self.assertIs(icons[-1], warning_icon)

    def test_check_succeeded_uses_actionable_updates_count_before_notifications(self) -> None:
        controller = TrayController.__new__(TrayController)
        synced_icons: list[int] = []
        synced_tooltips: list[int] = []
        controller._tray_status = TrayStatusModel(lambda text: text)

        def sync_icon() -> None:
            synced_icons.append(controller._tray_status.available_updates_count)

        def sync_tooltip() -> None:
            synced_tooltips.append(controller._tray_status.available_updates_count)

        controller._sync_tray_icon = sync_icon  # type: ignore[assignment]
        controller._sync_tooltip = sync_tooltip  # type: ignore[assignment]
        controller._updates_signature = lambda result: tuple()  # type: ignore[assignment]
        controller._force_next_updates_notification = False
        controller._is_debounced_updates_available = lambda signature: False  # type: ignore[assignment]
        controller._show_message = lambda **_kwargs: False  # type: ignore[assignment]
        controller._remember_updates_available = lambda signature: None  # type: ignore[assignment]
        controller.tr = lambda text: text  # type: ignore[assignment]

        result = UpdateCheckResult(
            packages=[_package("linux"), _package("nvidia", blocked_by_config=True)],
            checked_at=datetime.now(),
            logs=[],
        )

        controller._on_check_succeeded(result)

        self.assertEqual(controller._tray_status.available_updates_count, 1)
        self.assertEqual(synced_icons, [1])
        self.assertEqual(synced_tooltips, [1])

    def test_successful_update_marks_refresh_pending_without_clearing_count(self) -> None:
        controller = TrayController.__new__(TrayController)
        synced_icons: list[bool] = []
        synced_tooltips: list[bool] = []
        controller._tray_status = TrayStatusModel(lambda text: text)
        controller._tray_status.available_updates_count = 5
        controller._update_started_in_background = None
        controller._sync_tray_icon = (
            lambda: synced_icons.append(controller._tray_status.refresh_pending)
        )  # type: ignore[assignment]
        controller._sync_tooltip = (
            lambda: synced_tooltips.append(controller._tray_status.refresh_pending)
        )  # type: ignore[assignment]

        controller._on_update_completed(True, "", "success")

        self.assertTrue(controller._tray_status.refresh_pending)
        self.assertEqual(controller._tray_status.available_updates_count, 5)
        self.assertEqual(synced_icons, [True])
        self.assertEqual(synced_tooltips, [True])

    def test_cancelled_update_uses_warning_notification_not_failure(self) -> None:
        controller = TrayController.__new__(TrayController)
        shown: list[dict[str, object]] = []
        controller._update_started_in_background = True
        controller._should_notify = lambda: True  # type: ignore[assignment]
        controller._show_message = lambda **kwargs: shown.append(kwargs) or True  # type: ignore[assignment]
        controller.tr = lambda text: text  # type: ignore[assignment]

        controller._on_update_completed(
            False,
            "The update batch was interrupted.",
            BatchOutcome.CANCELLED.value,
        )

        self.assertEqual(shown[0]["message"], "The update was cancelled.")
        self.assertEqual(shown[0]["icon"], QSystemTrayIcon.MessageIcon.Warning)

    def test_sync_tooltip_reports_up_to_date_after_successful_check(self) -> None:
        controller = TrayController.__new__(TrayController)
        tooltips: list[str] = []
        controller._tray = types.SimpleNamespace(setToolTip=tooltips.append)
        controller._tray_status = TrayStatusModel(lambda text: text)
        controller._tray_status.has_successful_check_result = True
        controller._window = types.SimpleNamespace(next_auto_check_at=lambda: None)

        controller._sync_tooltip()

        self.assertEqual(tooltips[-1], "ArchUpdater: Up to date")

    def test_sync_menu_state_checks_current_auto_check_interval(self) -> None:
        controller = TrayController.__new__(TrayController)
        checked_values: list[bool] = []
        action = types.SimpleNamespace(setChecked=checked_values.append)
        controller._window = types.SimpleNamespace(
            auto_check_enabled=lambda: True,
            auto_check_interval_hours=lambda: 24,
        )
        controller._update_controller = types.SimpleNamespace(is_busy=lambda: False)
        controller._tray_status = TrayStatusModel(lambda text: text)
        controller._check_action = types.SimpleNamespace(setEnabled=lambda value: None)
        controller._auto_check_actions = {24: action, None: types.SimpleNamespace(setChecked=lambda value: None)}

        controller._sync_menu_state()

        self.assertEqual(checked_values, [True])

    def test_sync_menu_state_checks_off_when_auto_check_is_disabled(self) -> None:
        controller = TrayController.__new__(TrayController)
        checked_values: list[bool] = []
        off_action = types.SimpleNamespace(setChecked=checked_values.append)
        controller._window = types.SimpleNamespace(
            auto_check_enabled=lambda: False,
            auto_check_interval_hours=lambda: 24,
        )
        controller._update_controller = types.SimpleNamespace(is_busy=lambda: False)
        controller._tray_status = TrayStatusModel(lambda text: text)
        controller._check_action = types.SimpleNamespace(setEnabled=lambda value: None)
        controller._auto_check_actions = {None: off_action}

        controller._sync_menu_state()

        self.assertEqual(checked_values, [True])

    def test_sync_menu_state_disables_check_now_while_busy(self) -> None:
        controller = TrayController.__new__(TrayController)
        enabled_values: list[bool] = []
        controller._window = types.SimpleNamespace(
            auto_check_enabled=lambda: False,
            auto_check_interval_hours=lambda: 24,
        )
        controller._update_controller = types.SimpleNamespace(is_busy=lambda: True)
        controller._tray_status = TrayStatusModel(lambda text: text)
        controller._check_action = types.SimpleNamespace(setEnabled=enabled_values.append)
        controller._auto_check_actions = {None: types.SimpleNamespace(setChecked=lambda value: None)}

        controller._sync_menu_state()

        self.assertEqual(enabled_values, [False])

    def test_set_auto_check_schedule_delegates_to_window(self) -> None:
        controller = TrayController.__new__(TrayController)
        selected_values: list[int | None] = []
        controller._window = types.SimpleNamespace(set_auto_check_schedule=selected_values.append)

        controller._set_auto_check_schedule(72)

        self.assertEqual(selected_values, [72])

    def test_auto_check_interval_labels_are_explicitly_translatable(self) -> None:
        controller = TrayController.__new__(TrayController)
        controller.tr = lambda text: f"tr:{text}"  # type: ignore[assignment]

        self.assertEqual(controller._auto_check_interval_label(6), "tr:Every 6 hours")
        self.assertEqual(controller._auto_check_interval_label(72), "tr:Every 3 days")
        self.assertEqual(controller._auto_check_interval_label(168), "tr:Every week")
        self.assertEqual(controller._auto_check_interval_label(5), "tr:Every 5 hours")


if __name__ == "__main__":
    unittest.main()
