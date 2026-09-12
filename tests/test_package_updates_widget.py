from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QLabel

from archupdater.domain.enums import FlatpakRefKind, UpdateSource
from archupdater.domain.package_metadata import (
    AurPackageMetadata,
    FlatpakPackageMetadata,
    PlasmaWidgetPackageMetadata,
    SystemPackageMetadata,
)
from archupdater.domain.packages import PackageUpdate
from archupdater.presentation.widgets.package_updates_widget import PackageUpdatesWidget


class _IconResolverStub:
    def icon_path_for(self, _package: PackageUpdate) -> None:
        return None


class PackageUpdatesWidgetTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._app = QApplication.instance() or QApplication([])

    def setUp(self) -> None:
        self.widget = PackageUpdatesWidget(
            icon_resolver=_IconResolverStub(),  # type: ignore[arg-type]
        )
        self.selected_events: list[tuple[str, bool]] = []
        self.current_packages: list[object] = []
        self.widget.package_selection_changed.connect(
            lambda package_id, selected: self.selected_events.append((package_id, selected))
        )
        self.widget.current_package_changed.connect(self.current_packages.append)
        packages = [
            PackageUpdate(
                name="linux",
                current_version="1",
                new_version="2",
                source=UpdateSource.SYSTEM,
                source_metadata=SystemPackageMetadata(repository="core"),
                description="Kernel package",
                blocked_by_config=True,
                blocked_reason="Blocked by pacman.conf",
                selected=False,
                selection_locked=True,
            ),
            PackageUpdate(
                name="flatseal",
                current_version="2.2.0",
                new_version="2.3.0",
                source=UpdateSource.FLATPAK,
                source_metadata=FlatpakPackageMetadata(
                    ref="flatseal",
                    ref_kind=FlatpakRefKind.APP,
                    repository="flathub",
                ),
                description="Manage Flatpak permissions",
                selected=True,
            ),
            PackageUpdate(
                name="paru-pkg",
                current_version="1.0",
                new_version="1.1",
                source=UpdateSource.AUR,
                source_metadata=AurPackageMetadata(repository="AUR"),
                description="AUR helper package",
                selected=True,
            ),
            PackageUpdate(
                name="widget-kde",
                current_version="1.0",
                new_version="1.1",
                source=UpdateSource.PLASMA_WIDGET,
                source_metadata=PlasmaWidgetPackageMetadata(
                    content_id="5555",
                    repository="KDE Store",
                    package_kind="Plasma/Applet",
                    plugin_id="com.example.widget",
                ),
                description="KDE Store widget",
                backend_id="5555",
                selected=True,
            ),
            PackageUpdate(
                name="glibc",
                current_version="2.41",
                new_version="2.42",
                source=UpdateSource.SYSTEM,
                source_metadata=SystemPackageMetadata(repository="core"),
                description="Core C library",
                selected=True,
            ),
        ]
        self.widget.set_packages(
            packages,
            source_texts={
                UpdateSource.SYSTEM: "Pacman",
                UpdateSource.AUR: "AUR",
                UpdateSource.FLATPAK: "Flatpak",
                UpdateSource.FIRMWARE: "Firmware",
                UpdateSource.PLASMA_WIDGET: "KDE Store Add-ons",
            },
            system_tooltip="system updates are locked",
        )

    def tearDown(self) -> None:
        self.widget.deleteLater()

    def _visible_package_names(self) -> list[str]:
        return [
            self.widget.tree.topLevelItem(index).text(0)
            for index in range(self.widget.tree.topLevelItemCount())
            if not self.widget.tree.topLevelItem(index).isHidden()
        ]

    def _package_names(self) -> list[str]:
        return [
            self.widget.tree.topLevelItem(index).text(0)
            for index in range(self.widget.tree.topLevelItemCount())
        ]

    def _item_by_name(self, name: str):
        for index in range(self.widget.tree.topLevelItemCount()):
            item = self.widget.tree.topLevelItem(index)
            if item.text(0) == name:
                return item
        self.fail(f"Package row not found: {name}")

    def test_initial_state_has_no_selected_package(self) -> None:
        self.assertTrue(self.current_packages)
        self.assertIsNone(self.current_packages[-1])
        self.assertEqual(self.widget.tree.selectedItems(), [])

    def test_empty_result_shows_illustrated_up_to_date_state(self) -> None:
        self.widget.set_packages(
            [],
            source_texts={source: source.value for source in UpdateSource},
            system_tooltip="",
        )

        self.assertIs(
            self.widget.content_stack.currentWidget(),
            self.widget.empty_state_widget,
        )
        illustration = self.widget.empty_state_widget.findChild(
            QLabel,
            "updatesEmptyIllustration",
        )
        self.assertIsNotNone(illustration)
        assert illustration is not None
        self.assertFalse(illustration.pixmap().isNull())

    def test_source_column_is_shown_between_package_and_version(self) -> None:
        item = self._item_by_name("linux")

        self.assertEqual(self.widget.tree.headerItem().text(0), "Package")
        self.assertEqual(self.widget.tree.headerItem().text(1), "Source")
        self.assertEqual(self.widget.tree.headerItem().text(2), "Version")
        self.assertEqual(item.text(0), "linux")
        self.assertEqual(item.text(1), "Pacman")
        self.assertEqual(item.text(2), "1 -> 2")

    def test_flatpak_source_column_shows_ref_kind(self) -> None:
        item = self._item_by_name("flatseal")

        self.assertEqual(item.text(1), "Flatpak - App")

    def test_package_rows_get_an_icon(self) -> None:
        item = self._item_by_name("linux")

        self.assertFalse(item.icon(0).isNull())

    def test_package_header_sorts_by_name_and_toggles_direction(self) -> None:
        self.assertEqual(
            self._package_names(),
            ["flatseal", "glibc", "linux", "paru-pkg", "widget-kde"],
        )
        self.assertEqual(
            self.widget.tree.header().sortIndicatorOrder(),
            Qt.SortOrder.AscendingOrder,
        )

        self.widget.tree.header().sectionClicked.emit(0)

        self.assertEqual(
            self._package_names(),
            ["widget-kde", "paru-pkg", "linux", "glibc", "flatseal"],
        )
        self.assertEqual(
            self.widget.tree.header().sortIndicatorOrder(),
            Qt.SortOrder.DescendingOrder,
        )

        self.widget.tree.header().sectionClicked.emit(0)

        self.assertEqual(
            self._package_names(),
            ["flatseal", "glibc", "linux", "paru-pkg", "widget-kde"],
        )
        self.assertEqual(
            self.widget.tree.header().sortIndicatorOrder(),
            Qt.SortOrder.AscendingOrder,
        )

    def test_filter_hides_non_matching_rows_and_selects_first_visible(self) -> None:
        self.widget.search_input.setText("flatpak permissions")

        self.assertEqual(self._visible_package_names(), ["flatseal"])
        self.assertEqual(self.widget.tree.currentItem().text(0), "flatseal")

    def test_unchecking_regular_package_updates_model_and_emits_signal(self) -> None:
        item = self._item_by_name("flatseal")

        item.setCheckState(0, Qt.CheckState.Unchecked)

        self.assertEqual(self.selected_events[-1], ("flatpak:system:flatseal", False))

    def test_locked_package_cannot_be_unchecked(self) -> None:
        item = self._item_by_name("linux")

        item.setCheckState(0, Qt.CheckState.Unchecked)

        self.assertEqual(item.checkState(0), Qt.CheckState.Unchecked)
        self.assertEqual(self.selected_events, [])

    def test_ignored_package_exposes_note_and_tooltip(self) -> None:
        item = self._item_by_name("linux")

        self.assertFalse(self.widget.ignored_note_label.isHidden())
        self.assertEqual(item.toolTip(0), "Blocked by pacman.conf")

    def test_skipped_aur_package_exposes_note_and_tooltip(self) -> None:
        self.widget.set_packages(
            [
                PackageUpdate(
                    name="paru-pkg",
                    current_version="1.0",
                    new_version="1.1",
                    source=UpdateSource.AUR,
                    source_metadata=AurPackageMetadata(repository="AUR"),
                    selected=False,
                    selection_locked=True,
                    selection_lock_reason="PKGBUILD review was cancelled.",
                    skipped_by_pkgbuild_review=True,
                )
            ],
            source_texts={
                UpdateSource.SYSTEM: "Pacman",
                UpdateSource.AUR: "AUR",
                UpdateSource.FLATPAK: "Flatpak",
                UpdateSource.FIRMWARE: "Firmware",
                UpdateSource.PLASMA_WIDGET: "KDE Store Add-ons",
            },
            system_tooltip="system updates are locked",
        )

        item = self._item_by_name("paru-pkg")

        self.assertFalse(self.widget.aur_skipped_note_label.isHidden())
        self.assertEqual(item.toolTip(0), "PKGBUILD review was cancelled.")

    def test_source_filter_shows_only_matching_category(self) -> None:
        self.widget.set_source_filter(UpdateSource.FLATPAK)

        self.assertEqual(self._visible_package_names(), ["flatseal"])

    def test_deselect_visible_only_changes_currently_visible_unlocked_packages(self) -> None:
        self.widget.set_source_filter(UpdateSource.FLATPAK)

        self.widget.deselect_visible_packages()

        self.assertEqual(self._item_by_name("flatseal").checkState(0), Qt.CheckState.Unchecked)
        self.assertEqual(self._item_by_name("paru-pkg").checkState(0), Qt.CheckState.Checked)
        self.assertEqual(self.selected_events[-1], ("flatpak:system:flatseal", False))

    def test_select_visible_only_changes_currently_visible_unlocked_packages(self) -> None:
        flatpak_item = self._item_by_name("flatseal")
        aur_item = self._item_by_name("paru-pkg")
        flatpak_item.setCheckState(0, Qt.CheckState.Unchecked)
        aur_item.setCheckState(0, Qt.CheckState.Unchecked)
        self.selected_events.clear()
        self.widget.set_source_filter(UpdateSource.FLATPAK)

        self.widget.select_visible_packages()

        self.assertEqual(flatpak_item.checkState(0), Qt.CheckState.Checked)
        self.assertEqual(aur_item.checkState(0), Qt.CheckState.Unchecked)
        self.assertEqual(self.selected_events, [("flatpak:system:flatseal", True)])

    def test_deselect_visible_respects_locked_packages(self) -> None:
        self.widget.set_source_filter(UpdateSource.SYSTEM)

        self.widget.deselect_visible_packages()

        self.assertEqual(self._item_by_name("linux").checkState(0), Qt.CheckState.Unchecked)
        self.assertEqual(self._item_by_name("glibc").checkState(0), Qt.CheckState.Unchecked)
        self.assertEqual(self.selected_events[-1], ("system::glibc", False))

    def test_source_filter_and_search_are_combined(self) -> None:
        self.widget.set_source_filter(UpdateSource.AUR)
        self.widget.search_input.setText("helper")

        self.assertEqual(self._visible_package_names(), ["paru-pkg"])
        self.assertEqual(self.widget.tree.currentItem().text(0), "paru-pkg")

    def test_resetting_source_filter_restores_full_list(self) -> None:
        self.widget.set_source_filter(UpdateSource.FLATPAK)
        self.widget.set_source_filter(None)

        self.assertEqual(
            self._visible_package_names(),
            ["flatseal", "glibc", "linux", "paru-pkg", "widget-kde"],
        )
        self.assertEqual(self.widget.title_label.text(), "All Updates")

    def test_widget_package_can_be_unchecked_like_other_optional_updates(self) -> None:
        item = self._item_by_name("widget-kde")

        self.assertEqual(item.checkState(0), Qt.CheckState.Checked)
        item.setCheckState(0, Qt.CheckState.Unchecked)

        self.assertEqual(item.checkState(0), Qt.CheckState.Unchecked)
        self.assertEqual(self.selected_events[-1], ("plasma_widget::5555", False))

    def test_widget_source_filter_updates_title(self) -> None:
        self.widget.set_source_filter(UpdateSource.PLASMA_WIDGET)

        self.assertEqual(self._visible_package_names(), ["widget-kde"])
        self.assertEqual(self.widget.title_label.text(), "KDE Store Add-on Updates")

    def test_kde_store_addon_row_shows_addon_type(self) -> None:
        item = self._item_by_name("widget-kde")

        self.assertEqual(item.text(1), "KDE Store Add-ons - Plasma Widget")

    def test_pacman_packages_are_toggled_as_one_source(self) -> None:
        packages = [
            PackageUpdate(
                name=name,
                current_version="1",
                new_version="2",
                source=UpdateSource.SYSTEM,
                source_metadata=SystemPackageMetadata(repository="core"),
            )
            for name in ("glibc", "mesa")
        ]
        self.widget.set_packages(
            packages,
            source_texts={source: source.value for source in UpdateSource},
            system_tooltip="Pacman updates are installed together",
        )
        self.selected_events.clear()

        self._item_by_name("glibc").setCheckState(0, Qt.CheckState.Unchecked)

        self.assertEqual(
            self._item_by_name("mesa").checkState(0),
            Qt.CheckState.Unchecked,
        )
        self.assertEqual(
            set(self.selected_events),
            {("system::glibc", False), ("system::mesa", False)},
        )


if __name__ == "__main__":
    unittest.main()
