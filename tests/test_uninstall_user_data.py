"""Exercise the production purge function against temporary user directories."""
from __future__ import annotations

import os
from pathlib import Path
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]


class UninstallUserDataTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.user_home = self.root / "user"
        self.user_home.mkdir()
        self.environment = {
            key: value for key, value in os.environ.items()
            if key not in {"XDG_CONFIG_HOME", "XDG_CACHE_HOME", "XDG_STATE_HOME"}
        }
        self.environment.update(SUDO_USER="review", REVIEW_FAKE_HOME=str(self.user_home))
        source = (ROOT / "uninstall.sh").read_text()
        start = source.index("purge_invoking_user_data() {")
        self.function = source[start:source.index('\nwhile [[ "$#"', start)]

    def seed(self, cache, config, state):
        paths = [cache / "archupdater/logs/run.log", config / "ArchUpdater/ArchUpdater.conf",
                 config / "autostart/io.github.archupdater.desktop", state / "archupdater/aur-vcs.json"]
        for path in paths:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("fixture")
        for directory in (cache, config, state):
            (directory / "unrelated.txt").write_text("keep")
        return paths

    def purge(self, argument=""):
        # Emulate only passwd lookup and the UID switch. The production rm
        # commands run unchanged, but only against this test's own files.
        script = (
            'set -euo pipefail\n'
            'getent() { printf "review:x:1000:1000::%s:/bin/bash\\n" "$REVIEW_FAKE_HOME"; }\n'
            'runuser() { [[ $1 == -u && $2 == review && $3 == -- ]] || exit 80; shift 3; "$@"; }\n'
            + self.function + "\npurge_invoking_user_data " + argument + "\n"
        )
        return subprocess.run(["bash", "-c", script], env=self.environment, capture_output=True, text=True)

    def test_custom_xdg_directories_are_purged_without_removing_unrelated_data(self):
        cache, config, state = [self.root / name for name in ("cache", "config", "state")]
        paths = self.seed(cache, config, state)
        self.environment.update(XDG_CACHE_HOME=str(cache), XDG_CONFIG_HOME=str(config), XDG_STATE_HOME=str(state))
        result = self.purge()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(all(not path.exists() for path in paths))
        self.assertTrue(all((directory / "unrelated.txt").exists() for directory in (cache, config, state)))

    def test_relative_xdg_values_fall_back_to_invoking_user_home(self):
        cache = self.user_home / ".cache"
        config = self.user_home / ".config"
        state = self.user_home / ".local/state"
        paths = self.seed(cache, config, state)
        self.environment.update(XDG_CACHE_HOME="relative", XDG_CONFIG_HOME="relative", XDG_STATE_HOME="relative")
        result = self.purge()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(all(not path.exists() for path in paths))

    def test_prevalidation_does_not_remove_data(self):
        paths = self.seed(self.user_home / ".cache", self.user_home / ".config", self.user_home / ".local/state")
        result = self.purge("--validate-only")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(all(path.exists() for path in paths))

    def test_missing_invoking_user_is_rejected_before_any_user_deletion(self):
        paths = self.seed(self.user_home / ".cache", self.user_home / ".config", self.user_home / ".local/state")
        self.environment.pop("SUDO_USER")
        result = self.purge()
        self.assertNotEqual(result.returncode, 0)
        self.assertTrue(all(path.exists() for path in paths))


if __name__ == "__main__":
    unittest.main()
