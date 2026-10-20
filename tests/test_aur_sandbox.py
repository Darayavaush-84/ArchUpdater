from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from archupdater.domain.aur import AurPkgbuildReview, AurReviewFile, AurVcsSource
from archupdater.helper.actions import aur_artifacts, aur_workspace
from archupdater.helper.actions.validation import PrivilegedUpdateValidationError


FINGERPRINT = "A" * 40


def _review(srcinfo_extra: str = "") -> AurPkgbuildReview:
    return _review_from_files({
        ".SRCINFO": f"pkgbase = foo\n{srcinfo_extra}pkgname = foo\n",
        "PKGBUILD": "pkgname=foo\npkgver=1\npkgrel=1\n",
        "helper.sh": "#!/bin/sh\nprintf 'helper OK\\n'\n",
    }, executable={"helper.sh"})


def _review_from_files(
    contents: dict[str, str],
    *,
    name: str = "foo",
    executable: frozenset[str] | set[str] = frozenset(),
    vcs_sources: tuple[AurVcsSource, ...] = (),
) -> AurPkgbuildReview:
    files = []
    tree = hashlib.sha256()
    for path, content in sorted(contents.items()):
        raw = content.encode()
        sha256 = hashlib.sha256(raw).hexdigest()
        is_executable = path in executable
        files.append(AurReviewFile(path, sha256, len(raw), content, is_executable))
        for part in (path.encode(), str(len(raw)).encode(), sha256.encode()):
            tree.update(part + b"\0")
        tree.update(b"1\0" if is_executable else b"0\0")
    return AurPkgbuildReview(name, name, contents["PKGBUILD"], digest=tree.hexdigest(),
                             files=tuple(files), vcs_sources=vcs_sources)


def _user() -> aur_workspace.AurBuildUser:
    return aur_workspace.AurBuildUser("tester", os.getuid(), os.getgid(), Path("/tmp"))


class BuildInputTests(unittest.TestCase):
    def setUp(self) -> None:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.addCleanup(self._make_writable)

    def _make_writable(self) -> None:
        for path, _directories, _files in os.walk(self.root):
            os.chmod(path, 0o700)

    def prepare(self, overrides=("", ""), keys=b"", review=None):  # noqa: ANN001, ANN202
        logs: list[str] = []
        with (
            patch.object(aur_workspace, "_user_makepkg_overrides", return_value=overrides),
            patch.object(aur_workspace, "_export_user_pgp_keys", return_value=keys) as export,
        ):
            aur_workspace.prepare_build_input(
                review or _review(), self.root / "input", build_user=_user(), emit_log=logs.append,
            )
        return self.root / "input", export

    def test_input_is_read_only_and_keeps_reviewed_executable_bits(self) -> None:
        input_directory, _export = self.prepare()
        checkout = input_directory / "checkout"
        self.assertEqual((checkout / "helper.sh").stat().st_mode & 0o777, 0o555)
        self.assertEqual((checkout / "PKGBUILD").stat().st_mode & 0o777, 0o444)
        self.assertEqual(checkout.stat().st_mode & 0o777, 0o555)
        for name in ("makepkg.conf", "pgp-keys"):
            self.assertEqual((input_directory / name).stat().st_mode & 0o777, 0o444)

    def test_generated_config_sources_system_files_and_quotes_overrides(self) -> None:
        input_directory, _export = self.prepare(("-j8 -l4.5", "Jane 'J' Doe <jane@example.org>"))
        config = (input_directory / "makepkg.conf").read_text()
        self.assertTrue(config.splitlines()[1] == "source /etc/makepkg.conf")
        self.assertIn("/etc/makepkg.conf.d/*.conf", config)
        self.assertIn("MAKEFLAGS='-j8 -l4.5'\n", config)
        result = subprocess.run(
            ["bash", "-c", 'source /dev/stdin; printf "%s" "$PACKAGER"'],
            input="\n".join(line for line in config.splitlines() if line.startswith("PACKAGER=")),
            capture_output=True, text=True, check=True,
        )
        self.assertEqual(result.stdout, "Jane 'J' Doe <jane@example.org>")

    def test_without_overrides_the_system_configuration_is_untouched(self) -> None:
        input_directory, _export = self.prepare()
        config = (input_directory / "makepkg.conf").read_text()
        self.assertNotIn("MAKEFLAGS", config)
        self.assertNotIn("PACKAGER", config)

    def test_only_reviewed_fingerprints_are_exported(self) -> None:
        review = _review(
            f"\tvalidpgpkeys = {FINGERPRINT.lower()}\n\tvalidpgpkeys = {FINGERPRINT}\n"
            "\tvalidpgpkeys = --armor\n\tvalidpgpkeys = 1234\n"
        )
        input_directory, export = self.prepare(keys=b"public key", review=review)
        export.assert_called_once_with(_user(), [FINGERPRINT])
        self.assertEqual((input_directory / "pgp-keys").read_bytes(), b"public key")

    def test_build_script_builds_reviewed_copy_with_generated_config(self) -> None:
        # Runs the real unit script as the current user, without systemd.
        input_directory, _export = self.prepare(("-j2", ""))
        state = self.root / "state"
        state.mkdir()
        bin_directory = self.root / "bin"
        bin_directory.mkdir()
        fake_makepkg = bin_directory / "makepkg"
        fake_makepkg.write_text(
            "#!/bin/bash\nsource \"$MAKEPKG_CONF\" 2>/dev/null\n"
            "printf '%s|%s|%s\\n' \"$PWD\" \"$MAKEFLAGS\" \"$PKGDEST\"\n./helper.sh\n"
            "touch PKGBUILD && echo writable\n"
        )
        fake_makepkg.chmod(0o755)
        script = aur_workspace.BUILD_UNIT_SCRIPT.replace(
            "exec /usr/bin/makepkg", f"exec {fake_makepkg}",
        )
        result = subprocess.run(
            ["bash", "-c", script],
            env={"PATH": "/usr/bin:/bin", "STATE_DIRECTORY": str(state),
                 "ARCHUPDATER_INPUT": str(input_directory), "ARCHUPDATER_PHASE": "full"},
            capture_output=True, text=True, timeout=30,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        lines = result.stdout.splitlines()
        self.assertEqual(lines[0], f"{state}/checkout|-j2|{state}/packages")
        self.assertEqual(lines[1:], ["helper OK", "writable"])
        for name in ("build", "logs", "packages", "sources", "source-packages", "tmp", "home"):
            self.assertTrue((state / name).is_dir(), name)
        self.assertEqual((state / "gnupg").stat().st_mode & 0o777, 0o700)


class BuildPhaseScriptTests(unittest.TestCase):
    """Run the real unit script with a stand-in makepkg that reports its arguments."""

    def setUp(self) -> None:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.addCleanup(self._make_writable)
        with (
            patch.object(aur_workspace, "_user_makepkg_overrides", return_value=("", "")),
            patch.object(aur_workspace, "_export_user_pgp_keys", return_value=b""),
        ):
            aur_workspace.prepare_build_input(
                _review(), self.root / "input", build_user=_user(), emit_log=lambda _line: None,
            )
        self.state = self.root / "state"
        self.state.mkdir()
        self.fake_makepkg = self.root / "makepkg"
        self.fake_makepkg.write_text('#!/bin/sh\necho "makepkg $*"\n')
        self.fake_makepkg.chmod(0o755)

    def _make_writable(self) -> None:
        for path, _directories, _files in os.walk(self.root):
            os.chmod(path, 0o700)

    def run_phase(self, phase: str) -> subprocess.CompletedProcess[str]:
        script = aur_workspace.BUILD_UNIT_SCRIPT.replace(
            "exec /usr/bin/makepkg", f"exec {self.fake_makepkg}",
        )
        return subprocess.run(
            ["bash", "-c", script],
            env={"PATH": "/usr/bin:/bin", "STATE_DIRECTORY": str(self.state),
                 "ARCHUPDATER_INPUT": str(self.root / "input"), "ARCHUPDATER_PHASE": phase},
            capture_output=True, text=True, timeout=30,
        )

    def test_fetch_only_verifies_sources_and_build_keeps_them(self) -> None:
        fetch = self.run_phase("fetch")
        self.assertEqual(fetch.returncode, 0, fetch.stderr)
        self.assertEqual(fetch.stdout.strip(), "makepkg --verifysource --noconfirm --noprogressbar")
        build = self.run_phase("build")
        self.assertEqual(build.returncode, 0, build.stderr)
        self.assertEqual(
            build.stdout.strip(), "makepkg --holdver --force --noconfirm --noprogressbar",
        )

    def test_build_phase_requires_the_fetched_workspace(self) -> None:
        self.assertNotEqual(self.run_phase("build").returncode, 0)

    def test_unknown_phase_is_rejected(self) -> None:
        result = self.run_phase("install")
        self.assertEqual(result.returncode, 2)
        self.assertEqual(result.stdout, "")

    def test_each_phase_has_its_own_unit(self) -> None:
        sandbox = aur_workspace.AurBuildSandbox("0123456789ab")
        for phase, unit in (
            ("full", "archupdater-aur-0123456789ab"),
            ("fetch", "archupdater-aur-0123456789ab-fetch"),
            ("build", "archupdater-aur-0123456789ab-build"),
        ):
            command = aur_workspace.build_unit_command(sandbox, Path("/tmp/input"), phase)
            self.assertIn(f"--unit={unit}", command)
            self.assertIn(f"--setenv=ARCHUPDATER_PHASE={phase}", command)
            # Every phase shares the same private state directory.
            self.assertIn("--property=StateDirectory=archupdater-aur/0123456789ab", command)
        with self.assertRaises(ValueError):
            sandbox.unit("install")


def _git(*args: str, cwd: Path) -> str:
    return subprocess.run(
        ["git", "-c", "core.hooksPath=/dev/null", "-c", "commit.gpgsign=false",
         "-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid",
         "-c", "init.defaultBranch=main", *args],
        cwd=cwd, check=True, capture_output=True, text=True, timeout=30,
    ).stdout.strip()


@unittest.skipUnless(shutil.which("git"), "requires local Git")
class VcsMirrorVerificationTests(unittest.TestCase):
    def setUp(self) -> None:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.upstream = self.root / "upstream"
        self.upstream.mkdir()
        _git("init", "-q", cwd=self.upstream)
        (self.upstream / "file").write_text("one")
        _git("add", ".", cwd=self.upstream)
        _git("commit", "-qm", "one", cwd=self.upstream)
        _git("branch", "stable", cwd=self.upstream)
        self.stable = _git("rev-parse", "HEAD", cwd=self.upstream)
        (self.upstream / "file").write_text("two")
        _git("commit", "-qam", "two", cwd=self.upstream)
        self.head = _git("rev-parse", "HEAD", cwd=self.upstream)
        self.sources = self.root / "sources"
        self.sources.mkdir()
        _git("clone", "-q", "--mirror", str(self.upstream), str(self.sources / "fixture"),
             cwd=self.root)

    def verify(self, branch: str | None, commit: str) -> None:
        review = _review_from_files(
            {".SRCINFO": "pkgbase = foo\npkgname = foo\n", "PKGBUILD": "pkgname=foo\n"},
            vcs_sources=(AurVcsSource("fixture", "https://example.invalid/f.git", branch, commit),),
        )
        aur_artifacts._verify_vcs_mirror_commits(review, sources_directory=self.sources)

    def test_default_branch_and_named_branch_match_their_approved_commits(self) -> None:
        self.verify(None, self.head)
        self.verify("stable", self.stable)

    def test_moved_branch_or_missing_mirror_is_rejected(self) -> None:
        for branch, commit in ((None, self.stable), ("stable", self.head), ("missing", self.head)):
            with self.subTest(branch=branch), self.assertRaises(PrivilegedUpdateValidationError):
                self.verify(branch, commit)
        shutil.rmtree(self.sources / "fixture")
        with self.assertRaises(PrivilegedUpdateValidationError):
            self.verify(None, self.head)

    def test_symlinked_mirror_is_rejected(self) -> None:
        elsewhere = self.root / "elsewhere"
        (self.sources / "fixture").rename(elsewhere)
        (self.sources / "fixture").symlink_to(elsewhere)
        with self.assertRaises(PrivilegedUpdateValidationError):
            self.verify(None, self.head)


@unittest.skipUnless(
    all(shutil.which(tool) for tool in ("git", "makepkg", "fakeroot", "bsdtar")),
    "requires an Arch-based host with makepkg",
)
class TwoPhaseBuildIntegrationTests(unittest.TestCase):
    def test_build_uses_the_commit_verified_before_upstream_moved_on(self) -> None:
        if os.geteuid() == 0:
            self.skipTest("makepkg refuses to run as root.")
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        root = Path(directory.name)
        upstream = root / "upstream"
        upstream.mkdir()
        _git("init", "-q", cwd=upstream)
        (upstream / "version.txt").write_text("approved\n")
        _git("add", ".", cwd=upstream)
        _git("commit", "-qm", "approved", cwd=upstream)
        approved = _git("rev-parse", "HEAD", cwd=upstream)
        name = "archupdater-vcs-fixture"
        source = f"fixture::git+file://{upstream}"
        pkgbuild = (
            f"pkgname={name}\npkgver=1\npkgrel=1\narch=(any)\nlicense=(MIT)\n"
            f"source=('{source}')\nsha256sums=('SKIP')\n"
            "package() {\n"
            '    install -Dm644 "$srcdir/fixture/version.txt" '
            '"$pkgdir/usr/share/$pkgname/version.txt"\n}\n'
        )
        review = _review_from_files(
            {
                ".SRCINFO": f"pkgbase = {name}\n\tsource = {source}\npkgname = {name}\n",
                "PKGBUILD": pkgbuild,
            },
            name=name,
            vcs_sources=(AurVcsSource("fixture", "https://example.invalid/fixture.git",
                                      None, approved),),
        )
        input_directory = root / "input"
        with (
            patch.object(aur_workspace, "_user_makepkg_overrides", return_value=("", "")),
            patch.object(aur_workspace, "_export_user_pgp_keys", return_value=b""),
        ):
            aur_workspace.prepare_build_input(
                review, input_directory, build_user=_user(), emit_log=lambda _line: None,
            )
        self.addCleanup(lambda: [os.chmod(path, 0o700) for path, _d, _f in os.walk(root)])
        state = root / "state"
        state.mkdir()

        def run_phase(phase: str) -> subprocess.CompletedProcess[str]:
            return subprocess.run(
                ["bash", "-c", aur_workspace.BUILD_UNIT_SCRIPT],
                env={"PATH": "/usr/local/bin:/usr/bin:/bin", "LANG": "C.UTF-8",
                     "STATE_DIRECTORY": str(state), "ARCHUPDATER_INPUT": str(input_directory),
                     "ARCHUPDATER_PHASE": phase},
                capture_output=True, text=True, timeout=120,
            )

        fetch = run_phase("fetch")
        self.assertEqual(fetch.returncode, 0, fetch.stdout + fetch.stderr)
        # makepkg creates an empty src/ but no working copy before verification.
        self.assertFalse((state / "build" / name / "src" / "fixture").exists())
        self.assertTrue((state / "sources" / "fixture" / "HEAD").is_file())
        aur_artifacts._verify_vcs_mirror_commits(review, sources_directory=state / "sources")

        # Upstream moves on after verification; the build must not pick it up.
        (upstream / "version.txt").write_text("changed after approval\n")
        _git("commit", "-qam", "changed", cwd=upstream)

        build = run_phase("build")
        self.assertEqual(build.returncode, 0, build.stdout + build.stderr)
        package = next((state / "packages").glob(f"{name}-*.pkg.tar*"))
        built = subprocess.run(
            ["bsdtar", "-xOf", str(package), f"usr/share/{name}/version.txt"],
            capture_output=True, text=True, check=True,
        ).stdout
        self.assertEqual(built, "approved\n")


class UserOverrideTests(unittest.TestCase):
    def overrides(self, output):  # noqa: ANN001, ANN202
        logs: list[str] = []
        with patch.object(aur_workspace, "_run_as_user", return_value=output):
            return aur_workspace._user_makepkg_overrides(_user(), emit_log=logs.append), logs

    def test_accepts_job_and_load_limits(self) -> None:
        for makeflags in ("-j8", "-j16 -l8", "--jobs=4 --load-average=2.5"):
            with self.subTest(makeflags=makeflags):
                values, logs = self.overrides(f"{makeflags}\0Jane <j@example.org>\0".encode())
                self.assertEqual(values, (makeflags, "Jane <j@example.org>"))
                self.assertEqual(logs, [])

    def test_rejects_make_options_that_can_run_code(self) -> None:
        for makeflags in ("--eval=$(shell id)", "-j8 -f /tmp/evil.mk", "-j 8", "-j0", "-C /"):
            with self.subTest(makeflags=makeflags):
                values, logs = self.overrides(f"{makeflags}\0\0".encode())
                self.assertEqual(values, ("", ""))
                self.assertEqual(len(logs), 1)

    def test_rejects_packager_with_control_characters_or_excessive_length(self) -> None:
        for packager in ("Jane\nFake <x>", "x" * 257, "Jane\x1b[31m"):
            with self.subTest(packager=packager):
                values, _logs = self.overrides(f"-j2\0{packager}\0".encode())
                self.assertEqual(values, ("-j2", ""))

    def test_missing_or_failed_configuration_uses_system_defaults(self) -> None:
        for output in (None, b"", b"only-one-field"):
            with self.subTest(output=output):
                self.assertEqual(self.overrides(output)[0], ("", ""))


class BoundedOutputTests(unittest.TestCase):
    def run_shell(self, script: str, timeout: float = 5):  # noqa: ANN202
        process = subprocess.Popen(
            ["bash", "-c", script], stdout=subprocess.PIPE, stdin=subprocess.DEVNULL,
            start_new_session=True,
        )
        return aur_workspace._bounded_output(process, timeout_seconds=timeout)

    def test_returns_output_of_successful_command(self) -> None:
        self.assertEqual(self.run_shell("printf 'a\\0b\\0'"), b"a\0b\0")

    def test_failure_timeout_and_oversized_output_return_none(self) -> None:
        self.assertIsNone(self.run_shell("echo partial; exit 3"))
        started = time.monotonic()
        self.assertIsNone(self.run_shell("sleep 30", timeout=0.3))
        # A background child keeping stdout open must not block past the deadline.
        self.assertIsNone(self.run_shell("(sleep 30 &) ; echo done", timeout=0.3))
        self.assertLess(time.monotonic() - started, 5)
        limit = aur_workspace.MAX_USER_HELPER_OUTPUT_BYTES
        self.assertIsNone(self.run_shell(f"head -c {limit + 1} /dev/zero"))


class UnitCommandAndCleanupTests(unittest.TestCase):
    def test_unit_command_isolates_build_and_passes_only_safe_proxy_values(self) -> None:
        sandbox = aur_workspace.AurBuildSandbox("0123456789ab")
        environment = {"https_proxy": "http://proxy:3128", "http_proxy": "bad\nvalue"}
        with patch.dict(os.environ, environment, clear=True):
            command = aur_workspace.build_unit_command(sandbox, Path("/tmp/input"))
        self.assertEqual(command[0], "/usr/bin/systemd-run")
        self.assertIn("--unit=archupdater-aur-0123456789ab", command)
        self.assertIn("--property=StateDirectory=archupdater-aur/0123456789ab", command)
        self.assertIn(
            "--property=ExecPaths=/var/lib/private/archupdater-aur/0123456789ab", command,
        )
        self.assertIn(
            "--property=BindReadOnlyPaths=/tmp/input:/run/archupdater-aur-input", command,
        )
        for required in ("DynamicUser=yes", "ProtectHome=yes", "PrivateTmp=yes",
                         "ProtectSystem=strict", "NoNewPrivileges=yes",
                         "KillMode=control-group"):
            self.assertIn(f"--property={required}", command)
        self.assertIn("--setenv=https_proxy=http://proxy:3128", command)
        self.assertFalse(any(argument.startswith("--setenv=http_proxy") for argument in command))
        self.assertEqual(command[command.index("--") + 1:][:2], ["/usr/bin/bash", "-c"])
        self.assertEqual(sandbox.state_directory, aur_workspace.AUR_STATE_ROOT / "0123456789ab")

    def test_stale_states_are_removed_only_when_their_unit_is_not_running(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            state_root = Path(directory) / "private"
            link_root = Path(directory) / "links"
            link_root.mkdir()
            for token in ("aaaaaaaaaaaa", "bbbbbbbbbbbb", "not-a-token"):
                (state_root / token / "packages").mkdir(parents=True)
                (link_root / token).symlink_to(state_root / token)
            with (
                patch.object(aur_workspace, "AUR_STATE_ROOT", state_root),
                patch.object(aur_workspace, "AUR_STATE_LINK_ROOT", link_root),
                patch.object(aur_workspace, "_build_unit_is_running",
                             side_effect=lambda token: token == "bbbbbbbbbbbb"),
            ):
                aur_workspace.remove_stale_build_states()
                aur_workspace.remove_build_state("../escape")
            self.assertEqual(
                sorted(path.name for path in state_root.iterdir()),
                ["bbbbbbbbbbbb", "not-a-token"],
            )
            self.assertEqual(
                sorted(path.name for path in link_root.iterdir()),
                ["bbbbbbbbbbbb", "not-a-token"],
            )

    def test_stop_uses_systemctl_for_the_exact_unit(self) -> None:
        with patch.object(aur_workspace.subprocess, "run") as run:
            aur_workspace.stop_build_unit(aur_workspace.AurBuildSandbox("0123456789ab"))
        self.assertEqual(
            run.call_args.args[0],
            ["/usr/bin/systemctl", "stop", "--", "archupdater-aur-0123456789ab.service",
             "archupdater-aur-0123456789ab-fetch.service",
             "archupdater-aur-0123456789ab-build.service"],
        )


if __name__ == "__main__":
    unittest.main()
