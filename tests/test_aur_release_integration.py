"""Regression probes for the release review of September 26.

Run as the normal user. No network, sudo, host package installation, or host
uninstallation: makepkg builds a harmless local package, and fakeroot/pacman use
an explicit temporary root, database, cache, configuration and log.
"""
from __future__ import annotations

import os
from pathlib import Path
import pwd
import shutil
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from archupdater.application.helper_protocol import HelperEventType
from archupdater.application.update_session.backend import BackendRunContext, CommandRunResult
from archupdater.application.update_session.plan import BatchPlanInspector
from archupdater.application.update_session.step_backends import AurBackend
from archupdater.domain.aur import AurVcsSource
from archupdater.domain.enums import UpdateSource
from archupdater.domain.update_plan import UpdatePlan, UpdatePlanItem
from archupdater.helper.actions import aur_updates, aur_workspace, update_commands
from archupdater.services.aur_review import AurReviewManager
from archupdater.services.aur_rpc import AurRpcClient
from archupdater.services.aur_vcs import AurVcsTracker
from archupdater.services.aur_vcs_state import AurVcsStateStore
from archupdater.services.command_runner import CommandRunner

REPOSITORY = Path(__file__).resolve().parents[1]
NAME = "archupdater-review-fixture"
PKGBUILD = '''pkgname=archupdater-review-fixture
pkgver=1
pkgrel=1
pkgdesc="Harmless local release review fixture"
arch=('any')
license=('MIT')
prepare() {
    "$startdir/helper.sh"
}
package() {
    install -Dm644 "$startdir/helper.sh" "$pkgdir/usr/share/$pkgname/helper.txt"
}
'''


class LocalReviewManager(AurReviewManager):
    def __init__(self, original: Path, state: Path) -> None:
        runner = CommandRunner()
        super().__init__(runner, AurRpcClient(), AurVcsTracker(runner, AurVcsStateStore(state)))
        self.original = original

    def _clone_checkout(self, package_base: str, checkout_path: Path) -> None:
        shutil.copytree(self.original, checkout_path)


class AurReleaseIntegrationTests(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory(prefix="archupdater-review-probe-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.home = self.root / "home"
        self.home.mkdir()
        self.user = aur_workspace.AurBuildUser(
            pwd.getpwuid(os.getuid()).pw_name, os.getuid(), os.getgid(), self.home
        )

    def fixture(self):
        if os.geteuid() == 0:
            self.skipTest("Run these build probes as the normal desktop user.")
        for command in ("git", "makepkg", "fakeroot", "pacman"):
            if shutil.which(command) is None:
                self.skipTest(f"Requires {command} on an Arch-based test host.")
        original = self.root / "original"
        original.mkdir()
        (original / "PKGBUILD").write_text(PKGBUILD)
        (original / ".SRCINFO").write_text(
            f"pkgbase = {NAME}\n\tpkgver = 1\n\tpkgrel = 1\n\tarch = any\npkgname = {NAME}\n"
        )
        helper = original / "helper.sh"
        helper.write_text('#!/bin/sh\nprintf "HARMLESS_LOCAL_HELPER_OK\\n"\n')
        helper.chmod(0o755)
        git = ["git", "-C", str(original), "-c", "core.hooksPath=/dev/null"]
        for args in (
            ["init", "-q"], ["add", "."],
            ["-c", "user.name=Review Fixture", "-c", "user.email=review@example.invalid",
             "-c", "commit.gpgsign=false", "commit", "-qm", "fixture"],
        ):
            subprocess.run([*git, *args], check=True, capture_output=True, timeout=10)
        manager = LocalReviewManager(original, self.root / "state.json")
        review = manager.prepare(NAME, NAME)
        self.addCleanup(manager.discard, review)
        return original, manager, review

    def build(self, checkout: Path, name: str):
        work = self.root / name
        work.mkdir()
        directories = {
            key: work / key
            for key in ("build", "logs", "packages", "sources", "source-packages", "tmp")
        }
        for directory in directories.values():
            directory.mkdir()
        result = subprocess.run(
            ["/usr/bin/makepkg", "--dir", str(checkout), "--force", "--noconfirm", "--noprogressbar"],
            env=aur_workspace._aur_build_environment(self.user, directories),
            capture_output=True, text=True, timeout=60,
        )
        return result, directories["packages"]

    def test_f1_executable_file_still_builds_after_review_copy(self):
        original, _manager, review = self.fixture()
        baseline, _ = self.build(original, "baseline")
        self.assertEqual(baseline.returncode, 0, baseline.stdout + baseline.stderr)
        sealed_root = self.root / "sealed"
        sealed_root.mkdir()
        sealed = aur_workspace._seal_aur_build_checkout(review, build_root=sealed_root)
        workspace = self.root / "workspace"
        workspace.mkdir()
        copied = aur_workspace._create_user_aur_build_checkout(
            sealed, review, build_root=workspace, build_user=self.user
        )
        result, _ = self.build(copied, "reviewed")
        self.assertEqual((copied / "helper.sh").stat().st_mode & 0o777, 0o700)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_f2_aur_noop_does_not_claim_changes(self):
        original, manager, review = self.fixture()
        built, package_dir = self.build(original, "build-package")
        self.assertEqual(built.returncode, 0, built.stdout + built.stderr)
        artifact = next(package_dir.glob("*.pkg.tar.zst"))
        for name in ("rootfs", "db", "cache", "hooks", "helper-work"):
            (self.root / name).mkdir()
        config = self.root / "pacman.conf"
        config.write_text("[options]\nArchitecture = auto\nSigLevel = Never\nLocalFileSigLevel = Never\n")
        pacman = [
            "/usr/bin/fakeroot", "/usr/bin/pacman", "--root", str(self.root / "rootfs"),
            "--dbpath", str(self.root / "db"), "--cachedir", str(self.root / "cache"),
            "--logfile", str(self.root / "pacman.log"), "--config", str(config),
            "--hookdir", str(self.root / "hooks"),
        ]
        subprocess.run(
            [*pacman, "-U", "--dbonly", "--noscriptlet", "--noconfirm", str(artifact)],
            capture_output=True, text=True, check=True, timeout=30,
        )

        def installed():
            return subprocess.run(
                [*pacman, "-Q"], capture_output=True, text=True, check=True, timeout=10
            ).stdout

        before = installed()
        events, logs = [], []

        def supplied_build(_command, **kwargs):
            # Reuse the package just built above; the installation and package
            # identity inspection below still execute real pacman.
            shutil.copy2(artifact, Path(kwargs["env"]["PKGDEST"]) / artifact.name)
            return 0, []

        def isolated_command(command):
            assert command[0] == "/usr/bin/pacman" and "-U" in command
            return [*pacman, "--dbonly", "--noscriptlet", *command[1:]]

        class IsolatedStateRunner(CommandRunner):
            def run(self, command, **kwargs):
                assert command[:2] == ["/usr/bin/pacman", "-Q"]
                return super().run([*pacman, *command[1:]], **kwargs)

        def invoke(request, **_kwargs):
            with (
                patch.object(update_commands, "stream_subprocess", supplied_build),
                patch.object(update_commands, "_critical_command", isolated_command),
                patch.object(update_commands, "CommandRunner", IsolatedStateRunner),
            ):
                code = aur_updates.install_reviewed_aur(
                    review, request.expected_version, expected_package_base=NAME,
                    build_user=self.user, build_root=self.root / "helper-work",
                    emit_event=lambda event, **payload: events.append((event, payload)),
                    emit_log=logs.append,
                )
            self.assertEqual(code, 0)
            payload = [p for event, p in events if event is HelperEventType.COMPLETED][-1]
            return CommandRunResult(payload["success"], payload.get("message", ""), payload)

        plan = UpdatePlan([UpdatePlanItem(
            UpdateSource.AUR, NAME, package_name=NAME, package_base=NAME,
            expected_version="1-1", current_version="0-1",
        )])
        context = BackendRunContext(
            plan=plan,
            service=SimpleNamespace(
                aur_pkgbuild_review=lambda *args, **kwargs: review,
                aur_missing_build_dependencies=lambda candidate: [],
                discard_aur_pkgbuild_review=manager.discard,
            ),
            plan_inspector=BatchPlanInspector(plan, translate=lambda text: text),
            translate=lambda text: text, print_line=logs.append, emit_log=logs.append,
            emit_progress=lambda payload: None, request_question=lambda payload: True,
            run_command=lambda *args, **kwargs: self.fail("Unexpected nonprivileged command"),
            run_privileged=invoke, summarize_items=lambda items: ", ".join(items),
            command_available=lambda command: True,
        )
        result = AurBackend().run(context)
        after = installed()
        self.assertEqual(before, after)
        self.assertTrue(result.success)
        self.assertFalse(result.changed, "AUR no-op must not be reported as an installation.")

    def test_f3_purge_removes_aur_receipts(self):
        old_paths = (
            ".config/ArchUpdater/ArchUpdater.conf", ".cache/archupdater/logs/example.log",
            ".config/autostart/io.github.archupdater.desktop",
        )
        for name in old_paths:
            path = self.home / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("review fixture")
        state = self.home / ".local/state/archupdater/aur-vcs.json"
        AurVcsStateStore(state).record_install(
            "review-git", "r1-1", (AurVcsSource("review", "https://example.invalid/review.git", None, "a" * 40),)
        )
        source = (REPOSITORY / "uninstall.sh").read_text()
        start = source.index("purge_invoking_user_data() {")
        function = source[start:source.index('\nwhile [[ "$#"', start)]
        script = (
            'set -euo pipefail\n'
            'getent() { printf "review:x:1000:1000::%s:/bin/bash\\n" "$REVIEW_FAKE_HOME"; }\n'
            'runuser() { [[ $1 == -u && $2 == review && $3 == -- ]] || exit 80; shift 3; "$@"; }\n'
            + function + "\npurge_invoking_user_data\n"
        )
        result = subprocess.run(
            ["/bin/bash", "-c", script],
            env={**{k: v for k, v in os.environ.items() if k not in {"XDG_CONFIG_HOME", "XDG_CACHE_HOME", "XDG_STATE_HOME"}},
                 "SUDO_USER": "review", "REVIEW_FAKE_HOME": str(self.home)},
            capture_output=True, text=True, check=True, timeout=10,
        )
        self.assertTrue(all(not (self.home / path).exists() for path in old_paths))
        self.assertIn("Removed ArchUpdater data for review.", result.stdout)
        self.assertFalse(state.exists(), "--purge-user-data left the AUR installation receipt.")


if __name__ == "__main__":
    unittest.main(verbosity=2)
