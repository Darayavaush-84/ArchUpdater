from __future__ import annotations

from enum import Enum


class UpdateSource(str, Enum):
    SYSTEM = "system"
    AUR = "aur"
    FLATPAK = "flatpak"
    FIRMWARE = "firmware"
    PLASMA_WIDGET = "plasma_widget"

    @property
    def counter_field(self) -> str:
        return {
            UpdateSource.SYSTEM: "system",
            UpdateSource.AUR: "aur",
            UpdateSource.FLATPAK: "flatpak",
            UpdateSource.FIRMWARE: "firmware",
            UpdateSource.PLASMA_WIDGET: "plasma_widgets",
        }[self]


class FlatpakRefKind(str, Enum):
    APP = "app"
    RUNTIME = "runtime"


class PreflightSeverity(str, Enum):
    WARNING = "warning"
    BLOCKING = "blocking"


class OperationState(str, Enum):
    IDLE = "idle"
    CHECKING = "checking"
    WAITING_AUTH = "waiting_auth"
    UPDATING = "updating"
    COMPLETED = "completed"
    ERROR = "error"


class UpdateProgressPhase(str, Enum):
    SYSTEM = "system"
    AUR = "aur"
    FLATPAK = "flatpak"
    FIRMWARE = "firmware"
    PLASMA_WIDGET = "plasma_widget"
    COMPLETED = "completed"


class UpdateProgressStepState(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    INCOMPLETE = "incomplete"
    FAILED = "failed"
    NOT_EXECUTED = "not_executed"
