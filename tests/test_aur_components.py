from __future__ import annotations

import io
import json
import shutil
import stat
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch
from urllib.parse import parse_qs

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from support.aur import LocalGitAurReviewManager

from archupdater.domain.aur import AurVcsSource
from archupdater.services.aur import AurBuildError, AurPkgbuildFetchError
from archupdater.services.aur_rpc import AurRpcClient
from archupdater.services.aur_vcs_state import AurVcsStateStore


class AurRpcTests(unittest.TestCase):
    def test_injected_transport_receives_post_names_and_timeout(self) -> None:
        response = io.BytesIO(json.dumps({"results": [{"Name": "foo"}]}).encode())
        opener = Mock(return_value=response)
        client = AurRpcClient(opener=opener)
        self.assertEqual(client.fetch_chunk(["foo", "bar+baz"]), {"results": [{"Name": "foo"}]})
        request = opener.call_args.args[0]
        self.assertEqual(request.full_url, "https://aur.archlinux.org/rpc/v5/info")
        self.assertEqual(request.method, "POST")
        self.assertEqual(parse_qs(request.data.decode()), {"arg[]": ["foo", "bar+baz"]})
        self.assertEqual(opener.call_args.kwargs, {"timeout": 10})
        self.assertTrue(response.closed)

    def test_invalid_and_oversized_responses_are_closed_and_ignored(self) -> None:
        for raw in (b"invalid JSON", b"[]", b"x" * 65):
            with self.subTest(raw=raw):
                response = io.BytesIO(raw)
                client = AurRpcClient(opener=Mock(return_value=response))
                client.AUR_RPC_MAX_BYTES = 64
                self.assertEqual(client.fetch_chunk(["foo"]), {})
                self.assertTrue(response.closed)

    def test_network_failure_is_nonfatal(self) -> None:
        client = AurRpcClient(opener=Mock(side_effect=OSError("offline")))
        self.assertEqual(client.fetch_chunk(["foo"]), {})

    def test_empty_package_list_does_not_contact_network(self) -> None:
        opener = Mock(side_effect=AssertionError("unexpected network"))
        self.assertEqual(AurRpcClient(opener=opener).fetch_metadata([]), {})
        opener.assert_not_called()


class AurVcsStateTests(unittest.TestCase):
    def setUp(self) -> None:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.path = Path(directory.name) / "state" / "aur-vcs.json"
        self.store = AurVcsStateStore(self.path)
        self.source = AurVcsSource("foo", "https://example.invalid/foo.git", None, "a" * 40)

    def test_receipts_round_trip_without_losing_other_packages(self) -> None:
        self.store.record_install("foo-git", "r1-1", (self.source,))
        self.store.record_install("bar-git", "r2-1", (self.source,))
        state = AurVcsStateStore(self.path).load()
        self.assertEqual(state["packages"]["foo-git"]["version"], "r1-1")
        self.assertEqual(state["packages"]["bar-git"]["sources"][0]["commit"], "a" * 40)
        self.assertEqual(stat.S_IMODE(self.path.stat().st_mode), 0o600)
        self.assertEqual(list(self.path.parent.iterdir()), [self.path])

    def test_failed_atomic_replace_preserves_receipt_and_removes_temporary_file(self) -> None:
        self.store.record_install("foo-git", "r1-1", (self.source,))
        original = self.path.read_bytes()
        with patch(
            "archupdater.services.aur_vcs_state.os.replace", side_effect=OSError("disk error")
        ):
            with self.assertRaises(OSError):
                self.store.record_install("foo-git", "r2-1", (self.source,))
        self.assertEqual(self.path.read_bytes(), original)
        self.assertEqual(list(self.path.parent.iterdir()), [self.path])

    def test_oversized_save_does_not_replace_previous_state(self) -> None:
        self.store.record_install("foo-git", "r1-1", (self.source,))
        original = self.path.read_bytes()
        self.store.VCS_STATE_MAX_BYTES = 8
        with self.assertRaises(AurBuildError):
            self.store.save({"too_large": "payload"})
        self.assertEqual(self.path.read_bytes(), original)
        self.assertEqual(self.store.load()["packages"], {})

    def test_corrupt_state_is_ignored(self) -> None:
        self.path.parent.mkdir()
        self.path.write_text("{broken")
        self.assertEqual(self.store.load()["packages"], {})


@unittest.skipUnless(shutil.which("git"), "requires local Git")
class AurReviewLifecycleTests(unittest.TestCase):
    def setUp(self) -> None:
        self.manager = LocalGitAurReviewManager(
            {
                "PKGBUILD": "pkgname=foo\npkgver=1\npkgrel=1\n",
                ".SRCINFO": "pkgbase = foo\npkgname = foo\n",
            }
        )

    def test_discard_removes_checkout_and_invalidates_review(self) -> None:
        review = self.manager.prepare("foo", "foo")
        self.addCleanup(self.manager.discard, review)
        checkout = self.manager.checkout_path
        self.assertTrue(checkout.is_dir())
        self.assertEqual(self.manager.missing_build_dependencies(review), [])
        self.manager.discard(review)
        self.manager.discard(review)
        self.assertFalse(checkout.parent.exists())
        with self.assertRaisesRegex(AurBuildError, "no longer available"):
            self.manager.missing_build_dependencies(review)

    def test_failed_preparation_removes_temporary_checkout(self) -> None:
        del self.manager.files[".SRCINFO"]
        with self.assertRaisesRegex(AurPkgbuildFetchError, "no textual .SRCINFO"):
            self.manager.prepare("foo", "foo")
        self.assertFalse(self.manager.checkout_path.parent.exists())

    def test_changes_after_review_are_rejected_before_dependency_check(self) -> None:
        review = self.manager.prepare("foo", "foo")
        self.addCleanup(self.manager.discard, review)
        (self.manager.checkout_path / "PKGBUILD").write_text("pkgname=changed\n")
        with self.assertRaisesRegex(AurPkgbuildFetchError, "not clean"):
            self.manager.missing_build_dependencies(review)
