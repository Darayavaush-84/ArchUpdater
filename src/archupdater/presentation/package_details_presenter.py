from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from PySide6.QtWidgets import QStyle

from archupdater.domain.enums import OperationState
from archupdater.domain.packages import PackageUpdate
from archupdater.presentation.main_window.logic import details_placeholder_text, source_texts
from archupdater.presentation.widgets.package_details_panel import PackageDetailsPanel


Translate = Callable[[str], str]


@dataclass(slots=True)
class PackageDetailsPresenter:
    panel: PackageDetailsPanel
    style: QStyle
    translate: Translate

    def show_package(self, package: PackageUpdate) -> None:
        self.panel.set_package(
            package,
            source_text=source_texts()[package.source],
            unavailable_text=self.translate("Not available"),
            no_description_text=self.translate("No description provided."),
        )

    def show_empty_state(
        self,
        *,
        current_state: OperationState,
        has_packages: bool,
        failure_message: str = "",
    ) -> None:
        text = details_placeholder_text(
            current_state=current_state,
            has_packages=has_packages,
            failure_message=failure_message,
        )

        title = self.translate("Package Details")
        message = text
        icon = QStyle.StandardPixmap.SP_FileDialogDetailedView

        if current_state is OperationState.CHECKING:
            title = text
            message = ""
            icon = QStyle.StandardPixmap.SP_BrowserReload
        elif current_state is OperationState.ERROR and not has_packages:
            icon = QStyle.StandardPixmap.SP_MessageBoxWarning
        elif current_state is OperationState.COMPLETED and not has_packages:
            title, _, message = text.partition("\n")
            icon = QStyle.StandardPixmap.SP_DialogApplyButton

        self.panel.show_placeholder(title=title, text=message, icon=icon)
