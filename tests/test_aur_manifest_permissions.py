from __future__ import annotations

from copy import deepcopy
import json
import os
from pathlib import Path
import pwd
import shutil
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from support.aur import LocalGitAurReviewManager
from archupdater.application.helper_protocol import HelperAction, HelperRequest
from archupdater.helper.actions.aur_review import validate_aur_build_review
from archupdater.helper.actions.aur_workspace import (
    AurBuildUser, _create_user_aur_build_checkout, _seal_aur_build_checkout,
)
from archupdater.helper.actions.validation import PrivilegedUpdateValidationError
from archupdater.presentation.update_interaction_dialogs import _review_from_payload
from archupdater.services.aur_errors import AurBuildError


class ExecutableReviewManager(LocalGitAurReviewManager):
    def _clone_checkout(self, package_base, checkout_path):
        super()._clone_checkout(package_base, checkout_path)
        (checkout_path / "helper.sh").chmod(0o755)
        subprocess.run([
            "git", "-C", str(checkout_path), "-c", "core.hooksPath=/dev/null",
            "-c", "commit.gpgsign=false", "-c", "user.name=Test",
            "-c", "user.email=test@example.invalid", "commit", "-qam", "executable",
        ], check=True, capture_output=True)


@unittest.skipUnless(shutil.which("git"), "requires local Git")
class AurManifestPermissionTests(unittest.TestCase):
    def setUp(self):
        self.manager = ExecutableReviewManager({
            "PKGBUILD": "pkgname=foo\npkgver=1\npkgrel=1\n",
            ".SRCINFO": "pkgbase = foo\npkgname = foo\n",
            "helper.sh": "#!/bin/sh\nprintf 'review OK\\n'\n",
        })
        self.review = self.manager.prepare("foo", "foo")
        self.addCleanup(self.manager.discard, self.review)
        self.payload = json.loads(HelperRequest(
            HelperAction.INSTALL_REVIEWED_AUR, aur_review=self.review, expected_version="1-1"
        ).to_json_bytes())["aur_review"]

    def gui_payload(self, payload):
        return {**payload, "pkgbuild": self.review.pkgbuild, "commit": self.review.commit}

    def test_executable_roundtrips_through_helper_and_gui_and_runs_in_build_copy(self):
        parsed = validate_aur_build_review(self.payload)
        self.assertEqual(parsed.files, self.review.files)
        gui_review = _review_from_payload(self.gui_payload(self.payload))
        self.assertIsNotNone(gui_review)
        self.assertEqual(gui_review.files, self.review.files)
        self.assertIn("mode=0700", gui_review.rendered_content())
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            sealed = _seal_aur_build_checkout(parsed, build_root=root)
            workspace = root / "workspace"
            workspace.mkdir()
            user = AurBuildUser(pwd.getpwuid(os.getuid()).pw_name, os.getuid(), os.getgid(), root)
            checkout = _create_user_aur_build_checkout(
                sealed, parsed, build_root=workspace, build_user=user,
            )
            self.assertEqual((checkout / "helper.sh").stat().st_mode & 0o7777, 0o700)
            self.assertEqual((checkout / "PKGBUILD").stat().st_mode & 0o7777, 0o600)
            result = subprocess.run([str(checkout / "helper.sh")], capture_output=True, text=True, check=True)
            self.assertEqual(result.stdout, "review OK\n")

    def test_changed_executable_bit_invalidates_manifest_for_both_consumers(self):
        payload = deepcopy(self.payload)
        entry = next(f for f in payload["files"] if f["path"] == "helper.sh")
        self.assertIs(entry["executable"], True)
        entry["executable"] = False
        with self.assertRaisesRegex(PrivilegedUpdateValidationError, "digest"):
            validate_aur_build_review(payload)
        self.assertIsNone(_review_from_payload(self.gui_payload(payload)))

    def test_executable_flag_is_required_and_strictly_boolean(self):
        for value in (1, "true", None, "missing"):
            with self.subTest(value=value):
                payload = deepcopy(self.payload)
                if value == "missing":
                    del payload["files"][0]["executable"]
                else:
                    payload["files"][0]["executable"] = value
                with self.assertRaises(PrivilegedUpdateValidationError):
                    validate_aur_build_review(payload)
                self.assertIsNone(_review_from_payload(self.gui_payload(payload)))

    def test_mode_change_after_review_is_rejected_even_when_git_ignores_filemode(self):
        checkout = self.manager.checkout_path
        subprocess.run(["git", "-C", str(checkout), "config", "core.filemode", "false"], check=True)
        (checkout / "helper.sh").chmod(0o600)
        with self.assertRaisesRegex(AurBuildError, "changed after"):
            self.manager.missing_build_dependencies(self.review)


if __name__ == "__main__":
    unittest.main()
