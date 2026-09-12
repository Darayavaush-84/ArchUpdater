from __future__ import annotations

import platform
import re
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

from archupdater.domain.system_overview import SystemOverviewSnapshot


_PACMAN_EVENT_RE = re.compile(
    r"^\[(?P<timestamp>[^\]]+)\]\s+\[ALPM\]\s+"
    r"(?:upgraded|installed|removed)\s+"
)


class SystemOverviewProvider:
    def __init__(
        self,
        *,
        pacman_log: Path = Path("/var/log/pacman.log"),
        pacman_conf: Path = Path("/etc/pacman.conf"),
        mirrorlists: tuple[Path, ...] = (
            Path("/etc/pacman.d/cachyos-mirrorlist"),
            Path("/etc/pacman.d/mirrorlist"),
        ),
    ) -> None:
        self._pacman_log = pacman_log
        self._pacman_conf = pacman_conf
        self._mirrorlists = mirrorlists

    def snapshot(self) -> SystemOverviewSnapshot:
        return SystemOverviewSnapshot(
            kernel=platform.release() or "Unknown",
            last_update_at=self._last_package_change(),
            mirror=self._configured_mirror(),
            repository=self._repository_family(),
        )

    def _last_package_change(self) -> datetime | None:
        last_update: datetime | None = None
        for line in self._read_lines(self._pacman_log):
            match = _PACMAN_EVENT_RE.match(line)
            if match is None:
                continue
            try:
                last_update = datetime.fromisoformat(match.group("timestamp"))
            except ValueError:
                continue
        return last_update

    def _configured_mirror(self) -> str:
        for mirrorlist in self._mirrorlists:
            for raw_line in self._read_lines(mirrorlist):
                line = raw_line.strip()
                if not line or line.startswith("#") or not line.startswith("Server"):
                    continue
                _, separator, value = line.partition("=")
                if not separator:
                    continue
                hostname = urlparse(value.strip()).hostname
                if hostname:
                    return hostname
        return "Not detected"

    def _repository_family(self) -> str:
        repositories = {
            line[1:-1].strip().casefold()
            for raw_line in self._read_lines(self._pacman_conf)
            if (line := raw_line.strip()).startswith("[") and line.endswith("]")
        }
        if any(repository.startswith("cachyos") for repository in repositories):
            return "CachyOS"
        if repositories:
            return "Arch Linux"
        return "Not detected"

    def _read_lines(self, path: Path) -> list[str]:
        try:
            return path.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            return []
