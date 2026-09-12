from __future__ import annotations

import os
import sys
import tempfile
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from archupdater.services.checkupdates_workspace import CheckupdatesDbWorkspace


class CheckupdatesDbWorkspaceTests(unittest.TestCase):
    def test_root_path_uses_current_xdg_cache_home_lazily(self) -> None:
        workspace = CheckupdatesDbWorkspace()

        with tempfile.TemporaryDirectory() as tmp:
            old_cache_home = os.environ.get("XDG_CACHE_HOME")
            os.environ["XDG_CACHE_HOME"] = tmp
            try:
                self.assertEqual(
                    workspace.root_path(),
                    Path(tmp) / "archupdater" / "checkupdates-db-runs",
                )
            finally:
                if old_cache_home is None:
                    os.environ.pop("XDG_CACHE_HOME", None)
                else:
                    os.environ["XDG_CACHE_HOME"] = old_cache_home

    def test_create_run_path_prunes_stale_runs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = CheckupdatesDbWorkspace(cache_home=Path(tmp), stale_seconds=10)
            root = workspace.root_path()
            root.mkdir(parents=True)
            stale = root / "run-stale"
            stale.mkdir()
            fresh = root / "run-fresh"
            fresh.mkdir()
            old_timestamp = time.time() - 60
            os.utime(stale, (old_timestamp, old_timestamp))

            created = workspace.create_run_path()

            self.assertFalse(stale.exists())
            self.assertTrue(fresh.exists())
            self.assertTrue(created.exists())

    def test_cleanup_run_path_refuses_to_delete_root_or_outside_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = CheckupdatesDbWorkspace(cache_home=Path(tmp))
            root = workspace.root_path()
            root.mkdir(parents=True)
            outside = Path(tmp) / "outside"
            outside.mkdir()

            workspace.cleanup_run_path(root)
            workspace.cleanup_run_path(outside)

            self.assertTrue(root.exists())
            self.assertTrue(outside.exists())


if __name__ == "__main__":
    unittest.main()
