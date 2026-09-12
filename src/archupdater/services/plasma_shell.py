from __future__ import annotations

import os
import shutil
from dataclasses import dataclass, field

from archupdater.services.command_runner import CommandRunner


@dataclass(slots=True)
class PlasmaShellService:
    runner: CommandRunner = field(
        default_factory=lambda: CommandRunner(default_env={"LC_ALL": "C.UTF-8"})
    )
    env: dict[str, str] | None = None
    COMMAND_TIMEOUT_SECONDS = 20

    def can_restart_shell(self) -> bool:
        environment = self.env or os.environ
        desktop = environment.get("XDG_CURRENT_DESKTOP", "").upper()
        session = environment.get("DESKTOP_SESSION", "").upper()
        if "KDE" not in desktop and "PLASMA" not in desktop and "PLASMA" not in session:
            return False
        if shutil.which("systemctl") is None:
            return False

        status = self.runner.run(
            [
                "systemctl",
                "--user",
                "show",
                "--property=LoadState",
                "--value",
                "plasma-plasmashell.service",
            ],
            timeout_seconds=self.COMMAND_TIMEOUT_SECONDS,
        )
        if status.exit_code != 0:
            return False
        return status.stdout.strip() not in {"", "not-found", "masked"}

    def restart_shell(self) -> bool:
        result = self.runner.run(
            ["systemctl", "--user", "restart", "plasma-plasmashell.service"],
            timeout_seconds=self.COMMAND_TIMEOUT_SECONDS,
        )
        return result.exit_code == 0
