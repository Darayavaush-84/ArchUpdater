from __future__ import annotations

import re
from pathlib import Path

from PySide6.QtCore import QCoreApplication

FLATPAK_REF_RE = re.compile(r"^[A-Za-z0-9._/-]+$")


FIRMWARE_DEVICE_ID_RE = re.compile(r"^[A-Za-z0-9@._:+/{}/-]+$")


class PrivilegedUpdateValidationError(ValueError):
    pass


def validate_flatpak_refs(raw_refs: object) -> list[str]:
    return _validate_string_list(
        raw_refs,
        field_name="refs",
        pattern=FLATPAK_REF_RE,
        allow_empty=False,
    )


def validate_firmware_device_id(raw_device_id: object) -> str:
    if not isinstance(raw_device_id, str):
        raise PrivilegedUpdateValidationError(
            QCoreApplication.translate("PrivilegedHelper", "`device_id` must be a string.")
        )
    device_id = raw_device_id.strip()
    if (
        not device_id
        or len(device_id) > 256
        or device_id.startswith("-")
        or "\x00" in device_id
        or not FIRMWARE_DEVICE_ID_RE.fullmatch(device_id)
    ):
        raise PrivilegedUpdateValidationError(
            QCoreApplication.translate(
                "PrivilegedHelper",
                "Invalid firmware device id: {device_id}",
            ).format(device_id=repr(raw_device_id))
        )
    return device_id


def _validate_string_list(
    raw_values: object,
    *,
    field_name: str,
    pattern: re.Pattern[str],
    allow_empty: bool,
) -> list[str]:
    if not isinstance(raw_values, list):
        raise PrivilegedUpdateValidationError(
            QCoreApplication.translate(
                "PrivilegedHelper",
                "`{field_name}` must be an array.",
            ).format(field_name=field_name)
        )
    if not raw_values and not allow_empty:
        raise PrivilegedUpdateValidationError(
            QCoreApplication.translate(
                "PrivilegedHelper",
                "`{field_name}` must contain at least one item.",
            ).format(field_name=field_name)
        )

    validated: list[str] = []
    for raw_value in raw_values:
        if not isinstance(raw_value, str):
            raise PrivilegedUpdateValidationError(
                QCoreApplication.translate(
                    "PrivilegedHelper",
                    "Invalid `{field_name}` item: {value}",
                ).format(field_name=field_name, value=repr(raw_value))
            )
        value = raw_value.strip()
        if (
            not value
            or len(value) > 512
            or value.startswith("-")
            or "\x00" in value
            or not pattern.fullmatch(value)
            or ".." in Path(value).parts
        ):
            raise PrivilegedUpdateValidationError(
                QCoreApplication.translate(
                    "PrivilegedHelper",
                    "Invalid `{field_name}` item: {value}",
                ).format(field_name=field_name, value=repr(raw_value))
            )
        if value not in validated:
            validated.append(value)
    return validated
