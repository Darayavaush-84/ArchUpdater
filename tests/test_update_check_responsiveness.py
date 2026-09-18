from __future__ import annotations

import sys
import threading
import time
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import Mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from PySide6.QtCore import QEventLoop, QThread, QTimer
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from archupdater.application.updates import UpdateApplication
from archupdater.application.use_cases import ReadOptionalSources
from archupdater.domain.check_results import UpdateCheckResult
from archupdater.domain.enums import UpdateSource
from archupdater.presentation.update_controller import UpdateController
from archupdater.services.optional_sources import OptionalSourcesService


class UpdateCheckResponsivenessTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def test_firmware_probe_runs_in_check_worker_and_does_not_block_gui(self) -> None:
        release_probe = threading.Event()
        probe_threads: list[bool] = []

        def probe(_command: list[str], _timeout: float) -> tuple[int, str, str]:
            probe_threads.append(QThread.currentThread() is self.app.thread())
            release_probe.wait(2)
            return 0, '{"Devices": []}', ""

        sources = OptionalSourcesService(
            which=lambda name: "/usr/bin/fwupdmgr" if name == "fwupdmgr" else None,
            firmware_probe=probe,
        )
        check = Mock()
        check.run.return_value = UpdateCheckResult([], datetime.now(), [])
        service = UpdateApplication(
            check_updates_use_case=check, installation_use_case=Mock(),
            preflight_use_case=Mock(), optional_sources_reader=ReadOptionalSources(sources),
            plasma_shell_service=Mock(), plasma_widgets_update_service=Mock(),
        )
        controller = UpdateController(service)
        failures: list[str] = []
        controller.check_failed.connect(lambda message, _logs: failures.append(message))
        loop = QEventLoop()
        heartbeat: list[float] = []
        timer = QTimer()
        timer.setSingleShot(True)
        started = time.monotonic()

        def on_heartbeat() -> None:
            heartbeat.append(time.monotonic() - started)
            release_probe.set()
            loop.quit()

        timer.timeout.connect(on_heartbeat)
        try:
            timer.start(20)
            self.assertTrue(controller.start_check_updates())
            loop.exec()
            deadline = time.monotonic() + 2
            while controller.is_busy() and time.monotonic() < deadline:
                QTest.qWait(10)
            self.assertFalse(controller.is_busy())
            self.assertLess(heartbeat[0], 0.5)
            self.assertEqual(probe_threads, [False])
            self.assertEqual(failures, [])
            check.run.assert_called_once()
            self.assertEqual(
                service.optional_sources_snapshot().status_for(UpdateSource.FIRMWARE).status_text,
                "Installed, no compatible firmware devices detected",
            )
            self.assertEqual(probe_threads, [False])
        finally:
            release_probe.set()
            timer.stop()
            controller.shutdown()


if __name__ == "__main__":
    unittest.main()
