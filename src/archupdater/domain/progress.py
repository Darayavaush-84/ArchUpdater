from __future__ import annotations

from dataclasses import dataclass, field

from archupdater.domain.enums import UpdateProgressPhase, UpdateProgressStepState, UpdateResult


@dataclass(slots=True)
class UpdateProgressStep:
    phase: UpdateProgressPhase
    label: str
    state: UpdateProgressStepState = UpdateProgressStepState.PENDING
    log_lines: list[str] = field(default_factory=list)


@dataclass(slots=True)
class UpdateProgressSnapshot:
    title: str
    subtitle: str
    steps: list[UpdateProgressStep]
    percent: int
    console_lines: list[str] = field(default_factory=list)
    current_phase: UpdateProgressPhase | None = None
    notice_title: str | None = None
    notice_text: str | None = None
    present_dialog: bool = False
    final_state: bool = False
    success: bool | None = None
    summary_title: str | None = None
    summary_completed: list[str] = field(default_factory=list)
    summary_incomplete: list[str] = field(default_factory=list)
    summary_failed: list[str] = field(default_factory=list)
    summary_not_executed: list[str] = field(default_factory=list)
    summary_next_step: str | None = None
    activity_text: str | None = None
    activity_percent: int | None = None
    cancelled: bool = False

    @property
    def result(self) -> UpdateResult:
        if not self.final_state:
            return UpdateResult.IN_PROGRESS
        if self.cancelled:
            return UpdateResult.CANCELLED
        steps = [step for step in self.steps if step.phase is not UpdateProgressPhase.COMPLETED]
        has_unfinished_steps = bool(
            self.summary_incomplete or self.summary_failed or self.summary_not_executed
            or any(step.state is not UpdateProgressStepState.COMPLETED for step in steps)
        )
        if self.success is True and not has_unfinished_steps:
            return UpdateResult.SUCCESS
        if (
            self.success is True
            or self.summary_completed
            or any(step.state is UpdateProgressStepState.COMPLETED for step in steps)
        ):
            return UpdateResult.PARTIAL_SUCCESS
        return UpdateResult.FAILED
