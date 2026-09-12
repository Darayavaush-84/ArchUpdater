from __future__ import annotations

import os
import subprocess
import tempfile
import unittest
from pathlib import Path


class InstallDependencyTests(unittest.TestCase):
    def setUp(self) -> None:
        script = Path(__file__).resolve().parents[1].joinpath("install.sh").read_text()
        start = script.index("ensure_system_dependencies() {")
        end = script.index("\n}\n", start) + 3
        self.function = script[start:end]
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.bin = self.root / "bin"
        self.bin.mkdir()
        self.log = self.root / "calls"
        self.installed = self.root / "installed"
        self.installed.write_text("")
        self.packages = ["git", "python", "pacman-contrib", "fakeroot", "polkit", "qt6-svg", "github-cli"]
        pacman = self.bin / "pacman"
        pacman.write_text("""#!/bin/bash
printf '%s\\n' "$*" >> "$TEST_CALLS"
if [[ "$1" == -Q ]]; then
    while read -r package; do
        [[ "$package" != "$2" ]] || exit 0
    done < "$TEST_INSTALLED"
    exit 1
fi
[[ "${TEST_FAIL:-0}" != 1 ]] || exit 1
[[ "${TEST_NO_CHANGE:-0}" != 1 ]] || exit 0
shift 2
printf '%s\\n' "$@" >> "$TEST_INSTALLED"
""")
        pacman.chmod(0o755)

    def run_dependencies(self, **overrides: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [
                "/bin/bash",
                "-c",
                "set -euo pipefail\n"
                + self.function
                + "\nensure_system_dependencies\necho STAGING_REACHED",
            ],
            env={
                **os.environ,
                "PATH": str(self.bin),
                "TEST_CALLS": str(self.log),
                "TEST_INSTALLED": str(self.installed),
                **overrides,
            },
            capture_output=True,
            text=True,
            check=False,
        )

    def test_complete_system_does_not_start_a_transaction(self) -> None:
        self.installed.write_text("\n".join(self.packages) + "\n")
        result = self.run_dependencies()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn("-Syu", self.log.read_text())
        self.assertIn("STAGING_REACHED", result.stdout)

    def test_only_missing_packages_are_requested_with_interactive_full_upgrade(self) -> None:
        self.installed.write_text("git\npython\nfakeroot\npolkit\n")
        result = self.run_dependencies()
        self.assertEqual(result.returncode, 0, result.stderr)
        transactions = [line for line in self.log.read_text().splitlines() if line.startswith("-S")]
        self.assertEqual(transactions, ["-Syu --needed pacman-contrib qt6-svg github-cli"])
        self.assertIn("STAGING_REACHED", result.stdout)

    def test_python_can_be_installed_before_it_is_required(self) -> None:
        self.installed.write_text("\n".join(p for p in self.packages if p != "python") + "\n")
        result = self.run_dependencies()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("-Syu --needed python", self.log.read_text())
        script = Path(__file__).resolve().parents[1].joinpath("install.sh").read_text()
        self.assertLess(
            script.index("\nensure_system_dependencies\n"),
            script.index("\nrequire_supported_python\n"),
        )

    def test_cancelled_or_failed_transaction_stops_before_staging(self) -> None:
        result = self.run_dependencies(TEST_FAIL="1")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("cancelled or failed", result.stdout)
        self.assertNotIn("STAGING_REACHED", result.stdout)

    def test_success_without_installed_packages_does_not_continue(self) -> None:
        result = self.run_dependencies(TEST_NO_CHANGE="1")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("still missing", result.stdout)
        self.assertNotIn("STAGING_REACHED", result.stdout)

    def test_missing_pacman_has_clear_error(self) -> None:
        (self.bin / "pacman").unlink()
        result = self.run_dependencies()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Arch-based system", result.stdout)
        self.assertNotIn("STAGING_REACHED", result.stdout)
