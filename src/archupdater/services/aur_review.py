from __future__ import annotations

import hashlib
import re
import stat
import tempfile
import unicodedata
import urllib.parse
import uuid
from dataclasses import dataclass, field
from pathlib import Path

from archupdater.domain.aur import AurPkgbuildReview, AurReviewFile
from archupdater.services import aur_sources
from archupdater.services.aur_errors import AurBuildError, AurPkgbuildFetchError
from archupdater.services.aur_rpc import AurRpcClient
from archupdater.services.aur_vcs import AurVcsTracker
from archupdater.services.command_runner import CommandRunner


@dataclass(slots=True)
class _PreparedAurCheckout:
    temporary_dir: tempfile.TemporaryDirectory[str]
    checkout_path: Path
    review: AurPkgbuildReview
    dependencies: tuple[str, ...]


@dataclass
class AurReviewManager:
    runner: CommandRunner
    rpc: AurRpcClient
    vcs: AurVcsTracker
    _prepared_checkouts: dict[str, _PreparedAurCheckout] = field(
        default_factory=dict, init=False, repr=False
    )
    GIT_PATH = Path("/usr/bin/git")
    PACMAN_PATH = Path("/usr/bin/pacman")
    INFO_TIMEOUT_SECONDS = 120
    CHECKOUT_TIMEOUT_SECONDS = 120
    CHECKOUT_MAX_BYTES = 16 * 1024 * 1024
    CHECKOUT_MAX_FILES = 512

    def prepare(
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
            vcs_sources = self.vcs.resolve_sources(srcinfo) if lock_vcs_sources else ()
            if lock_vcs_sources and not vcs_sources:
                raise AurPkgbuildFetchError(
                    "The development package has no resolvable unpinned Git source."
                )
            dependencies = aur_sources.srcinfo_dependencies(
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

    def discard(self, review: AurPkgbuildReview) -> None:
        prepared = self._prepared_checkouts.pop(review.preparation_id, None)
        if prepared is not None:
            prepared.temporary_dir.cleanup()

    def _resolve_package_base(self, package_name: str, package_base: str | None) -> str:
        if not aur_sources.PACKAGE_NAME_RE.fullmatch(package_name):
            raise AurPkgbuildFetchError(f"Invalid AUR package name: {package_name!r}")
        resolved = str(package_base or "").strip()
        if not resolved:
            payload = self.rpc.fetch_chunk([package_name])
            results = payload.get("results") if isinstance(payload, dict) else None
            if not isinstance(results, list):
                results = []
            match = next(
                (
                    item
                    for item in results
                    if isinstance(item, dict) and item.get("Name") == package_name
                ),
                None,
            )
            resolved = str(match.get("PackageBase") or "").strip() if match else ""
            if not resolved:
                raise AurPkgbuildFetchError(
                    f"Could not resolve the AUR package base for {package_name}."
                )
        if not aur_sources.PACKAGE_NAME_RE.fullmatch(resolved):
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
            raise AurPkgbuildFetchError(f"The AUR checkout is not clean: {changed_paths[0]}")

        checkout_root = checkout_path.resolve()
        total_size = 0
        files: list[AurReviewFile] = []
        tree_digest = hashlib.sha256()
        for relative_name in tracked_paths:
            if self._has_unsafe_path_characters(relative_name):
                raise AurPkgbuildFetchError(f"Invalid tracked AUR path: {relative_name!r}")
            relative_path = Path(relative_name)
            if relative_path.is_absolute() or ".." in relative_path.parts:
                raise AurPkgbuildFetchError(f"Invalid tracked AUR path: {relative_name!r}")
            file_path = checkout_path / relative_path
            try:
                resolved_path = file_path.resolve(strict=True)
                resolved_path.relative_to(checkout_root)
                file_stat = file_path.lstat()
            except (OSError, ValueError) as exc:
                raise AurPkgbuildFetchError(f"Invalid tracked AUR file: {relative_name}") from exc
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
                (unicodedata.category(character) == "Cc" and character not in {"\n", "\r", "\t"})
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
        return any(unicodedata.category(character) in {"Cc", "Cf", "Cs"} for character in path)

    def _required_text_file(
        self,
        files: tuple[AurReviewFile, ...],
        path: str,
    ) -> str:
        match = next((reviewed_file for reviewed_file in files if reviewed_file.path == path), None)
        if match is None or not match.content.strip():
            raise AurPkgbuildFetchError(f"The AUR repository has no textual {path} file.")
        return match.content

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
            if self.vcs.resolve_sources(srcinfo) != prepared.review.vcs_sources:
                raise AurBuildError("A reviewed AUR VCS source changed before installation.")
