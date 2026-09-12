from __future__ import annotations

import subprocess
import sys
import time
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from archupdater.services.batch_process import BatchProcessRunner


class _ProcessStub:
    def __init__(self, *, exits_after_terminate: bool) -> None:
        self.exits_after_terminate = exits_after_terminate
        self.terminated = 0
        self.killed = 0
        self.wait_calls: list[int | None] = []
        self._running = True

    def poll(self) -> int | None:
        return None if self._running else 0

    def terminate(self) -> None:
        self.terminated += 1
        if self.exits_after_terminate:
            self._running = False

    def kill(self) -> None:
        self.killed += 1
        self._running = False

    def wait(self, timeout: int | None = None) -> int:
        self.wait_calls.append(timeout)
        if self._running:
            raise subprocess.TimeoutExpired("fake", timeout)
        return 0


class BatchProcessRunnerTests(unittest.TestCase):
    def _runner(self) -> BatchProcessRunner:
        return BatchProcessRunner(
            print_line=lambda _line: None,
            emit_log=lambda _line: None,
            translate=lambda value: value,
        )

    def test_terminate_process_waits_after_graceful_terminate(self) -> None:
        process = _ProcessStub(exits_after_terminate=True)

        self._runner()._terminate_process(process)  # type: ignore[arg-type]

        self.assertEqual(process.terminated, 1)
        self.assertEqual(process.killed, 0)
        self.assertEqual(process.wait_calls, [2])

    def test_terminate_process_kills_after_timeout(self) -> None:
        process = _ProcessStub(exits_after_terminate=False)

        self._runner()._terminate_process(process)  # type: ignore[arg-type]

        self.assertEqual(process.terminated, 1)
        self.assertEqual(process.killed, 1)
        self.assertEqual(process.wait_calls, [2, 1])

    def test_noninteractive_timeout_terminates_process(self) -> None:
        runner = self._runner()
        original_timeout = BatchProcessRunner.NONINTERACTIVE_TIMEOUT_SECONDS
        BatchProcessRunner.NONINTERACTIVE_TIMEOUT_SECONDS = 0.01
        try:
            result = runner.run_process(
                [sys.executable, "-c", "import time; time.sleep(1)"],
            )
        finally:
            BatchProcessRunner.NONINTERACTIVE_TIMEOUT_SECONDS = original_timeout

        self.assertFalse(result.success)
        self.assertEqual(result.return_code, 124)
        self.assertEqual(result.output, "Update command timed out.")

    def test_noninteractive_process_emits_output_while_running(self) -> None:
        printed: list[tuple[str, float]] = []
        started_at = time.monotonic()
        runner = BatchProcessRunner(
            print_line=lambda line: printed.append((line, time.monotonic() - started_at)),
            emit_log=lambda _line: None,
            translate=lambda value: value,
        )

        result = runner.run_process(
            [
                sys.executable,
                "-c",
                (
                    "import sys, time; "
                    "print('first', flush=True); "
                    "time.sleep(0.4); "
                    "print('second', flush=True)"
                ),
            ],
        )

        self.assertTrue(result.success)
        self.assertEqual([line for line, _elapsed in printed], ["first", "second"])
        self.assertLess(printed[0][1], 0.3)

    def test_noninteractive_process_stdout_uses_terminal(self) -> None:
        result = self._runner().run_process(
            [sys.executable, "-c", "import sys; print(sys.stdout.isatty(), flush=True)"],
        )

        self.assertTrue(result.success)
        self.assertEqual(result.output, "True")

    def test_noninteractive_process_starts_new_session_for_group_termination(self) -> None:
        with patch("archupdater.services.batch_process.subprocess.Popen", wraps=subprocess.Popen) as popen:
            result = self._runner().run_process(
                [sys.executable, "-c", "print('ok', flush=True)"],
            )

        self.assertTrue(result.success)
        self.assertTrue(popen.call_args.kwargs["start_new_session"])

if __name__ == "__main__":
    unittest.main()
