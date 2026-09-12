from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass

from archupdater.domain.enums import UpdateProgressPhase, UpdateProgressStepState, UpdateSource
from archupdater.domain.progress import (
    UpdateProgressSnapshot,
    UpdateProgressStep,
)
from archupdater.domain.update_plan import UpdatePlan
from archupdater.application.update_sources.descriptors import UPDATE_STEP_ORDER, plan_has_source, source_descriptors
from archupdater.application.update_session.protocol import BatchStep, step_from_running_status
from archupdater.application.update_session.messages import UpdateSessionMessages


Translate = Callable[[str], str]


@dataclass(frozen=True, slots=True)
class _ParsedPackageProgress:
    key: str
    console_line: str
    phase: UpdateProgressPhase | None
    phase_fraction: float | None = None
    activity_text: str = ""
    activity_percent: int = 0


class UpdateProgressModel:
    CONSOLE_LINE_LIMIT = 2000
    CONSOLE_LINE_CHARACTER_LIMIT = 16 * 1024
    STEP_LOG_LINE_LIMIT = 500
    ANSI_ESCAPE_RE = re.compile(r"\x1b\[[0-9;?]*[ -/]*[@-~]")
    PACMAN_PROGRESS_RE = re.compile(
        r"^\s*(?P<prefix>.+?)\s+\[[^\]]+\]\s*(?P<percent>\d{1,3})%\s*$"
    )
    PACMAN_TRANSACTION_RE = re.compile(
        r"^\((?P<index>\d+)/(?P<total>\d+)\)\s+"
        r"(?P<action>[A-Za-z][A-Za-z -]*?)\s+"
        r"(?P<package>\S+)"
    )

    def __init__(self, translate: Translate) -> None:
        self._t = translate
        self._messages = UpdateSessionMessages(translate)
        self.reset_for_check()

    @property
    def summary_completed(self) -> list[str]:
        return list(self._summary_completed)

    @property
    def dialog_revealed(self) -> bool:
        return self._dialog_revealed

    def reset_for_check(self) -> None:
        self._steps: list[UpdateProgressStep] = []
        self._dialog_revealed = False
        self._current_running_phase: UpdateProgressPhase | None = None
        self._notice_title: str | None = None
        self._notice_text: str | None = None
        self._last_title = ""
        self._last_subtitle = ""
        self._last_final_state = False
        self._last_success: bool | None = None
        self._summary_title: str | None = None
        self._summary_completed: list[str] = []
        self._summary_incomplete: list[str] = []
        self._summary_failed: list[str] = []
        self._summary_not_executed: list[str] = []
        self._summary_next_step: str | None = None
        self._console_lines: list[str] = []
        self._progress_line_indexes: dict[str, int] = {}
        self._phase_unit_counts: dict[UpdateProgressPhase, int] = {}
        self._phase_progress: dict[UpdateProgressPhase, float] = {}
        self._activity_text: str | None = None
        self._activity_percent: int | None = None

    def initialize(self, plan: UpdatePlan) -> None:
        self.reset_for_check()
        descriptors = source_descriptors(self._t)
        selected_sources = {
            source for source in descriptors if plan_has_source(plan, source)
        }
        self._steps.extend(
            UpdateProgressStep(
                descriptors[source].progress_phase,
                descriptors[source].progress_title,
            )
            for source in UPDATE_STEP_ORDER
            if source in selected_sources
        )
        for source in UPDATE_STEP_ORDER:
            if source not in selected_sources:
                continue
            unit_count = self._plan_unit_count(plan, source)
            if unit_count > 0:
                self._phase_unit_counts[descriptors[source].progress_phase] = unit_count
        plasma_widgets = plan.update_items(UpdateSource.PLASMA_WIDGET)
        if plasma_widgets:
            self._notice_title = self._t("KDE Store Add-ons")
            self._notice_text = self._t(
                "{count} selected. Some add-ons may need a plasmashell restart after installation."
            ).format(count=len(plasma_widgets))

    def reveal_dialog(self) -> None:
        self._dialog_revealed = True

    def append_console_lines(self, message: str) -> None:
        lines = message.splitlines() or [message]
        for line in lines:
            if len(line) > self.CONSOLE_LINE_CHARACTER_LIMIT:
                line = line[: self.CONSOLE_LINE_CHARACTER_LIMIT] + "…"
            if self._handle_package_progress_line(line):
                self._append_step_log_line(line)
                continue
            clean_line = self.ANSI_ESCAPE_RE.sub("", line).strip()
            if clean_line.startswith((":: ", "==> ", "(", "Pacman: ")):
                self._activity_text = clean_line.removeprefix(":: ").removeprefix("==> ")
                self._activity_percent = None
            self._console_lines.append(line)
            self._append_step_log_line(line)
            self._trim_console_lines()

    def snapshot(
        self,
        title: str,
        subtitle: str,
        *,
        final_state: bool = False,
        success: bool | None = None,
    ) -> UpdateProgressSnapshot:
        self._last_title = title
        self._last_subtitle = subtitle
        self._last_final_state = final_state
        self._last_success = success

        visual_steps = [
            UpdateProgressStep(step.phase, step.label, step.state, list(step.log_lines))
            for step in self._steps
        ]
        percent = self._calculate_percent(
            visual_steps,
            final_state=final_state,
            success=success,
        )

        return UpdateProgressSnapshot(
            title=title,
            subtitle=subtitle,
            steps=visual_steps,
            percent=max(0, min(100, percent)),
            console_lines=list(self._console_lines),
            current_phase=self._current_running_phase,
            notice_title=self._notice_title,
            notice_text=self._notice_text,
            present_dialog=self._dialog_revealed or final_state,
            final_state=final_state,
            success=success,
            summary_title=self._summary_title,
            summary_completed=list(self._summary_completed),
            summary_incomplete=list(self._summary_incomplete),
            summary_failed=list(self._summary_failed),
            summary_not_executed=list(self._summary_not_executed),
            summary_next_step=self._summary_next_step,
            activity_text=self._activity_text,
            activity_percent=self._activity_percent,
        )

    def last_snapshot(self, *, default_title: str, default_subtitle: str) -> UpdateProgressSnapshot:
        return self.snapshot(
            self._last_title or default_title,
            self._last_subtitle or default_subtitle,
            final_state=self._last_final_state,
            success=self._last_success,
        )

    def handle_step_completed(
        self,
        step_value: str,
        *,
        success: bool,
        incomplete: bool = False,
    ) -> bool:
        phase = self.phase_from_step(step_value)
        if phase is None:
            return False
        state = UpdateProgressStepState.FAILED
        if success:
            state = (
                UpdateProgressStepState.INCOMPLETE
                if incomplete
                else UpdateProgressStepState.COMPLETED
            )
        self._set_phase_state(
            phase,
            state,
        )
        if success:
            self._phase_progress[phase] = 1.0
        if self._current_running_phase is phase:
            self._current_running_phase = None
        return True

    def start_running_status(self, value: str) -> tuple[str, str] | None:
        phase = self.phase_from_status(value)
        if phase is None:
            return None

        if self._current_running_phase is not None and self._current_running_phase is not phase:
            self._set_phase_state(self._current_running_phase, UpdateProgressStepState.COMPLETED)
            self._phase_progress[self._current_running_phase] = 1.0

        self._dialog_revealed = True
        self._current_running_phase = phase
        self._activity_text = None
        self._activity_percent = None
        self._set_phase_state(phase, UpdateProgressStepState.RUNNING)
        self._phase_progress.setdefault(phase, 0.0)
        return self._progress_titles(phase)

    def complete_success(self, *, refresh_expected: bool = True) -> None:
        if self._current_running_phase is not None:
            self._set_phase_state(self._current_running_phase, UpdateProgressStepState.COMPLETED)
        for phase in self._phase_unit_counts:
            self._phase_progress[phase] = 1.0
        self._build_summary(success=True, refresh_expected=refresh_expected)

    def complete_failure(self) -> None:
        if self._current_running_phase is not None:
            self._set_phase_state(self._current_running_phase, UpdateProgressStepState.FAILED)
        self._mark_pending_steps_not_executed()
        self._build_summary(success=False, refresh_expected=False)

    def complete_cancelled(self) -> None:
        if self._current_running_phase is not None:
            self._set_phase_state(
                self._current_running_phase,
                UpdateProgressStepState.NOT_EXECUTED,
            )
            self._current_running_phase = None
        self._mark_pending_steps_not_executed()
        self._build_summary(success=False, refresh_expected=False)

    def phase_from_status(self, value: str) -> UpdateProgressPhase | None:
        return self._phase_from_batch_step(step_from_running_status(value))

    def phase_from_step(self, value: str) -> UpdateProgressPhase | None:
        try:
            step = BatchStep(value)
        except ValueError:
            return None
        return self._phase_from_batch_step(step)

    def _phase_from_batch_step(self, step: BatchStep | None) -> UpdateProgressPhase | None:
        if step is None:
            return None
        for descriptor in source_descriptors(self._t).values():
            if descriptor.batch_step is step:
                return descriptor.progress_phase
        return None

    def _progress_titles(self, phase: UpdateProgressPhase) -> tuple[str, str]:
        return {
            UpdateProgressPhase.SYSTEM: (
                self._t("Installing Updates"),
                self._t("Running the full Pacman system upgrade"),
            ),
            UpdateProgressPhase.AUR: (
                self._t("Installing Updates"),
                self._t("Installing selected AUR packages"),
            ),
            UpdateProgressPhase.FLATPAK: (
                self._t("Installing Updates"),
                self._t("Applying selected Flatpak updates"),
            ),
            UpdateProgressPhase.FIRMWARE: (
                self._t("Installing Updates"),
                self._t("Installing selected firmware updates"),
            ),
            UpdateProgressPhase.PLASMA_WIDGET: (
                self._t("Installing Updates"),
                self._t("Updating selected KDE Store add-ons"),
            ),
        }[phase]

    def _set_phase_state(
        self,
        phase: UpdateProgressPhase,
        state: UpdateProgressStepState,
    ) -> None:
        for step in self._steps:
            if step.phase is phase:
                step.state = state
                return

    def _plan_unit_count(self, plan: UpdatePlan, source: UpdateSource) -> int:
        return len(plan.update_items(source)) + len(plan.cleanup_items(source))

    def _handle_package_progress_line(self, line: str) -> bool:
        parsed = self._parse_package_progress_line(line)
        if parsed is None:
            return False

        self._append_or_replace_progress_line(parsed)
        self._activity_text = parsed.activity_text
        self._activity_percent = parsed.activity_percent

        if parsed.phase is not None and parsed.phase_fraction is not None:
            current_progress = self._phase_progress.get(parsed.phase, 0.0)
            self._phase_progress[parsed.phase] = max(
                current_progress,
                max(0.0, min(1.0, parsed.phase_fraction)),
            )
        return True

    def _parse_package_progress_line(self, line: str) -> _ParsedPackageProgress | None:
        clean_line = self.ANSI_ESCAPE_RE.sub("", line).strip()
        if not clean_line:
            return None

        match = self.PACMAN_PROGRESS_RE.match(clean_line)
        if match is None:
            return None

        percent = max(0, min(100, int(match.group("percent"))))
        label_prefix = match.group("prefix").strip()
        label = self._package_progress_label(label_prefix)
        phase = self._current_running_phase
        transaction_match = self.PACMAN_TRANSACTION_RE.match(label)
        phase_fraction: float | None = None
        activity_text = (
            self._t("Downloading {package}").format(package=label)
            if "/s" in label_prefix else label
        )
        activity_percent = percent

        if transaction_match is not None:
            index = int(transaction_match.group("index"))
            total = max(1, int(transaction_match.group("total")))
            label = transaction_match.group("package")
            phase_fraction = ((max(1, index) - 1) + (percent / 100.0)) / total
            activity_percent = round(phase_fraction * 100)
            activity_text = self._t("{action} {package} — {current} of {total}").format(
                action=transaction_match.group("action").capitalize(),
                package=label, current=index, total=total,
            )

        phase_key = phase.value if phase is not None else "session"
        return _ParsedPackageProgress(
            key=f"{phase_key}:{label}",
            console_line=clean_line,
            phase=phase,
            phase_fraction=phase_fraction,
            activity_text=activity_text,
            activity_percent=activity_percent,
        )

    def _package_progress_label(self, prefix: str) -> str:
        return re.split(r"\s{2,}", prefix, maxsplit=1)[0].strip() or prefix

    def _append_or_replace_progress_line(self, parsed: _ParsedPackageProgress) -> None:
        line_index = self._progress_line_indexes.get(parsed.key)
        if line_index is not None and line_index < len(self._console_lines):
            self._console_lines[line_index] = parsed.console_line
            return

        self._console_lines.append(parsed.console_line)
        self._progress_line_indexes[parsed.key] = len(self._console_lines) - 1
        self._trim_console_lines()

    def _trim_console_lines(self) -> None:
        overflow = len(self._console_lines) - self.CONSOLE_LINE_LIMIT
        if overflow <= 0:
            return
        del self._console_lines[:overflow]
        for key, line_index in list(self._progress_line_indexes.items()):
            updated_index = line_index - overflow
            if updated_index < 0:
                del self._progress_line_indexes[key]
            else:
                self._progress_line_indexes[key] = updated_index

    def _append_step_log_line(self, line: str) -> None:
        if self._current_running_phase is None:
            return
        for step in self._steps:
            if step.phase is not self._current_running_phase:
                continue
            step.log_lines.append(line)
            overflow = len(step.log_lines) - self.STEP_LOG_LINE_LIMIT
            if overflow > 0:
                del step.log_lines[:overflow]
            return

    def _calculate_percent(
        self,
        steps: list[UpdateProgressStep],
        *,
        final_state: bool,
        success: bool | None,
    ) -> int:
        if final_state and success:
            return 100

        unit_percent = self._unit_based_percent()
        if unit_percent is not None:
            return unit_percent

        return self._step_based_percent(steps, final_state=final_state, success=success)

    def _unit_based_percent(self) -> int | None:
        total_units = sum(self._phase_unit_counts.values())
        if total_units <= 0:
            return None

        completed_units = 0.0
        for phase, unit_count in self._phase_unit_counts.items():
            phase_progress = max(0.0, min(1.0, self._phase_progress.get(phase, 0.0)))
            completed_units += unit_count * phase_progress
        return round((completed_units / total_units) * 100)

    def _step_based_percent(
        self,
        steps: list[UpdateProgressStep],
        *,
        final_state: bool,
        success: bool | None,
    ) -> int:
        total_steps = len(
            [step for step in steps if step.phase is not UpdateProgressPhase.COMPLETED]
        )
        completed_steps = len(
            [
                step
                for step in steps
                if step.phase is not UpdateProgressPhase.COMPLETED
                and step.state is UpdateProgressStepState.COMPLETED
            ]
        )
        percent = 100 if final_state and success else 0
        if total_steps > 0 and not (final_state and success):
            percent = round((completed_steps / total_steps) * 100)
            if self._current_running_phase is not None:
                percent = max(percent, round(((completed_steps + 0.5) / total_steps) * 100))
        return percent

    def _mark_pending_steps_not_executed(self) -> None:
        for step in self._steps:
            if step.phase is UpdateProgressPhase.COMPLETED:
                continue
            if step.state is UpdateProgressStepState.PENDING:
                step.state = UpdateProgressStepState.NOT_EXECUTED

    def _build_summary(self, *, success: bool, refresh_expected: bool) -> None:
        actionable_steps = [
            step for step in self._steps if step.phase is not UpdateProgressPhase.COMPLETED
        ]
        self._summary_completed = [
            step.label for step in actionable_steps if step.state is UpdateProgressStepState.COMPLETED
        ]
        self._summary_incomplete = [
            step.label
            for step in actionable_steps
            if step.state is UpdateProgressStepState.INCOMPLETE
        ]
        self._summary_failed = [
            step.label for step in actionable_steps if step.state is UpdateProgressStepState.FAILED
        ]
        self._summary_not_executed = [
            step.label
            for step in actionable_steps
            if step.state is UpdateProgressStepState.NOT_EXECUTED
        ]

        self._summary_title = self._t("Session Summary")
        if success:
            if self._summary_incomplete:
                self._summary_next_step = self._messages.incomplete_next_step()
            elif refresh_expected:
                self._summary_next_step = self._messages.successful_next_step()
            else:
                self._summary_next_step = (
                    self._messages.no_package_status_refresh_required()
                )
            return

        if self._summary_failed:
            self._summary_next_step = self._messages.failed_next_step(
                has_not_executed_steps=bool(self._summary_not_executed)
            )
            return

        self._summary_next_step = self._messages.failed_next_step(has_not_executed_steps=False)
