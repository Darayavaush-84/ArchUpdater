from __future__ import annotations

import sys
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from archupdater.services.command_runner import CommandRunner


class CommandRunnerTests(unittest.TestCase):
    def test_run_returns_timeout_log_entry(self) -> None:
        runner = CommandRunner(default_timeout_seconds=0.01)

        log_entry = runner.run(
            [sys.executable, "-c", "import time; time.sleep(1)"],
        )

        self.assertEqual(log_entry.exit_code, -124)
        self.assertTrue(log_entry.timed_out)
        self.assertIn("timed out", log_entry.stderr)

    def test_run_allows_per_command_timeout_override(self) -> None:
        runner = CommandRunner(default_timeout_seconds=0.01)

        log_entry = runner.run(
            [sys.executable, "-c", "print('ok')"],
            timeout_seconds=1,
        )

        self.assertEqual(log_entry.exit_code, 0)
        self.assertFalse(log_entry.timed_out)
        self.assertEqual(log_entry.stdout.strip(), "ok")

    def test_run_terminates_command_when_combined_output_exceeds_limit(self) -> None:
        runner = CommandRunner(default_timeout_seconds=2, max_output_bytes=1024)

        log_entry = runner.run(
            [
                sys.executable,
                "-c",
                "import sys; sys.stdout.write('x' * 900); sys.stderr.write('y' * 900)",
            ],
        )

        self.assertEqual(log_entry.exit_code, -125)
        self.assertLessEqual(
            len(log_entry.stdout.encode()) + len(log_entry.stderr.encode()),
            1200,
        )
        self.assertIn("safety limit", log_entry.stderr)

    def test_run_kills_descendant_that_keeps_output_pipe_open(self) -> None:
        runner = CommandRunner(
            default_timeout_seconds=2,
            termination_grace_seconds=0.05,
            kill_drain_seconds=0.2,
        )
        started_at = time.monotonic()

        log_entry = runner.run(
            [
                sys.executable,
                "-c",
                (
                    "import subprocess, sys; "
                    "subprocess.Popen([sys.executable, '-c', "
                    "'import signal, time; signal.signal(signal.SIGTERM, signal.SIG_IGN); "
                    "time.sleep(30)'])"
                ),
            ],
        )

        self.assertEqual(log_entry.exit_code, 0)
        self.assertLess(time.monotonic() - started_at, 1)


if __name__ == "__main__":
    unittest.main()
