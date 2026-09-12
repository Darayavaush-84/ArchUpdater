from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from support.commands import CommandResponse, FakeCommandRunner
from archupdater.services.plasma_shell import PlasmaShellService




class PlasmaShellServiceTests(unittest.TestCase):
    def test_can_restart_shell_requires_plasma_and_user_service(self) -> None:
        runner = FakeCommandRunner([CommandResponse(stdout="loaded\n")])
        service = PlasmaShellService(
            runner=runner,  # type: ignore[arg-type]
            env={"XDG_CURRENT_DESKTOP": "KDE"},
        )

        with patch("shutil.which", return_value="/usr/bin/systemctl"):
            self.assertTrue(service.can_restart_shell())

        self.assertEqual(
            runner.commands[0],
            [
                "systemctl",
                "--user",
                "show",
                "--property=LoadState",
                "--value",
                "plasma-plasmashell.service",
            ],
        )

    def test_can_restart_shell_returns_false_outside_plasma(self) -> None:
        service = PlasmaShellService(env={"XDG_CURRENT_DESKTOP": "GNOME"})

        with patch("shutil.which", return_value="/usr/bin/systemctl"):
            self.assertFalse(service.can_restart_shell())

    def test_restart_shell_uses_systemctl_user_restart(self) -> None:
        runner = FakeCommandRunner([CommandResponse()])
        service = PlasmaShellService(runner=runner)  # type: ignore[arg-type]

        self.assertTrue(service.restart_shell())
        self.assertEqual(
            runner.commands[0],
            ["systemctl", "--user", "restart", "plasma-plasmashell.service"],
        )


if __name__ == "__main__":
    unittest.main()
