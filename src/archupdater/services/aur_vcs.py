from __future__ import annotations

import platform
import re
from dataclasses import dataclass
from pathlib import Path

from archupdater.domain.aur import AurVcsSource
from archupdater.domain.command_log import CheckLogEntry
from archupdater.domain.packages import PackageUpdate
from archupdater.services import aur_metadata, aur_sources
from archupdater.services.aur_errors import AurPkgbuildFetchError
from archupdater.services.aur_vcs_state import AurVcsStateStore
from archupdater.services.command_runner import CommandRunner


@dataclass
class AurVcsTracker:
    runner: CommandRunner
    store: AurVcsStateStore
    GIT_PATH = Path("/usr/bin/git")
    INFO_TIMEOUT_SECONDS = 120

    def filter_stale_updates(
        self,
        packages: list[PackageUpdate],
        *,
        local_output: str,
        logs: list[CheckLogEntry],
    ) -> list[PackageUpdate]:
        dynamic = [
            package for package in packages if aur_metadata.aur_metadata(package).dynamic_version
        ]
        if not dynamic:
            return packages
        local_versions = {
            section.get("Name", ""): section.get("Version", "")
            for section in aur_metadata.parse_sections(local_output)
            if section.get("Name") and section.get("Version")
        }
        receipts = self.store.load().get("packages")
        if not isinstance(receipts, dict):
            return packages

        suppressed: set[str] = set()
        for package in dynamic:
            receipt = receipts.get(package.name)
            if not isinstance(receipt, dict):
                continue
            version = receipt.get("version")
            raw_sources = receipt.get("sources")
            if version != local_versions.get(package.name) or not isinstance(raw_sources, list):
                continue
            sources = aur_sources.vcs_sources_from_payload(raw_sources)
            if not sources:
                continue
            unchanged = True
            for source in sources:
                commit, log = self.remote_commit(source.url, source.branch)
                logs.append(log)
                if commit != source.commit:
                    unchanged = False
                    break
            if unchanged:
                suppressed.add(package.name)
        return [package for package in packages if package.name not in suppressed]

    def resolve_sources(self, srcinfo: str) -> tuple[AurVcsSource, ...]:
        sources: list[AurVcsSource] = []
        seen: set[tuple[str, str, str | None]] = set()
        source_keys = {"source", f"source_{platform.machine()}"}
        for raw_line in srcinfo.splitlines():
            key, separator, value = raw_line.strip().partition("=")
            if separator != "=" or key.strip() not in source_keys:
                continue
            parsed = aur_sources.parse_git_source(value.strip())
            if parsed is None:
                continue
            name, url, branch = parsed
            identity = (name, url, branch)
            if identity in seen:
                continue
            commit, _log = self.remote_commit(url, branch)
            if not commit:
                raise AurPkgbuildFetchError(f"Could not resolve Git source {url}.")
            sources.append(AurVcsSource(name=name, url=url, branch=branch, commit=commit))
            seen.add(identity)
        return tuple(sources)

    def remote_commit(
        self,
        url: str,
        branch: str | None,
    ) -> tuple[str, CheckLogEntry]:
        reference = f"refs/heads/{branch}" if branch else "HEAD"
        command = [str(self.GIT_PATH), "ls-remote", url, reference]
        log = self.runner.run(
            command,
            timeout_seconds=self.INFO_TIMEOUT_SECONDS,
            extra_env={"GIT_TERMINAL_PROMPT": "0"},
        )
        if log.exit_code != 0:
            return "", log
        for line in log.stdout.splitlines():
            fields = line.split()
            if len(fields) != 2 or fields[1] != reference:
                continue
            commit = fields[0].lower()
            if re.fullmatch(r"[0-9a-f]{40,64}", commit):
                return commit, log
        return "", log
