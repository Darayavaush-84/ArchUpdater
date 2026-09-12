from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import QCoreApplication, Qt
from PySide6.QtWidgets import (
    QHBoxLayout,
    QMainWindow,
    QSplitter,
    QStyle,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from archupdater.presentation.widgets.action_bar import ActionBarWidget
from archupdater.presentation.widgets.package_details_panel import PackageDetailsPanel
from archupdater.presentation.widgets.package_updates_widget import PackageUpdatesWidget
from archupdater.presentation.widgets.status_header import StatusHeaderWidget


@dataclass(frozen=True, slots=True)
class MainWindowUi:
    header_widget: StatusHeaderWidget
    package_updates_widget: PackageUpdatesWidget
    details_panel: PackageDetailsPanel
    side_panel: QWidget
    close_details_button: QToolButton
    action_bar: ActionBarWidget


def build_main_window_ui(parent: QMainWindow) -> MainWindowUi:
    central = QWidget(parent)
    central.setObjectName("central")
    parent.setCentralWidget(central)
    root_layout = QVBoxLayout(central)
    root_layout.setContentsMargins(24, 20, 24, 20)
    root_layout.setSpacing(18)

    header_widget = StatusHeaderWidget()
    package_updates_widget = PackageUpdatesWidget()
    details_panel = PackageDetailsPanel()
    side_panel = QWidget()
    side_panel.setMinimumWidth(320)
    side_layout = QVBoxLayout(side_panel)
    side_layout.setContentsMargins(0, 0, 0, 0)
    side_layout.setSpacing(4)
    close_row = QHBoxLayout()
    close_row.addStretch(1)
    close_details_button = QToolButton()
    close_details_button.setIcon(
        parent.style().standardIcon(QStyle.StandardPixmap.SP_TitleBarCloseButton)
    )
    close_details_button.setToolTip(QCoreApplication.translate("MainWindow", "Close"))
    close_details_button.setAccessibleName(QCoreApplication.translate("MainWindow", "Close"))
    close_row.addWidget(close_details_button)
    side_layout.addLayout(close_row)
    side_layout.addWidget(details_panel, stretch=1)

    splitter = QSplitter(Qt.Orientation.Horizontal)
    splitter.setObjectName("mainContentSplitter")
    splitter.setChildrenCollapsible(False)
    splitter.addWidget(package_updates_widget)
    splitter.addWidget(side_panel)
    splitter.setStretchFactor(0, 7)
    splitter.setStretchFactor(1, 3)
    splitter.setSizes([800, 360])
    side_panel.hide()
    action_bar = ActionBarWidget()

    root_layout.addWidget(header_widget)
    root_layout.addWidget(splitter, stretch=1)
    root_layout.addWidget(action_bar)
    return MainWindowUi(
        header_widget=header_widget,
        package_updates_widget=package_updates_widget,
        details_panel=details_panel,
        side_panel=side_panel,
        close_details_button=close_details_button,
        action_bar=action_bar,
    )
