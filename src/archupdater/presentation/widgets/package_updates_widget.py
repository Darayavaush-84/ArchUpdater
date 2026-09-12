from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QIcon, QPainter, QPalette, QPen, QPixmap
from PySide6.QtWidgets import (
    QAbstractItemView,
    QFrame,
    QGridLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPushButton,
    QSizePolicy,
    QStackedWidget,
    QStyledItemDelegate,
    QStyle,
    QStyleOptionHeader,
    QStyleOptionViewItem,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from archupdater.domain.enums import UpdateSource
from archupdater.domain.packages import PackageUpdate
from archupdater.application.update_sources.descriptors import source_descriptors
from archupdater.presentation.package_updates_view_model import (
    PackageUpdateRowView,
    build_package_update_row_view,
    package_matches_filter,
    source_filter_title,
)
from archupdater.presentation.package_icons import PackageIconResolver
from archupdater.resources.assets import illustration_path


def _mix_color(a: QColor, b: QColor, ratio: float) -> QColor:
    ratio = max(0.0, min(1.0, ratio))
    inv = 1.0 - ratio
    return QColor(
        round(a.red() * inv + b.red() * ratio),
        round(a.green() * inv + b.green() * ratio),
        round(a.blue() * inv + b.blue() * ratio),
        round(a.alpha() * inv + b.alpha() * ratio),
    )


class VersionSplitDelegate(QStyledItemDelegate):
    OLD_VERSION_ROLE = Qt.ItemDataRole.UserRole + 10
    NEW_VERSION_ROLE = Qt.ItemDataRole.UserRole + 11

    def paint(self, painter: QPainter, option, index) -> None:  # type: ignore[override]
        old_version = index.data(self.OLD_VERSION_ROLE)
        new_version = index.data(self.NEW_VERSION_ROLE)
        if not old_version or not new_version:
            super().paint(painter, option, index)
            return

        style = option.widget.style() if option.widget is not None else None
        if style is None:
            super().paint(painter, option, index)
            return

        opt = QStyleOptionViewItem(option)
        self.initStyleOption(opt, index)
        opt.text = ""
        style.drawControl(QStyle.ControlElement.CE_ItemViewItem, opt, painter, option.widget)

        painter.save()
        text_rect = style.subElementRect(
            QStyle.SubElement.SE_ItemViewItemText,
            opt,
            option.widget,
        ).adjusted(0, 0, 0, 0)
        painter.setClipRect(text_rect)

        palette = opt.palette
        selected = bool(opt.state & QStyle.StateFlag.State_Selected)
        colors = self._version_colors(palette, selected)
        metrics = painter.fontMetrics()
        arrow = " -> "

        old_text = str(old_version)
        new_text = str(new_version)
        old_width = metrics.horizontalAdvance(old_text)
        arrow_width = metrics.horizontalAdvance(arrow)
        total_width = old_width + arrow_width + metrics.horizontalAdvance(new_text)

        draw_rect = text_rect
        if total_width < text_rect.width():
            draw_rect = text_rect.adjusted(0, 0, -(text_rect.width() - total_width), 0)

        x = draw_rect.left()
        baseline = draw_rect.top() + ((draw_rect.height() + metrics.ascent() - metrics.descent()) // 2)

        painter.setPen(colors["old"])
        painter.drawText(x, baseline, old_text)
        x += old_width

        painter.setPen(colors["arrow"])
        painter.drawText(x, baseline, arrow)
        x += arrow_width

        painter.setPen(colors["new"])
        painter.drawText(x, baseline, new_text)
        painter.restore()

    def _version_colors(self, palette: QPalette, selected: bool) -> dict[str, QColor]:
        if selected:
            highlighted = palette.color(QPalette.ColorRole.HighlightedText)
            return {
                "old": _mix_color(highlighted, QColor("#f0c97a"), 0.35),
                "arrow": highlighted,
                "new": _mix_color(highlighted, QColor("#8cd8a4"), 0.45),
            }

        text = palette.color(QPalette.ColorRole.Text)
        return {
            "old": _mix_color(QColor("#d39b46"), text, 0.28),
            "arrow": text,
            "new": _mix_color(QColor("#63bf82"), text, 0.18),
        }


class PackageNameBadgeDelegate(QStyledItemDelegate):
    BLOCKED_ROLE = Qt.ItemDataRole.UserRole + 20
    BLOCKED_REASON_ROLE = Qt.ItemDataRole.UserRole + 21

    def paint(self, painter: QPainter, option, index) -> None:  # type: ignore[override]
        blocked = bool(index.data(self.BLOCKED_ROLE))
        if not blocked:
            super().paint(painter, option, index)
            self._paint_selection_checkbox(painter, option, index)
            return

        style = option.widget.style() if option.widget is not None else None
        if style is None:
            super().paint(painter, option, index)
            self._paint_selection_checkbox(painter, option, index)
            return

        opt = QStyleOptionViewItem(option)
        self.initStyleOption(opt, index)
        text = opt.text
        opt.text = ""
        style.drawControl(QStyle.ControlElement.CE_ItemViewItem, opt, painter, option.widget)

        painter.save()
        text_rect = style.subElementRect(
            QStyle.SubElement.SE_ItemViewItemText,
            opt,
            option.widget,
        ).adjusted(0, 0, 0, 0)
        painter.setClipRect(text_rect)

        metrics = painter.fontMetrics()
        badge_text = self.tr("Ignored")
        badge_padding_x = 7
        badge_padding_y = 3
        gap = 10
        badge_text_width = metrics.horizontalAdvance(badge_text)
        badge_width = badge_text_width + (badge_padding_x * 2)
        badge_height = metrics.height() + (badge_padding_y * 2)
        available_width = max(0, text_rect.width() - badge_width - gap)
        package_text = metrics.elidedText(text, Qt.TextElideMode.ElideRight, available_width)

        selected = bool(opt.state & QStyle.StateFlag.State_Selected)
        palette = opt.palette
        text_color = palette.color(
            QPalette.ColorRole.HighlightedText if selected else QPalette.ColorRole.Text
        )
        badge_bg = QColor("#d0a248") if selected else QColor("#f0c97a")
        badge_fg = QColor("#2f2410") if not selected else QColor("#2a1e08")
        badge_border = QColor("#c08d2f")

        baseline = text_rect.top() + ((text_rect.height() + metrics.ascent() - metrics.descent()) // 2)
        x = text_rect.left()

        painter.setPen(text_color)
        painter.drawText(x, baseline, package_text)
        x += min(metrics.horizontalAdvance(package_text), available_width) + gap

        badge_top = text_rect.top() + max(0, (text_rect.height() - badge_height) // 2)
        badge_rect = text_rect.adjusted(x - text_rect.left(), badge_top - text_rect.top(), 0, 0)
        badge_rect.setWidth(badge_width)
        badge_rect.setHeight(badge_height)

        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setPen(QPen(badge_border))
        painter.setBrush(badge_bg)
        painter.drawRoundedRect(badge_rect, 9, 9)
        painter.setPen(badge_fg)
        painter.drawText(
            badge_rect.adjusted(badge_padding_x, badge_padding_y, -badge_padding_x, -badge_padding_y),
            Qt.AlignmentFlag.AlignCenter,
            badge_text,
        )
        painter.restore()
        self._paint_selection_checkbox(painter, option, index)

    def _paint_selection_checkbox(self, painter: QPainter, option, index) -> None:  # noqa: ANN001
        check_state = index.data(Qt.ItemDataRole.CheckStateRole)
        if check_state is None:
            return

        style = option.widget.style() if option.widget is not None else None
        if style is None:
            return

        opt = QStyleOptionViewItem(option)
        self.initStyleOption(opt, index)
        indicator_rect = style.subElementRect(
            QStyle.SubElement.SE_ItemViewItemCheckIndicator,
            opt,
            option.widget,
        ).adjusted(1, 1, -1, -1)
        if indicator_rect.isEmpty():
            return
        indicator_size = min(18, indicator_rect.width(), indicator_rect.height())
        indicator_rect.setWidth(indicator_size)
        indicator_rect.setHeight(indicator_size)
        indicator_rect.moveTop(option.rect.top() + (option.rect.height() - indicator_size) // 2)

        checked = check_state == Qt.CheckState.Checked or check_state == Qt.CheckState.Checked.value
        enabled = bool(opt.state & QStyle.StateFlag.State_Enabled)
        selected = bool(opt.state & QStyle.StateFlag.State_Selected)
        palette = opt.palette

        green = QColor("#22c55e")
        green_border = QColor("#16a34a")
        muted_border = _mix_color(
            palette.color(QPalette.ColorRole.HighlightedText if selected else QPalette.ColorRole.Text),
            palette.color(QPalette.ColorRole.Window),
            0.42,
        )
        fill = green if checked else palette.color(QPalette.ColorRole.Base)
        border = green_border if checked else muted_border
        if not enabled:
            fill = _mix_color(fill, palette.color(QPalette.ColorRole.Window), 0.55)
            border = _mix_color(border, palette.color(QPalette.ColorRole.Window), 0.55)

        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setPen(QPen(border, 1.4))
        painter.setBrush(fill)
        painter.drawRoundedRect(indicator_rect, 4, 4)

        if checked:
            tick_color = QColor("#ffffff")
            if not enabled:
                tick_color = _mix_color(tick_color, palette.color(QPalette.ColorRole.Window), 0.35)
            tick_pen = QPen(tick_color, 2.0)
            tick_pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            tick_pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
            painter.setPen(tick_pen)
            painter.drawLine(
                indicator_rect.left() + 4,
                indicator_rect.center().y(),
                indicator_rect.left() + 7,
                indicator_rect.bottom() - 4,
            )
            painter.drawLine(
                indicator_rect.left() + 7,
                indicator_rect.bottom() - 4,
                indicator_rect.right() - 4,
                indicator_rect.top() + 4,
            )
        painter.restore()


class PackageUpdateTreeItem(QTreeWidgetItem):
    def __lt__(self, other: QTreeWidgetItem) -> bool:
        tree = self.treeWidget()
        column = tree.sortColumn() if tree is not None else 0
        left = self.text(column).casefold()
        right = other.text(column).casefold()
        if left == right:
            return self.text(0).casefold() < other.text(0).casefold()
        return left < right


class PackageSortHeaderView(QHeaderView):
    _ARROW_LENGTH = 11
    _ARROW_GAP = 5
    _ARROW_WIDTH = 7
    _HEADER_TEXT_PADDING = 8

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(Qt.Orientation.Horizontal, parent)
        self._package_text_padding = 68

    def set_package_text_padding(self, padding: int) -> None:
        self._package_text_padding = max(self._HEADER_TEXT_PADDING, padding)
        self.viewport().update()

    def paintSection(self, painter: QPainter, rect, logical_index: int) -> None:  # type: ignore[override]
        option = QStyleOptionHeader()
        self.initStyleOption(option)
        option.rect = rect
        option.section = logical_index
        option.text = ""
        self.style().drawControl(QStyle.ControlElement.CE_Header, option, painter, self)

        if rect.isEmpty():
            return
        text = self.model().headerData(
            logical_index,
            self.orientation(),
            Qt.ItemDataRole.DisplayRole,
        )
        if not text:
            return

        painter.save()
        palette = option.palette
        text_color = palette.color(QPalette.ColorRole.Text)
        text_left_padding = (
            self._package_text_padding if logical_index == 0 else self._HEADER_TEXT_PADDING
        )
        text_left = rect.left() + text_left_padding
        text_rect = rect.adjusted(text_left_padding, 0, -self._HEADER_TEXT_PADDING, 0)
        painter.setPen(text_color)
        painter.drawText(text_rect, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, str(text))

        if logical_index != 0:
            painter.restore()
            return

        arrow_color = _mix_color(
            text_color,
            palette.color(QPalette.ColorRole.Window),
            0.18,
        )
        metrics = painter.fontMetrics()
        text_width = metrics.horizontalAdvance(str(text))
        x = text_left + text_width + self._ARROW_GAP + (self._ARROW_WIDTH // 2)
        y_center = rect.center().y()
        half_length = self._ARROW_LENGTH // 2
        head_size = 3

        if self.sortIndicatorOrder() == Qt.SortOrder.AscendingOrder:
            line_start_y = y_center + half_length
            line_end_y = y_center - half_length
            head_y = line_end_y
            head_left_y = head_y + head_size
        else:
            line_start_y = y_center - half_length
            line_end_y = y_center + half_length
            head_y = line_end_y
            head_left_y = head_y - head_size

        pen = QPen(arrow_color, 1.15)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setPen(pen)
        painter.drawLine(x, line_start_y, x, line_end_y)
        painter.drawLine(x, head_y, x - head_size, head_left_y)
        painter.drawLine(x, head_y, x + head_size, head_left_y)
        painter.restore()


class PackageUpdatesWidget(QFrame):
    current_package_changed = Signal(object)
    package_selection_changed = Signal(str, bool)

    def __init__(
        self,
        parent: QWidget | None = None,
        *,
        icon_resolver: PackageIconResolver | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("card")
        self._packages_by_id: dict[str, PackageUpdate] = {}
        self._rows_by_id: dict[str, PackageUpdateRowView] = {}
        self._items_by_id: dict[str, QTreeWidgetItem] = {}
        self._is_populating = False
        self._is_adjusting_checks = False
        self._active_source_filter: UpdateSource | None = None
        self._has_ignored_system_updates = False
        self._has_skipped_aur_updates = False
        self._icon_resolver = icon_resolver or PackageIconResolver()
        self._package_sort_order = Qt.SortOrder.AscendingOrder

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(14)

        title_row = QGridLayout()
        title_row.setContentsMargins(0, 0, 0, 0)
        title_row.setHorizontalSpacing(10)
        title_row.setColumnMinimumWidth(0, 130)
        title_row.setColumnStretch(1, 1)
        title_row.setColumnStretch(3, 1)

        self.title_label = QLabel(self.tr("All Updates"))
        self.title_label.setObjectName("sectionTitle")
        title_row.addWidget(self.title_label, 0, 0, alignment=Qt.AlignmentFlag.AlignVCenter)

        self.search_icon_label = QLabel("⌕")
        self.search_icon_label.setObjectName("searchIcon")
        title_row.addWidget(self.search_icon_label, 0, 2, alignment=Qt.AlignmentFlag.AlignVCenter)

        self.search_input = QLineEdit()
        self.search_input.setObjectName("updatesSearchInput")
        self.search_input.setPlaceholderText(self.tr("Search packages…"))
        self.search_input.textChanged.connect(self._apply_filter)
        self.search_input.setClearButtonEnabled(True)
        self.search_input.setMinimumWidth(150)
        self.search_input.setMaximumWidth(240)
        title_row.addWidget(self.search_input, 0, 3)

        self.select_visible_button = QPushButton(self.tr("Select All"))
        self.select_visible_button.setProperty("density", "compact")
        self.select_visible_button.clicked.connect(self.select_visible_packages)
        title_row.addWidget(self.select_visible_button, 0, 4)

        self.deselect_visible_button = QPushButton(self.tr("Deselect All"))
        self.deselect_visible_button.setProperty("density", "compact")
        self.deselect_visible_button.clicked.connect(self.deselect_visible_packages)
        title_row.addWidget(self.deselect_visible_button, 0, 5)
        layout.addLayout(title_row)

        self.ignored_note_label = QLabel(
            self.tr("Some system packages are ignored by pacman.conf.")
        )
        self.ignored_note_label.setObjectName("mutedText")
        self.ignored_note_label.setWordWrap(True)
        self.ignored_note_label.hide()
        layout.addWidget(self.ignored_note_label)

        self.aur_skipped_note_label = QLabel(
            self.tr("Some AUR updates were skipped after PKGBUILD review was cancelled.")
        )
        self.aur_skipped_note_label.setObjectName("mutedText")
        self.aur_skipped_note_label.setWordWrap(True)
        self.aur_skipped_note_label.hide()
        layout.addWidget(self.aur_skipped_note_label)

        self.tree = QTreeWidget()
        self.tree.setObjectName("packageUpdatesTree")
        self.tree.setHeader(PackageSortHeaderView(self.tree))
        self.tree.setHeaderLabels([self.tr("Package"), self.tr("Source"), self.tr("Version")])
        self.tree.setRootIsDecorated(False)
        self.tree.setAlternatingRowColors(True)
        self.tree.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.tree.setUniformRowHeights(True)
        header = self.tree.header()
        header.setStretchLastSection(True)
        header.resizeSection(0, 280)
        header.resizeSection(1, 140)
        header.resizeSection(2, 260)
        header.setSectionsClickable(True)
        header.setSortIndicatorShown(False)
        header.setSortIndicator(0, self._package_sort_order)
        if isinstance(header, PackageSortHeaderView):
            header.set_package_text_padding(self._package_header_text_padding())
        header.sectionClicked.connect(self._on_header_section_clicked)
        self.tree.setItemDelegateForColumn(0, PackageNameBadgeDelegate(self.tree))
        self.tree.setItemDelegateForColumn(2, VersionSplitDelegate(self.tree))
        self.tree.itemSelectionChanged.connect(self._on_selection_changed)
        self.tree.itemChanged.connect(self._on_item_changed)

        self.content_stack = QStackedWidget()
        self.content_stack.setObjectName("updatesContentStack")
        self.empty_state_widget = self._build_empty_state()
        self.content_stack.addWidget(self.tree)
        self.content_stack.addWidget(self.empty_state_widget)
        self.content_stack.setCurrentWidget(self.tree)
        layout.addWidget(self.content_stack, stretch=1)
        self._update_filter_status_label()

    def set_packages(
        self,
        packages: list[PackageUpdate],
        *,
        source_texts: dict[UpdateSource, str],
        system_tooltip: str,
    ) -> None:
        self._is_populating = True
        for control in (
            self.search_icon_label, self.search_input,
            self.select_visible_button, self.deselect_visible_button,
        ):
            control.setVisible(bool(packages))
        selectable_system_packages = [
            package
            for package in packages
            if package.source is UpdateSource.SYSTEM and not package.selection_locked
        ]
        select_system_updates = any(package.selected for package in selectable_system_packages)
        for package in selectable_system_packages:
            package.selected = select_system_updates
        self._packages_by_id = {package.id: package for package in packages}
        self._rows_by_id = {}
        self._items_by_id = {}
        self.tree.clear()
        ignored_count = 0
        skipped_aur_count = 0

        for package in packages:
            row = build_package_update_row_view(
                package,
                source_text=source_texts[package.source],
                system_tooltip=system_tooltip,
                translate=self.tr,
            )
            self._rows_by_id[row.package_id] = row
            item = PackageUpdateTreeItem([row.name, row.source_text, row.version_text])
            self._items_by_id[row.package_id] = item
            item.setIcon(0, self._icon_for_package(package))
            item.setData(0, PackageNameBadgeDelegate.BLOCKED_ROLE, row.blocked_by_config)
            item.setData(
                0,
                PackageNameBadgeDelegate.BLOCKED_REASON_ROLE,
                row.blocked_reason,
            )
            item.setData(2, VersionSplitDelegate.OLD_VERSION_ROLE, row.current_version)
            item.setData(2, VersionSplitDelegate.NEW_VERSION_ROLE, row.new_version)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            locked_state = Qt.CheckState.Checked if row.checked else Qt.CheckState.Unchecked
            if row.selection_locked:
                item.setCheckState(0, locked_state)
            else:
                item.setCheckState(0, locked_state)
            if row.tooltip:
                item.setToolTip(0, row.tooltip)
                item.setToolTip(1, row.tooltip)
                item.setToolTip(2, row.tooltip)

            item.setData(0, Qt.ItemDataRole.UserRole, row.package_id)
            self._apply_row_color(item)
            self.tree.addTopLevelItem(item)
            if row.blocked_by_config:
                ignored_count += 1
            if row.skipped_by_pkgbuild_review:
                skipped_aur_count += 1

        self._has_ignored_system_updates = ignored_count > 0
        self._has_skipped_aur_updates = skipped_aur_count > 0
        self._sync_note_labels()

        self._is_populating = False
        self._sort_packages_by_name()
        self._apply_filter(self.search_input.text(), select_first_visible=False)
        if packages:
            self.content_stack.setCurrentWidget(self.tree)
            self._clear_initial_selection()
            return
        self.show_up_to_date()
        self.current_package_changed.emit(None)

    def _icon_for_package(self, package: PackageUpdate) -> QIcon:
        icon_path = self._icon_resolver.icon_path_for(package)
        if icon_path is not None:
            icon = QIcon(str(icon_path))
            if not icon.isNull():
                return icon

        if package.icon_name:
            icon = QIcon.fromTheme(package.icon_name)
            if not icon.isNull():
                return icon

        descriptor = source_descriptors(self.tr).get(package.source)
        default_icon = QIcon.fromTheme(
            descriptor.default_icon_name if descriptor is not None else "package-x-generic"
        )
        if not default_icon.isNull():
            return default_icon
        return self.style().standardIcon(QStyle.StandardPixmap.SP_FileIcon)

    def _package_header_text_padding(self) -> int:
        style = self.tree.style()
        checkbox_width = style.pixelMetric(
            QStyle.PixelMetric.PM_IndicatorWidth,
            None,
            self.tree,
        )
        icon_size = self.tree.iconSize()
        icon_width = icon_size.width() if icon_size.isValid() else 16
        focus_margin = style.pixelMetric(
            QStyle.PixelMetric.PM_FocusFrameHMargin,
            None,
            self.tree,
        )
        return 8 + checkbox_width + icon_width + (focus_margin * 4) + 18

    def clear_packages(self) -> None:
        self._packages_by_id = {}
        self._rows_by_id = {}
        self._items_by_id = {}
        self._has_ignored_system_updates = False
        self._has_skipped_aur_updates = False
        self.tree.clear()
        self.content_stack.setCurrentWidget(self.tree)
        self._sync_note_labels()
        self.current_package_changed.emit(None)

    def _build_empty_state(self) -> QWidget:
        empty_state = QWidget()
        empty_state.setObjectName("updatesEmptyState")
        empty_state.setSizePolicy(
            QSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        )
        layout = QVBoxLayout(empty_state)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(10)
        layout.addStretch(1)

        illustration_label = QLabel()
        illustration_label.setObjectName("updatesEmptyIllustration")
        illustration_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        illustration_label.setFixedSize(220, 220)
        asset_path = illustration_path("up_to_date.png")
        if asset_path is not None:
            pixmap = QPixmap(str(asset_path))
            if not pixmap.isNull():
                illustration_label.setPixmap(
                    pixmap.scaled(
                        210,
                        210,
                        Qt.AspectRatioMode.KeepAspectRatio,
                        Qt.TransformationMode.SmoothTransformation,
                    )
                )
        layout.addWidget(
            illustration_label,
            alignment=Qt.AlignmentFlag.AlignHCenter,
        )

        title = QLabel(self.tr("Everything is up to date!"))
        title.setObjectName("updatesEmptyTitle")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(title)

        message = QLabel(
            self.tr("New updates will appear here after the next refresh.")
        )
        message.setObjectName("updatesEmptyMessage")
        message.setAlignment(Qt.AlignmentFlag.AlignCenter)
        message.setWordWrap(True)
        layout.addWidget(message)
        layout.addStretch(1)
        self.empty_illustration = illustration_label
        self.empty_title = title
        self.empty_message = message
        return empty_state

    def show_status_placeholder(self, title: str, message: str) -> None:
        self.empty_illustration.hide()
        self.empty_title.setText(title)
        self.empty_message.setText(message)
        self.content_stack.setCurrentWidget(self.empty_state_widget)

    def show_up_to_date(self) -> None:
        self.empty_illustration.show()
        self.empty_title.setText(self.tr("Everything is up to date!"))
        self.empty_message.setText(self.tr("New updates will appear here after the next refresh."))
        self.content_stack.setCurrentWidget(self.empty_state_widget)

    def clear_selection(self) -> None:
        self._clear_initial_selection()

    def set_enabled_for_operations(self, enabled: bool) -> None:
        self.tree.setEnabled(enabled)
        self.select_visible_button.setEnabled(enabled)
        self.deselect_visible_button.setEnabled(enabled)

    def set_source_filter(self, source: UpdateSource | None) -> None:
        self._active_source_filter = source
        self._update_filter_status_label()
        self._sync_note_labels()
        self._apply_filter(self.search_input.text(), select_first_visible=source is not None)

    def _on_selection_changed(self) -> None:
        selected_items = self.tree.selectedItems()
        if not selected_items:
            self.current_package_changed.emit(None)
            return

        package_id = selected_items[0].data(0, Qt.ItemDataRole.UserRole)
        self.current_package_changed.emit(self._packages_by_id.get(package_id))

    def _on_item_changed(self, item: QTreeWidgetItem, column: int) -> None:
        if self._is_populating or self._is_adjusting_checks or column != 0:
            return

        package_id = item.data(0, Qt.ItemDataRole.UserRole)
        package = self._packages_by_id.get(package_id)
        if package is None:
            return

        next_selected = item.checkState(0) == Qt.CheckState.Checked
        if package.selection_locked:
            self._set_item_check_state(
                item,
                Qt.CheckState.Checked if package.selected else Qt.CheckState.Unchecked,
            )
            return
        if package.source is UpdateSource.SYSTEM:
            self._set_system_packages_selected(next_selected)
            return
        self._set_package_selected(package, next_selected)

    def _on_header_section_clicked(self, section: int) -> None:
        if section != 0:
            return

        self._package_sort_order = (
            Qt.SortOrder.DescendingOrder
            if self._package_sort_order is Qt.SortOrder.AscendingOrder
            else Qt.SortOrder.AscendingOrder
        )
        self._sort_packages_by_name()

    def _sort_packages_by_name(self) -> None:
        current_item = self.tree.currentItem()
        current_package_id = (
            current_item.data(0, Qt.ItemDataRole.UserRole) if current_item is not None else None
        )
        self.tree.sortItems(0, self._package_sort_order)
        self.tree.header().setSortIndicator(0, self._package_sort_order)
        if current_package_id is None:
            return

        for index in range(self.tree.topLevelItemCount()):
            item = self.tree.topLevelItem(index)
            if item.data(0, Qt.ItemDataRole.UserRole) == current_package_id:
                self.tree.setCurrentItem(item)
                return

    def select_visible_packages(self) -> None:
        self._set_visible_packages_selected(True)

    def deselect_visible_packages(self) -> None:
        self._set_visible_packages_selected(False)

    def _set_visible_packages_selected(self, selected: bool) -> None:
        system_updates_handled = False
        for item in self._visible_items():
            package_id = item.data(0, Qt.ItemDataRole.UserRole)
            package = self._packages_by_id.get(package_id)
            if package is None or package.selection_locked:
                continue
            if package.source is UpdateSource.SYSTEM:
                if not system_updates_handled:
                    self._set_system_packages_selected(selected)
                    system_updates_handled = True
                continue
            self._set_package_selected(package, selected)

    def _visible_items(self) -> list[QTreeWidgetItem]:
        return [
            self.tree.topLevelItem(index)
            for index in range(self.tree.topLevelItemCount())
            if not self.tree.topLevelItem(index).isHidden()
        ]

    def _set_system_packages_selected(self, selected: bool) -> None:
        for package in self._packages_by_id.values():
            if package.source is UpdateSource.SYSTEM and not package.selection_locked:
                self._set_package_selected(package, selected)

    def _set_package_selected(self, package: PackageUpdate, selected: bool) -> None:
        item = self._items_by_id.get(package.id)
        if item is None:
            return
        if item.checkState(0) != (
            Qt.CheckState.Checked if selected else Qt.CheckState.Unchecked
        ):
            self._set_item_check_state(
                item,
                Qt.CheckState.Checked if selected else Qt.CheckState.Unchecked,
            )
        if package.selected == selected:
            return
        package.selected = selected
        self.package_selection_changed.emit(package.id, selected)

    def _set_item_check_state(self, item: QTreeWidgetItem, state: Qt.CheckState) -> None:
        self._is_adjusting_checks = True
        item.setCheckState(0, state)
        self._is_adjusting_checks = False

    def _apply_row_color(self, item: QTreeWidgetItem) -> None:
        palette = self.palette()
        text = palette.color(QPalette.ColorRole.Text)
        window = palette.color(QPalette.ColorRole.Window)
        slate_tint = QColor("#334155")
        dark = window.lightness() < 128
        base = _mix_color(text, slate_tint, 0.20 if dark else 0.62)
        for column in range(3):
            item.setForeground(column, base)

    def _apply_filter(self, raw_query: str, *, select_first_visible: bool = True) -> None:
        query = raw_query.strip().lower()
        first_visible: QTreeWidgetItem | None = None
        current_item = self.tree.currentItem()

        for index in range(self.tree.topLevelItemCount()):
            item = self.tree.topLevelItem(index)
            package_id = item.data(0, Qt.ItemDataRole.UserRole)
            row = self._rows_by_id.get(package_id)
            matches = row is not None and package_matches_filter(
                row,
                query=query,
                source_filter=self._active_source_filter,
            )
            item.setHidden(not matches)
            if matches and first_visible is None:
                first_visible = item

        if current_item is not None and not current_item.isHidden():
            return

        if first_visible is not None and select_first_visible:
            self.tree.setCurrentItem(first_visible)
            return

        self.tree.clearSelection()
        self.current_package_changed.emit(None)

    def _update_filter_status_label(self) -> None:
        self.title_label.setText(
            source_filter_title(self._active_source_filter, translate=self.tr)
        )

    def _sync_note_labels(self) -> None:
        self.ignored_note_label.setVisible(self._has_ignored_system_updates)
        self.aur_skipped_note_label.setVisible(
            self._has_skipped_aur_updates
            and self._active_source_filter in {None, UpdateSource.AUR}
        )

    def _clear_initial_selection(self) -> None:
        self.tree.clearSelection()
        self.tree.setCurrentItem(None)
        self.current_package_changed.emit(None)
