from __future__ import annotations

from PySide6.QtCore import QCoreApplication

from archupdater.application.helper_protocol import HelperEventType
from archupdater.helper.actions import update_commands
from archupdater.helper.actions.common import (
    EmitEvent,
    EmitLog,
)


def run_system_update(
    _expected_versions: dict[str, str],
    *,
    emit_event: EmitEvent,
    emit_log: EmitLog,
) -> int:
    if not update_commands._require_executable(
        update_commands.PACMAN_PATH, "pacman", emit_event=emit_event, emit_log=emit_log
    ):
        return 2

    emit_event(HelperEventType.STATUS, value="running")
    emit_log(
        QCoreApplication.translate(
            "PrivilegedHelper",
            "Running system package update with pacman.",
        )
    )
    command = [str(update_commands.PACMAN_PATH), "-Syu", "--confirm", "--color", "never"]
    return update_commands._run_helper_command(
        update_commands._critical_command(command),
        success_message=QCoreApplication.translate(
            "PrivilegedHelper",
            "System update completed successfully.",
        ),
        failure_message=QCoreApplication.translate(
            "PrivilegedHelper",
            "pacman exited with code {code}.",
        ),
        emit_event=emit_event,
        emit_log=emit_log,
        survive_parent_exit=True,
    )
