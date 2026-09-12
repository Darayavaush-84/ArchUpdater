from __future__ import annotations

import hashlib
import os

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
        effective_server_name = server_name or cls.default_server_name()
        socket = QLocalSocket()
        socket.connectToServer(effective_server_name)
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
        digest = hashlib.sha256(session_identity.encode("utf-8")).hexdigest()[:12]
        return f"{cls.SERVER_NAME_PREFIX}.{os.getuid()}.{digest}"

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
