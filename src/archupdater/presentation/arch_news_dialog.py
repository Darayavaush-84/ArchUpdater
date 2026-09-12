from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from PySide6.QtCore import Qt
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QLabel,
    QPushButton,
    QStyle,
    QTabWidget,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from archupdater.domain.arch_news import ArchNewsItem


@dataclass(frozen=True, slots=True)
class ArchNewsDialogResult:
    accepted: bool
    deleted_read_ids: set[str]


def show_arch_news_dialog(
    parent: QWidget,
    items: Sequence[ArchNewsItem],
    *,
    intro: str,
    ok_text: str,
    cancel_text: str,
    include_cancel: bool,
    enable_ok: bool,
) -> ArchNewsDialogResult:
    dialog = QDialog(parent)
    dialog.setWindowTitle(parent.tr("Arch Linux News"))
    dialog.resize(780, 420)
    deleted_read_ids: set[str] = set()

    layout = QVBoxLayout(dialog)
    layout.setContentsMargins(22, 22, 22, 22)
    layout.setSpacing(12)

    intro_label = QLabel(intro)
    intro_label.setWordWrap(True)
    layout.addWidget(intro_label)

    unread_items = [item for item in items if not item.read]
    read_items = [item for item in items if item.read]

    tabs = QTabWidget()
    tabs.addTab(
        _news_tree(
            parent,
            unread_items,
            empty_text=parent.tr("No unread Arch Linux news."),
        ),
        parent.tr("New ({count})").format(count=len(unread_items)),
    )
    read_tree = _news_tree(
            parent,
            read_items,
            empty_text=parent.tr("No read Arch Linux news."),
            checkable=bool(read_items),
        )
    tabs.addTab(
        read_tree,
        parent.tr("Read ({count})").format(count=len(read_items)),
    )
    layout.addWidget(tabs)

    buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok)
    delete_button = QPushButton(parent.tr("Delete Selected Read"))
    delete_button.setIcon(
        dialog.style().standardIcon(QStyle.StandardPixmap.SP_TrashIcon)
        if hasattr(QStyle.StandardPixmap, "SP_TrashIcon")
        else QIcon()
    )
    delete_button.setEnabled(False)
    buttons.addButton(delete_button, QDialogButtonBox.ButtonRole.ActionRole)
    if include_cancel:
        buttons.addButton(QDialogButtonBox.StandardButton.Cancel)
    else:
        buttons.addButton(QDialogButtonBox.StandardButton.Close)
    buttons.button(QDialogButtonBox.StandardButton.Ok).setText(ok_text)
    buttons.button(QDialogButtonBox.StandardButton.Ok).setEnabled(enable_ok)

    cancel_button = buttons.button(QDialogButtonBox.StandardButton.Cancel)
    if cancel_button is not None:
        cancel_button.setText(cancel_text)
    close_button = buttons.button(QDialogButtonBox.StandardButton.Close)
    if close_button is not None:
        close_button.setText(cancel_text)

    def selected_read_rows() -> list[QTreeWidgetItem]:
        rows: list[QTreeWidgetItem] = []
        for index in range(read_tree.topLevelItemCount()):
            row = read_tree.topLevelItem(index)
            if row.data(0, Qt.ItemDataRole.UserRole) and row.checkState(0) == Qt.CheckState.Checked:
                rows.append(row)
        return rows

    def refresh_delete_button() -> None:
        delete_button.setEnabled(bool(selected_read_rows()))

    def delete_selected_read_rows() -> None:
        for row in selected_read_rows():
            item_id = str(row.data(0, Qt.ItemDataRole.UserRole) or "").strip()
            if item_id:
                deleted_read_ids.add(item_id)
            index = read_tree.indexOfTopLevelItem(row)
            if index >= 0:
                read_tree.takeTopLevelItem(index)
        if read_tree.topLevelItemCount() == 0:
            empty_row = QTreeWidgetItem([parent.tr("No read Arch Linux news."), "", ""])
            empty_row.setDisabled(True)
            read_tree.addTopLevelItem(empty_row)
        refresh_delete_button()

    read_tree.itemChanged.connect(lambda _item, _column: refresh_delete_button())
    delete_button.clicked.connect(delete_selected_read_rows)
    buttons.accepted.connect(dialog.accept)
    buttons.rejected.connect(dialog.reject)
    layout.addWidget(buttons)

    return ArchNewsDialogResult(
        accepted=dialog.exec() == QDialog.DialogCode.Accepted,
        deleted_read_ids=deleted_read_ids,
    )


def _news_tree(
    parent: QWidget,
    items: Sequence[ArchNewsItem],
    *,
    empty_text: str,
    checkable: bool = False,
) -> QTreeWidget:
    tree = QTreeWidget()
    tree.setColumnCount(3)
    tree.setHeaderLabels([parent.tr("News"), parent.tr("Date"), parent.tr("Summary")])
    tree.setRootIsDecorated(False)
    tree.setAlternatingRowColors(True)
    tree.setMinimumHeight(240)

    if not items:
        row = QTreeWidgetItem([empty_text, "", ""])
        row.setDisabled(True)
        tree.addTopLevelItem(row)
        tree.resizeColumnToContents(0)
        return tree

    for item in items:
        date_text = item.published_at.strftime("%Y-%m-%d") if item.published_at else ""
        row = QTreeWidgetItem([item.title, date_text, item.summary])
        row.setData(0, Qt.ItemDataRole.UserRole, item.item_id)
        if checkable:
            row.setFlags(row.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            row.setCheckState(0, Qt.CheckState.Unchecked)
        row.setToolTip(0, item.summary or item.url or item.title)
        row.setToolTip(2, item.url or item.summary or item.title)
        tree.addTopLevelItem(row)
    tree.resizeColumnToContents(0)
    tree.resizeColumnToContents(1)
    return tree
