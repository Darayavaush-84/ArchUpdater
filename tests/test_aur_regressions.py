from __future__ import annotations

import io
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from archupdater.domain.aur import AurVcsSource
from archupdater.services.aur_errors import AurPkgbuildFetchError
from archupdater.services.aur_metadata import apply_aur_rpc_metadata, parse_update_lines
from archupdater.services.aur_review import AurReviewManager
from archupdater.services.aur_rpc import AurRpcClient
from archupdater.services.aur_vcs import AurVcsTracker
from archupdater.services.aur_vcs_state import AurVcsStateStore
from archupdater.services.command_runner import CommandRunner
from support.aur import LocalGitAurReviewManager, create_git_checkout
from support.commands import CommandResponse, FakeCommandRunner


class AurResponseRegressionTests(unittest.TestCase):
    def test_remote_commit_accepts_only_the_exact_requested_ref(self) -> None:
        expected_commit = "a" * 40
        other_commit = "b" * 40
        for branch, expected_ref in ((None, "HEAD"), ("release", "refs/heads/release")):
            with self.subTest(branch=branch):
                runner = FakeCommandRunner(
                    [
                        CommandResponse(
                            stdout=(
                                f"{other_commit}\trefs/heads/aaa/release\n"
                                f"{other_commit}\trefs/tags/release\n"
                                f"{expected_commit}\t{expected_ref}\n"
                            )
                        )
                    ]
                )
                tracker = AurVcsTracker(runner, AurVcsStateStore())
                commit, _log = tracker.remote_commit("https://example.invalid/foo.git", branch)
                self.assertEqual(commit, expected_commit)

    def test_missing_or_malformed_exact_ref_is_not_a_commit(self) -> None:
        for output in (
            f"{'a' * 40}\trefs/tags/release\n",
            f"{'a' * 40}\trefs/heads/aaa/release\n",
            f"{'a' * 40}\n",
            "not-a-commit\trefs/heads/release\n",
        ):
            with self.subTest(output=output):
                runner = FakeCommandRunner([CommandResponse(stdout=output)])
                tracker = AurVcsTracker(runner, AurVcsStateStore())
                commit, _log = tracker.remote_commit("https://example.invalid/foo.git", "release")
                self.assertEqual(commit, "")

    def test_out_of_range_timestamps_do_not_discard_other_package_metadata(self) -> None:
        for timestamp in (10**30, 253402300800):
            with self.subTest(timestamp=timestamp):
                packages = parse_update_lines("foo 1 -> 2\nbar 1 -> 2")
                apply_aur_rpc_metadata(
                    packages,
                    {
                        "foo": {
                            "PackageBase": "foo",
                            "Maintainer": "alice",
                            "FirstSubmitted": timestamp,
                            "LastModified": timestamp,
                            "OutOfDate": timestamp,
                            "URL": "https://example.invalid/foo",
                        },
                        "bar": {
                            "PackageBase": "bar",
                            "Maintainer": "bob",
                            "LastModified": 1704067200,
                        },
                    },
                )
                self.assertIsNone(packages[0].source_metadata.first_submitted)
                self.assertIsNone(packages[0].source_metadata.last_modified)
                self.assertIsNone(packages[0].source_metadata.out_of_date)
                self.assertEqual(packages[0].source_metadata.maintainer, "alice")
                self.assertEqual(packages[0].homepage, "https://example.invalid/foo")
                self.assertEqual(packages[1].source_metadata.last_modified, "2024-01-01")

    def test_invalid_rpc_results_raise_a_preparation_error_before_any_command(self) -> None:
        for results in (42, True, "invalid", {"Name": "foo"}, None, []):
            with self.subTest(results=results):
                response = io.BytesIO(json.dumps({"results": results}).encode())
                rpc = AurRpcClient(opener=Mock(return_value=response))
                runner = FakeCommandRunner()
                manager = AurReviewManager(runner, rpc, AurVcsTracker(runner, AurVcsStateStore()))
                with self.assertRaisesRegex(AurPkgbuildFetchError, "Could not resolve.*foo"):
                    manager.prepare("foo")
                self.assertEqual(runner.commands, [])
                self.assertTrue(response.closed)


@unittest.skipUnless(shutil.which("git"), "requires local Git")
class AurGitRefRegressionTests(unittest.TestCase):
    def test_branch_collision_does_not_hide_new_commits_or_accept_a_tag(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            checkout = Path(directory) / "checkout"

            def git(*arguments: str) -> str:
                return subprocess.check_output(
                    ["git", "-C", str(checkout), *arguments],
                    text=True,
                ).strip()

            create_git_checkout(checkout, {"PKGBUILD": "pkgver=1\n"})
            old_commit = git("rev-parse", "HEAD")
            git("branch", "aaa/release")
            git("tag", "release")
            create_git_checkout(checkout, {"PKGBUILD": "pkgver=2\n"})
            new_commit = git("rev-parse", "HEAD")
            git("branch", "release")
            tracker = AurVcsTracker(
                CommandRunner(), AurVcsStateStore(Path(directory) / "state.json")
            )
            source = AurVcsSource("foo", str(checkout), "release", old_commit)
            tracker.store.record_install("foo-git", "r1-1", (source,))
            packages = parse_update_lines("foo-git r1-1 -> latest-commit")
            filtered = tracker.filter_stale_updates(
                packages,
                local_output="Name : foo-git\nVersion : r1-1\n",
                logs=[],
            )
            self.assertEqual(filtered, packages)
            self.assertEqual(tracker.remote_commit(str(checkout), "release")[0], new_commit)
            self.assertEqual(tracker.remote_commit(str(checkout), None)[0], new_commit)
            git("branch", "-D", "release")
            self.assertEqual(tracker.remote_commit(str(checkout), "release")[0], "")

    def test_valid_rpc_package_base_still_prepares_the_review(self) -> None:
        manager = LocalGitAurReviewManager(
            {
                "PKGBUILD": "pkgname=foo\npkgver=1\n",
                ".SRCINFO": "pkgbase = foo\npkgname = foo\n",
            }
        )
        response = io.BytesIO(
            json.dumps({"results": [None, {"Name": "foo", "PackageBase": "foo"}]}).encode()
        )
        manager.rpc = AurRpcClient(opener=Mock(return_value=response))
        review = manager.prepare("foo")
        self.addCleanup(manager.discard, review)
        self.assertEqual(review.package_base, "foo")
        self.assertEqual(manager.fetched, ["foo"])
