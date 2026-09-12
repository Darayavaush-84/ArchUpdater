from __future__ import annotations

import hashlib
import re
import unicodedata
from pathlib import Path

from PySide6.QtCore import QCoreApplication

from archupdater.domain.aur import (
    AurPkgbuildReview,
    AurReviewFile,
    AurVcsSource,
)
from archupdater.helper.actions import validation

PACKAGE_NAME_RE = re.compile(r"^[A-Za-z0-9@._+-]+$")


SHA256_RE = re.compile(r"^[0-9a-fA-F]{64}$")


VCS_COMMIT_RE = re.compile(r"^[0-9a-fA-F]{40,64}$")


VCS_BRANCH_RE = re.compile(r"^[A-Za-z0-9._/-]+$")


MAX_AUR_REVIEW_FILES = 512


MAX_AUR_REVIEW_BYTES = 16 * 1024 * 1024


def validate_aur_build_review(raw_review: object) -> AurPkgbuildReview:
    if not isinstance(raw_review, dict) or set(raw_review) != {
        "package_name",
        "package_base",
        "digest",
        "files",
        "vcs_sources",
    }:
        raise validation.PrivilegedUpdateValidationError(
            QCoreApplication.translate(
                "PrivilegedHelper",
                "Invalid reviewed AUR build manifest.",
            )
        )
    package_name = raw_review["package_name"]
    package_base = raw_review["package_base"]
    digest = raw_review["digest"]
    raw_files = raw_review["files"]
    raw_vcs_sources = raw_review["vcs_sources"]
    if (
        not isinstance(package_name, str)
        or not PACKAGE_NAME_RE.fullmatch(package_name)
        or not isinstance(package_base, str)
        or not PACKAGE_NAME_RE.fullmatch(package_base)
        or not isinstance(digest, str)
        or not SHA256_RE.fullmatch(digest)
        or not isinstance(raw_files, list)
        or not raw_files
        or len(raw_files) > MAX_AUR_REVIEW_FILES
        or not isinstance(raw_vcs_sources, list)
        or len(raw_vcs_sources) > 64
    ):
        raise validation.PrivilegedUpdateValidationError(
            QCoreApplication.translate(
                "PrivilegedHelper",
                "Invalid reviewed AUR build manifest.",
            )
        )

    files: list[AurReviewFile] = []
    paths: list[str] = []
    total_size = 0
    tree_digest = hashlib.sha256()
    for raw_file in raw_files:
        if not isinstance(raw_file, dict) or set(raw_file) != {
            "path",
            "sha256",
            "size",
            "content",
        }:
            raise validation.PrivilegedUpdateValidationError(
                QCoreApplication.translate(
                    "PrivilegedHelper",
                    "Invalid reviewed AUR build manifest.",
                )
            )
        path = raw_file["path"]
        sha256 = raw_file["sha256"]
        size = raw_file["size"]
        content = raw_file["content"]
        if (
            not isinstance(path, str)
            or not path
            or len(path) > 4096
            or Path(path).is_absolute()
            or ".." in Path(path).parts
            or any(unicodedata.category(character) in {"Cc", "Cf", "Cs"} for character in path)
            or path in paths
            or not isinstance(sha256, str)
            or not SHA256_RE.fullmatch(sha256)
            or isinstance(size, bool)
            or not isinstance(size, int)
            or size < 0
            or not isinstance(content, str)
            or any(
                (unicodedata.category(character) == "Cc" and character not in {"\n", "\r", "\t"})
                or unicodedata.category(character) in {"Cf", "Cs"}
                for character in content
            )
        ):
            raise validation.PrivilegedUpdateValidationError(
                QCoreApplication.translate(
                    "PrivilegedHelper",
                    "Invalid reviewed AUR build manifest.",
                )
            )
        raw_content = content.encode("utf-8")
        total_size += len(raw_content)
        if (
            len(raw_content) != size
            or hashlib.sha256(raw_content).hexdigest() != sha256.lower()
            or total_size > MAX_AUR_REVIEW_BYTES
        ):
            raise validation.PrivilegedUpdateValidationError(
                QCoreApplication.translate(
                    "PrivilegedHelper",
                    "Reviewed AUR file content does not match its manifest.",
                )
            )
        paths.append(path)
        files.append(AurReviewFile(path=path, sha256=sha256.lower(), size=size, content=content))
        tree_digest.update(path.encode("utf-8"))
        tree_digest.update(b"\0")
        tree_digest.update(str(size).encode("ascii"))
        tree_digest.update(b"\0")
        tree_digest.update(sha256.lower().encode("ascii"))
        tree_digest.update(b"\0")

    if paths != sorted(paths) or tree_digest.hexdigest() != digest.lower():
        raise validation.PrivilegedUpdateValidationError(
            QCoreApplication.translate(
                "PrivilegedHelper",
                "Reviewed AUR tree digest does not match its manifest.",
            )
        )
    if not {"PKGBUILD", ".SRCINFO"}.issubset(set(paths)):
        raise validation.PrivilegedUpdateValidationError(
            QCoreApplication.translate(
                "PrivilegedHelper",
                "The reviewed AUR build manifest is incomplete.",
            )
        )
    vcs_sources: list[AurVcsSource] = []
    seen_source_names: set[str] = set()
    for raw_source in raw_vcs_sources:
        if not isinstance(raw_source, dict) or set(raw_source) != {
            "name",
            "url",
            "branch",
            "commit",
        }:
            raise validation.PrivilegedUpdateValidationError(
                QCoreApplication.translate(
                    "PrivilegedHelper", "Invalid reviewed AUR VCS source lock."
                )
            )
        name = raw_source["name"]
        url = raw_source["url"]
        branch = raw_source["branch"]
        commit = raw_source["commit"]
        if (
            not isinstance(name, str)
            or not PACKAGE_NAME_RE.fullmatch(name)
            or name in seen_source_names
            or not isinstance(url, str)
            or len(url) > 2048
            or not re.fullmatch(r"(?:https|git|ssh)://[^\s]+", url)
            or (branch is not None and not isinstance(branch, str))
            or (
                isinstance(branch, str)
                and (
                    not branch
                    or len(branch) > 512
                    or not VCS_BRANCH_RE.fullmatch(branch)
                    or branch.startswith(("-", "/"))
                    or ".." in branch.split("/")
                )
            )
            or not isinstance(commit, str)
            or not VCS_COMMIT_RE.fullmatch(commit)
        ):
            raise validation.PrivilegedUpdateValidationError(
                QCoreApplication.translate(
                    "PrivilegedHelper", "Invalid reviewed AUR VCS source lock."
                )
            )
        seen_source_names.add(name)
        vcs_sources.append(
            AurVcsSource(
                name=name,
                url=url,
                branch=branch,
                commit=commit.lower(),
            )
        )

    return AurPkgbuildReview(
        package_name=package_name,
        package_base=package_base,
        pkgbuild=next(file.content for file in files if file.path == "PKGBUILD"),
        digest=digest.lower(),
        files=tuple(files),
        vcs_sources=tuple(vcs_sources),
    )


def _validate_review_targets(
    review: AurPkgbuildReview,
    *,
    package_names: set[str],
    expected_package_base: str,
) -> None:
    if review.package_base != expected_package_base:
        raise validation.PrivilegedUpdateValidationError(
            QCoreApplication.translate(
                "PrivilegedHelper",
                "The reviewed AUR package base does not match the authorized update plan.",
            )
        )
    srcinfo = next(
        (reviewed.content for reviewed in review.files if reviewed.path == ".SRCINFO"),
        "",
    )
    declared_base = ""
    declared_packages: set[str] = set()
    for raw_line in srcinfo.splitlines():
        key, separator, value = raw_line.strip().partition("=")
        if separator != "=":
            continue
        key = key.strip()
        value = value.strip()
        if key == "pkgbase":
            declared_base = value
        elif key == "pkgname":
            declared_packages.add(value)
    if (
        declared_base != expected_package_base
        or not package_names
        or not package_names.issubset(declared_packages)
        or review.package_name not in package_names
    ):
        raise validation.PrivilegedUpdateValidationError(
            QCoreApplication.translate(
                "PrivilegedHelper",
                "The reviewed .SRCINFO does not declare the authorized AUR package.",
            )
        )
