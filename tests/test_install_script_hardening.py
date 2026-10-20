from __future__ import annotations

import os
import subprocess
import tempfile
import unittest
from pathlib import Path


class InstallScriptHardeningTests(unittest.TestCase):
    def setUp(self) -> None:
        root = Path(__file__).resolve().parents[1]
        self.script = root.joinpath("install.sh").read_text(encoding="utf-8")
        self.uninstaller = root.joinpath("uninstall.sh").read_text(encoding="utf-8")

    def test_installer_refuses_symlink_targets(self) -> None:
        self.assertIn("ensure_not_symlink", self.script)
        self.assertIn("refusing to use symlink path", self.script)
        self.assertIn('"${HELPER_WRAPPER}"', self.script)

    def test_installer_locks_root_owned_trees_before_using_existing_install(self) -> None:
        self.assertIn("tree_is_root_locked", self.script)
        self.assertIn("chmod -R go-w", self.script)
        self.assertIn("chown -R root:root", self.script)

    def test_installer_stages_and_smoke_tests_a_versioned_release(self) -> None:
        self.assertIn("! -type l -perm /022", self.script)
        self.assertIn('FINAL_RELEASE="${RELEASES_DIR}/${PACKAGE_VERSION}-${release_suffix}"', self.script)
        self.assertIn('STAGING_RELEASE="${FINAL_RELEASE}"', self.script)
        self.assertIn('archupdater.__version__ != sys.argv[1]', self.script)
        self.assertIn('mv -fT -- "${next_link}" "${CURRENT_LINK}"', self.script)
        self.assertLess(
            self.script.index('"${STAGING_VENV}/bin/pip" install'),
            self.script.index('mv -fT -- "${next_link}" "${CURRENT_LINK}"'),
        )
        self.assertLess(
            self.script.index('mv -fT -- "${desktop_tmp}" "${DESKTOP_DEST}"'),
            self.script.index('mv -fT -- "${next_link}" "${CURRENT_LINK}"'),
        )

    def test_installer_sanitizes_python_environment_for_launchers(self) -> None:
        self.assertIn("unset PYTHONPATH PYTHONHOME", self.script)
        self.assertIn('export PATH="/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"', self.script)

    def test_installer_rejects_broad_or_user_controlled_install_roots(self) -> None:
        self.assertIn("validate_install_root", self.script)
        self.assertIn("realpath -m", self.script)
        self.assertIn("/|/bin|/boot|/dev|/etc|/home", self.script)
        self.assertIn("/bin/*|/boot/*|/dev/*|/etc/*|/home/*", self.script)
        self.assertIn("/usr/*|/var/tmp/*", self.script)
        self.assertIn('${normalized_path##*/}', self.script)
        self.assertIn("dedicated 'archupdater' directory", self.script)
        self.assertLess(
            self.script.index('validate_install_root "${INSTALL_ROOT}"'),
            self.script.index('install -d -o root -g root -m 0755'),
        )

    def run_systemd_check(self, *, booted: bool, executable: bool, skip: str = ""):  # noqa: ANN202
        start = self.script.index("require_systemd() {")
        function = self.script[start:self.script.index("\n}\n", start) + 3]
        with tempfile.TemporaryDirectory() as directory:
            runtime = Path(directory) / "systemd-system"
            systemd_run = Path(directory) / "systemd-run"
            if booted:
                runtime.mkdir()
            systemd_run.write_text("#!/bin/sh\n")
            systemd_run.chmod(0o755 if executable else 0o644)
            script = (
                f'set -euo pipefail\nSYSTEMD_RUNTIME_DIR="{runtime}"\n'
                f'SYSTEMD_RUN_PATH="{systemd_run}"\n{function}\nrequire_systemd\necho continued\n'
            )
            environment = {"PATH": os.environ.get("PATH", "/usr/bin:/bin")}
            if skip:
                environment["ARCHUPDATER_SKIP_SYSTEMD_CHECK"] = skip
            return subprocess.run(
                ["bash", "-c", script], env=environment, capture_output=True, text=True, timeout=10,
            )

    def test_installer_requires_running_systemd_and_explains_why(self) -> None:
        self.assertEqual(self.run_systemd_check(booted=True, executable=True).stdout, "continued\n")
        for booted, executable in ((False, True), (True, False)):
            with self.subTest(booted=booted, executable=executable):
                result = self.run_systemd_check(booted=booted, executable=executable)
                self.assertEqual(result.returncode, 1)
                self.assertNotIn("continued", result.stdout)
                self.assertIn("requires systemd", result.stdout)
                self.assertIn("isolated, temporary systemd service", result.stdout)
                self.assertIn("Nothing was installed or changed.", result.stdout)
        self.assertEqual(self.script.count('SYSTEMD_RUNTIME_DIR="/run/systemd/system"'), 1)
        self.assertNotIn("pacman -S systemd", self.script)

    def test_systemd_check_can_only_be_skipped_explicitly(self) -> None:
        skipped = self.run_systemd_check(booted=False, executable=False, skip="1")
        self.assertEqual(skipped.returncode, 0)
        self.assertIn("AUR updates will not work", skipped.stdout)
        self.assertEqual(self.run_systemd_check(booted=False, executable=False, skip="yes").returncode, 1)

    def test_systemd_check_runs_before_any_system_change(self) -> None:
        main = self.script[self.script.index('if [[ "${EUID}" -ne 0 ]]; then'):]
        check = main.index("\nrequire_systemd\n")
        for later in ("ensure_system_dependencies\n", "install -d -o root -g root -m 0755"):
            self.assertLess(check, main.index(later), later)

    def test_uninstaller_removes_only_owned_system_paths(self) -> None:
        for path in (
            "/usr/local/bin/archupdater",
            "/usr/local/bin/archupdater-uninstall",
            "/usr/share/polkit-1/actions/io.github.archupdater.policy",
        ):
            self.assertIn(path, self.uninstaller)
        self.assertIn('HELPER_DIR="/usr/lib/archupdater"', self.uninstaller)
        self.assertIn('HELPER_WRAPPER="${HELPER_DIR}/archupdater-helper"', self.uninstaller)
        self.assertIn('DESKTOP_DIR="/usr/share/applications"', self.uninstaller)
        self.assertIn('DESKTOP_DEST="${DESKTOP_DIR}/io.github.archupdater.desktop"', self.uninstaller)
        self.assertIn("refusing to remove a symlinked install root", self.uninstaller)
        self.assertIn("tree_is_root_locked", self.uninstaller)
        self.assertNotIn("pacman -R", self.uninstaller)
        self.assertIn('AUR_STATE_DIR="/var/lib/private/archupdater-aur"', self.uninstaller)
        self.assertIn('AUR_STATE_LINK_DIR="/var/lib/archupdater-aur"', self.uninstaller)

    def test_user_data_purge_is_explicit_and_scoped_to_sudo_user(self) -> None:
        self.assertIn("--purge-user-data", self.uninstaller)
        self.assertIn('local target_user="${SUDO_USER:-}"', self.uninstaller)
        self.assertIn('"${user_cache_home}/archupdater"', self.uninstaller)
        self.assertIn('"${user_config_home}/ArchUpdater"', self.uninstaller)
        self.assertIn('"${user_state_home}/archupdater"', self.uninstaller)


if __name__ == "__main__":
    unittest.main()
