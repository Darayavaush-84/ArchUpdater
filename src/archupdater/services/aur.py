from __future__ import annotations

import hashlib
import json
import os
import platform
import re
import shutil
import stat
import tempfile
import unicodedata
import urllib.parse
import urllib.request
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from PySide6.QtCore import QCoreApplication

from archupdater.domain.check_results import SourceCheckResult
from archupdater.domain.command_log import CheckLogEntry
from archupdater.domain.aur import AurPkgbuildReview, AurReviewFile, AurVcsSource
from archupdater.domain.enums import UpdateSource
from archupdater.domain.package_metadata import AurPackageMetadata
from archupdater.domain.packages import PackageUpdate
from archupdater.services.command_runner import CommandRunner
from archupdater.services.io_limits import read_limited
from archupdater.domain.package_size import format_size_diff


class AurPkgbuildFetchError(RuntimeError):
    pass


class AurBuildError(RuntimeError):
    pass


@dataclass(slots=True)
class _PreparedAurCheckout:
    temporary_dir: tempfile.TemporaryDirectory[str]
    checkout_path: Path
    review: AurPkgbuildReview
    dependencies: tuple[str, ...]


@dataclass(slots=True)
class AurUpdateService:
    runner: CommandRunner
    vcs_state_path: Path | None = None
    _prepared_checkouts: dict[str, _PreparedAurCheckout] = field(
        default_factory=dict,
        init=False,
        repr=False,
    )

    ANSI_ESCAPE_RE = re.compile(r"\x1b\[[0-9;?]*[ -/]*[@-~]")
    UPDATE_LINE_RE = re.compile(
        r"^(?:(?P<repository>[A-Za-z0-9@._+-]+)/)?"
        r"(?P<name>[A-Za-z0-9@._+-]+)\s+"
        r"(?P<current_version>\S+)\s+->\s+"
        r"(?P<new_version>\S+)$"
    )
    QUERY_TIMEOUT_SECONDS = 120
    INFO_TIMEOUT_SECONDS = 120
    LOCAL_INFO_TIMEOUT_SECONDS = 120
    AUR_RPC_TIMEOUT_SECONDS = 10
    AUR_RPC_CHUNK_SIZE = 100
    AUR_RPC_MAX_BYTES = 2 * 1024 * 1024
    CHECKOUT_TIMEOUT_SECONDS = 120
    CHECKOUT_MAX_BYTES = 16 * 1024 * 1024
    CHECKOUT_MAX_FILES = 512
    VCS_STATE_SCHEMA_VERSION = 2
    VCS_STATE_MAX_BYTES = 1024 * 1024
    PACKAGE_NAME_RE = re.compile(r"^[A-Za-z0-9@._+-]+$")
    VCS_BRANCH_RE = re.compile(r"^[A-Za-z0-9._/-]+$")
    GIT_PATH = Path("/usr/bin/git")
    PACMAN_PATH = Path("/usr/bin/pacman")
    LIST_METADATA_KEYS = frozenset(
        {
            "Licenses",
            "Groups",
            "Provides",
            "Conflicts With",
            "Replaces",
            "Depends On",
            "Optional Deps",
            "Required By",
            "Make Deps",
            "Check Deps",
        }
    )

    def check_updates(self) -> SourceCheckResult:
        helper = self.detect_helper()
        if helper is None:
            return SourceCheckResult()

        result = SourceCheckResult()
        command = [helper, "-Qua"]
        if helper == "pikaur":
            command.append("--noconfirm")

        query_log = self.runner.run(command, timeout_seconds=self.QUERY_TIMEOUT_SECONDS)
        result.logs.append(query_log)

        no_updates = (
            query_log.exit_code == 0 and not query_log.stdout.strip()
        ) or (
            query_log.exit_code == 1
            and not query_log.stdout.strip()
            and not query_log.stderr.strip()
        )
        if no_updates:
            return result

        if query_log.exit_code != 0:
            details = query_log.stderr.strip() or query_log.stdout.strip() or helper
            result.warnings.append(
                QCoreApplication.translate(
                    "AurUpdateService",
                    "Failed to check AUR updates: {details}",
                ).format(details=details)
            )
            return result

        result.packages, unparsed_lines = self._parse_update_output(query_log.stdout)
        if unparsed_lines:
            result.warnings.append(
                QCoreApplication.translate(
                    "AurUpdateService",
                    "Some AUR update lines could not be parsed: {lines}",
                ).format(lines="; ".join(unparsed_lines[:3]))
            )
        if not result.packages:
            return result

        info_command = [helper, "-Si", "--aur", *[package.name for package in result.packages]]
        if helper == "pikaur":
            info_command.append("--noconfirm")
        info_log = self.runner.run(info_command, timeout_seconds=self.INFO_TIMEOUT_SECONDS)
        result.logs.append(info_log)
        if info_log.stdout.strip():
            self._apply_metadata(result.packages, info_log.stdout)

        local_info_log = self.runner.run(
            ["pacman", "-Qi", *[package.name for package in result.packages]],
            timeout_seconds=self.LOCAL_INFO_TIMEOUT_SECONDS,
        )
        result.logs.append(local_info_log)
        local_output = self._complete_local_metadata_output(
            result.packages,
            initial_output=local_info_log.stdout,
            logs=result.logs,
        )
        if local_output.strip():
            self._apply_local_metadata(result.packages, local_output)

        result.packages = self._filter_stale_dynamic_updates(
            result.packages,
            local_output=local_output,
            logs=result.logs,
        )
        if not result.packages:
            return result

        self._apply_aur_rpc_metadata(result.packages, self._fetch_aur_rpc_metadata(result.packages))
        unresolved = [
            package.name
            for package in result.packages
            if not (self._aur_metadata(package).package_base or "").strip()
        ]
        if unresolved:
            result.warnings.append(
                QCoreApplication.translate(
                    "AurUpdateService",
                    "AUR package base metadata could not be resolved: {packages}",
                ).format(packages=", ".join(unresolved[:8]))
            )
            unresolved_names = set(unresolved)
            result.packages = [
                package for package in result.packages if package.name not in unresolved_names
            ]
        return result

    def detect_helper(self) -> str | None:
        for candidate in ("paru", "yay", "pikaur"):
            if shutil.which(candidate):
                return candidate
        return None

    def fetch_pkgbuild_review(
        self,
        package_name: str,
        package_base: str | None = None,
        *,
        lock_vcs_sources: bool = False,
    ) -> AurPkgbuildReview:
        resolved_base = self._resolve_package_base(package_name, package_base)
        temporary_dir = tempfile.TemporaryDirectory(prefix="archupdater-aur-review-")
        checkout_path = Path(temporary_dir.name) / "checkout"
        try:
            self._clone_checkout(resolved_base, checkout_path)
            commit = self._checkout_commit(checkout_path)
            reviewed_files, digest = self._checkout_snapshot(checkout_path)
            pkgbuild = self._required_text_file(reviewed_files, "PKGBUILD")
            srcinfo = self._required_text_file(reviewed_files, ".SRCINFO")
            vcs_sources = self._resolve_vcs_sources(srcinfo) if lock_vcs_sources else ()
            if lock_vcs_sources and not vcs_sources:
                raise AurPkgbuildFetchError(
                    "The development package has no resolvable unpinned Git source."
                )
            dependencies = self._srcinfo_dependencies(
                srcinfo,
                package_name=package_name,
                package_base=resolved_base,
            )
            preparation_id = uuid.uuid4().hex
            review = AurPkgbuildReview(
                package_name=package_name,
                package_base=resolved_base,
                pkgbuild=pkgbuild,
                commit=commit,
                digest=digest,
                files=reviewed_files,
                vcs_sources=vcs_sources,
                preparation_id=preparation_id,
            )
            self._prepared_checkouts[preparation_id] = _PreparedAurCheckout(
                temporary_dir=temporary_dir,
                checkout_path=checkout_path,
                review=review,
                dependencies=dependencies,
            )
            return review
        except Exception:
            temporary_dir.cleanup()
            raise

    def missing_build_dependencies(self, review: AurPkgbuildReview) -> list[str]:
        prepared = self._prepared_checkout(review)
        self._assert_checkout_matches_review(prepared)
        if not prepared.dependencies:
            return []
        result = self.runner.run(
            [str(self.PACMAN_PATH), "-T", *prepared.dependencies],
            timeout_seconds=self.INFO_TIMEOUT_SECONDS,
        )
        if result.exit_code == 0:
            return []
        missing = [line.strip() for line in result.stdout.splitlines() if line.strip()]
        if missing:
            return missing
        details = result.stderr.strip() or f"pacman exited with code {result.exit_code}"
        raise AurBuildError(f"Could not check AUR build dependencies: {details}")

    def discard_pkgbuild_review(self, review: AurPkgbuildReview) -> None:
        prepared = self._prepared_checkouts.pop(review.preparation_id, None)
        if prepared is not None:
            prepared.temporary_dir.cleanup()

    def record_vcs_install(
        self,
        package_name: str,
        version: str,
        sources: tuple[AurVcsSource, ...],
    ) -> None:
        if not self.PACKAGE_NAME_RE.fullmatch(package_name) or not version or not sources:
            raise AurBuildError("Invalid AUR VCS installation receipt.")
        state = self._load_vcs_state()
        packages = state.setdefault("packages", {})
        assert isinstance(packages, dict)
        packages[package_name] = {
            "version": version,
            "sources": [self._vcs_source_payload(source) for source in sources],
        }
        self._save_vcs_state(state)

    def _parse_update_lines(self, raw_output: str) -> list[PackageUpdate]:
        packages, _unparsed_lines = self._parse_update_output(raw_output)
        return packages

    def _parse_update_output(self, raw_output: str) -> tuple[list[PackageUpdate], list[str]]:
        packages: list[PackageUpdate] = []
        unparsed_lines: list[str] = []
        for raw_line in raw_output.splitlines():
            line = self.ANSI_ESCAPE_RE.sub("", raw_line).strip()
            if not line:
                continue

            match = self.UPDATE_LINE_RE.match(line)
            if not match:
                unparsed_lines.append(line)
                continue

            name = match.group("name")
            current_version = match.group("current_version")
            new_version = match.group("new_version")
            packages.append(
                PackageUpdate(
                    name=name,
                    current_version=current_version,
                    new_version=new_version,
                    source=UpdateSource.AUR,
                    source_metadata=AurPackageMetadata(
                        repository=QCoreApplication.translate("AurUpdateService", "AUR"),
                        dynamic_version=new_version == "latest-commit",
                    ),
                    backend_id=name,
                )
            )
        return packages, unparsed_lines

    def _apply_metadata(self, packages: list[PackageUpdate], raw_output: str) -> None:
        metadata_by_name = {
            section.get("Name", ""): section
            for section in self._parse_sections(raw_output)
            if section.get("Name")
        }
        for package in packages:
            metadata = metadata_by_name.get(package.name)
            if not metadata:
                continue
            source_metadata = self._aur_metadata(package)
            package.description = metadata.get("Description", "")
            source_metadata.repository = metadata.get("Repository") or source_metadata.repository
            source_metadata.package_base = (
                metadata.get("Package Base") or source_metadata.package_base
            )
            package.download_size = metadata.get("Download Size")
            package.installed_size = metadata.get("Installed Size")
            package.size = package.download_size or package.installed_size
            package.homepage = metadata.get("URL") or package.homepage
            source_metadata.architecture = metadata.get("Architecture")
            source_metadata.packager = metadata.get("Packager")
            source_metadata.build_date = metadata.get("Build Date")
            source_metadata.licenses = self._split_metadata_list(metadata.get("Licenses"))
            source_metadata.groups = self._split_metadata_list(metadata.get("Groups"))
            source_metadata.provides = self._split_metadata_list(metadata.get("Provides"))
            source_metadata.conflicts = self._split_metadata_list(metadata.get("Conflicts With"))
            source_metadata.replaces = self._split_metadata_list(metadata.get("Replaces"))
            package.dependencies = self._split_metadata_list(metadata.get("Depends On"))
            package.optional_dependencies = self._split_metadata_list(metadata.get("Optional Deps"))
            source_metadata.make_dependencies = self._split_metadata_list(metadata.get("Make Deps"))
            source_metadata.check_dependencies = self._split_metadata_list(metadata.get("Check Deps"))

    def _apply_local_metadata(self, packages: list[PackageUpdate], raw_output: str) -> None:
        local_metadata_by_name = {
            section.get("Name", ""): section
            for section in self._parse_sections(raw_output)
            if section.get("Name")
        }
        for package in packages:
            metadata = local_metadata_by_name.get(package.name)
            if not metadata:
                continue
            source_metadata = self._aur_metadata(package)
            package.current_installed_size = metadata.get("Installed Size")
            source_metadata.install_date = metadata.get("Install Date")
            source_metadata.install_reason = metadata.get("Install Reason")
            source_metadata.required_by = self._split_metadata_list(metadata.get("Required By"))
            package.size_diff = format_size_diff(
                package.installed_size,
                package.current_installed_size,
            )

    def _filter_stale_dynamic_updates(
        self,
        packages: list[PackageUpdate],
        *,
        local_output: str,
        logs: list[CheckLogEntry],
    ) -> list[PackageUpdate]:
        dynamic = [
            package
            for package in packages
            if self._aur_metadata(package).dynamic_version
        ]
        if not dynamic:
            return packages
        local_versions = {
            section.get("Name", ""): section.get("Version", "")
            for section in self._parse_sections(local_output)
            if section.get("Name") and section.get("Version")
        }
        receipts = self._load_vcs_state().get("packages")
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
            sources = self._vcs_sources_from_payload(raw_sources)
            if not sources:
                continue
            unchanged = True
            for source in sources:
                commit, log = self._remote_vcs_commit(source.url, source.branch)
                logs.append(log)
                if commit != source.commit:
                    unchanged = False
                    break
            if unchanged:
                suppressed.add(package.name)
        return [package for package in packages if package.name not in suppressed]

    def _resolve_vcs_sources(self, srcinfo: str) -> tuple[AurVcsSource, ...]:
        sources: list[AurVcsSource] = []
        seen: set[tuple[str, str, str | None]] = set()
        source_keys = {"source", f"source_{platform.machine()}"}
        for raw_line in srcinfo.splitlines():
            key, separator, value = raw_line.strip().partition("=")
            if separator != "=" or key.strip() not in source_keys:
                continue
            parsed = self._parse_git_source(value.strip())
            if parsed is None:
                continue
            name, url, branch = parsed
            identity = (name, url, branch)
            if identity in seen:
                continue
            commit, _log = self._remote_vcs_commit(url, branch)
            if not commit:
                raise AurPkgbuildFetchError(f"Could not resolve Git source {url}.")
            sources.append(AurVcsSource(name=name, url=url, branch=branch, commit=commit))
            seen.add(identity)
        return tuple(sources)

    def _parse_git_source(self, source: str) -> tuple[str, str, str | None] | None:
        alias, separator, raw_url = source.partition("::")
        if not separator:
            raw_url = alias
            alias = ""
        if not raw_url.startswith("git+") or "://" not in raw_url:
            return None
        raw_url = raw_url.removeprefix("git+")
        base_url, marker, fragment = raw_url.partition("#")
        base_url = base_url.split("?", 1)[0]
        parsed_url = urllib.parse.urlparse(base_url)
        if (
            parsed_url.scheme not in {"https", "git", "ssh"}
            or not parsed_url.netloc
            or len(base_url) > 2048
        ):
            return None
        branch: str | None = None
        if marker:
            fragment = fragment.split("?", 1)[0]
            fragment_type, equals, fragment_value = fragment.partition("=")
            if fragment_type in {"commit", "tag"}:
                return None
            if fragment_type == "branch" and equals:
                branch = fragment_value
        name = alias or Path(parsed_url.path).name.removesuffix(".git")
        if (
            not self.PACKAGE_NAME_RE.fullmatch(name)
            or (
                branch is not None
                and (
                    self._unsafe_vcs_text(branch, 512)
                    or not self.VCS_BRANCH_RE.fullmatch(branch)
                    or branch.startswith(("-", "/"))
                    or ".." in branch.split("/")
                )
            )
        ):
            return None
        return name, base_url, branch

    def _remote_vcs_commit(
        self,
        url: str,
        branch: str | None,
    ) -> tuple[str, CheckLogEntry]:
        command = [str(self.GIT_PATH), "ls-remote", url, branch or "HEAD"]
        log = self.runner.run(
            command,
            timeout_seconds=self.INFO_TIMEOUT_SECONDS,
            extra_env={"GIT_TERMINAL_PROMPT": "0"},
        )
        lines = log.stdout.splitlines()
        fields = lines[0].split(maxsplit=1) if lines else []
        commit = fields[0].lower() if fields else ""
        if log.exit_code != 0 or not re.fullmatch(r"[0-9a-f]{40,64}", commit):
            return "", log
        return commit, log

    @staticmethod
    def _unsafe_vcs_text(value: str, maximum: int) -> bool:
        return (
            not value
            or len(value) > maximum
            or any(unicodedata.category(character) in {"Cc", "Cf", "Cs"} for character in value)
        )

    @staticmethod
    def _vcs_source_payload(source: AurVcsSource) -> dict[str, str | None]:
        return {
            "name": source.name,
            "url": source.url,
            "branch": source.branch,
            "commit": source.commit,
        }

    def _vcs_sources_from_payload(self, raw_sources: list[object]) -> tuple[AurVcsSource, ...]:
        sources: list[AurVcsSource] = []
        for raw_source in raw_sources:
            if not isinstance(raw_source, dict) or set(raw_source) != {
                "name",
                "url",
                "branch",
                "commit",
            }:
                return ()
            name = raw_source["name"]
            url = raw_source["url"]
            branch = raw_source["branch"]
            commit = raw_source["commit"]
            if (
                not isinstance(name, str)
                or not self.PACKAGE_NAME_RE.fullmatch(name)
                or not isinstance(url, str)
                or len(url) > 2048
                or (branch is not None and not isinstance(branch, str))
                or (
                    isinstance(branch, str)
                    and (
                        self._unsafe_vcs_text(branch, 512)
                        or not self.VCS_BRANCH_RE.fullmatch(branch)
                        or branch.startswith(("-", "/"))
                        or ".." in branch.split("/")
                    )
                )
                or not isinstance(commit, str)
                or not re.fullmatch(r"[0-9a-f]{40,64}", commit)
            ):
                return ()
            sources.append(AurVcsSource(name, url, branch, commit))
        return tuple(sources)

    def _resolved_vcs_state_path(self) -> Path:
        if self.vcs_state_path is not None:
            return self.vcs_state_path
        state_home = os.environ.get("XDG_STATE_HOME")
        root = Path(state_home) if state_home else Path.home() / ".local" / "state"
        return root / "archupdater" / "aur-vcs.json"

    def _load_vcs_state(self) -> dict[str, object]:
        empty: dict[str, object] = {
            "schema_version": self.VCS_STATE_SCHEMA_VERSION,
            "packages": {},
        }
        path = self._resolved_vcs_state_path()
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

    def _save_vcs_state(self, state: dict[str, object]) -> None:
        path = self._resolved_vcs_state_path()
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

    def _complete_local_metadata_output(
        self,
        packages: list[PackageUpdate],
        *,
        initial_output: str,
        logs: list[CheckLogEntry],
    ) -> str:
        output_parts = [initial_output] if initial_output.strip() else []
        found_names = {
            section.get("Name", "")
            for section in self._parse_sections(initial_output)
            if section.get("Name")
        }
        missing_names = [package.name for package in packages if package.name not in found_names]
        for name in missing_names:
            info_log = self.runner.run(
                ["pacman", "-Qi", name],
                timeout_seconds=self.LOCAL_INFO_TIMEOUT_SECONDS,
            )
            logs.append(info_log)
            if info_log.stdout.strip():
                output_parts.append(info_log.stdout)
        return "\n\n".join(output_parts)

    def _fetch_aur_rpc_metadata(self, packages: list[PackageUpdate]) -> dict[str, dict[str, object]]:
        names = [package.name for package in packages]
        if not names:
            return {}
        metadata: dict[str, dict[str, object]] = {}
        for chunk in self._chunks(names, self.AUR_RPC_CHUNK_SIZE):
            payload = self._fetch_aur_rpc_chunk(chunk)
            results = payload.get("results") if isinstance(payload, dict) else None
            if not isinstance(results, list):
                continue
            for item in results:
                if isinstance(item, dict) and item.get("Name"):
                    metadata[str(item["Name"])] = item
        return metadata

    def _fetch_aur_rpc_chunk(self, names: list[str]) -> dict[str, object]:
        body = urllib.parse.urlencode([("arg[]", name) for name in names]).encode("utf-8")
        request = urllib.request.Request(
            "https://aur.archlinux.org/rpc/v5/info",
            data=body,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.AUR_RPC_TIMEOUT_SECONDS) as response:
                payload = json.loads(
                    self._read_limited_response(response).decode("utf-8", errors="replace")
                )
        except (OSError, json.JSONDecodeError):
            return {}
        return payload if isinstance(payload, dict) else {}

    def _read_limited_response(self, response) -> bytes:  # noqa: ANN001
        try:
            return read_limited(response, self.AUR_RPC_MAX_BYTES)
        except ValueError as exc:
            raise OSError("AUR RPC response is too large.") from exc

    def _chunks(self, values: list[str], size: int) -> list[list[str]]:
        return [values[index : index + size] for index in range(0, len(values), size)]

    def _apply_aur_rpc_metadata(
        self,
        packages: list[PackageUpdate],
        metadata_by_name: dict[str, dict[str, object]],
    ) -> None:
        for package in packages:
            metadata = metadata_by_name.get(package.name)
            if not metadata:
                continue
            source_metadata = self._aur_metadata(package)
            source_metadata.maintainer = self._optional_str(metadata.get("Maintainer"))
            source_metadata.package_base = (
                self._optional_str(metadata.get("PackageBase"))
                or source_metadata.package_base
            )
            source_metadata.votes = self._optional_str(metadata.get("NumVotes"))
            source_metadata.popularity = self._optional_str(metadata.get("Popularity"))
            source_metadata.out_of_date = (
                self._format_timestamp(metadata.get("OutOfDate"))
                if metadata.get("OutOfDate")
                else "No"
            )
            source_metadata.first_submitted = self._format_timestamp(metadata.get("FirstSubmitted"))
            source_metadata.last_modified = self._format_timestamp(metadata.get("LastModified"))
            package.homepage = self._optional_str(metadata.get("URL")) or package.homepage
            source_metadata.licenses = self._merge_metadata_list(
                source_metadata.licenses,
                metadata.get("License"),
            )
            package.dependencies = self._merge_metadata_list(package.dependencies, metadata.get("Depends"))
            package.optional_dependencies = self._merge_metadata_list(
                package.optional_dependencies,
                metadata.get("OptDepends"),
            )
            source_metadata.make_dependencies = self._merge_metadata_list(
                source_metadata.make_dependencies,
                metadata.get("MakeDepends"),
            )
            source_metadata.check_dependencies = self._merge_metadata_list(
                source_metadata.check_dependencies,
                metadata.get("CheckDepends"),
            )
            source_metadata.provides = self._merge_metadata_list(
                source_metadata.provides,
                metadata.get("Provides"),
            )
            source_metadata.conflicts = self._merge_metadata_list(
                source_metadata.conflicts,
                metadata.get("Conflicts"),
            )
            source_metadata.replaces = self._merge_metadata_list(
                source_metadata.replaces,
                metadata.get("Replaces"),
            )

    def _aur_metadata(self, package: PackageUpdate) -> AurPackageMetadata:
        metadata = package.source_metadata
        if not isinstance(metadata, AurPackageMetadata):
            raise TypeError("AUR package metadata expected.")
        return metadata

    def _parse_sections(self, raw_output: str) -> list[dict[str, str]]:
        sections: list[dict[str, str]] = []
        current: dict[str, str] = {}
        current_key: str | None = None

        for line in raw_output.splitlines():
            if not line.strip():
                if current:
                    sections.append(current)
                    current = {}
                    current_key = None
                continue

            match = re.match(r"^([A-Za-z][A-Za-z ]+?)\s*:\s*(.*)$", line)
            if match:
                current_key = match.group(1).strip()
                current[current_key] = match.group(2).strip()
                continue

            if current_key:
                separator = "  " if current_key in self.LIST_METADATA_KEYS else " "
                current[current_key] = (
                    f"{current[current_key]}{separator}{line.strip()}".strip()
                )

        if current:
            sections.append(current)

        return sections

    def _split_metadata_list(self, value: str | None) -> list[str]:
        if not value:
            return []
        stripped = value.strip()
        if not stripped or stripped.lower() == "none":
            return []
        return [
            item.strip()
            for item in re.split(r"\s{2,}|,\s*", stripped)
            if item.strip() and item.strip().lower() != "none"
        ]

    def _merge_metadata_list(self, current: list[str], value: object) -> list[str]:
        if isinstance(value, list):
            incoming = [str(item).strip() for item in value if str(item).strip()]
        else:
            incoming = self._split_metadata_list(str(value) if value is not None else None)
        merged = list(current)
        for item in incoming:
            if item not in merged:
                merged.append(item)
        return merged

    def _optional_str(self, value: object) -> str | None:
        text = str(value).strip() if value is not None else ""
        return text or None

    def _format_timestamp(self, value: object) -> str | None:
        try:
            timestamp = int(str(value))
        except (TypeError, ValueError):
            return None
        if timestamp <= 0:
            return None
        return datetime.fromtimestamp(timestamp, tz=timezone.utc).date().isoformat()

    def _resolve_package_base(self, package_name: str, package_base: str | None) -> str:
        if not self.PACKAGE_NAME_RE.fullmatch(package_name):
            raise AurPkgbuildFetchError(f"Invalid AUR package name: {package_name!r}")
        resolved = str(package_base or "").strip()
        if not resolved:
            payload = self._fetch_aur_rpc_chunk([package_name])
            results = payload.get("results") if isinstance(payload, dict) else None
            match = next(
                (
                    item
                    for item in results or []
                    if isinstance(item, dict) and item.get("Name") == package_name
                ),
                None,
            )
            resolved = str(match.get("PackageBase") or "").strip() if match else ""
            if not resolved:
                raise AurPkgbuildFetchError(
                    f"Could not resolve the AUR package base for {package_name}."
                )
        if not self.PACKAGE_NAME_RE.fullmatch(resolved):
            raise AurPkgbuildFetchError(f"Invalid AUR package base: {resolved!r}")
        return resolved

    def _clone_checkout(self, package_base: str, checkout_path: Path) -> None:
        encoded_base = urllib.parse.quote(package_base, safe="")
        source_url = f"https://aur.archlinux.org/{encoded_base}.git"
        result = self.runner.run(
            [
                str(self.GIT_PATH),
                "clone",
                "--depth",
                "1",
                source_url,
                str(checkout_path),
            ],
            timeout_seconds=self.CHECKOUT_TIMEOUT_SECONDS,
        )
        if result.exit_code != 0:
            details = result.stderr.strip() or result.stdout.strip()
            raise AurPkgbuildFetchError(
                f"Could not clone the AUR repository for {package_base}: "
                f"{details or result.exit_code}"
            )

    def _checkout_commit(self, checkout_path: Path) -> str:
        result = self.runner.run(
            [str(self.GIT_PATH), "-C", str(checkout_path), "rev-parse", "HEAD"],
            timeout_seconds=self.INFO_TIMEOUT_SECONDS,
        )
        commit = result.stdout.strip()
        if result.exit_code != 0 or not re.fullmatch(r"[0-9a-fA-F]{40,64}", commit):
            raise AurPkgbuildFetchError("Could not identify the reviewed AUR commit.")
        return commit.lower()

    def _checkout_snapshot(
        self,
        checkout_path: Path,
    ) -> tuple[tuple[AurReviewFile, ...], str]:
        tracked_result = self.runner.run(
            [str(self.GIT_PATH), "-C", str(checkout_path), "ls-files", "-z"],
            timeout_seconds=self.INFO_TIMEOUT_SECONDS,
        )
        if tracked_result.exit_code != 0:
            raise AurPkgbuildFetchError("Could not enumerate tracked AUR files.")
        tracked_paths = sorted(path for path in tracked_result.stdout.split("\0") if path)
        if not tracked_paths:
            raise AurPkgbuildFetchError("The AUR repository contains no tracked files.")
        if len(tracked_paths) > self.CHECKOUT_MAX_FILES:
            raise AurPkgbuildFetchError("The reviewed AUR checkout contains too many files.")

        status_result = self.runner.run(
            [
                str(self.GIT_PATH),
                "-C",
                str(checkout_path),
                "status",
                "--porcelain=v1",
                "--untracked-files=all",
                "--ignored=matching",
                "-z",
            ],
            timeout_seconds=self.INFO_TIMEOUT_SECONDS,
        )
        if status_result.exit_code != 0:
            raise AurPkgbuildFetchError("Could not inspect the AUR checkout status.")
        changed_paths = [path for path in status_result.stdout.split("\0") if path]
        if changed_paths:
            raise AurPkgbuildFetchError(
                f"The AUR checkout is not clean: {changed_paths[0]}"
            )

        checkout_root = checkout_path.resolve()
        total_size = 0
        files: list[AurReviewFile] = []
        tree_digest = hashlib.sha256()
        for relative_name in tracked_paths:
            if self._has_unsafe_path_characters(relative_name):
                raise AurPkgbuildFetchError(
                    f"Invalid tracked AUR path: {relative_name!r}"
                )
            relative_path = Path(relative_name)
            if relative_path.is_absolute() or ".." in relative_path.parts:
                raise AurPkgbuildFetchError(
                    f"Invalid tracked AUR path: {relative_name!r}"
                )
            file_path = checkout_path / relative_path
            try:
                resolved_path = file_path.resolve(strict=True)
                resolved_path.relative_to(checkout_root)
                file_stat = file_path.lstat()
            except (OSError, ValueError) as exc:
                raise AurPkgbuildFetchError(
                    f"Invalid tracked AUR file: {relative_name}"
                ) from exc
            if file_path.is_symlink() or not stat.S_ISREG(file_stat.st_mode):
                raise AurPkgbuildFetchError(
                    f"Tracked AUR file is not a regular file: {relative_name}"
                )
            total_size += file_stat.st_size
            if total_size > self.CHECKOUT_MAX_BYTES:
                raise AurPkgbuildFetchError("The reviewed AUR checkout is too large.")
            try:
                raw_content = resolved_path.read_bytes()
            except OSError as exc:
                raise AurPkgbuildFetchError(
                    f"Could not read tracked AUR file: {relative_name}"
                ) from exc
            file_digest = hashlib.sha256(raw_content).hexdigest()
            if b"\0" in raw_content:
                raise AurPkgbuildFetchError(
                    f"Tracked AUR file is not reviewable UTF-8 text: {relative_name}"
                )
            try:
                content = raw_content.decode("utf-8", errors="strict")
            except UnicodeDecodeError as exc:
                raise AurPkgbuildFetchError(
                    f"Tracked AUR file is not reviewable UTF-8 text: {relative_name}"
                ) from exc
            if any(
                (
                    unicodedata.category(character) == "Cc"
                    and character not in {"\n", "\r", "\t"}
                )
                or unicodedata.category(character) in {"Cf", "Cs"}
                for character in content
            ):
                raise AurPkgbuildFetchError(
                    f"Tracked AUR file contains unsafe control characters: {relative_name}"
                )
            reviewed_file = AurReviewFile(
                path=relative_path.as_posix(),
                sha256=file_digest,
                size=len(raw_content),
                content=content,
            )
            files.append(reviewed_file)
            tree_digest.update(relative_path.as_posix().encode("utf-8"))
            tree_digest.update(b"\0")
            tree_digest.update(str(len(raw_content)).encode("ascii"))
            tree_digest.update(b"\0")
            tree_digest.update(file_digest.encode("ascii"))
            tree_digest.update(b"\0")
        return tuple(files), tree_digest.hexdigest()

    @staticmethod
    def _has_unsafe_path_characters(path: str) -> bool:
        return any(
            unicodedata.category(character) in {"Cc", "Cf", "Cs"}
            for character in path
        )

    def _required_text_file(
        self,
        files: tuple[AurReviewFile, ...],
        path: str,
    ) -> str:
        match = next((reviewed_file for reviewed_file in files if reviewed_file.path == path), None)
        if match is None or not match.content.strip():
            raise AurPkgbuildFetchError(f"The AUR repository has no textual {path} file.")
        return match.content

    def _srcinfo_dependencies(
        self,
        srcinfo: str,
        *,
        package_name: str,
        package_base: str,
    ) -> tuple[str, ...]:
        current_package: str | None = None
        declared_base = ""
        package_names: set[str] = set()
        dependencies: list[str] = []
        architecture = platform.machine()
        dependency_keys = {"depends", "makedepends", "checkdepends"}

        for raw_line in srcinfo.splitlines():
            key, separator, value = raw_line.strip().partition("=")
            if separator != "=":
                continue
            key = key.strip()
            value = value.strip()
            if key == "pkgbase":
                declared_base = value
                current_package = None
                continue
            if key == "pkgname":
                current_package = value
                package_names.add(value)
                continue

            base_key, separator, qualifier = key.partition("_")
            if base_key not in dependency_keys:
                continue
            if separator and qualifier != architecture:
                continue
            if current_package not in {None, package_name}:
                continue
            if value and value not in dependencies:
                dependencies.append(value)

        if declared_base != package_base:
            raise AurPkgbuildFetchError(
                f"AUR package base mismatch: expected {package_base}, found {declared_base or '-'}"
            )
        if package_name not in package_names:
            raise AurPkgbuildFetchError(
                f"AUR checkout does not declare the requested package {package_name}."
            )
        return tuple(dependencies)

    def _prepared_checkout(self, review: AurPkgbuildReview) -> _PreparedAurCheckout:
        prepared = self._prepared_checkouts.get(review.preparation_id)
        if prepared is None or prepared.review != review:
            raise AurBuildError("The reviewed AUR checkout is no longer available.")
        return prepared

    def _assert_checkout_matches_review(self, prepared: _PreparedAurCheckout) -> None:
        commit = self._checkout_commit(prepared.checkout_path)
        files, digest = self._checkout_snapshot(prepared.checkout_path)
        if commit != prepared.review.commit or digest != prepared.review.digest:
            raise AurBuildError("The AUR checkout changed after it was reviewed.")
        if prepared.review.vcs_sources:
            srcinfo = self._required_text_file(files, ".SRCINFO")
            if self._resolve_vcs_sources(srcinfo) != prepared.review.vcs_sources:
                raise AurBuildError("A reviewed AUR VCS source changed before installation.")
