from __future__ import annotations

from dataclasses import replace
from typing import Any

from archupdater.domain.enums import UpdateSource
from archupdater.domain.update_plan import (
    UpdatePlan,
    UpdatePlanAction,
    UpdatePlanItem,
)
from archupdater.presentation.preflight_dialogs import ask_flatpak_cleanup_scopes
from archupdater.presentation.main_window.state import MainWindowState
from archupdater.application.package_selection import selected_packages_for_plan


class MainWindowUpdatePreconditions:
    def __init__(self, window: Any, state: MainWindowState) -> None:
        self._window = window
        self._state = state

    def confirm(self, plan: UpdatePlan) -> UpdatePlan | None:
        confirmed_plan = UpdatePlan(items=list(plan.items))
        if not self._window._arch_news_coordinator.confirm_before_update(
            self._state.arch_news,
            check_state=self._state.arch_news_state,
        ):
            return None
        if not self._window._preflight_coordinator.confirm(confirmed_plan):
            return None

        cleanup_items = [
            UpdatePlanItem(
                UpdateSource.FLATPAK,
                scope,
                action=UpdatePlanAction.CLEANUP,
                installation_scope=scope,
            )
            for scope in self._flatpak_cleanup_scopes(confirmed_plan)
        ]
        confirmed_plan.items = [*confirmed_plan.items, *cleanup_items]
        self._state.active_update_packages = selected_packages_for_plan(
            confirmed_plan,
            self._state.packages,
        )
        return confirmed_plan

    def _flatpak_cleanup_scopes(self, plan: UpdatePlan) -> list[str]:
        settings = self._window._background_behavior.load_app_settings()
        return ask_flatpak_cleanup_scopes(
            self._window,
            plan,
            cleanup_enabled=settings.cleanup_unused_flatpak_runtimes,
            cleanup_preference_set=(
                self._window._settings.has_cleanup_unused_flatpak_runtimes_preference()
            ),
            save_cleanup_preference=self._save_flatpak_cleanup_preference,
        )

    def _save_flatpak_cleanup_preference(self, enabled: bool) -> None:
        current_settings = self._window._background_behavior.load_app_settings()
        self._window._settings.save_app_settings(
            replace(current_settings, cleanup_unused_flatpak_runtimes=enabled)
        )
