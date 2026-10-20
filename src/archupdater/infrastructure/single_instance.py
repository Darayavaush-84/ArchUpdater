from __future__ import annotations

import hashlib
import os
import stat
from pathlib import Path

from PySide6.QtCore import QObject, Signal
from PySide6.QtNetwork import QLocalServer, QLocalSocket


class SingleInstanceGuard(QObject):
    SERVER_NAME_PREFIX = "io.github.archupdater.instance"
    ACTIVATE_MESSAGE = b"activate\n"
    PING_MESSAGE = b"ping\n"

    activated = Signal()

    def __init__(
        self,
        server_name: str | None = None,
        *,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._server_name = server_name or self.default_server_name()
        self._server: QLocalServer | None = None
        self._sockets: set[QLocalSocket] = set()

    @classmethod
    def notify_existing(
        cls,
        server_name: str | None = None,
        *,
        activate: bool = True,
        timeout_ms: int = 500,
    ) -> bool:
        if server_name is not None:
            return cls._notify(server_name, activate=activate, timeout_ms=timeout_ms)
        # Instances started by an older release still listen on the legacy name.
        candidates = dict.fromkeys((cls.default_server_name(), cls.legacy_server_name()))
        return any(
            cls._notify(candidate, activate=activate, timeout_ms=timeout_ms)
            for candidate in candidates
        )

    @classmethod
    def _notify(cls, server_name: str, *, activate: bool, timeout_ms: int) -> bool:
        socket = QLocalSocket()
        socket.connectToServer(server_name)
        if not socket.waitForConnected(timeout_ms):
            socket.abort()
            return False

        message = cls.ACTIVATE_MESSAGE if activate else cls.PING_MESSAGE
        socket.write(message)
        socket.flush()
        socket.waitForBytesWritten(timeout_ms)
        socket.disconnectFromServer()
        if socket.state() != QLocalSocket.LocalSocketState.UnconnectedState:
            socket.waitForDisconnected(timeout_ms)
        return True

    @classmethod
    def default_server_name(cls) -> str:
        # A relative name lives in the shared /tmp, where another local user could
        # claim it first. The per-user runtime directory is private to this user.
        runtime_directory = cls._private_runtime_directory()
        if runtime_directory is not None:
            path = runtime_directory / f"{cls.SERVER_NAME_PREFIX}.{cls._session_digest()}"
            if len(os.fsencode(path)) < 100:
                return str(path)
        return cls.legacy_server_name()

    @classmethod
    def legacy_server_name(cls) -> str:
        return f"{cls.SERVER_NAME_PREFIX}.{os.getuid()}.{cls._session_digest()}"

    @staticmethod
    def _session_digest() -> str:
        session_identity = next(
            (
                value
                for value in (
                    os.environ.get("XDG_SESSION_ID"),
                    os.environ.get("WAYLAND_DISPLAY"),
                    os.environ.get("DISPLAY"),
                    os.environ.get("XDG_RUNTIME_DIR"),
                )
                if value
            ),
            "headless",
        )
        return hashlib.sha256(session_identity.encode("utf-8")).hexdigest()[:12]

    @staticmethod
    def _private_runtime_directory() -> Path | None:
        raw_path = os.environ.get("XDG_RUNTIME_DIR", "")
        if not raw_path.startswith("/"):
            return None
        path = Path(raw_path)
        try:
            info = path.lstat()
        except OSError:
            return None
        if (
            not stat.S_ISDIR(info.st_mode)
            or info.st_uid != os.getuid()
            or info.st_mode & 0o077
        ):
            return None
        return path

    def acquire(self) -> bool:
        if self._server is not None:
            return True

        server = QLocalServer(self)
        if self._listen(server):
            return True

        if self.notify_existing(self._server_name, activate=False, timeout_ms=200):
            server.deleteLater()
            return False

        QLocalServer.removeServer(self._server_name)
        if self._listen(server):
            return True

        server.deleteLater()
        return False

    def close(self) -> None:
        owns_server = self._server is not None
        if self._server is not None:
            self._server.close()
            self._server.deleteLater()
            self._server = None
        if owns_server:
            QLocalServer.removeServer(self._server_name)

        for socket in tuple(self._sockets):
            self._discard_socket(socket)

    def _listen(self, server: QLocalServer) -> bool:
        if not server.listen(self._server_name):
            return False
        self._server = server
        server.newConnection.connect(self._handle_new_connection)
        return True

    def _handle_new_connection(self) -> None:
        if self._server is None:
            return
        while self._server.hasPendingConnections():
            socket = self._server.nextPendingConnection()
            if socket is None:
                continue
            self._sockets.add(socket)
            socket.readyRead.connect(lambda socket=socket: self._handle_socket_ready(socket))
            socket.disconnected.connect(lambda socket=socket: self._discard_socket(socket))

    def _handle_socket_ready(self, socket: QLocalSocket) -> None:
        message = bytes(socket.readAll()).strip()
        if message == self.ACTIVATE_MESSAGE.strip():
            self.activated.emit()
        socket.disconnectFromServer()

    def _discard_socket(self, socket: QLocalSocket) -> None:
        self._sockets.discard(socket)
        socket.deleteLater()
