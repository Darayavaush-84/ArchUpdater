from __future__ import annotations

import os
import re
import stat
import tempfile
from pathlib import Path

from PySide6.QtCore import QCoreApplication

from archupdater.application.helper_protocol import HelperEventType
from archupdater.helper.actions.common import EmitEvent
from archupdater.services.command_runner import CommandRunner, CommandRunnerError


PACMAN_CONFIG = Path("/etc/pacman.conf")
PACMAN_CONF_PATH = Path("/usr/bin/pacman-conf")


def _download_timeouts_disabled(config: Path, runner: CommandRunner) -> bool:
    result = runner.run(
        [str(PACMAN_CONF_PATH), "--config", str(config), "DisableDownloadTimeout"],
        timeout_seconds=5,
    )
    if result.exit_code != 0:
        raise OSError("Could not verify the effective pacman configuration")
    return "DisableDownloadTimeout" in result.stdout.splitlines()


def _enable_download_timeouts_in_file(path: Path, runner: CommandRunner) -> None:
    # The caller only uses the fixed system path; no path comes from the frontend.
    with os.fdopen(os.open(path, os.O_RDONLY | os.O_NOFOLLOW), "r", newline="") as source:
        metadata = os.fstat(source.fileno())
        if not stat.S_ISREG(metadata.st_mode) or metadata.st_uid != os.geteuid():
            raise OSError("Unexpected pacman.conf ownership or file type")
        original = source.read()
    updated = re.sub(
        r"(?m)^([ \t]*)DisableDownloadTimeout([ \t]*(?:#.*)?)(\r?)$",
        r"\1#DisableDownloadTimeout\2\3",
        original,
    )
    if updated == original:
        if _download_timeouts_disabled(path, runner):
            raise OSError("DisableDownloadTimeout is set in a file included by pacman.conf")
        return
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", dir=path.parent, prefix=".pacman.conf-", delete=False, newline="",
        ) as target:
            temporary_path = Path(target.name)
            os.fchown(target.fileno(), metadata.st_uid, metadata.st_gid)
            os.fchmod(target.fileno(), stat.S_IMODE(metadata.st_mode))
            target.write(updated)
            target.flush()
            os.fsync(target.fileno())
        # Includes may still enable the directive: verify the candidate before it
        # replaces the original, so a failure leaves pacman.conf untouched.
        if _download_timeouts_disabled(temporary_path, runner):
            raise OSError("DisableDownloadTimeout is set in a file included by pacman.conf")
        current = path.stat(follow_symlinks=False)
        if (current.st_ino, current.st_mtime_ns, current.st_size) != (
            metadata.st_ino, metadata.st_mtime_ns, metadata.st_size,
        ):
            raise OSError("pacman.conf changed during the operation")
        os.replace(temporary_path, path)
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)


def enable_download_timeouts(*, emit_event: EmitEvent) -> int:
    try:
        _enable_download_timeouts_in_file(PACMAN_CONFIG, CommandRunner())
    except (OSError, UnicodeError, CommandRunnerError) as exc:
        emit_event(
            HelperEventType.COMPLETED, success=False,
            message=QCoreApplication.translate(
                "PrivilegedHelper",
                "Could not enable download timeouts. Check /etc/pacman.conf and its included files: {error}",
            ).format(error=exc),
        )
        return 1
    emit_event(
        HelperEventType.COMPLETED, success=True,
        message=QCoreApplication.translate("PrivilegedHelper", "Download timeouts enabled."),
    )
    return 0
