from __future__ import annotations

from PySide6.QtCore import QByteArray, QObject, Signal
from PySide6.QtNetwork import QNetworkReply


class FakeNetworkReply(QObject):
    finished = Signal()

    def __init__(self, payload: bytes, error=QNetworkReply.NetworkError.NoError) -> None:
        super().__init__()
        self.payload = payload
        self.network_error = error
        self.deleted = False

    def error(self):
        return self.network_error

    def readAll(self):
        return QByteArray(self.payload)

    def deleteLater(self) -> None:
        self.deleted = True


class FakeNetworkAccessManager:
    def __init__(self, reply: FakeNetworkReply) -> None:
        self.requests = []
        self.reply = reply

    def get(self, request):
        self.requests.append(request)
        return self.reply


class FakeReachability:
    Disconnected = object()
    Online = object()


class FakeNetworkInformation(QObject):
    reachabilityChanged = Signal(object)

    def __init__(self, reachability: object) -> None:
        super().__init__()
        self._reachability = reachability

    def reachability(self) -> object:
        return self._reachability

    def set_reachability(self, reachability: object) -> None:
        self._reachability = reachability
        self.reachabilityChanged.emit(reachability)


class FakeNetworkInformationApi:
    Reachability = FakeReachability

    def __init__(self, network_information: FakeNetworkInformation) -> None:
        self._network_information = network_information

    def loadDefaultBackend(self) -> bool:
        return True

    def instance(self) -> FakeNetworkInformation:
        return self._network_information
