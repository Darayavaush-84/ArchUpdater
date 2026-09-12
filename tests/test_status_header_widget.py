from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from PySide6.QtWidgets import QApplication, QLabel, QSizePolicy

from archupdater.domain.enums import UpdateSource
from archupdater.domain.optional_sources import OptionalSourceStatus, OptionalSourcesSnapshot
from archupdater.domain.packages import UpdateCounters
from archupdater.presentation.widgets.status_header import StatusHeaderWidget


class StatusHeaderWidgetTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._app = QApplication.instance() or QApplication([])

    def setUp(self) -> None:
        self.widget = StatusHeaderWidget()
        self.events: list[object] = []
        self.widget.source_filter_changed.connect(self.events.append)

    def tearDown(self) -> None:
        self.widget.deleteLater()

    def _click_source(self, source: UpdateSource) -> None:
        card = self.widget._counter_cards[source]
        card.clicked.emit(source)

    def _all_optional_sources_active(self) -> OptionalSourcesSnapshot:
        return OptionalSourcesSnapshot(
            statuses={
                UpdateSource.AUR: OptionalSourceStatus(
                    source=UpdateSource.AUR,
                    installed=True,
                    active=True,
                    status_text="Installed",
                ),
                UpdateSource.FLATPAK: OptionalSourceStatus(
                    source=UpdateSource.FLATPAK,
                    installed=True,
                    active=True,
                    status_text="Installed",
                ),
                UpdateSource.PLASMA_WIDGET: OptionalSourceStatus(
                    source=UpdateSource.PLASMA_WIDGET,
                    installed=True,
                    active=True,
                    status_text="Installed",
                ),
                UpdateSource.FIRMWARE: OptionalSourceStatus(
                    source=UpdateSource.FIRMWARE,
                    installed=True,
                    active=True,
                    status_text="Installed",
                ),
            }
        )

    def test_clicking_kpi_activates_filter(self) -> None:
        self._click_source(UpdateSource.AUR)

        self.assertEqual(self.events[-1], UpdateSource.AUR)
        self.assertTrue(self.widget._counter_cards[UpdateSource.AUR].property("filterActive"))
        self.assertFalse(self.widget._filter_badges[UpdateSource.AUR].isHidden())
        self.assertTrue(self.widget._filter_badges[UpdateSource.FLATPAK].isHidden())

    def test_clicking_active_kpi_clears_filter(self) -> None:
        self._click_source(UpdateSource.AUR)
        self._click_source(UpdateSource.AUR)

        self.assertIsNone(self.events[-1])
        self.assertFalse(self.widget._counter_cards[UpdateSource.AUR].property("filterActive"))
        self.assertTrue(self.widget._filter_badges[UpdateSource.AUR].isHidden())

    def test_clicking_second_kpi_replaces_previous_filter(self) -> None:
        self._click_source(UpdateSource.AUR)
        self._click_source(UpdateSource.PLASMA_WIDGET)

        self.assertEqual(self.events[-1], UpdateSource.PLASMA_WIDGET)
        self.assertFalse(self.widget._counter_cards[UpdateSource.AUR].property("filterActive"))
        self.assertTrue(
            self.widget._counter_cards[UpdateSource.PLASMA_WIDGET].property("filterActive")
        )

    def test_optional_snapshot_hides_inactive_optional_kpis(self) -> None:
        self.widget.set_optional_sources_snapshot(
            OptionalSourcesSnapshot(
                statuses={
                    UpdateSource.AUR: OptionalSourceStatus(
                        source=UpdateSource.AUR,
                        installed=False,
                        active=False,
                        status_text="Missing",
                    ),
                    UpdateSource.FLATPAK: OptionalSourceStatus(
                        source=UpdateSource.FLATPAK,
                        installed=True,
                        active=True,
                        status_text="Installed",
                    ),
                    UpdateSource.PLASMA_WIDGET: OptionalSourceStatus(
                        source=UpdateSource.PLASMA_WIDGET,
                        installed=False,
                        active=False,
                        status_text="Missing",
                    ),
                    UpdateSource.FIRMWARE: OptionalSourceStatus(
                        source=UpdateSource.FIRMWARE,
                        installed=False,
                        active=False,
                        status_text="Missing",
                    ),
                }
            )
        )

        self.assertFalse(self.widget._counter_cards[UpdateSource.SYSTEM].isHidden())
        self.assertTrue(self.widget._counter_cards[UpdateSource.AUR].isHidden())
        self.assertFalse(self.widget._counter_cards[UpdateSource.FLATPAK].isHidden())
        self.assertTrue(self.widget._counter_cards[UpdateSource.PLASMA_WIDGET].isHidden())
        self.assertTrue(self.widget._counter_cards[UpdateSource.FIRMWARE].isHidden())

    def test_snapshot_clears_active_filter_when_source_becomes_unselectable(self) -> None:
        self._click_source(UpdateSource.AUR)

        self.widget.set_optional_sources_snapshot(
            OptionalSourcesSnapshot(
                statuses={
                    UpdateSource.AUR: OptionalSourceStatus(
                        source=UpdateSource.AUR,
                        installed=False,
                        active=False,
                        status_text="Missing",
                    ),
                    UpdateSource.FLATPAK: OptionalSourceStatus(
                        source=UpdateSource.FLATPAK,
                        installed=True,
                        active=True,
                        status_text="Installed",
                    ),
                    UpdateSource.PLASMA_WIDGET: OptionalSourceStatus(
                        source=UpdateSource.PLASMA_WIDGET,
                        installed=True,
                        active=True,
                        status_text="Installed",
                    ),
                    UpdateSource.FIRMWARE: OptionalSourceStatus(
                        source=UpdateSource.FIRMWARE,
                        installed=True,
                        active=True,
                        status_text="Installed",
                    ),
                }
            )
        )

        self.assertIsNone(self.events[-1])
        self.assertFalse(self.widget._counter_cards[UpdateSource.AUR].property("filterActive"))

    def test_firmware_kpi_is_hidden_until_there_are_firmware_updates(self) -> None:
        self.widget.set_optional_sources_snapshot(self._all_optional_sources_active())

        self.assertFalse(self.widget._counter_cards[UpdateSource.SYSTEM].isHidden())
        self.assertFalse(self.widget._counter_cards[UpdateSource.AUR].isHidden())
        self.assertTrue(self.widget._counter_cards[UpdateSource.FIRMWARE].isHidden())

        self.widget.set_counters(UpdateCounters(firmware=1))

        self.assertFalse(self.widget._counter_cards[UpdateSource.FIRMWARE].isHidden())
        self.assertEqual(self.widget.counter_labels["firmware"].text(), "1")

    def test_hidden_firmware_kpi_clears_active_filter_when_count_returns_to_zero(self) -> None:
        self.widget.set_optional_sources_snapshot(self._all_optional_sources_active())
        self.widget.set_counters(UpdateCounters(firmware=1))
        self._click_source(UpdateSource.FIRMWARE)

        self.widget.set_counters(UpdateCounters())

        self.assertIsNone(self.events[-1])
        self.assertTrue(self.widget._counter_cards[UpdateSource.FIRMWARE].isHidden())
        self.assertFalse(
            self.widget._counter_cards[UpdateSource.FIRMWARE].property("filterActive")
        )

    def test_cards_use_expanding_width_with_reasonable_minimums(self) -> None:
        system_card = self.widget._counter_cards[UpdateSource.SYSTEM]
        flatpak_card = self.widget._counter_cards[UpdateSource.FLATPAK]

        self.assertEqual(
            system_card.sizePolicy().horizontalPolicy(),
            QSizePolicy.Policy.Expanding,
        )
        self.assertGreaterEqual(system_card.minimumWidth(), 120)
        self.assertGreaterEqual(flatpak_card.minimumWidth(), 120)

    def test_flatpak_card_does_not_duplicate_app_runtime_breakdown(self) -> None:
        self.widget.set_counters(
            UpdateCounters(
                flatpak=3,
            )
        )

        self.assertEqual(self.widget.counter_labels["flatpak"].text(), "3")
        flatpak_texts = [
            child.text()
            for child in self.widget._counter_cards[UpdateSource.FLATPAK].findChildren(QLabel)
        ]
        self.assertNotIn("Apps 2 | Runtimes 1", flatpak_texts)

    def test_cards_keep_stable_geometry_when_filter_changes(self) -> None:
        self.widget.resize(1180, 180)
        self.widget.show()
        self._app.processEvents()

        self.widget.set_active_source_filter(UpdateSource.SYSTEM)
        self._app.processEvents()
        system_geometry = self.widget._counter_cards[UpdateSource.SYSTEM].geometry()
        aur_geometry = self.widget._counter_cards[UpdateSource.AUR].geometry()

        self.widget.set_active_source_filter(UpdateSource.AUR)
        self._app.processEvents()

        self.assertEqual(
            self.widget._counter_cards[UpdateSource.SYSTEM].geometry(),
            system_geometry,
        )
        self.assertEqual(
            self.widget._counter_cards[UpdateSource.AUR].geometry(),
            aur_geometry,
        )
        self.assertEqual(system_geometry.height(), 44)
        self.assertEqual(aur_geometry.height(), 44)


if __name__ == "__main__":
    unittest.main()
