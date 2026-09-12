from __future__ import annotations

import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from archupdater.services.preflight import SystemPreflightEnvironment


class SystemPreflightEnvironmentTests(unittest.TestCase):
    def test_run_command_uses_injected_runner(self) -> None:
        def runner(command: list[str], timeout: float) -> tuple[int, str, str]:
            self.assertEqual(command, ["pacman-conf", "Architecture"])
            self.assertEqual(timeout, 20)
            return 0, "x86_64\n", ""

        environment = SystemPreflightEnvironment(command_runner=runner)

        self.assertEqual(
            environment.run_command(["pacman-conf", "Architecture"], 20),
            (0, "x86_64\n", ""),
        )

    def test_command_details_prefers_stderr_and_elides_long_output(self) -> None:
        environment = SystemPreflightEnvironment()
        stderr = "\n".join(f"line-{index}" for index in range(10))

        self.assertEqual(
            environment.command_details(stdout="ignored", stderr=stderr),
            ["line-0", "line-1", "line-2", "line-3", "...", "line-7", "line-8", "line-9"],
        )

    def test_disk_space_resolves_existing_parent(self) -> None:
        environment = SystemPreflightEnvironment()
        checked_paths: list[Path] = []

        def disk_usage(path: Path):
            checked_paths.append(path)
            return types.SimpleNamespace(free=123)

        with tempfile.TemporaryDirectory() as tmp, patch("shutil.disk_usage", side_effect=disk_usage):
            missing_path = Path(tmp) / "missing" / "child"
            result = environment.disk_space(missing_path)

        self.assertEqual(result, (Path(tmp), 123))
        self.assertEqual(checked_paths, [Path(tmp)])

    def test_command_available_uses_path_lookup(self) -> None:
        environment = SystemPreflightEnvironment()

        with patch("shutil.which", return_value="/usr/bin/flatpak"):
            self.assertTrue(environment.command_available("flatpak"))


if __name__ == "__main__":
    unittest.main()
