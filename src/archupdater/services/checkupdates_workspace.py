from __future__ import annotations

import os
import shutil
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path


@dataclass(slots=True)
class CheckupdatesDbWorkspace:
    cache_home: Path | None = None
    stale_seconds: int = 24 * 60 * 60

    def root_path(self) -> Path:
        cache_home = self.cache_home or Path(os.environ.get("XDG_CACHE_HOME") or Path.home() / ".cache")
        return cache_home / "archupdater" / "checkupdates-db-runs"

    def create_run_path(self) -> Path:
        root = self.root_path()
        root.mkdir(parents=True, exist_ok=True)
        self._chmod_private(root)
        self.cleanup_stale_runs(root)
        return Path(tempfile.mkdtemp(prefix="run-", dir=root))

    def cleanup_run_path(self, path: Path) -> None:
        root = self.root_path().resolve()
        try:
            resolved = path.resolve()
        except OSError:
            return
        if not self._is_relative_to(resolved, root) or resolved == root:
            return
        shutil.rmtree(resolved, ignore_errors=True)

    def cleanup_stale_runs(self, root: Path | None = None) -> None:
        root = root or self.root_path()
        now = time.time()
        try:
            candidates = list(root.iterdir())
        except OSError:
            return
        for candidate in candidates:
            if not candidate.name.startswith("run-"):
                continue
            try:
                age = now - candidate.stat().st_mtime
            except OSError:
                continue
            if age < self.stale_seconds:
                continue
            shutil.rmtree(candidate, ignore_errors=True)

    def _chmod_private(self, path: Path) -> None:
        try:
            path.chmod(0o700)
        except OSError:
            pass

    def _is_relative_to(self, path: Path, parent: Path) -> bool:
        try:
            path.relative_to(parent)
        except ValueError:
            return False
        return True
