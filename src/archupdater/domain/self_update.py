from __future__ import annotations

from dataclasses import dataclass
import re

from packaging.version import Version

REPOSITORY = "Darayavaush-84/ArchUpdater"
RELEASE_WORKFLOW = f"https://github.com/{REPOSITORY}/.github/workflows/release.yml"
MAX_WHEEL_BYTES = 32 * 1024 * 1024
MAX_BUNDLE_BYTES = 4 * 1024 * 1024


def release_version(value: str) -> str:
    if not re.fullmatch(r"(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)", value):
        raise ValueError("Invalid ArchUpdater release version.")
    return value


@dataclass(frozen=True, slots=True)
class SelfUpdateRelease:
    version: str
    notes: str
    wheel_url: str
    bundle_url: str

    @property
    def tag(self) -> str:
        return f"v{self.version}"

    @property
    def wheel_name(self) -> str:
        return f"archupdater-{self.version}-py3-none-any.whl"


def self_update_release(payload: object, current_version: str) -> SelfUpdateRelease | None:
    if not isinstance(payload, dict) or payload.get("draft") or payload.get("prerelease"):
        return None
    tag = payload.get("tag_name")
    if not isinstance(tag, str) or not tag.startswith("v"):
        return None
    try:
        version = release_version(tag[1:])
    except ValueError:
        return None
    if Version(version) <= Version(current_version):
        return None
    assets = payload.get("assets")
    if not isinstance(assets, list):
        return None
    names = [
        f"archupdater-{version}-py3-none-any.whl",
        f"archupdater-{version}-py3-none-any.whl.sigstore.json",
    ]
    urls = []
    for name, limit in zip(names, (MAX_WHEEL_BYTES, MAX_BUNDLE_BYTES), strict=True):
        matches = [item for item in assets if isinstance(item, dict) and item.get("name") == name]
        if len(matches) != 1:
            return None
        asset = matches[0]
        expected_url = f"https://github.com/{REPOSITORY}/releases/download/{tag}/{name}"
        size = asset.get("size")
        if (
            asset.get("browser_download_url") != expected_url
            or type(size) is not int
            or not 0 < size <= limit
        ):
            return None
        urls.append(expected_url)
    notes = payload.get("body")
    return SelfUpdateRelease(version, notes[:12000] if isinstance(notes, str) else "", *urls)
