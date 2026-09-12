from __future__ import annotations

import json
import time
from collections.abc import Callable

from packaging.version import InvalidVersion, Version
from PySide6.QtCore import QObject, QUrl, Signal
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkReply, QNetworkRequest

from archupdater import __version__
from archupdater.domain.self_update import SelfUpdateRelease, self_update_release


GITHUB_URL = "https://github.com/Darayavaush-84/ArchUpdater"
RELEASES_URL = GITHUB_URL + "/releases/latest"
RELEASE_API_URL = "https://api.github.com/repos/Darayavaush-84/ArchUpdater/releases/latest"


def newer_release_tag(payload: object, current_version: str) -> str:
    if not isinstance(payload, dict):
        raise ValueError("Invalid release response")
    if payload.get("draft") is True or payload.get("prerelease") is True:
        return ""
    tag = payload.get("tag_name")
    if not isinstance(tag, str) or not tag.strip():
        raise ValueError("Missing release tag")
    tag = tag.strip()
    try:
        latest = Version(tag)
        current = Version(current_version)
    except InvalidVersion as exc:
        raise ValueError("Invalid release version") from exc
    return tag if not latest.is_prerelease and not latest.is_devrelease and latest > current else ""


class AppReleaseChecker(QObject):
    release_checked = Signal(str)
    check_finished = Signal()
    CACHE_TTL_SECONDS = 6 * 60 * 60
    RETRY_COOLDOWN_SECONDS = 10 * 60

    def __init__(
        self,
        parent: QObject | None = None,
        *,
        current_version: str = __version__,
        manager: QNetworkAccessManager | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        super().__init__(parent)
        self._manager = manager if manager is not None else QNetworkAccessManager(self)
        self._current_version = current_version
        self._clock = clock
        self._next_check_at = 0.0
        self._reply: QNetworkReply | None = None
        self.available_tag = ""
        self.available_release: SelfUpdateRelease | None = None

    def check(self, *, force: bool = False) -> None:
        if self._reply is not None or (not force and self._clock() < self._next_check_at):
            return
        request = QNetworkRequest(QUrl(RELEASE_API_URL))
        request.setRawHeader(b"Accept", b"application/vnd.github+json")
        request.setRawHeader(b"User-Agent", f"ArchUpdater/{self._current_version}".encode())
        request.setTransferTimeout(10000)
        self._reply = self._manager.get(request)
        self._reply.finished.connect(self._on_finished)

    def _on_finished(self) -> None:
        reply = self._reply
        if reply is None:
            return
        self._reply = None
        self._next_check_at = self._clock() + self.RETRY_COOLDOWN_SECONDS
        try:
            # Keep the last confirmed result on network/API failure, including
            # private or unavailable repositories (404).
            if reply.error() != QNetworkReply.NetworkError.NoError:
                return
            payload = json.loads(bytes(reply.readAll()))
            tag = newer_release_tag(payload, self._current_version)
            self.available_tag = tag
            self.available_release = self_update_release(payload, self._current_version)
            self._next_check_at = self._clock() + self.CACHE_TTL_SECONDS
            self.release_checked.emit(tag)
        except (ValueError, UnicodeError):
            pass
        finally:
            reply.deleteLater()
            self.check_finished.emit()
