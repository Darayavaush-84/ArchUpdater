from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path

from archupdater.domain.aur import AurVcsSource
from archupdater.services import aur_sources
from archupdater.services.aur_errors import AurBuildError


@dataclass
class AurVcsStateStore:
    vcs_state_path: Path | None = None
    VCS_STATE_SCHEMA_VERSION = 2
    VCS_STATE_MAX_BYTES = 1024 * 1024

    def record_install(
        self,
        package_name: str,
        version: str,
        sources: tuple[AurVcsSource, ...],
    ) -> None:
        if not aur_sources.PACKAGE_NAME_RE.fullmatch(package_name) or not version or not sources:
            raise AurBuildError("Invalid AUR VCS installation receipt.")
        state = self.load()
        packages = state.setdefault("packages", {})
        assert isinstance(packages, dict)
        packages[package_name] = {
            "version": version,
            "sources": [aur_sources.vcs_source_payload(source) for source in sources],
        }
        self.save(state)

    def resolved_path(self) -> Path:
        if self.vcs_state_path is not None:
            return self.vcs_state_path
        state_home = os.environ.get("XDG_STATE_HOME")
        root = Path(state_home) if state_home else Path.home() / ".local" / "state"
        return root / "archupdater" / "aur-vcs.json"

    def load(self) -> dict[str, object]:
        empty: dict[str, object] = {
            "schema_version": self.VCS_STATE_SCHEMA_VERSION,
            "packages": {},
        }
        path = self.resolved_path()
        try:
            if path.stat().st_size > self.VCS_STATE_MAX_BYTES:
                return empty
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError, json.JSONDecodeError):
            return empty
        if (
            not isinstance(payload, dict)
            or payload.get("schema_version") != self.VCS_STATE_SCHEMA_VERSION
            or not isinstance(payload.get("packages"), dict)
        ):
            return empty
        return payload

    def save(self, state: dict[str, object]) -> None:
        path = self.resolved_path()
        path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        raw = (json.dumps(state, ensure_ascii=True, sort_keys=True, indent=2) + "\n").encode()
        if len(raw) > self.VCS_STATE_MAX_BYTES:
            raise AurBuildError("AUR VCS installation state exceeds the safety limit.")
        temporary_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="wb",
                dir=path.parent,
                prefix=f".{path.name}.",
                delete=False,
            ) as handle:
                temporary_path = Path(handle.name)
                os.chmod(handle.name, 0o600)
                handle.write(raw)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary_path, path)
        finally:
            if temporary_path is not None:
                temporary_path.unlink(missing_ok=True)
