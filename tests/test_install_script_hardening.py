from __future__ import annotations

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

    def test_installer_never_runs_pacman_or_auto_installs_system_dependencies(self) -> None:
        self.assertIn("pacman-contrib", self.script)
        self.assertIn("fakeroot", self.script)
        self.assertIn("will not upgrade the operating system", self.script)
        self.assertNotIn("pacman -Syu --needed --noconfirm", self.script)

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

    def test_user_data_purge_is_explicit_and_scoped_to_sudo_user(self) -> None:
        self.assertIn("--purge-user-data", self.uninstaller)
        self.assertIn('local target_user="${SUDO_USER:-}"', self.uninstaller)
        self.assertIn('"${user_home}/.cache/archupdater"', self.uninstaller)
        self.assertIn('"${user_home}/.config/ArchUpdater"', self.uninstaller)


if __name__ == "__main__":
    unittest.main()
