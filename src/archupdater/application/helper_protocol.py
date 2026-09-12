from __future__ import annotations

import json
from dataclasses import dataclass
from enum import Enum

from archupdater.domain.aur import AurInstallTarget, AurPkgbuildReview


class HelperAction(str, Enum):
    INITIALIZE_UPDATE_SESSION = "initialize_update_session"
    INSTALL_REVIEWED_AUR = "install_reviewed_aur"
    INSTALL_REVIEWED_AUR_GROUP = "install_reviewed_aur_group"
    INSTALL_SUPPORT_PACKAGES = "install_support_packages"
    REMOVE_SUPPORT_PACKAGES = "remove_support_packages"
    RUN_SYSTEM_UPDATE = "run_system_update"
    RUN_FLATPAK_SYSTEM_UPDATE = "run_flatpak_system_update"
    RUN_FLATPAK_SYSTEM_CLEANUP = "run_flatpak_system_cleanup"
    RUN_FIRMWARE_UPDATE = "run_firmware_update"


class HelperEventType(str, Enum):
    STATUS = "status"
    LOG = "log"
    QUESTION = "question"
    COMPLETED = "completed"


@dataclass(slots=True)
class HelperRequest:
    action: HelperAction
    package_names: list[str] | None = None
    refs: list[str] | None = None
    device_id: str | None = None
    language_code: str | None = None
    aur_targets: list[AurInstallTarget] | None = None
    aur_review: AurPkgbuildReview | None = None
    expected_version: str | None = None
    expected_versions: dict[str, str] | None = None

    def to_json_bytes(self) -> bytes:
        payload = {
            "action": self.action.value,
        }
        if self.package_names:
            payload["package_names"] = self.package_names
        if self.refs:
            payload["refs"] = self.refs
        if self.device_id:
            payload["device_id"] = self.device_id
        if self.language_code:
            payload["language_code"] = self.language_code
        if self.aur_targets is not None:
            payload["aur_targets"] = [
                {
                    "package_name": target.package_name,
                    "package_base": target.package_base,
                    "version": target.version,
                    "current_version": target.current_version,
                    "dynamic_version": target.dynamic_version,
                }
                for target in self.aur_targets
            ]
        if self.aur_review is not None:
            payload["aur_review"] = {
                "package_name": self.aur_review.package_name,
                "package_base": self.aur_review.package_base,
                "digest": self.aur_review.digest,
                "vcs_sources": [
                    {
                        "name": source.name,
                        "url": source.url,
                        "branch": source.branch,
                        "commit": source.commit,
                    }
                    for source in self.aur_review.vcs_sources
                ],
                "files": [
                    {
                        "path": reviewed_file.path,
                        "sha256": reviewed_file.sha256,
                        "size": reviewed_file.size,
                        "content": reviewed_file.content,
                    }
                    for reviewed_file in self.aur_review.files
                ],
            }
        if self.expected_version is not None:
            payload["expected_version"] = self.expected_version
        if self.expected_versions is not None:
            payload["expected_versions"] = self.expected_versions
        return (json.dumps(payload, ensure_ascii=False) + "\n").encode("utf-8")
