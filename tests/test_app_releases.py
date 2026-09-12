from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from PySide6.QtCore import QByteArray, QObject, Signal
from PySide6.QtNetwork import QNetworkReply
from PySide6.QtWidgets import QApplication

from archupdater.infrastructure.app_releases import AppReleaseChecker, RELEASE_API_URL, newer_release_tag


class FakeReply(QObject):
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


class FakeManager:
    def __init__(self) -> None:
        self.requests = []
        self.reply = FakeReply(b'{"tag_name":"v1.1.0"}')

    def get(self, request):
        self.requests.append(request)
        return self.reply


class AppReleaseTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def test_compares_versions_numerically_and_accepts_v_prefix(self) -> None:
        self.assertEqual(newer_release_tag({"tag_name": "v0.10.0"}, "0.9.0.0"), "v0.10.0")
        self.assertEqual(newer_release_tag({"tag_name": "v1.1.0"}, "1.1.0.0"), "")
        self.assertEqual(newer_release_tag({"tag_name": "v1.0.0"}, "1.1.0"), "")

    def test_ignores_drafts_and_unstable_releases(self) -> None:
        for payload in (
            {"tag_name": "v2.0.0", "draft": True},
            {"tag_name": "v2.0.0", "prerelease": True},
            {"tag_name": "v2.0.0rc1"},
            {"tag_name": "v2.0.0.dev1"},
        ):
            with self.subTest(payload=payload):
                self.assertEqual(newer_release_tag(payload, "1.0.0"), "")

    def test_rejects_malformed_payloads_without_claiming_up_to_date(self) -> None:
        for payload in (None, [], {}, {"tag_name": 2}, {"tag_name": "latest"}):
            with self.subTest(payload=payload), self.assertRaises(ValueError):
                newer_release_tag(payload, "1.0.0")

    def test_request_is_asynchronous_deduplicated_and_throttled(self) -> None:
        manager = FakeManager()
        now = [100.0]
        checker = AppReleaseChecker(manager=manager, current_version="1.0.0", clock=lambda: now[0])
        received = []
        checker.release_checked.connect(received.append)
        checker.check()
        checker.check()
        self.assertEqual(len(manager.requests), 1)
        self.assertEqual(received, [])
        request = manager.requests[0]
        self.assertEqual(request.url().toString(), RELEASE_API_URL)
        self.assertEqual(request.transferTimeout(), 10000)
        self.assertFalse(request.hasRawHeader("Authorization"))
        manager.reply.finished.emit()
        self.assertEqual(received, ["v1.1.0"])
        self.assertEqual(checker.available_tag, "v1.1.0")
        self.assertTrue(manager.reply.deleted)
        checker.check()
        self.assertEqual(len(manager.requests), 1)
        now[0] += checker.CHECK_INTERVAL_SECONDS
        manager.reply = FakeReply(b'{"tag_name":"v1.0.0"}')
        checker.check()
        manager.reply.finished.emit()
        self.assertEqual(received[-1], "")
        self.assertEqual(checker.available_tag, "")

    def test_failures_preserve_confirmed_update_and_allow_retry(self) -> None:
        for payload, error in (
            (b'{}', QNetworkReply.NetworkError.ContentNotFoundError),
            (b'', QNetworkReply.NetworkError.TimeoutError),
            (b'not json', QNetworkReply.NetworkError.NoError),
            (json.dumps({"message": "rate limited"}).encode(), QNetworkReply.NetworkError.NoError),
        ):
            with self.subTest(error=error, payload=payload):
                manager = FakeManager()
                manager.reply = FakeReply(payload, error)
                now = [100.0]
                checker = AppReleaseChecker(manager=manager, clock=lambda: now[0])
                checker.available_tag = "v1.1.0"
                received, finished = [], []
                checker.release_checked.connect(received.append)
                checker.check_finished.connect(lambda: finished.append(True))
                checker.check()
                manager.reply.finished.emit()
                self.assertEqual(received, [])
                self.assertEqual(finished, [True])
                self.assertEqual(checker.available_tag, "v1.1.0")
                self.assertTrue(manager.reply.deleted)
                checker.check()
                self.assertEqual(len(manager.requests), 1)
                now[0] += checker.RETRY_INTERVAL_SECONDS
                manager.reply = FakeReply(b'{"tag_name":"v1.2.0"}')
                checker.check()
                self.assertEqual(len(manager.requests), 2)
                manager.reply.finished.emit()
                self.assertEqual(received, ["v1.2.0"])


if __name__ == "__main__":
    unittest.main()
