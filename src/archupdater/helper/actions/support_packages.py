from __future__ import annotations

import re

from PySide6.QtCore import QCoreApplication

from archupdater.helper.actions.common import (
    EmitEvent,
    EmitLog,
    PACMAN_PATH,
    require_pacman,
    stream_command,
)
from archupdater.application.helper_protocol import HelperEventType


PACKAGE_NAME_RE = re.compile(r"^[A-Za-z0-9@._+-]+$")
MANAGED_SUPPORT_PACKAGES = frozenset({"flatpak", "fwupd"})


class SupportPackageValidationError(ValueError):
    pass


def validate_package_list(raw_packages: object, field_name: str) -> list[str]:
    if not isinstance(raw_packages, list):
        raise SupportPackageValidationError(
            QCoreApplication.translate(
                "PrivilegedHelper",
                "`{field_name}` must be an array.",
            ).format(field_name=field_name)
        )
    if not raw_packages:
        raise SupportPackageValidationError(
            QCoreApplication.translate(
                "PrivilegedHelper",
                "`{field_name}` must contain at least one package.",
            ).format(field_name=field_name)
        )

    validated: list[str] = []
    for package in raw_packages:
        if (
            not isinstance(package, str)
            or package.startswith("-")
            or not PACKAGE_NAME_RE.fullmatch(package)
            or package not in MANAGED_SUPPORT_PACKAGES
        ):
            raise SupportPackageValidationError(
                QCoreApplication.translate(
                    "PrivilegedHelper",
                    "Invalid package name: {package}",
                ).format(package=repr(package))
            )
        if package not in validated:
            validated.append(package)
    return validated


def install_support_packages(
    package_names: list[str],
    *,
    emit_event: EmitEvent,
    emit_log: EmitLog,
) -> int:
    if not require_pacman(emit_event=emit_event, emit_log=emit_log):
        return 2

    emit_event(HelperEventType.STATUS, value="running")
    emit_log(
        QCoreApplication.translate(
            "PrivilegedHelper",
            "Installing support packages: {packages}",
        ).format(packages=", ".join(package_names))
    )

    return_code = _install_repo_packages(package_names, emit_log=emit_log)
    if return_code != 0:
        emit_event(
            HelperEventType.COMPLETED,
            success=False,
            message=QCoreApplication.translate(
                "PrivilegedHelper",
                "pacman exited with code {code}.",
            ).format(code=return_code),
        )
        return 3

    emit_event(
        HelperEventType.COMPLETED,
        success=True,
        message=QCoreApplication.translate(
            "PrivilegedHelper",
            "Optional source support installed successfully.",
        ),
    )
    return 0


def _install_repo_packages(package_names: list[str], *, emit_log: EmitLog) -> int:
    command = [
        str(PACMAN_PATH),
        "-Syu",
        "--noconfirm",
        "--needed",
        "--color",
        "never",
        "--",
        *package_names,
    ]
    return_code, _output = stream_command(command, emit_log=emit_log)
    return return_code


def remove_support_packages(
    package_names: list[str],
    *,
    emit_event: EmitEvent,
    emit_log: EmitLog,
) -> int:
    if not require_pacman(emit_event=emit_event, emit_log=emit_log):
        return 2

    emit_event(HelperEventType.STATUS, value="running")
    emit_log(
        QCoreApplication.translate(
            "PrivilegedHelper",
            "Removing support packages: {packages}",
        ).format(packages=", ".join(package_names))
    )
    command = [
        str(PACMAN_PATH),
        "-R",
        "--noconfirm",
        "--color",
        "never",
        "--",
        *package_names,
    ]
    return_code, _ = stream_command(command, emit_log=emit_log)
    if return_code == 0:
        emit_event(
            HelperEventType.COMPLETED,
            success=True,
            message=QCoreApplication.translate(
                "PrivilegedHelper",
                "Optional source support removed successfully.",
            ),
        )
        return 0

    emit_event(
        HelperEventType.COMPLETED,
        success=False,
        message=QCoreApplication.translate(
            "PrivilegedHelper",
            "pacman exited with code {code}.",
        ).format(code=return_code),
    )
    return 3
