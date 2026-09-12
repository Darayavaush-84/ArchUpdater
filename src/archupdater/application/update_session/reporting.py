from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from archupdater.application.update_session.plan import BatchPlanInspector
from archupdater.application.update_session.messages import UpdateSessionMessages


Translate = Callable[[str], str]
PrintLine = Callable[[str], None]


@dataclass(slots=True)
class BatchSessionReporter:
    plan_inspector: BatchPlanInspector
    session_messages: UpdateSessionMessages
    translate: Translate
    print_line: PrintLine

    def print_banner(self) -> None:
        self.print_separator()
        self.print_line(self.translate("ArchUpdater update session"))
        self.print_separator()
        self.print_line(self.translate("The following updates will be installed:"))
        for label, details in self.plan_inspector.banner_lines():
            self.print_line(f"- {label}: {details}")
        if self.plan_inspector.requires_privileged_auth():
            self.print_line(
                self.translate(
                    "You may be asked to authorize privileged update steps."
                )
            )
        self.print_separator()

    def print_step_header(self, step: str, label: str) -> None:
        index, total = self.plan_inspector.step_position(step)
        self.print_line("")
        self.print_separator()
        if index > 1:
            self.print_line(self.transition_message(step))
        self.print_line(f"[{index}/{total}] {label}")
        self.print_separator()

    def print_footer(
        self,
        *,
        success: bool,
        message: str,
        refresh_expected: bool = True,
    ) -> None:
        status = self.translate("Success") if success else self.translate("Failed")
        self.print_line("")
        self.print_separator()
        self.print_line(f"{status}: {message}")
        if success:
            self.print_line(
                self.session_messages.successful_next_step()
                if refresh_expected
                else self.session_messages.no_package_status_refresh_required()
            )
        else:
            self.print_line(self.session_messages.review_log_before_closing())
        self.print_separator()

    def print_summary(self, *, success: bool, step_results: dict[str, str]) -> None:
        completed = self.completed_steps(step_results)
        incomplete = self.incomplete_steps(step_results)
        failed = self.failed_steps(step_results)
        not_executed = self.not_executed_steps(step_results)
        next_step = self.summary_next_step(
            success=success,
            incomplete=incomplete,
            failed=failed,
            not_executed=not_executed,
        )

        if not any((completed, incomplete, failed, not_executed, next_step)):
            return

        self.print_line("")
        self.print_separator()
        self.print_line(self.translate("Update summary"))
        self.print_separator()

        self.print_summary_section(self.translate("Completed"), completed)
        self.print_summary_section(self.translate("Incomplete"), incomplete)
        self.print_summary_section(self.translate("Failed"), failed)
        self.print_summary_section(self.translate("Not executed"), not_executed)
        if next_step:
            self.print_line(self.translate("Next step"))
            self.print_line(next_step)

    def print_summary_section(self, heading: str, items: list[str]) -> None:
        if not items:
            return
        self.print_line(heading)
        for item in items:
            self.print_line(f"- {item}")

    def completed_steps(self, step_results: dict[str, str]) -> list[str]:
        return [
            label
            for step, label in self.plan_inspector.selected_steps()
            if step_results.get(step) == "completed"
        ]

    def failed_steps(self, step_results: dict[str, str]) -> list[str]:
        return [
            label
            for step, label in self.plan_inspector.selected_steps()
            if step_results.get(step) == "failed"
        ]

    def incomplete_steps(self, step_results: dict[str, str]) -> list[str]:
        return [
            label
            for step, label in self.plan_inspector.selected_steps()
            if step_results.get(step) == "incomplete"
        ]

    def not_executed_steps(self, step_results: dict[str, str]) -> list[str]:
        return [
            label
            for step, label in self.plan_inspector.selected_steps()
            if step not in step_results
        ]

    def summary_next_step(
        self,
        *,
        success: bool,
        incomplete: list[str],
        failed: list[str],
        not_executed: list[str],
    ) -> str | None:
        if failed:
            return self.session_messages.failed_next_step(
                has_not_executed_steps=bool(not_executed)
            )
        if incomplete:
            return self.session_messages.incomplete_next_step()
        if success:
            return self.session_messages.no_further_action_required()
        return self.session_messages.failed_next_step(has_not_executed_steps=False)

    def transition_message(self, step: str) -> str:
        messages = {
            "system": self.translate("Continuing with system package updates."),
            "aur": self.translate("Continuing with AUR package updates."),
            "flatpak": self.translate("Continuing with Flatpak updates."),
            "firmware": self.translate("Continuing with firmware updates."),
            "plasma_widget": self.translate("Continuing with KDE Store add-on updates."),
        }
        return messages.get(step, self.translate("Continuing with the next update step."))

    def print_separator(self) -> None:
        self.print_line("-" * 56)
