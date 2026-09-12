from __future__ import annotations

import html
from collections.abc import Iterable

from PySide6.QtCore import QPoint, QRect, QSize, Qt, QTimer, QUrl
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (
    QFormLayout,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLayout,
    QLayoutItem,
    QScrollArea,
    QSizePolicy,
    QStyle,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from archupdater.domain.packages import PackageUpdate
from archupdater.presentation.package_details_view_model import (
    PackageDetailsViewModel,
    build_package_details_view_model,
)
from archupdater.presentation.package_icons import PackageIconResolver


METRIC_LAYOUT = (
    ("current", "Current", 0, 0),
    ("new", "New", 0, 1),
    ("size_diff", "Size diff", 1, 0),
    ("download", "Download", 1, 1),
    ("installed", "Installed", 2, 0),
    ("repository", "Repository", 2, 1),
)

TECHNICAL_ROW_LABELS = (
    ("source", "Source"),
    ("author", "Author"),
    ("size", "Size"),
    ("repository", "Repository"),
    ("kind", "Kind"),
    ("scope", "Scope"),
    ("remote", "Remote"),
    ("branch", "Branch"),
    ("runtime", "Runtime"),
    ("plugin", "Plugin ID"),
    ("current_installed_size", "Current installed size"),
    ("architecture", "Architecture"),
    ("packager", "Packager"),
    ("build_date", "Build date"),
    ("install_date", "Install date"),
    ("install_reason", "Install reason"),
    ("maintainer", "Maintainer"),
    ("votes", "Votes"),
    ("popularity", "Popularity"),
    ("out_of_date", "Out of date"),
    ("first_submitted", "First submitted"),
    ("last_modified", "Last modified"),
    ("licenses", "Licenses"),
    ("groups", "Groups"),
    ("provides", "Provides"),
    ("conflicts", "Conflicts"),
    ("replaces", "Replaces"),
    ("required_by", "Required by"),
)

LIST_SECTION_LABELS = (
    ("dependencies", "Dependencies", True),
    ("optional_dependencies", "Optional Dependencies", True),
    ("make_dependencies", "Make Dependencies", True),
    ("check_dependencies", "Check Dependencies", True),
    ("release_notes", "Release Notes", True),
    ("warnings", "Warnings", False),
)


class _FlowLayout(QLayout):
    def __init__(
        self,
        parent: QWidget | None = None,
        *,
        horizontal_spacing: int = 6,
        vertical_spacing: int = 6,
    ) -> None:
        super().__init__(parent)
        self._items: list[QLayoutItem] = []
        self._horizontal_spacing = horizontal_spacing
        self._vertical_spacing = vertical_spacing
        self.setContentsMargins(0, 0, 0, 0)

    def addItem(self, item: QLayoutItem) -> None:  # type: ignore[override]
        self._items.append(item)

    def count(self) -> int:  # type: ignore[override]
        return len(self._items)

    def itemAt(self, index: int) -> QLayoutItem | None:  # type: ignore[override]
        if 0 <= index < len(self._items):
            return self._items[index]
        return None

    def takeAt(self, index: int) -> QLayoutItem | None:  # type: ignore[override]
        if 0 <= index < len(self._items):
            return self._items.pop(index)
        return None

    def expandingDirections(self) -> Qt.Orientation:  # type: ignore[override]
        return Qt.Orientation(0)

    def hasHeightForWidth(self) -> bool:  # type: ignore[override]
        return True

    def heightForWidth(self, width: int) -> int:  # type: ignore[override]
        return self._do_layout(QRect(0, 0, width, 0), test_only=True)

    def setGeometry(self, rect: QRect) -> None:  # type: ignore[override]
        super().setGeometry(rect)
        self._do_layout(rect, test_only=False)

    def sizeHint(self) -> QSize:  # type: ignore[override]
        return self.minimumSize()

    def minimumSize(self) -> QSize:  # type: ignore[override]
        size = QSize()
        for item in self._items:
            size = size.expandedTo(item.minimumSize())
        margins = self.contentsMargins()
        size += QSize(margins.left() + margins.right(), margins.top() + margins.bottom())
        return size

    def _do_layout(self, rect: QRect, *, test_only: bool) -> int:
        margins = self.contentsMargins()
        effective_rect = rect.adjusted(
            margins.left(),
            margins.top(),
            -margins.right(),
            -margins.bottom(),
        )
        x = effective_rect.x()
        y = effective_rect.y()
        line_height = 0
        max_width = max(effective_rect.width(), 1)

        for item in self._items:
            widget = item.widget()
            if widget is not None and widget.isHidden():
                continue

            hint = item.sizeHint()
            item_width = min(hint.width(), max_width)
            item_height = hint.height()
            if widget is not None and widget.hasHeightForWidth():
                item_height = max(item_height, widget.heightForWidth(item_width))

            next_x = x + item_width + self._horizontal_spacing
            if next_x - self._horizontal_spacing > effective_rect.right() + 1 and line_height > 0:
                x = effective_rect.x()
                y += line_height + self._vertical_spacing
                next_x = x + item_width + self._horizontal_spacing
                line_height = 0

            if not test_only:
                item.setGeometry(QRect(QPoint(x, y), QSize(item_width, item_height)))
            x = next_x
            line_height = max(line_height, item_height)

        return y + line_height - rect.y() + margins.bottom()


class PackageDetailsPanel(QFrame):
    def __init__(
        self,
        parent: QWidget | None = None,
        *,
        icon_resolver: PackageIconResolver | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("card")
        self.setFrameShape(QFrame.Shape.NoFrame)
        self._icon_resolver = icon_resolver or PackageIconResolver()

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(16)

        self._title_row_widget = QWidget()
        title_row = QHBoxLayout(self._title_row_widget)
        title_row.setContentsMargins(0, 0, 0, 0)
        title_row.setSpacing(10)
        self._title_label = QLabel(self.tr("Package Details"))
        self._title_label.setObjectName("sectionTitle")
        title_row.addWidget(self._title_label)
        title_row.addStretch(1)
        layout.addWidget(self._title_row_widget)

        self._placeholder_widget = QWidget()
        placeholder_layout = QVBoxLayout(self._placeholder_widget)
        placeholder_layout.setContentsMargins(0, 0, 0, 0)
        placeholder_layout.setSpacing(0)
        placeholder_layout.addStretch(1)

        self._placeholder_content = QWidget()
        self._placeholder_content.setMinimumWidth(340)
        self._placeholder_content.setMaximumWidth(440)
        self._placeholder_content.setSizePolicy(
            QSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        )
        placeholder_content_layout = QVBoxLayout(self._placeholder_content)
        placeholder_content_layout.setContentsMargins(8, 8, 8, 8)
        placeholder_content_layout.setSpacing(18)
        placeholder_content_layout.setAlignment(Qt.AlignmentFlag.AlignHCenter)

        self._placeholder_icon = QLabel()
        self._placeholder_icon.setObjectName("emptyStateIcon")
        self._placeholder_icon.setFixedSize(52, 52)
        self._placeholder_icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        placeholder_content_layout.addWidget(
            self._placeholder_icon,
            alignment=Qt.AlignmentFlag.AlignHCenter,
        )

        self._placeholder_text_block = QWidget()
        self._placeholder_text_block.setSizePolicy(
            QSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        )
        placeholder_text_layout = QVBoxLayout(self._placeholder_text_block)
        placeholder_text_layout.setContentsMargins(0, 0, 0, 0)
        placeholder_text_layout.setSpacing(0)
        placeholder_text_layout.setAlignment(Qt.AlignmentFlag.AlignHCenter)

        self._placeholder_title = QLabel(self.tr("Package Details"))
        self._placeholder_title.setObjectName("detailsEmptyStateTitle")
        self._placeholder_title.setAlignment(
            Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignBottom
        )
        self._placeholder_title.setWordWrap(True)
        self._placeholder_title.setSizePolicy(
            QSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)
        )
        placeholder_text_layout.addWidget(self._placeholder_title)

        self._details_placeholder = QLabel(self.tr("Select an update to view details"))
        self._details_placeholder.setObjectName("detailsEmptyStateMessage")
        self._details_placeholder.setAlignment(
            Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop
        )
        self._details_placeholder.setWordWrap(True)
        self._details_placeholder.setSizePolicy(
            QSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)
        )
        self._details_placeholder.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        placeholder_text_layout.addWidget(self._details_placeholder)
        placeholder_content_layout.addWidget(self._placeholder_text_block)

        placeholder_layout.addWidget(
            self._placeholder_content,
            alignment=Qt.AlignmentFlag.AlignCenter,
        )
        placeholder_layout.addStretch(1)
        layout.addWidget(self._placeholder_widget, stretch=1)

        self._details_scroll = QScrollArea()
        self._details_scroll.setObjectName("packageDetailsScroll")
        self._details_scroll.setWidgetResizable(True)
        self._details_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._details_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._details_widget = QWidget()
        self._details_widget.setObjectName("packageDetailsContent")
        self._details_widget.setMinimumWidth(0)
        self._details_widget.setSizePolicy(
            QSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        )
        details_layout = QVBoxLayout(self._details_widget)
        details_layout.setContentsMargins(0, 0, 0, 0)
        details_layout.setSpacing(16)

        self._build_header(details_layout)
        self._build_summary_cards(details_layout)
        self._build_technical_details(details_layout)
        self._build_list_sections(details_layout)
        details_layout.addStretch(1)

        self._details_scroll.setWidget(self._details_widget)
        self._details_scroll.hide()
        layout.addWidget(self._details_scroll, stretch=1)

    def _build_header(self, details_layout: QVBoxLayout) -> None:
        header = QFrame()
        header.setObjectName("packageDetailsHeader")
        header.setMinimumWidth(0)
        header.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(14, 14, 14, 14)
        header_layout.setSpacing(14)

        self._detail_icon = QLabel()
        self._detail_icon.setObjectName("packageDetailsIcon")
        self._detail_icon.setFixedSize(52, 52)
        self._detail_icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        header_layout.addWidget(self._detail_icon, alignment=Qt.AlignmentFlag.AlignTop)

        text_block = QVBoxLayout()
        text_block.setContentsMargins(0, 0, 0, 0)
        text_block.setSpacing(6)

        title_row = QHBoxLayout()
        title_row.setContentsMargins(0, 0, 0, 0)
        title_row.setSpacing(8)
        self._detail_name = QLabel()
        self._detail_name.setObjectName("packageDetailsName")
        self._detail_name.setTextFormat(Qt.TextFormat.PlainText)
        self._detail_name.setWordWrap(True)
        self._detail_name.setMinimumWidth(0)
        self._detail_name.setSizePolicy(
            QSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Minimum)
        )
        title_row.addWidget(self._detail_name, stretch=1)
        self._source_badge = QLabel()
        self._source_badge.setObjectName("packageDetailsBadge")
        self._source_badge.setTextFormat(Qt.TextFormat.PlainText)
        self._source_badge.setSizePolicy(
            QSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed)
        )
        title_row.addWidget(self._source_badge, alignment=Qt.AlignmentFlag.AlignTop)
        text_block.addLayout(title_row)

        self._detail_description = QLabel()
        self._detail_description.setWordWrap(True)
        self._detail_description.setObjectName("detailText")
        self._detail_description.setTextFormat(Qt.TextFormat.PlainText)
        self._detail_description.setMinimumWidth(0)
        self._detail_description.setSizePolicy(
            QSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Minimum)
        )
        self._detail_description.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        text_block.addWidget(self._detail_description)
        header_layout.addLayout(text_block, stretch=1)
        details_layout.addWidget(header)

    def _build_summary_cards(self, details_layout: QVBoxLayout) -> None:
        summary = QGridLayout()
        summary.setContentsMargins(0, 0, 0, 0)
        summary.setHorizontalSpacing(10)
        summary.setVerticalSpacing(10)
        summary.setColumnStretch(0, 1)
        summary.setColumnStretch(1, 1)
        summary.setColumnMinimumWidth(0, 0)
        summary.setColumnMinimumWidth(1, 0)
        self._metric_cards: dict[str, tuple[QFrame, QLabel, QLabel]] = {}
        for key, title, row, column in METRIC_LAYOUT:
            card, title_label, value_label = self._create_metric_card(self.tr(title))
            summary.addWidget(card, row, column)
            self._metric_cards[key] = (card, title_label, value_label)
        details_layout.addLayout(summary)

    def _build_technical_details(self, details_layout: QVBoxLayout) -> None:
        self._technical_card = QFrame()
        self._technical_card.setObjectName("packageDetailsSection")
        self._technical_card.setMinimumWidth(0)
        self._technical_card.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)
        section_layout = QVBoxLayout(self._technical_card)
        section_layout.setContentsMargins(14, 14, 14, 14)
        section_layout.setSpacing(10)
        caption = QLabel(self.tr("Technical Details"))
        caption.setObjectName("sectionCaption")
        section_layout.addWidget(caption)

        self._technical_form = QFormLayout()
        self._technical_form.setLabelAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        self._technical_form.setFormAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        self._technical_form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        self._technical_form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)
        self._technical_form.setHorizontalSpacing(18)
        self._technical_form.setVerticalSpacing(9)

        self._detail_source = self._create_value_label()
        self._detail_author = self._create_value_label()
        self._detail_size = self._create_value_label()
        self._detail_repository = self._create_value_label()
        self._detail_homepage = self._create_value_label()
        self._detail_homepage.setObjectName("detailLinkText")
        self._detail_homepage.setTextFormat(Qt.TextFormat.RichText)
        self._detail_homepage.setOpenExternalLinks(True)
        self._detail_homepage.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextBrowserInteraction
        )
        self._detail_homepage_label = QLabel(self.tr("URL"))
        self._detail_homepage_label.setObjectName("detailFieldLabel")

        existing_value_labels = {
            "source": self._detail_source,
            "author": self._detail_author,
            "size": self._detail_size,
            "repository": self._detail_repository,
        }
        self._technical_rows: dict[str, tuple[QLabel, QLabel]] = {}
        for key, title in TECHNICAL_ROW_LABELS:
            value_label = existing_value_labels.get(key) or self._create_value_label()
            self._technical_rows[key] = self._create_form_row(self.tr(title), value_label)
        self._technical_rows["homepage"] = (self._detail_homepage_label, self._detail_homepage)
        for label, value in self._technical_rows.values():
            self._technical_form.addRow(label, value)
        section_layout.addLayout(self._technical_form)
        details_layout.addWidget(self._technical_card)

    def _build_list_sections(self, details_layout: QVBoxLayout) -> None:
        self._list_sections: dict[str, tuple[QFrame, QLabel | QToolButton, QWidget, _FlowLayout]] = {}
        self._collapsible_list_sections = {
            key for key, _title, collapsible in LIST_SECTION_LABELS if collapsible
        }
        self._list_section_expanded: dict[str, bool] = {}
        self._list_section_toggles: dict[str, QToolButton] = {}
        for key, title, collapsible in LIST_SECTION_LABELS:
            section = QFrame()
            section.setObjectName("packageDetailsSection")
            section.setMinimumWidth(0)
            section.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)
            layout = QVBoxLayout(section)
            layout.setContentsMargins(14, 14, 14, 14)
            layout.setSpacing(10)

            header = QWidget()
            header_layout = QHBoxLayout(header)
            header_layout.setContentsMargins(0, 0, 0, 0)
            header_layout.setSpacing(6)

            if collapsible:
                caption = QToolButton()
                caption.setObjectName("packageDetailsExpanderButton")
                caption.setText(self.tr(title))
                caption.setAutoRaise(True)
                caption.setCheckable(True)
                caption.setChecked(False)
                caption.setArrowType(Qt.ArrowType.RightArrow)
                caption.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
                caption.setCursor(Qt.CursorShape.PointingHandCursor)
                caption.setSizePolicy(
                    QSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
                )
                caption.clicked.connect(
                    lambda _checked=False, section_key=key: self._toggle_list_section(section_key)
                )
                toggle = caption
            else:
                caption = QLabel(self.tr(title))
                caption.setObjectName("sectionCaption")
                toggle = QToolButton()
                toggle.hide()
            header_layout.addWidget(caption, stretch=1)
            layout.addWidget(header)

            chips_widget = QWidget()
            chips_layout = _FlowLayout(chips_widget, horizontal_spacing=6, vertical_spacing=6)
            layout.addWidget(chips_widget)
            details_layout.addWidget(section)
            self._list_sections[key] = (section, caption, chips_widget, chips_layout)
            self._list_section_toggles[key] = toggle
            self._list_section_expanded[key] = key not in self._collapsible_list_sections

    def show_placeholder(
        self,
        *,
        title: str,
        text: str,
        icon: QStyle.StandardPixmap | None = None,
    ) -> None:
        self._title_row_widget.hide()
        self._placeholder_title.setText(title)
        self._details_placeholder.setText(text)
        self._details_placeholder.setVisible(bool(text))
        self._placeholder_widget.show()
        self._details_scroll.hide()
        self._detail_icon.hide()
        self._detail_icon.clear()
        self._apply_placeholder_icon(icon)
        self._refresh_placeholder_label_heights()

    def set_package(
        self,
        package: PackageUpdate,
        *,
        source_text: str,
        unavailable_text: str,
        no_description_text: str,
    ) -> None:
        view_model = build_package_details_view_model(
            package,
            source_text=source_text,
            unavailable_text=unavailable_text,
            no_description_text=no_description_text,
        )
        self._title_row_widget.hide()
        self._placeholder_widget.hide()
        self._details_scroll.show()

        self._apply_view_model(view_model)
        self._apply_package_icon(package)
        self._scroll_details_to_top()

    def _apply_view_model(self, view_model: PackageDetailsViewModel) -> None:
        self._detail_name.setText(view_model.name)
        self._source_badge.setText(view_model.source_text)
        self._detail_description.setText(view_model.description)
        for metric in view_model.metrics:
            self._set_metric(metric.key, metric.value)
        for row in view_model.rows:
            self._set_row(row.key, row.value, hide_when_empty=row.hide_when_empty)
        self._set_homepage(view_model.homepage)
        for key in self._collapsible_list_sections:
            self._list_section_expanded[key] = False
        for section in view_model.chip_sections:
            self._set_chip_section(section.key, section.values)

    def resizeEvent(self, event) -> None:  # type: ignore[override]
        super().resizeEvent(event)
        if self._placeholder_widget.isVisible():
            self._refresh_placeholder_label_heights()

    def _create_metric_card(self, title: str) -> tuple[QFrame, QLabel, QLabel]:
        card = QFrame()
        card.setObjectName("packageMetricCard")
        card.setMinimumWidth(0)
        card.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)
        layout = QVBoxLayout(card)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(4)
        title_label = QLabel(title)
        title_label.setObjectName("packageMetricTitle")
        title_label.setWordWrap(True)
        title_label.setMinimumWidth(0)
        title_label.setSizePolicy(
            QSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Minimum)
        )
        value_label = QLabel()
        value_label.setObjectName("packageMetricValue")
        value_label.setWordWrap(True)
        value_label.setMinimumWidth(0)
        value_label.setSizePolicy(
            QSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Minimum)
        )
        value_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        layout.addWidget(title_label)
        layout.addWidget(value_label)
        return card, title_label, value_label

    def _set_metric(self, key: str, value: str) -> None:
        card, _title, value_label = self._metric_cards[key]
        value_label.setText(value)
        unavailable = not value or value == self.tr("Unavailable") or value == self.tr("Not available")
        card.setProperty("metricState", "empty" if unavailable else "ready")
        self._refresh_style(card)

    def _create_form_row(self, label_text: str, value_widget: QLabel) -> tuple[QLabel, QLabel]:
        label = QLabel(label_text)
        label.setObjectName("detailFieldLabel")
        label.setWordWrap(True)
        return label, value_widget

    def _set_row(
        self,
        key: str,
        value: str,
        *,
        default_text: str = "",
        hide_when_empty: bool = False,
    ) -> None:
        label, value_label = self._technical_rows[key]
        text = value.strip() or default_text
        visible = bool(text) or not hide_when_empty
        label.setVisible(visible)
        value_label.setVisible(visible)
        value_label.setText(text)

    def _set_homepage(self, homepage: str | None) -> None:
        label, value_label = self._technical_rows["homepage"]
        safe_homepage = self._safe_external_url(homepage)
        visible = bool(safe_homepage)
        label.setVisible(visible)
        value_label.setVisible(visible)
        if safe_homepage:
            escaped_url = html.escape(safe_homepage, quote=True)
            value_label.setText(f'<a href="{escaped_url}">{escaped_url}</a>')
        else:
            value_label.clear()

    def _safe_external_url(self, value: str | None) -> str | None:
        if not value:
            return None
        text = value.strip()
        url = QUrl(text)
        if (
            not url.isValid()
            or url.scheme().lower() not in {"http", "https"}
            or not url.host()
        ):
            return None
        return text

    def _set_chip_section(self, key: str, values: Iterable[str]) -> None:
        section, caption, chips_widget, chips_layout = self._list_sections[key]
        cleaned_values = [value.strip() for value in values if value.strip()]
        section.setVisible(bool(cleaned_values))
        caption.setText(f"{caption.text().split(' (', 1)[0]} ({len(cleaned_values)})")
        while chips_layout.count():
            item = chips_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        for value in cleaned_values[:12]:
            chips_layout.addWidget(self._create_chip(value, selectable=True))
        if len(cleaned_values) > 12:
            chips_layout.addWidget(
                self._create_chip(
                    self.tr("+{count} more").format(count=len(cleaned_values) - 12),
                    selectable=False,
                )
            )
        self._sync_list_section_visibility(key, has_values=bool(cleaned_values))

    def _create_chip(self, text: str, *, selectable: bool) -> QLabel:
        chip = QLabel(text)
        chip.setObjectName("packageDetailChip")
        chip.setTextFormat(Qt.TextFormat.PlainText)
        chip.setWordWrap(True)
        chip.setMinimumWidth(0)
        chip.setSizePolicy(QSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Minimum))
        if selectable:
            chip.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        return chip

    def _toggle_list_section(self, key: str) -> None:
        section, _caption, _chips_widget, chips_layout = self._list_sections[key]
        if section.isHidden() or chips_layout.count() == 0:
            return
        self._list_section_expanded[key] = not self._list_section_expanded.get(key, False)
        self._sync_list_section_visibility(key, has_values=True)

    def _sync_list_section_visibility(self, key: str, *, has_values: bool) -> None:
        _section, _caption, chips_widget, _chips_layout = self._list_sections[key]
        toggle = self._list_section_toggles[key]
        collapsible = key in self._collapsible_list_sections
        expanded = self._list_section_expanded.get(key, not collapsible)
        chips_widget.setVisible(has_values and (expanded or not collapsible))
        toggle.setVisible(has_values and collapsible)
        toggle.setArrowType(Qt.ArrowType.DownArrow if expanded else Qt.ArrowType.RightArrow)
        if toggle.isCheckable():
            toggle.setChecked(has_values and expanded)

    def _apply_placeholder_icon(self, icon: QStyle.StandardPixmap | None) -> None:
        if icon is None:
            self._placeholder_icon.hide()
            self._placeholder_icon.clear()
            return

        resolved_icon = self.style().standardIcon(icon)
        if resolved_icon.isNull():
            self._placeholder_icon.hide()
            self._placeholder_icon.clear()
            return

        self._placeholder_icon.setPixmap(resolved_icon.pixmap(40, 40))
        self._placeholder_icon.show()

    def _apply_package_icon(self, package: PackageUpdate) -> None:
        icon = QIcon()
        icon_path = self._icon_resolver.icon_path_for(package)
        if icon_path is not None:
            icon = QIcon(str(icon_path))
        if icon.isNull() and package.icon_name:
            icon = QIcon.fromTheme(package.icon_name)
        if icon.isNull():
            icon = QIcon.fromTheme("package-x-generic")
        if icon.isNull():
            icon = self.style().standardIcon(QStyle.StandardPixmap.SP_FileIcon)
        if icon.isNull():
            self._detail_icon.hide()
            self._detail_icon.clear()
            return

        self._detail_icon.setPixmap(icon.pixmap(42, 42))
        self._detail_icon.show()

    def _create_value_label(self) -> QLabel:
        label = QLabel()
        label.setObjectName("detailValueText")
        label.setTextFormat(Qt.TextFormat.PlainText)
        label.setWordWrap(True)
        label.setMinimumWidth(0)
        label.setSizePolicy(
            QSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Minimum)
        )
        label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        return label

    def _refresh_placeholder_label_heights(self) -> None:
        self._placeholder_text_block.setMinimumHeight(0)
        self._placeholder_text_block.setMaximumHeight(16777215)
        self._placeholder_content.setMinimumHeight(0)
        self._placeholder_content.setMaximumHeight(16777215)
        for label in (self._placeholder_title, self._details_placeholder):
            label.setMinimumHeight(0)
            label.setMaximumHeight(16777215)
            if label.isHidden():
                continue
            width = max(label.width(), self._placeholder_content.minimumWidth(), 1)
            height = label.sizeHint().height()
            if label.hasHeightForWidth():
                height = max(height, label.heightForWidth(width))
            label.setMinimumHeight(height + 2)
        self._placeholder_text_block.setMinimumHeight(
            self._placeholder_text_block.sizeHint().height()
        )
        self._placeholder_content.setMinimumHeight(self._placeholder_content.sizeHint().height())
        self._placeholder_text_block.updateGeometry()
        self._placeholder_content.updateGeometry()

    def _scroll_details_to_top(self) -> None:
        scrollbar = self._details_scroll.verticalScrollBar()
        scrollbar.setValue(0)
        QTimer.singleShot(0, lambda: scrollbar.setValue(0))

    def _refresh_style(self, widget: QWidget) -> None:
        widget.style().unpolish(widget)
        widget.style().polish(widget)
        widget.update()
