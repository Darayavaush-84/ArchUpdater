from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QIcon, QPixmap
from PySide6.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from archupdater.application.update_sources.descriptors import (
    SOURCE_ORDER,
    SourceDescriptor,
    source_descriptors,
)
from archupdater.domain.enums import UpdateSource
from archupdater.domain.optional_sources import OptionalSourcesSnapshot
from archupdater.domain.packages import UpdateCounters
from archupdater.presentation.status_header_filter_state import StatusHeaderFilterState
from archupdater.resources.assets import counter_logo_path


class CounterCardWidget(QFrame):
    clicked = Signal(object)

    def __init__(self, source: UpdateSource, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._source = source
        self.setObjectName("counterCard")
        self.setProperty("sourceKind", source.value)
        self.setProperty("filterActive", False)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setSizePolicy(
            QSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        )

    @property
    def source(self) -> UpdateSource:
        return self._source

    def set_filter_active(self, active: bool) -> None:
        self.setProperty("filterActive", active)
        self.style().unpolish(self)
        self.style().polish(self)
        self.update()

    def mousePressEvent(self, event) -> None:  # type: ignore[override]
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit(self._source)
            event.accept()
            return
        super().mousePressEvent(event)

    def keyPressEvent(self, event) -> None:  # type: ignore[override]
        if event.key() in {Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Space}:
            self.clicked.emit(self._source)
            event.accept()
            return
        super().keyPressEvent(event)


class StatusHeaderWidget(QFrame):
    source_filter_changed = Signal(object)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("statusHero")
        self._filter_state = StatusHeaderFilterState()
        self._filter_badges: dict[UpdateSource, QLabel] = {}

        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 0)
        layout.setSpacing(16)

        summary_widget = QWidget()
        summary_widget.setObjectName("statusSummary")
        summary_layout = QHBoxLayout(summary_widget)
        summary_layout.setContentsMargins(0, 0, 0, 0)
        summary_layout.setSpacing(22)

        text_layout = QVBoxLayout()
        text_layout.setSpacing(5)
        text_layout.addStretch(1)

        self.system_status_label = QLabel()
        self.system_status_label.setObjectName("systemStatus")
        self.system_status_label.setWordWrap(True)
        text_layout.addWidget(self.system_status_label)

        self.last_checked_label = QLabel()
        self.last_checked_label.setObjectName("statusMeta")
        self.next_check_label = QLabel()
        self.next_check_label.setObjectName("statusMeta")

        self.progress_widget = QWidget()
        self.progress_widget.hide()
        progress_layout = QHBoxLayout(self.progress_widget)
        progress_layout.setContentsMargins(0, 4, 0, 0)
        progress_layout.setSpacing(8)

        self.progress_label = QLabel(self.tr("Progress"))
        self.progress_label.setObjectName("sectionCaption")
        self.progress_bar = QProgressBar()
        self.progress_bar.setObjectName("headerProgressBar")
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setTextVisible(False)
        self.progress_bar.setMinimumWidth(140)
        self.progress_bar.setFixedHeight(9)
        self.progress_percent = QLabel("0%")
        self.progress_percent.setObjectName("progressPercent")

        progress_layout.addWidget(self.progress_label)
        progress_layout.addWidget(self.progress_bar, stretch=1)
        progress_layout.addWidget(self.progress_percent)
        text_layout.addWidget(self.progress_widget)
        text_layout.addStretch(1)

        summary_layout.addLayout(text_layout, stretch=1)
        meta_layout = QVBoxLayout()
        meta_layout.setSpacing(4)
        self.last_checked_label.setAlignment(Qt.AlignmentFlag.AlignRight)
        self.next_check_label.setAlignment(Qt.AlignmentFlag.AlignRight)
        meta_layout.addWidget(self.last_checked_label)
        meta_layout.addWidget(self.next_check_label)
        summary_layout.addLayout(meta_layout)
        layout.addWidget(summary_widget)

        counters_widget = QWidget()
        counters_widget.setObjectName("counterArea")
        self._counters_layout = QGridLayout(counters_widget)
        self._counters_layout.setContentsMargins(0, 0, 0, 0)
        self._counters_layout.setHorizontalSpacing(12)
        self._counters_layout.setVerticalSpacing(12)

        self.counter_labels: dict[str, QLabel] = {}
        self._counter_cards: dict[UpdateSource, CounterCardWidget] = {}
        self._source_descriptors = source_descriptors(self.tr)
        for source in SOURCE_ORDER:
            descriptor = self._source_descriptors[source]
            card_widget = self._create_counter_card(descriptor)
            value_label = card_widget.findChild(QLabel, "counterValue")
            if value_label is not None:
                self.counter_labels[descriptor.counter_key] = value_label
            self._counter_cards[source] = card_widget
        self._sync_visible_cards()
        layout.addWidget(counters_widget)

    def set_system_status(self, text: str) -> None:
        self.system_status_label.setText(text)

    def set_last_checked(self, text: str) -> None:
        self.last_checked_label.setText(text)

    def set_next_check(self, text: str) -> None:
        self.next_check_label.setText(text)
        self.next_check_label.setVisible(bool(text))

    def set_counters(self, counters: UpdateCounters) -> None:
        values = {
            UpdateSource.SYSTEM: counters.system,
            UpdateSource.AUR: counters.aur,
            UpdateSource.FLATPAK: counters.flatpak,
            UpdateSource.PLASMA_WIDGET: counters.plasma_widgets,
            UpdateSource.FIRMWARE: counters.firmware,
        }
        for source, count in values.items():
            key = self._source_descriptors[source].counter_key
            self.counter_labels[key].setText(str(count))
        cleared_filter = self._filter_state.set_counter_values(values)
        self._sync_visible_cards()
        if cleared_filter:
            self.source_filter_changed.emit(None)
        self.set_active_source_filter(self._filter_state.active_source_filter)

    def set_progress(self, label: str, value: int, visible: bool) -> None:
        self.progress_label.setText(label or self.tr("Progress"))
        clamped_value = max(0, min(100, value))
        self.progress_bar.setValue(clamped_value)
        self.progress_percent.setText(f"{clamped_value}%")
        self.progress_widget.setVisible(visible)

    def set_active_source_filter(self, source: UpdateSource | None) -> None:
        active_source = self._filter_state.set_active_source_filter(source)
        for card_source, card in self._counter_cards.items():
            active = card_source is active_source
            card.set_filter_active(active)
            self._filter_badges[card_source].setVisible(active)

    def set_optional_sources_snapshot(self, snapshot: OptionalSourcesSnapshot) -> None:
        cleared_filter = self._filter_state.set_selectable_sources(
            snapshot.selectable_sources
        )
        self._sync_visible_cards()
        if cleared_filter:
            self.source_filter_changed.emit(None)
        self.set_active_source_filter(self._filter_state.active_source_filter)

    def resizeEvent(self, event) -> None:  # type: ignore[override]
        super().resizeEvent(event)
        self._sync_visible_cards()

    def _create_counter_card(
        self,
        descriptor: SourceDescriptor,
    ) -> CounterCardWidget:
        card = CounterCardWidget(descriptor.source, self)
        card.clicked.connect(self._toggle_source_filter)
        card.setAccessibleName(
            self.tr("{source} update filter").format(source=descriptor.counter_title)
        )
        card.setToolTip(
            self.tr("Filter updates by {source}").format(
                source=descriptor.counter_title
            )
        )
        card.setMinimumWidth(descriptor.preferred_card_width)
        card.setFixedHeight(44)

        layout = QHBoxLayout(card)
        layout.setContentsMargins(10, 6, 10, 6)
        layout.setSpacing(12)

        indicator_widget = self._create_counter_indicator(
            descriptor.counter_key,
            descriptor.source,
        )
        if indicator_widget is not None:
            layout.addWidget(
                indicator_widget,
                alignment=Qt.AlignmentFlag.AlignVCenter,
            )

        title_label = QLabel(descriptor.counter_title)
        title_label.setObjectName("counterTitle")
        filter_badge = QLabel("•")
        filter_badge.setObjectName("counterFilterBadge")
        filter_badge.hide()
        value_label = QLabel("0")
        value_label.setObjectName("counterValue")
        value_label.setProperty("sourceKind", descriptor.source.value)
        layout.addWidget(title_label)
        layout.addWidget(filter_badge)
        layout.addStretch(1)
        layout.addWidget(value_label)

        self._filter_badges[descriptor.source] = filter_badge
        return card

    def _toggle_source_filter(self, source: UpdateSource) -> None:
        toggle = self._filter_state.toggle_source_filter(source)
        if not toggle.changed:
            return
        self.set_active_source_filter(toggle.active_source)
        self.source_filter_changed.emit(toggle.active_source)

    def _sync_visible_cards(self) -> None:
        visible_sources = [
            source
            for source in SOURCE_ORDER
            if source in self._filter_state.visible_sources
        ]
        while self._counters_layout.count():
            item = self._counters_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.setParent(None)

        columns = len(visible_sources)
        columns = max(1, columns)

        for index, source in enumerate(visible_sources):
            card = self._counter_cards[source]
            self._counters_layout.addWidget(card, index // columns, index % columns)
            self._counters_layout.setColumnStretch(index % columns, 1)
            card.show()

        for source, card in self._counter_cards.items():
            if source not in visible_sources:
                card.hide()

    def _load_counter_logo(self, key: str) -> QPixmap:
        logo_path = counter_logo_path(key)
        if logo_path is None:
            return QPixmap()
        return QIcon(str(logo_path)).pixmap(22, 22)

    def _create_counter_indicator(
        self,
        key: str,
        source: UpdateSource,
    ) -> QLabel | None:
        label = QLabel()
        label.setObjectName("counterLogoBadge")
        label.setProperty("sourceKind", source.value)
        label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        label.setFixedSize(26, 26)

        if key == "aur":
            label.setText(self.tr("AUR"))
            label.setProperty("badgeKind", "aur")
            return label

        pixmap = self._load_counter_logo(key)
        if pixmap.isNull():
            return None
        label.setPixmap(pixmap)
        return label
