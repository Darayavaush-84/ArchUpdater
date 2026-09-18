from __future__ import annotations

import re

from PySide6.QtCore import QCoreApplication

from archupdater.application.helper_protocol import HelperEventType
from archupdater.helper.actions import update_commands
from archupdater.helper.actions.common import (
    EmitEvent,
    EmitLog,
)

from archupdater.services.command_runner import CommandRunner, CommandRunnerError


def run_system_update(
    expected_versions: dict[str, str],
    *,
    emit_event: EmitEvent,
    emit_log: EmitLog,
) -> int:
    if not update_commands._require_executable(
        update_commands.PACMAN_PATH, "pacman", emit_event=emit_event, emit_log=emit_log
    ):
        return 2

    before = _installed_package_versions()
    failure_message = QCoreApplication.translate("BatchUpdateRunner", "System update failed.")
    if before is None:
        emit_log("Could not read installed package versions before the system transaction.")
        emit_event(
            HelperEventType.COMPLETED, success=False, message=failure_message,
            reason="preparation_failed", changed=False,
        )
        return 3

    verification_failed = False

    def report_result(event: HelperEventType, **payload: object) -> None:
        nonlocal verification_failed
        if event is HelperEventType.COMPLETED:
            if payload.get("reason") == "plan_changed":
                payload["changed"] = False
            else:
                after = _installed_package_versions()
                if after is None:
                    verification_failed = True
                    emit_log("Could not verify installed package versions after the system transaction.")
                    payload.update(
                        success=False, message=failure_message,
                        reason="postcondition_failed", changed=None,
                    )
                else:
                    payload["changed"] = before != after
        emit_event(event, **payload)

    emit_event(HelperEventType.STATUS, value="running")
    emit_log(
        QCoreApplication.translate(
            "PrivilegedHelper",
            "Running system package update with pacman.",
        )
    )
    command = [str(update_commands.PACMAN_PATH), "-Syu", "--confirm", "--color", "never"]
    return_code = update_commands._run_helper_command(
        update_commands._critical_command(command),
        success_message=QCoreApplication.translate(
            "PrivilegedHelper",
            "System update completed successfully.",
        ),
        failure_message=QCoreApplication.translate(
            "PrivilegedHelper",
            "pacman exited with code {code}.",
        ),
        emit_event=report_result,
        emit_log=emit_log,
        survive_parent_exit=True,
        expected_versions=expected_versions,
    )
    return 3 if verification_failed else return_code


def _installed_package_versions() -> dict[str, str] | None:
    """Read local package state, without refreshing any repository database."""
    try:
        result = CommandRunner(default_env={"LC_ALL": "C", "LANG": "C"}).run(
            [str(update_commands.PACMAN_PATH), "-Q", "--color", "never"],
            timeout_seconds=30,
        )
    except CommandRunnerError:
        return None
    if result.exit_code != 0:
        return None
    versions: dict[str, str] = {}
    for line in result.stdout.splitlines():
        match = re.fullmatch(r"([A-Za-z0-9@._+-]+) ([^\s]+)", line)
        if match is None or match[1] in versions:
            return None
        versions[match[1]] = match[2]
    return versions
