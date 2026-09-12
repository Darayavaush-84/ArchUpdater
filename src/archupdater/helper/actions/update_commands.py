from __future__ import annotations

import os
from pathlib import Path

from PySide6.QtCore import QCoreApplication

from archupdater.application.helper_protocol import HelperEventType
from archupdater.helper.actions.common import (
    PACMAN_PATH,
    EmitEvent,
    EmitLog,
    stream_command,
)
from archupdater.helper.actions.common import stream_subprocess as stream_subprocess
from archupdater.helper.actions.pacman_prompts import PacmanPromptHandler

SYSTEMD_INHIBIT_PATH = Path("/usr/bin/systemd-inhibit")


def _critical_command(command: list[str]) -> list[str]:
    if not SYSTEMD_INHIBIT_PATH.exists():
        return command
    return [
        str(SYSTEMD_INHIBIT_PATH),
        "--what=shutdown:sleep",
        "--who=ArchUpdater",
        "--why=Installing critical system updates",
        "--mode=block",
        "--",
        *command,
    ]


def _require_executable(
    path: Path,
    command_name: str,
    *,
    emit_event: EmitEvent,
    emit_log: EmitLog,
) -> bool:
    if path.exists():
        return True
    emit_log(
        QCoreApplication.translate(
            "PrivilegedHelper",
            "{command} executable not found at {path}.",
        ).format(command=command_name, path=path)
    )
    emit_event(
        HelperEventType.COMPLETED,
        success=False,
        message=QCoreApplication.translate(
            "PrivilegedHelper",
            "{command} is not available on this system.",
        ).format(command=command_name),
    )
    return False


def _run_helper_command(
    command: list[str],
    *,
    success_message: str,
    failure_message: str,
    emit_event: EmitEvent,
    emit_log: EmitLog,
    survive_parent_exit: bool = False,
    success_payload: dict[str, object] | None = None,
) -> int:
    if str(PACMAN_PATH) in command:
        return_code, _output = stream_command(
            command,
            emit_log=emit_log,
            survive_parent_exit=survive_parent_exit,
            input_handler=PacmanPromptHandler(emit_event=emit_event, emit_log=emit_log),
            env={**os.environ, "LC_ALL": "C", "LANG": "C"},
        )
    elif survive_parent_exit:
        return_code, _output = stream_command(
            command,
            emit_log=emit_log,
            survive_parent_exit=True,
        )
    else:
        return_code, _output = stream_command(command, emit_log=emit_log)
    if return_code != 0:
        emit_event(
            HelperEventType.COMPLETED,
            success=False,
            message=failure_message.format(code=return_code),
        )
        return 3

    emit_event(
        HelperEventType.COMPLETED,
        success=True,
        message=success_message,
        **(success_payload or {}),
    )
    return 0
