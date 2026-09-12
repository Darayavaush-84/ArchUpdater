from __future__ import annotations

import copy
import io
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch
import urllib.request
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from archupdater.domain.self_update import MAX_WHEEL_BYTES, REPOSITORY, self_update_release
from archupdater.helper.self_update import (
    ManagedInstall,
    private_copy,
    site_packages,
    wheel_version,
)
from archupdater.services.self_update import (
    ReleaseRedirectHandler,
    download_release,
    verify_artifact,
)


def release_payload():
    names = [
        "archupdater-1.0.1-py3-none-any.whl",
        "archupdater-1.0.1-py3-none-any.whl.sigstore.json",
    ]
    return {
        "tag_name": "v1.0.1",
        "body": "Release notes",
        "assets": [
            {
                "name": name,
                "size": 100,
                "browser_download_url": f"https://github.com/{REPOSITORY}/releases/download/v1.0.1/{name}",
            }
            for name in names
        ],
    }


class ReleaseCandidateTests(unittest.TestCase):
    def test_accepts_new_stable_release_with_exact_assets(self):
        release = self_update_release(release_payload(), "1.0.0")
        self.assertEqual(release.version, "1.0.1")
        self.assertEqual(release.notes, "Release notes")

    def test_rejects_ineligible_versions_and_missing_assets(self):
        for changes in (
            {"draft": True},
            {"prerelease": True},
            {"tag_name": "v1.0.0"},
            {"tag_name": "v1.0.2rc1"},
            {"tag_name": "v01.0.1"},
            {"tag_name": "v1.0.1.0"},
            {"assets": []},
            {"assets": None},
        ):
            with self.subTest(changes=changes):
                self.assertIsNone(self_update_release(release_payload() | changes, "1.0.0"))

    def test_rejects_duplicates_wrong_origins_and_invalid_sizes(self):
        for changes in (
            {"size": True},
            {"size": 0},
            {"size": MAX_WHEEL_BYTES + 1},
            {"browser_download_url": "https://example.com/wheel"},
        ):
            payload = release_payload()
            payload["assets"][0].update(changes)
            self.assertIsNone(self_update_release(payload, "1.0.0"))
        payload = release_payload()
        payload["assets"].append(copy.deepcopy(payload["assets"][0]))
        self.assertIsNone(self_update_release(payload, "1.0.0"))

    def test_bounds_release_notes(self):
        self.assertEqual(
            len(self_update_release(release_payload() | {"body": "x" * 20000}, "1.0.0").notes),
            12000,
        )


class DownloadTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.directory = Path(temporary.name)
        self.release = self_update_release(release_payload(), "1.0.0")

    def test_downloads_then_verifies_and_limits_permissions(self):
        opener = Mock()
        opener.open.side_effect = [io.BytesIO(b"wheel"), io.BytesIO(b"bundle")]
        with (
            patch(
                "archupdater.services.self_update.urllib.request.build_opener", return_value=opener
            ),
            patch("archupdater.services.self_update.verify_artifact") as verify,
        ):
            wheel, bundle = download_release(self.release, self.directory)
        self.assertEqual(wheel.read_bytes(), b"wheel")
        self.assertEqual(bundle.read_bytes(), b"bundle")
        self.assertEqual(wheel.stat().st_mode & 0o777, 0o600)
        verify.assert_called_once_with(wheel, bundle, "1.0.1", home=self.directory)

    def test_oversized_empty_and_slow_downloads_fail_before_verification(self):
        for data, clock, error in (
            (b"12345", [0, 1], ValueError),
            (b"", [0], ValueError),
            (b"123", [0, 181], TimeoutError),
        ):
            with self.subTest(error=error), tempfile.TemporaryDirectory() as directory:
                opener = Mock()
                opener.open.return_value = io.BytesIO(data)
                with (
                    patch(
                        "archupdater.services.self_update.urllib.request.build_opener",
                        return_value=opener,
                    ),
                    patch("archupdater.services.self_update.MAX_WHEEL_BYTES", 4),
                    patch("archupdater.services.self_update.time.monotonic", side_effect=clock),
                    patch("archupdater.services.self_update.verify_artifact") as verify,
                ):
                    with self.assertRaises(error):
                        download_release(self.release, Path(directory))
                    verify.assert_not_called()

    def test_refuses_unsafe_redirects(self):
        handler = ReleaseRedirectHandler()
        request = urllib.request.Request("https://github.com/asset")
        for url in (
            "http://github.com/a",
            "https://example.org/a",
            "https://user@github.com/a",
            "https://github.com:8443/a",
        ):
            with self.subTest(url=url), self.assertRaises(ValueError):
                handler.redirect_request(request, None, 302, "Found", {}, url)
        redirected = handler.redirect_request(
            request, None, 302, "Found", {}, "https://release-assets.githubusercontent.com/a"
        )
        self.assertEqual(redirected.full_url, "https://release-assets.githubusercontent.com/a")

    def test_verifier_pins_repository_workflow_tag_and_clean_environment(self):
        with (
            patch.dict(os.environ, {"GH_TOKEN": "secret", "SSL_CERT_FILE": "/untrusted"}),
            patch(
                "archupdater.services.self_update.subprocess.run", return_value=Mock(returncode=0)
            ) as run,
        ):
            verify_artifact(Path("wheel"), Path("bundle"), "1.0.1", home=self.directory)
        args = run.call_args.args[0]
        self.assertIn(REPOSITORY, args)
        self.assertIn(
            f"https://github.com/{REPOSITORY}/.github/workflows/release.yml@refs/tags/v1.0.1", args
        )
        self.assertIn("refs/tags/v1.0.1", args)
        self.assertIn("--deny-self-hosted-runners", args)
        self.assertNotIn("GH_TOKEN", run.call_args.kwargs["env"])
        self.assertNotIn("SSL_CERT_FILE", run.call_args.kwargs["env"])

    def test_invalid_attestation_is_rejected(self):
        with (
            patch(
                "archupdater.services.self_update.subprocess.run", return_value=Mock(returncode=1)
            ),
            self.assertRaisesRegex(ValueError, "authenticity"),
        ):
            verify_artifact(Path("wheel"), Path("bundle"), "1.0.1", home=self.directory)


class ManagedInstallTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name) / "archupdater"
        self.current = self.root / "releases/old"
        old_site = site_packages(self.current)
        metadata = old_site / "archupdater-1.0.0.dist-info"
        metadata.mkdir(parents=True)
        (metadata / "METADATA").write_text("Name: archupdater\nVersion: 1.0.0\n")
        (old_site / "dependency.py").write_text("VALUE = 42")
        (self.root / "current").symlink_to("releases/old")
        self.wheel = self.root / "archupdater-1.0.1-py3-none-any.whl"
        self.make_wheel()
        self.bundle = self.root / "bundle"
        self.bundle.write_text("attestation")
        self.installation = ManagedInstall(self.root)

    def make_wheel(self, name="archupdater", version="1.0.1"):
        with zipfile.ZipFile(self.wheel, "w") as archive:
            archive.writestr(
                "archupdater-1.0.1.dist-info/METADATA", f"Name: {name}\nVersion: {version}\n"
            )

    def perform_install(self):
        self.installation.install(self.wheel, self.bundle, "1.0.1", uid=os.getuid())

    def fake_venv(self, path):
        site_packages(path.parent).mkdir(parents=True)

    def test_private_copy_rejects_symlink_fifo_owner_and_limit(self):
        source = self.root / "link"
        source.symlink_to(self.bundle)
        with self.assertRaises(OSError):
            private_copy(source, self.root / "copy", uid=os.getuid(), limit=100)
        source.unlink()
        os.mkfifo(source)
        with self.assertRaises(ValueError):
            private_copy(source, self.root / "copy", uid=os.getuid(), limit=100)
        for uid, limit in ((os.getuid() + 1, 100), (os.getuid(), 1)):
            with self.assertRaises(ValueError):
                private_copy(self.bundle, self.root / "copy", uid=uid, limit=limit)

    def test_refuses_downgrade_without_verifying_or_installing(self):
        with (
            patch("archupdater.helper.self_update.verify_artifact") as verify,
            self.assertRaisesRegex(ValueError, "newer"),
        ):
            self.installation.install(self.wheel, self.bundle, "1.0.0", uid=os.getuid())
        verify.assert_not_called()

    def test_bad_attestation_leaves_current_untouched(self):
        with (
            patch(
                "archupdater.helper.self_update.verify_artifact",
                side_effect=ValueError("bad attestation"),
            ),
            self.assertRaises(ValueError),
        ):
            self.perform_install()
        self.assertEqual(self.installation.link_target("current"), self.current)
        self.assertEqual(list(self.installation.releases.iterdir()), [self.current])
        self.assertFalse(list(self.root.glob(".verified-*")))

    def test_wrong_wheel_identity_or_version_leaves_current_untouched(self):
        for name, version in (("other", "1.0.1"), ("archupdater", "1.0.2")):
            self.make_wheel(name, version)
            with (
                patch("archupdater.helper.self_update.verify_artifact"),
                self.assertRaises(ValueError),
            ):
                self.perform_install()
            self.assertEqual(self.installation.link_target("current"), self.current)

    def test_seals_input_before_verification_and_switches_after_smoke_test(self):
        def verify(wheel, bundle, version, *, home):
            self.assertNotEqual(wheel, self.wheel)
            self.assertEqual(wheel.parent, home)
            self.assertEqual(wheel.stat().st_mode & 0o777, 0o600)
            self.wheel.write_bytes(b"changed after sealing")
            self.assertEqual(wheel_version(wheel), version)

        def smoke(stage, version):
            self.assertEqual(self.installation.link_target("current"), self.current)
            self.assertEqual((site_packages(stage) / "dependency.py").read_text(), "VALUE = 42")

        with (
            patch("archupdater.helper.self_update.verify_artifact", side_effect=verify),
            patch(
                "archupdater.helper.self_update.venv.EnvBuilder.create", side_effect=self.fake_venv
            ),
            patch.object(self.installation, "run") as run,
            patch.object(self.installation, "smoke_test", side_effect=smoke),
        ):
            self.perform_install()
        self.assertNotEqual(self.installation.link_target("current"), self.current)
        self.assertEqual(self.installation.link_target("previous"), self.current)
        self.assertIn("--no-index", run.call_args.args[0])
        self.assertIn("--no-deps", run.call_args.args[0])

    def test_preparation_and_smoke_failures_remove_stage_and_preserve_current(self):
        for method in ("run", "smoke_test"):
            with (
                self.subTest(method=method),
                patch("archupdater.helper.self_update.verify_artifact"),
                patch(
                    "archupdater.helper.self_update.venv.EnvBuilder.create",
                    side_effect=self.fake_venv,
                ),
                patch.object(self.installation, "run"),
                patch.object(self.installation, "smoke_test"),
            ):
                with (
                    patch.object(self.installation, method, side_effect=ValueError("failure")),
                    self.assertRaises(ValueError),
                ):
                    self.perform_install()
                self.assertEqual(self.installation.link_target("current"), self.current)
                self.assertEqual(list(self.installation.releases.iterdir()), [self.current])

    def test_rollback_smoke_failure_preserves_current(self):
        (self.root / "previous").symlink_to("releases/old")
        with (
            patch.object(self.installation, "smoke_test", side_effect=ValueError("broken")),
            patch.object(self.installation, "switch") as switch,
            self.assertRaises(ValueError),
        ):
            self.installation.rollback()
        switch.assert_not_called()

    def test_rollback_restores_previous_release(self):
        (self.root / "previous").symlink_to("releases/old")
        newer = self.installation.releases / "new"
        newer.mkdir()
        self.installation.switch("current", newer)
        with patch.object(self.installation, "smoke_test"):
            self.installation.rollback()
        self.assertEqual(self.installation.link_target("current"), self.current)

    def test_rejects_release_links_outside_managed_directory(self):
        (self.root / "previous").symlink_to(self.root.parent)
        with self.assertRaises(ValueError):
            self.installation.rollback()

    def test_rejects_unprotected_installation_ancestors(self):
        with self.assertRaisesRegex(ValueError, "not protected"):
            self.installation.validate()

    def test_subprocess_failure_is_reported(self):
        with (
            patch(
                "archupdater.helper.self_update.subprocess.run",
                return_value=subprocess.CompletedProcess([], 1),
            ),
            self.assertRaisesRegex(ValueError, "dependencies"),
        ):
            self.installation.run(["false"])
