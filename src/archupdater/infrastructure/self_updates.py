from __future__ import annotations

from pathlib import Path
import tempfile

from PySide6.QtCore import QObject, QProcess, QProcessEnvironment, QThread, Signal, Slot

from archupdater.domain.self_update import SelfUpdateRelease
from archupdater.services.self_update import download_release

SELF_UPDATE_HELPER = "/usr/lib/archupdater/archupdater-self-update"


class DownloadWorker(QObject):
    finished = Signal(object, str)

    def __init__(self, release: SelfUpdateRelease, directory: Path) -> None:
        super().__init__()
        self.release = release
        self.directory = directory

    @Slot()
    def run(self) -> None:
        try:
            paths = download_release(self.release, self.directory)
        except Exception as exc:
            self.finished.emit(None, str(exc))
        else:
            self.finished.emit(paths, "")


class SelfUpdateClient(QObject):
    stage_changed = Signal(str)
    completed = Signal(bool, str)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._temporary: tempfile.TemporaryDirectory | None = None
        self._thread: QThread | None = None
        self._worker: DownloadWorker | None = None
        self._process: QProcess | None = None
        self._release: SelfUpdateRelease | None = None
        self._download_result: tuple[object, str] = (None, "")
        self._output = bytearray()
        self.busy = False

    def start(self, release: SelfUpdateRelease) -> None:
        if self.busy:
            return
        self.busy = True
        self._release = release
        self._download_result = (None, "")
        try:
            self._temporary = tempfile.TemporaryDirectory(prefix="archupdater-self-update-")
        except OSError as exc:
            self._finish(False, str(exc))
            return
        self._thread = QThread(self)
        self._worker = DownloadWorker(release, Path(self._temporary.name))
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run)
        self._worker.finished.connect(self._download_finished)
        self._worker.finished.connect(self._thread.quit)
        self._thread.finished.connect(self._worker.deleteLater)
        self._thread.finished.connect(self._download_thread_stopped)
        self.stage_changed.emit("download")
        self._thread.start()

    @Slot(object, str)
    def _download_finished(self, paths: object, error: str) -> None:
        self._download_result = paths, error

    @Slot()
    def _download_thread_stopped(self) -> None:
        self._thread.wait()
        self._thread.deleteLater()
        self._thread = None
        self._worker = None
        paths, error = self._download_result
        if error or paths is None:
            self._finish(False, error)
            return
        wheel, bundle = paths
        self._start_helper(["--install", self._release.version, str(wheel), str(bundle)])

    def rollback(self) -> None:
        if not self.busy:
            self.busy = True
            self._start_helper(["--rollback"])

    def _start_helper(self, arguments: list[str]) -> None:
        self.stage_changed.emit("install")
        self._output.clear()
        self._process = QProcess(self)
        environment = QProcessEnvironment.systemEnvironment()
        for name in ("PYTHONPATH", "PYTHONHOME", "GH_TOKEN", "GITHUB_TOKEN"):
            environment.remove(name)
        self._process.setProcessEnvironment(environment)
        self._process.setProcessChannelMode(QProcess.ProcessChannelMode.MergedChannels)
        self._process.readyReadStandardOutput.connect(self._read_output)
        self._process.finished.connect(self._helper_finished)
        self._process.errorOccurred.connect(self._helper_error)
        self._process.start(
            "/usr/bin/pkexec", [SELF_UPDATE_HELPER, "--archupdater-auth=self-update", *arguments]
        )
        self._process.closeWriteChannel()

    @Slot()
    def _read_output(self) -> None:
        if self._process is not None:
            output = bytes(self._process.readAllStandardOutput())
            self._output.extend(output[: max(0, 64 * 1024 - len(self._output))])

    @Slot(QProcess.ProcessError)
    def _helper_error(self, error: QProcess.ProcessError) -> None:
        if error == QProcess.ProcessError.FailedToStart:
            self._finish(False, "Could not start the authorized updater.")

    @Slot(int, QProcess.ExitStatus)
    def _helper_finished(self, code: int, status: QProcess.ExitStatus) -> None:
        self._read_output()
        success = status == QProcess.ExitStatus.NormalExit and code == 0
        self._finish(
            success,
            "" if success else bytes(self._output).decode("utf-8", errors="replace").strip(),
        )

    def _finish(self, success: bool, details: str) -> None:
        if not self.busy:
            return
        if self._process is not None:
            self._process.deleteLater()
            self._process = None
        if self._temporary is not None:
            self._temporary.cleanup()
            self._temporary = None
        self.busy = False
        self.completed.emit(success, details)
