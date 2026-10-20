from __future__ import annotations

import os
import sys
import tempfile
import time
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from archupdater.infrastructure.single_instance import SingleInstanceGuard


class SingleInstanceGuardTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._app = QApplication.instance() or QApplication([])

    def setUp(self) -> None:
        self.server_name = f"io.github.archupdater.tests.{uuid.uuid4()}"
        self.guard = SingleInstanceGuard(self.server_name)

    def tearDown(self) -> None:
        self.guard.close()
        self._process_events(50)

    def test_notify_existing_emits_activation(self) -> None:
        activations: list[bool] = []
        self.assertTrue(self.guard.acquire())
        self.guard.activated.connect(lambda: activations.append(True))

        self.assertTrue(SingleInstanceGuard.notify_existing(self.server_name))
        self._process_until(lambda: bool(activations))

        self.assertEqual(activations, [True])

    def test_ping_existing_does_not_emit_activation(self) -> None:
        activations: list[bool] = []
        self.assertTrue(self.guard.acquire())
        self.guard.activated.connect(lambda: activations.append(True))

        self.assertTrue(SingleInstanceGuard.notify_existing(self.server_name, activate=False))
        self._process_events(100)

        self.assertEqual(activations, [])

    def test_second_guard_does_not_acquire_live_server(self) -> None:
        self.assertTrue(self.guard.acquire())
        second_guard = SingleInstanceGuard(self.server_name)

        try:
            self.assertFalse(second_guard.acquire())
        finally:
            second_guard.close()

    def test_default_server_name_is_scoped_to_user_and_graphical_session(self) -> None:
        with (
            patch("archupdater.infrastructure.single_instance.os.getuid", return_value=1000),
            patch.dict(
                "os.environ",
                {"XDG_SESSION_ID": "session-a"},
                clear=True,
            ),
        ):
            first = SingleInstanceGuard.default_server_name()
        with (
            patch("archupdater.infrastructure.single_instance.os.getuid", return_value=1000),
            patch.dict(
                "os.environ",
                {"XDG_SESSION_ID": "session-b"},
                clear=True,
            ),
        ):
            second = SingleInstanceGuard.default_server_name()
        with (
            patch("archupdater.infrastructure.single_instance.os.getuid", return_value=1001),
            patch.dict(
                "os.environ",
                {"XDG_SESSION_ID": "session-a"},
                clear=True,
            ),
        ):
            third = SingleInstanceGuard.default_server_name()

        self.assertNotEqual(first, second)
        self.assertNotEqual(first, third)
        self.assertIn(".1000.", first)

    def test_default_server_name_uses_private_runtime_directory(self) -> None:
        with tempfile.TemporaryDirectory() as runtime_directory:
            os.chmod(runtime_directory, 0o700)
            environment = {"XDG_SESSION_ID": "session-a", "XDG_RUNTIME_DIR": runtime_directory}
            with patch.dict("os.environ", environment, clear=True):
                name = SingleInstanceGuard.default_server_name()
                legacy = SingleInstanceGuard.legacy_server_name()
            self.assertEqual(Path(name).parent, Path(runtime_directory))
            self.assertTrue(Path(name).name.startswith(SingleInstanceGuard.SERVER_NAME_PREFIX))
            self.assertFalse(legacy.startswith("/"))

            os.chmod(runtime_directory, 0o755)
            with patch.dict("os.environ", environment, clear=True):
                self.assertEqual(SingleInstanceGuard.default_server_name(), legacy)
        with patch.dict("os.environ", {"XDG_RUNTIME_DIR": "relative/run"}, clear=True):
            self.assertFalse(SingleInstanceGuard.default_server_name().startswith("/"))

    def test_notify_existing_reaches_an_instance_on_the_legacy_name(self) -> None:
        with tempfile.TemporaryDirectory() as runtime_directory:
            os.chmod(runtime_directory, 0o700)
            environment = {
                "XDG_SESSION_ID": f"legacy-{os.getpid()}-{time.monotonic_ns()}",
                "XDG_RUNTIME_DIR": runtime_directory,
            }
            with patch.dict("os.environ", environment, clear=True):
                legacy_guard = SingleInstanceGuard(SingleInstanceGuard.legacy_server_name())
                activations: list[bool] = []
                legacy_guard.activated.connect(lambda: activations.append(True))
                self.assertTrue(legacy_guard.acquire())
                try:
                    self.assertTrue(SingleInstanceGuard.notify_existing())
                    self._process_until(lambda: bool(activations))
                    self.assertEqual(activations, [True])
                finally:
                    legacy_guard.close()

    def _process_until(self, condition, *, timeout_ms: int = 1000) -> None:  # noqa: ANN001
        deadline = time.monotonic() + (timeout_ms / 1000)
        while not condition() and time.monotonic() < deadline:
            self._app.processEvents()
            QTest.qWait(1)

    def _process_events(self, delay_ms: int) -> None:
        end = time.monotonic() + (delay_ms / 1000)
        while time.monotonic() < end:
            self._app.processEvents()
            QTest.qWait(1)


if __name__ == "__main__":
    unittest.main()
