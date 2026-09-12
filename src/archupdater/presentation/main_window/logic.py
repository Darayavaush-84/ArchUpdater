from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import QCoreApplication

from archupdater.domain.enums import OperationState, UpdateSource
from archupdater.domain.packages import PackageUpdate
from archupdater.domain.update_plan import UpdatePlan, UpdatePlanItem
from archupdater.application.update_sources.descriptors import source_texts as build_source_texts
from archupdater.application.update_session.protocol import BatchStep, step_from_running_status


Translate = Callable[[str], str]

def source_texts() -> dict[UpdateSource, str]:
    return build_source_texts(lambda text: QCoreApplication.translate("MainWindowLogic", text))


def system_status_summary(
    update_count: int,
    *,
    has_warnings: bool,
) -> str:
    if update_count <= 0:
        if has_warnings:
            return QCoreApplication.translate("MainWindowLogic", "Checked with Warnings")
        return QCoreApplication.translate("MainWindowLogic", "Up to Date")
    if update_count == 1:
        return QCoreApplication.translate("MainWindowLogic", "1 Update Available")
    return QCoreApplication.translate("MainWindowLogic", "{count} Updates Available").format(
        count=update_count
    )


def check_completion_message(
    *,
    package_count: int,
    warning_count: int,
) -> str:
    if package_count > 0:
        return QCoreApplication.translate("MainWindowLogic", "Updates are ready.")
    if warning_count > 0:
        return QCoreApplication.translate("MainWindowLogic", "Refresh completed with warnings.")
    return QCoreApplication.translate("MainWindowLogic", "Everything is up to date.")


def details_placeholder_text(
    *,
    current_state: OperationState,
    has_packages: bool,
    failure_message: str = "",
) -> str:
    if current_state is OperationState.CHECKING:
        return QCoreApplication.translate("MainWindowLogic", "Checking for updates...")
    if current_state is OperationState.ERROR and not has_packages:
        text = QCoreApplication.translate(
            "MainWindowLogic",
            "Details are unavailable because the last refresh did not complete.",
        )
        failure_message = failure_message.strip()
        if failure_message:
            text = "\n\n".join(
                (
                    text,
                    QCoreApplication.translate(
                        "MainWindowLogic",
                        "Error: {message}",
                    ).format(message=failure_message),
                )
            )
        return text
    if current_state is OperationState.COMPLETED and not has_packages:
        return QCoreApplication.translate(
            "MainWindowLogic",
            "Your system is up to date.\nNew updates will appear here after the next refresh.",
        )
    return QCoreApplication.translate("MainWindowLogic", "Select an update to view details")


def update_status_messages(
    value: str,
    *,
    translate: Translate,
) -> tuple[str, str] | None:
    if value == "starting_integrated":
        return (
            translate("Starting update session..."),
            translate("Installing updates"),
        )

    running_messages = {
        BatchStep.SYSTEM: (
            translate("Running pacman update..."),
            translate("Updating pacman packages"),
        ),
        BatchStep.AUR: (
            translate("Running AUR update..."),
            translate("Updating AUR packages"),
        ),
        BatchStep.FLATPAK: (
            translate("Running Flatpak update..."),
            translate("Updating Flatpak apps"),
        ),
        BatchStep.FIRMWARE: (
            translate("Running firmware update..."),
            translate("Updating firmware"),
        ),
        BatchStep.PLASMA_WIDGET: (
            translate("Running KDE Store add-on update..."),
            translate("Updating KDE Store add-ons"),
        ),
    }
    return running_messages.get(step_from_running_status(value))


def build_update_plan(packages: list[PackageUpdate]) -> UpdatePlan:
    selected_system_transaction = any(
        package.source is UpdateSource.SYSTEM
        and package.selected
        and not package.blocked_by_config
        for package in packages
    )
    return UpdatePlan(
        items=[
            UpdatePlanItem.from_package(package)
            for package in packages
            if (
                package.source is UpdateSource.SYSTEM
                and selected_system_transaction
                and not package.blocked_by_config
            )
            or (package.source is not UpdateSource.SYSTEM and package.selected)
        ]
    )
