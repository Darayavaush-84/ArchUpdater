from __future__ import annotations

import json
import re
import unicodedata
from enum import Enum

from archupdater.domain.enums import UpdateSource
from archupdater.domain.update_plan import (
    UpdatePlan,
    UpdatePlanAction,
    UpdatePlanItem,
)


UPDATE_PLAN_SCHEMA_VERSION = 7
MAX_UPDATE_PLAN_BYTES = 16 * 1024 * 1024
PLAN_ITEM_FIELDS = frozenset(
    {
        "source",
        "target_id",
        "action",
        "installation_scope",
        "package_name",
        "package_kind",
        "plugin_id",
        "package_base",
        "expected_version",
        "current_version",
        "dynamic_version",
    }
)
AUR_PACKAGE_NAME_RE = re.compile(r"^[A-Za-z0-9@._+-]+$")
FLATPAK_REF_RE = re.compile(r"^[A-Za-z0-9._/-]+$")


class BatchEventType(str, Enum):
    BATCH_STARTED = "batch_started"
    STEP_STARTED = "step_started"
    COMMAND_STARTED = "command_started"
    LOG = "log"
    PROGRESS = "progress"
    STEP_COMPLETED = "step_completed"
    QUESTION_REQUESTED = "question_requested"
    BATCH_COMPLETED = "batch_completed"


class BatchControlType(str, Enum):
    CANCEL = "cancel"
    QUESTION_RESPONSE = "question_response"


class BatchStep(str, Enum):
    SYSTEM = "system"
    AUR = "aur"
    FLATPAK = "flatpak"
    FIRMWARE = "firmware"
    PLASMA_WIDGET = "plasma_widget"


class BatchStepResult(str, Enum):
    COMPLETED = "completed"
    INCOMPLETE = "incomplete"
    FAILED = "failed"


class BatchOutcome(str, Enum):
    SUCCESS = "success"
    PARTIAL_SUCCESS = "partial_success"
    NO_CHANGES = "no_changes"
    FAILED = "failed"
    CANCELLED = "cancelled"
    AUTH_CANCELLED = "auth_cancelled"
    SYSTEM_TRANSACTION_FAILED = "system_transaction_failed"


def running_status_for_step(step: BatchStep | str) -> str:
    return f"running_{step.value if isinstance(step, BatchStep) else step}"


def step_from_running_status(status: str) -> BatchStep | None:
    if not status.startswith("running_"):
        return None
    raw_step = status.removeprefix("running_")
    try:
        return BatchStep(raw_step)
    except ValueError:
        return None


def serialize_update_plan(plan: UpdatePlan) -> dict[str, object]:
    return {
        "schema_version": UPDATE_PLAN_SCHEMA_VERSION,
        "items": [
            {
                "source": item.source.value,
                "target_id": item.target_id,
                "action": item.action.value,
                "installation_scope": item.installation_scope,
                "package_name": item.package_name,
                "package_kind": item.package_kind,
                "plugin_id": item.plugin_id,
                "package_base": item.package_base,
                "expected_version": item.expected_version,
                "current_version": item.current_version,
                "dynamic_version": item.dynamic_version,
            }
            for item in plan.items
        ],
    }


def deserialize_update_plan_payload(payload: object) -> UpdatePlan:
    if not isinstance(payload, dict):
        raise ValueError("Update plan payload must be an object.")
    data = payload
    if set(data) != {"schema_version", "items"}:
        raise ValueError("Update plan payload contains missing or unsupported fields.")
    if _field(data, "schema_version") != UPDATE_PLAN_SCHEMA_VERSION:
        raise ValueError(
            f"Update plan schema_version must be {UPDATE_PLAN_SCHEMA_VERSION}."
        )
    raw_items = _dict_list_field(data, "items")
    if not raw_items:
        raise ValueError("Update plan must contain at least one item.")
    items = [_plan_item(item) for item in raw_items]
    identities = [
        (item.source, item.target_id, item.action, item.installation_scope)
        for item in items
    ]
    if len(identities) != len(set(identities)):
        raise ValueError("Update plan contains duplicate items.")
    return UpdatePlan(items=items)


def deserialize_update_plan_json(raw_json: str) -> UpdatePlan:
    if len(raw_json.encode("utf-8")) > MAX_UPDATE_PLAN_BYTES:
        raise ValueError("Update plan exceeds the safety limit.")
    return deserialize_update_plan_payload(json.loads(raw_json))


def _field(payload: dict[object, object], key: str) -> object:
    try:
        return payload[key]
    except KeyError as exc:
        raise ValueError(f"Update plan payload is missing {key!r}.") from exc


def _string_field(payload: dict[object, object], key: str) -> str:
    value = _field(payload, key)
    if not isinstance(value, str):
        raise ValueError(f"Update plan field {key!r} must be a string.")
    return _validated_text(value, key=key, allow_empty=False)


def _optional_string_field(payload: dict[object, object], key: str) -> str | None:
    value = _field(payload, key)
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError(f"Update plan field {key!r} must be a string or null.")
    return _validated_text(value, key=key, allow_empty=False)


def _bool_field(payload: dict[object, object], key: str) -> bool:
    value = _field(payload, key)
    if not isinstance(value, bool):
        raise ValueError(f"Update plan field {key!r} must be a boolean.")
    return value


def _dict_list_field(payload: dict[object, object], key: str) -> list[dict[object, object]]:
    value = _field(payload, key)
    if not isinstance(value, list) or not all(isinstance(item, dict) for item in value):
        raise ValueError(f"Update plan field {key!r} must be a list of objects.")
    return list(value)


def _enum_field(enum_type, payload: dict[object, object], key: str):  # noqa: ANN001, ANN202
    value = _string_field(payload, key)
    try:
        return enum_type(value)
    except ValueError as exc:
        raise ValueError(f"Update plan field {key!r} has an unknown value.") from exc


def _plan_item(payload: dict[object, object]) -> UpdatePlanItem:
    if set(payload) != PLAN_ITEM_FIELDS:
        raise ValueError("Update plan item contains missing or unsupported fields.")
    item = UpdatePlanItem(
        source=_enum_field(UpdateSource, payload, "source"),
        target_id=_string_field(payload, "target_id"),
        action=_enum_field(UpdatePlanAction, payload, "action"),
        installation_scope=_optional_string_field(payload, "installation_scope"),
        package_name=_optional_string_field(payload, "package_name"),
        package_kind=_optional_string_field(payload, "package_kind"),
        plugin_id=_optional_string_field(payload, "plugin_id"),
        package_base=_optional_string_field(payload, "package_base"),
        expected_version=_optional_string_field(payload, "expected_version"),
        current_version=_optional_string_field(payload, "current_version"),
        dynamic_version=_bool_field(payload, "dynamic_version"),
    )
    _validate_plan_item_semantics(item)
    return item


def _validated_text(value: str, *, key: str, allow_empty: bool) -> str:
    if len(value) > 4096 or (not allow_empty and not value):
        raise ValueError(f"Update plan field {key!r} has an invalid length.")
    if any(unicodedata.category(character) in {"Cc", "Cf", "Cs"} for character in value):
        raise ValueError(f"Update plan field {key!r} contains unsafe characters.")
    return value


def _validate_plan_item_semantics(item: UpdatePlanItem) -> None:
    if item.action is UpdatePlanAction.CLEANUP:
        if item.source is not UpdateSource.FLATPAK:
            raise ValueError("Only Flatpak cleanup actions are supported.")
        if item.installation_scope not in {"system", "user"}:
            raise ValueError("Flatpak cleanup scope must be system or user.")
        if item.target_id != item.installation_scope or any(
            value is not None
            for value in (
                item.package_name,
                item.package_kind,
                item.plugin_id,
                item.package_base,
                item.expected_version,
                item.current_version,
            )
        ) or item.dynamic_version:
            raise ValueError("Flatpak cleanup item contains inconsistent fields.")
        return
    if item.source is UpdateSource.FLATPAK:
        if item.installation_scope not in {"system", "user"}:
            raise ValueError("Flatpak installation scope must be system or user.")
        if (
            item.action is UpdatePlanAction.UPDATE
            and (
                item.target_id.startswith("-")
                or not FLATPAK_REF_RE.fullmatch(item.target_id)
                or ".." in item.target_id.split("/")
            )
        ):
            raise ValueError("Flatpak update reference is invalid.")
    elif item.installation_scope is not None:
        raise ValueError("Installation scope is only valid for Flatpak items.")
    if item.source is UpdateSource.AUR:
        if not all((item.package_name, item.package_base, item.expected_version)):
            raise ValueError("AUR update items require package name, base, and version.")
        if not AUR_PACKAGE_NAME_RE.fullmatch(item.package_name or ""):
            raise ValueError("AUR package name is invalid.")
        if not AUR_PACKAGE_NAME_RE.fullmatch(item.package_base or ""):
            raise ValueError("AUR package base is invalid.")
        if item.target_id != item.package_name:
            raise ValueError("AUR target id must match its package name.")
        if item.dynamic_version and item.expected_version != "latest-commit":
            raise ValueError("Dynamic AUR updates require the latest-commit marker.")
        if item.dynamic_version and not item.current_version:
            raise ValueError("Dynamic AUR updates require the current installed version.")
    elif item.current_version is not None or item.dynamic_version:
        raise ValueError("Dynamic and current versions are only valid for AUR items.")
    if item.source in {
        UpdateSource.SYSTEM,
        UpdateSource.FLATPAK,
        UpdateSource.FIRMWARE,
    } and item.action is UpdatePlanAction.UPDATE and not item.expected_version:
        raise ValueError("Update items require an expected version.")
    if item.source is UpdateSource.PLASMA_WIDGET and not all(
        (item.package_name, item.package_kind, item.expected_version)
    ):
        raise ValueError(
            "KDE Store update items require package name, type, and expected version."
        )
