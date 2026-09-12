from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import QCoreApplication
from PySide6.QtWidgets import QCheckBox, QMessageBox, QWidget

from archupdater.domain.enums import PreflightSeverity, UpdateSource
from archupdater.domain.preflight import PreflightIssue
from archupdater.domain.update_plan import UpdatePlan


def confirm_preflight_issues(
    parent: QWidget,
    issues: list[PreflightIssue],
) -> bool:
    if not issues:
        return True

    blocking = [issue for issue in issues if issue.severity is PreflightSeverity.BLOCKING]
    if blocking:
        QMessageBox.warning(
            parent,
            QCoreApplication.translate("MainWindow", "Update Cannot Start"),
            preflight_message(
                QCoreApplication.translate(
                    "MainWindow", "Resolve these problems before installing updates."
                ),
                blocking,
            ),
        )
        return False

    answer = QMessageBox.warning(
        parent,
        QCoreApplication.translate("MainWindow", "Preflight Warnings"),
        preflight_message(
            QCoreApplication.translate(
                "MainWindow", "ArchUpdater found warnings before installing updates."
            ),
            issues,
        ),
        QMessageBox.StandardButton.Cancel | QMessageBox.StandardButton.Ok,
        QMessageBox.StandardButton.Ok,
    )
    return answer is QMessageBox.StandardButton.Ok


def preflight_message(heading: str, issues: list[PreflightIssue]) -> str:
    lines = [heading, ""]
    for issue in issues:
        lines.append(f"{issue.title}: {issue.message}")
        lines.extend(f"  {detail}" for detail in issue.details)
    return "\n".join(lines)


def ask_flatpak_cleanup_scopes(
    parent: QWidget,
    plan: UpdatePlan,
    *,
    cleanup_enabled: bool,
    cleanup_preference_set: bool = True,
    save_cleanup_preference: Callable[[bool], None] | None = None,
) -> list[str]:
    if not plan.update_items():
        return []

    scopes = sorted(
        {
            item.installation_scope or "system"
            for item in plan.update_items()
            if item.source is UpdateSource.FLATPAK
        }
    )
    if not scopes:
        return []
    if cleanup_preference_set:
        return scopes if cleanup_enabled else []

    box = QMessageBox(parent)
    box.setIcon(QMessageBox.Icon.Question)
    box.setWindowTitle(QCoreApplication.translate("MainWindow", "Clean Up Flatpak Runtimes"))
    box.setText(
        QCoreApplication.translate(
            "MainWindow",
            "After installing the selected Flatpak updates, remove unused Flatpak runtimes for the selected installation scopes?",
        )
    )
    remember_checkbox = QCheckBox(QCoreApplication.translate("MainWindow", "Remember this choice"))
    remember_checkbox.setChecked(True)
    box.setCheckBox(remember_checkbox)
    box.setStandardButtons(QMessageBox.StandardButton.No | QMessageBox.StandardButton.Yes)
    box.setDefaultButton(QMessageBox.StandardButton.No)
    answer = box.exec()
    cleanup_requested = answer is QMessageBox.StandardButton.Yes
    if remember_checkbox.isChecked() and save_cleanup_preference is not None:
        save_cleanup_preference(cleanup_requested)
    return scopes if cleanup_requested else []
