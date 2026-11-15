from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from enum import Enum

from archupdater.domain.aur import AurInstallTarget, AurPkgbuildReview

MAX_AUR_REVIEW_BYTES = 16 * 1024 * 1024
# JSON escaping at most doubles accepted review content (quotes, backslashes and
# \n/\r/\t; other control characters are rejected). The margin covers up to 512
# escaped file paths and the remaining manifest fields.
MAX_HELPER_REQUEST_CHARACTERS = 2 * MAX_AUR_REVIEW_BYTES + 8 * 1024 * 1024


class HelperAction(str, Enum):
    ENABLE_DOWNLOAD_TIMEOUTS = "enable_download_timeouts"
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


class HelperText(str):
    """English helper text that carries its Qt catalog key.

    The privileged helper runs without Qt, so it emits the English text together with
    the catalog key and lets the unprivileged client translate it. String operations
    see the English text; composing it into a new string drops the key.
    """

    __slots__ = ("context", "source", "arguments")

    context: str
    source: str
    arguments: dict[str, str]

    def __new__(
        cls,
        context: str,
        source: str,
        arguments: Mapping[str, object] | None = None,
    ) -> HelperText:
        values = {name: str(value) for name, value in (arguments or {}).items()}
        text = super().__new__(cls, source.format(**values) if values else source)
        text.context = context
        text.source = source
        text.arguments = values
        return text

    def format(self, /, **arguments: object) -> HelperText:  # type: ignore[override]
        return HelperText(self.context, self.source, {**self.arguments, **arguments})

    def translation_payload(self) -> dict[str, object]:
        return {
            "context": self.context,
            "source": self.source,
            "arguments": dict(self.arguments),
        }


def translate(context: str, source: str) -> HelperText:
    """Mark helper text for lupdate; the client translates it with this key."""
    return HelperText(context, source)


def translated_helper_message(
    payload: Mapping[str, object],
    translate_text: Callable[[str, str], str],
) -> str:
    """Translate a helper event message, falling back to its English text."""
    message = str(payload.get("message") or "")
    raw_translation = payload.get("message_translation")
    if not isinstance(raw_translation, dict) or set(raw_translation) != {
        "context",
        "source",
        "arguments",
    }:
        return message
    context = raw_translation["context"]
    source = raw_translation["source"]
    arguments = raw_translation["arguments"]
    if (
        not isinstance(context, str)
        or not isinstance(source, str)
        or not isinstance(arguments, dict)
        or not all(
            isinstance(name, str) and isinstance(value, str)
            for name, value in arguments.items()
        )
    ):
        return message
    translated = translate_text(context, source)
    if not arguments:
        return translated
    try:
        return translated.format(**arguments)
    except (AttributeError, IndexError, KeyError, ValueError):
        return message


@dataclass(slots=True)
class HelperRequest:
    action: HelperAction
    package_names: list[str] | None = None
    refs: list[str] | None = None
    device_id: str | None = None
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
                        "executable": reviewed_file.executable,
                    }
                    for reviewed_file in self.aur_review.files
                ],
            }
        if self.expected_version is not None:
            payload["expected_version"] = self.expected_version
        if self.expected_versions is not None:
            payload["expected_versions"] = self.expected_versions
        return (json.dumps(payload, ensure_ascii=False) + "\n").encode("utf-8")
