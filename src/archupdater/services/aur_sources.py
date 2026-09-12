from __future__ import annotations

import platform
import re
import unicodedata
import urllib.parse
from pathlib import Path

from archupdater.domain.aur import AurVcsSource
from archupdater.services.aur_errors import AurPkgbuildFetchError

PACKAGE_NAME_RE = re.compile(r"^[A-Za-z0-9@._+-]+$")
VCS_BRANCH_RE = re.compile(r"^[A-Za-z0-9._/-]+$")


def parse_git_source(source: str) -> tuple[str, str, str | None] | None:
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
    if not PACKAGE_NAME_RE.fullmatch(name) or (
        branch is not None
        and (
            unsafe_vcs_text(branch, 512)
            or not VCS_BRANCH_RE.fullmatch(branch)
            or branch.startswith(("-", "/"))
            or ".." in branch.split("/")
        )
    ):
        return None
    return name, base_url, branch


def unsafe_vcs_text(value: str, maximum: int) -> bool:
    return (
        not value
        or len(value) > maximum
        or any(unicodedata.category(character) in {"Cc", "Cf", "Cs"} for character in value)
    )


def vcs_source_payload(source: AurVcsSource) -> dict[str, str | None]:
    return {
        "name": source.name,
        "url": source.url,
        "branch": source.branch,
        "commit": source.commit,
    }


def vcs_sources_from_payload(raw_sources: list[object]) -> tuple[AurVcsSource, ...]:
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
            or not PACKAGE_NAME_RE.fullmatch(name)
            or not isinstance(url, str)
            or len(url) > 2048
            or (branch is not None and not isinstance(branch, str))
            or (
                isinstance(branch, str)
                and (
                    unsafe_vcs_text(branch, 512)
                    or not VCS_BRANCH_RE.fullmatch(branch)
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


def srcinfo_dependencies(
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
