from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QCoreApplication

from archupdater.application.helper_protocol import HelperEventType
from archupdater.helper.actions import update_commands
from archupdater.helper.actions.common import (
    EmitEvent,
    EmitLog,
)

FWUPDMGR_PATH = Path("/usr/bin/fwupdmgr")


def run_firmware_update(
    device_id: str,
    expected_version: str,
    *,
    emit_event: EmitEvent,
    emit_log: EmitLog,
) -> int:
    if not update_commands._require_executable(
        FWUPDMGR_PATH, "fwupdmgr", emit_event=emit_event, emit_log=emit_log
    ):
        return 2

    emit_event(HelperEventType.STATUS, value="running")
    emit_log(
        QCoreApplication.translate(
            "PrivilegedHelper",
            "Running firmware update for device {device}.",
        ).format(device=device_id)
    )
    return update_commands._run_helper_command(
        update_commands._critical_command(
            [
                str(FWUPDMGR_PATH),
                "install",
                "--assume-yes",
                "--no-reboot-check",
                "--no-device-prompt",
                "--",
                device_id,
                expected_version,
            ]
        ),
        success_message=QCoreApplication.translate(
            "PrivilegedHelper",
            "Firmware update completed successfully.",
        ),
        failure_message=QCoreApplication.translate(
            "PrivilegedHelper",
            "fwupdmgr exited with code {code}.",
        ),
        emit_event=emit_event,
        emit_log=emit_log,
        survive_parent_exit=True,
    )
