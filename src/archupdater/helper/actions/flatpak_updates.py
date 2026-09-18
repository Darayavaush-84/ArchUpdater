from __future__ import annotations

import re
from pathlib import Path

from PySide6.QtCore import QCoreApplication

from archupdater.application.helper_protocol import HelperEventType
from archupdater.helper.actions import update_commands
from archupdater.helper.actions.common import (
    EmitEvent,
    EmitLog,
)

FLATPAK_PATH = Path("/usr/bin/flatpak")


def run_flatpak_system_update(
    refs: list[str],
    expected_versions: dict[str, str],
    *,
    emit_event: EmitEvent,
    emit_log: EmitLog,
) -> int:
    if not update_commands._require_executable(
        FLATPAK_PATH, "flatpak", emit_event=emit_event, emit_log=emit_log
    ):
        return 2

    emit_event(HelperEventType.STATUS, value="preparing")
    emit_log(
        QCoreApplication.translate(
            "PrivilegedHelper",
            "Running system Flatpak update.",
        )
    )
    preview_code, preview_output = update_commands.stream_command(
        [
            str(FLATPAK_PATH),
            "remote-ls",
            "--system",
            "--updates",
            "--columns=ref,version,branch,commit",
        ],
        emit_log=emit_log,
    )
    if preview_code != 0:
        message = QCoreApplication.translate(
            "PrivilegedHelper",
            "Could not prepare the Flatpak transaction (exit code {code}).",
        ).format(code=preview_code)
        emit_event(
            HelperEventType.COMPLETED,
            success=False,
            message=message,
            reason="preparation_failed",
        )
        return 3
    available_versions = _parse_tab_versions(preview_output)
    actual_versions = {ref: available_versions[ref] for ref in refs if available_versions.get(ref)}
    target_commits = {
        columns[0]: columns[3]
        for line in preview_output
        if len(columns := line.split("\t")) == 4
        and re.fullmatch(r"[0-9a-f]{12,64}", columns[3])
        and columns[0] in refs
    }
    if actual_versions != expected_versions or set(target_commits) != set(refs):
        message = QCoreApplication.translate(
            "PrivilegedHelper",
            "The Flatpak transaction changed after it was reviewed.",
        )
        emit_event(
            HelperEventType.COMPLETED,
            success=False,
            message=message,
            reason="plan_changed",
            actual_versions=actual_versions,
        )
        return 3

    emit_event(HelperEventType.STATUS, value="running")
    update_code, _update_output = update_commands.stream_command(
        update_commands._critical_command(
            [
                str(FLATPAK_PATH),
                "update",
                "--system",
                "--assumeyes",
                "--noninteractive",
                "--",
                *refs,
            ]
        ),
        emit_log=emit_log,
        survive_parent_exit=True,
    )
    if update_code != 0:
        message = QCoreApplication.translate(
            "PrivilegedHelper",
            "flatpak exited with code {code}.",
        ).format(code=update_code)
        emit_event(HelperEventType.COMPLETED, success=False, message=message)
        return 3

    completed_refs: set[str] = set()
    for ref in refs:
        verify_code, verify_output = update_commands.stream_command(
            [str(FLATPAK_PATH), "info", "--system", "--show-commit", "--", ref],
            emit_log=emit_log,
        )
        installed_commit = "\n".join(verify_output).strip()
        if (
            verify_code == 0
            and re.fullmatch(r"[0-9a-f]{64}", installed_commit)
            and installed_commit.startswith(target_commits[ref])
        ):
            completed_refs.add(ref)
    if completed_refs != set(refs):
        message = QCoreApplication.translate(
            "PrivilegedHelper",
            "Flatpak finished without installing all selected updates.",
        )
        emit_event(
            HelperEventType.COMPLETED,
            success=False,
            message=message,
            reason="postcondition_failed",
        )
        return 3

    emit_event(
        HelperEventType.COMPLETED,
        success=True,
        message=QCoreApplication.translate(
            "PrivilegedHelper",
            "System Flatpak update completed successfully.",
        ),
    )
    return 0


def run_flatpak_system_cleanup(
    *,
    emit_event: EmitEvent,
    emit_log: EmitLog,
) -> int:
    if not update_commands._require_executable(
        FLATPAK_PATH, "flatpak", emit_event=emit_event, emit_log=emit_log
    ):
        return 2

    emit_event(HelperEventType.STATUS, value="running")
    emit_log(
        QCoreApplication.translate(
            "PrivilegedHelper",
            "Removing unused system Flatpak runtimes.",
        )
    )
    return update_commands._run_helper_command(
        [
            str(FLATPAK_PATH),
            "uninstall",
            "--system",
            "--unused",
            "--noninteractive",
        ],
        success_message=QCoreApplication.translate(
            "PrivilegedHelper",
            "System Flatpak cleanup completed successfully.",
        ),
        failure_message=QCoreApplication.translate(
            "PrivilegedHelper",
            "flatpak exited with code {code}.",
        ),
        emit_event=emit_event,
        emit_log=emit_log,
    )


def _parse_tab_versions(lines: list[str]) -> dict[str, str]:
    versions: dict[str, str] = {}
    for raw_line in lines:
        columns = raw_line.split("\t")
        if len(columns) < 2:
            continue
        ref = columns[0].strip()
        version = columns[1].strip()
        branch = columns[2].strip() if len(columns) >= 3 else ""
        if ref:
            versions[ref] = version or branch
    return versions
