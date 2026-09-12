from __future__ import annotations

from collections.abc import Callable


Translate = Callable[[str], str]


class UpdateSessionMessages:
    def __init__(self, translate: Translate) -> None:
        self._t = translate

    def successful_next_step(self) -> str:
        return self._t("ArchUpdater will refresh package status automatically.")

    def no_package_status_refresh_required(self) -> str:
        return self._t("No package status refresh is required.")

    def selected_updates_completed(self) -> str:
        return self._t("Selected updates completed successfully.")

    def selected_updates_partially_completed(self) -> str:
        return self._t("Selected updates completed with incomplete or failed steps.")

    def independent_steps_failed(self) -> str:
        return self._t("No selected updates were installed because the selected steps failed.")

    def no_selected_updates_installed(self) -> str:
        return self._t("No selected updates were installed.")

    def no_further_steps(self) -> str:
        return self._t("No further update steps will be executed.")

    def authentication_cancelled(self) -> str:
        return self._t(
            "Authentication was cancelled. The administrator password is required to continue, so the update has been interrupted."
        )

    def review_log_before_closing(self) -> str:
        return self._t("Review the update log above before closing this window.")

    def no_further_action_required(self) -> str:
        return self._t("No further action is required.")

    def incomplete_next_step(self) -> str:
        return self._t("Skipped AUR updates remain available and can be retried later.")

    def failed_next_step(self, *, has_not_executed_steps: bool) -> str:
        if has_not_executed_steps:
            return self._t("Review the live activity log, then run the remaining updates again.")
        return self._t("Review the live activity log, then try the update again.")
