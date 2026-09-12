from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import QApplication
from PySide6.QtWidgets import QStyle

from archupdater.domain.enums import UpdateSource
from archupdater.domain.package_metadata import (
    AurPackageMetadata,
    PlasmaWidgetPackageMetadata,
    SystemPackageMetadata,
)
from archupdater.domain.packages import PackageUpdate
from archupdater.presentation.widgets.package_details_panel import PackageDetailsPanel


class PackageDetailsPanelTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._app = QApplication.instance() or QApplication([])

    def setUp(self) -> None:
        self.panel = PackageDetailsPanel()

    def tearDown(self) -> None:
        self.panel.deleteLater()

    def test_set_package_renders_author_and_store_link(self) -> None:
        package = PackageUpdate(
            name="Example Widget",
            current_version="1.0",
            new_version="1.1",
            source=UpdateSource.PLASMA_WIDGET,
            source_metadata=PlasmaWidgetPackageMetadata(
                content_id="5555",
                repository="KDE Store",
                package_kind="KWin/Script",
            ),
            author="example-author",
            homepage="https://store.kde.org/p/5555",
            description="Store summary",
        )

        self.panel.set_package(
            package,
            source_text="KDE Store Add-ons",
            unavailable_text="Unavailable",
            no_description_text="No description available.",
        )

        self.assertEqual(self.panel._detail_author.text(), "example-author")
        self.assertIn("https://store.kde.org/p/5555", self.panel._detail_homepage.text())
        self.assertEqual(self.panel._technical_rows["kind"][1].text(), "KWin Script")

    def test_show_placeholder_uses_centered_empty_state(self) -> None:
        self.panel.show_placeholder(
            title="Up to Date",
            text="No updates are available right now.",
            icon=QStyle.StandardPixmap.SP_DialogApplyButton,
        )

        self.assertTrue(self.panel._title_row_widget.isHidden())
        self.assertFalse(self.panel._placeholder_widget.isHidden())
        self.assertEqual(self.panel._placeholder_title.text(), "Up to Date")
        self.assertEqual(self.panel._details_placeholder.text(), "No updates are available right now.")
        self.assertGreaterEqual(self.panel._placeholder_content.minimumWidth(), 320)

    def test_wrapped_placeholder_title_gets_enough_height(self) -> None:
        self.panel.resize(420, 320)
        self.panel.show_placeholder(
            title="Ricerca aggiornamenti in corso...",
            text="",
            icon=QStyle.StandardPixmap.SP_BrowserReload,
        )
        self.panel.show()
        self._app.processEvents()

        title = self.panel._placeholder_title
        expected_height = title.heightForWidth(max(title.width(), 1))
        self.assertGreaterEqual(title.minimumHeight(), expected_height)

    def test_repeated_placeholder_refresh_keeps_empty_state_geometry_stable(self) -> None:
        self.panel.resize(424, 416)
        self.panel.show()
        self._process_events()

        geometries = []
        for _ in range(6):
            self.panel.show_placeholder(
                title="Package Details",
                text="Select an update to view details",
                icon=QStyle.StandardPixmap.SP_FileDialogDetailedView,
            )
            self._process_events()
            geometries.append(
                (
                    self.panel._placeholder_icon.geometry(),
                    self.panel._placeholder_title.geometry(),
                    self.panel._details_placeholder.geometry(),
                    self.panel._placeholder_content.geometry(),
                )
            )

        self.assertEqual(len(set(geometries)), 1)

    def test_placeholder_refresh_after_width_changes_does_not_accumulate_vertical_offset(self) -> None:
        self.panel.show()
        self._process_events()

        geometries = []
        for width in (424, 390, 424, 390, 424, 390):
            self.panel.resize(width, 416)
            self.panel.show_placeholder(
                title="Package Details",
                text="Select an update to view details",
                icon=QStyle.StandardPixmap.SP_FileDialogDetailedView,
            )
            self._process_events()
            geometries.append(
                (
                    self.panel._placeholder_icon.y(),
                    self.panel._placeholder_title.y(),
                    self.panel._details_placeholder.y(),
                )
            )

        first_424 = geometries[0]
        repeated_424 = [geometries[index] for index in (0, 2, 4)]
        repeated_390 = [geometries[index] for index in (1, 3, 5)]
        self.assertEqual(repeated_424, [first_424, first_424, first_424])
        self.assertEqual(len(set(repeated_390)), 1)

    def test_non_widget_package_shows_url_and_update_summary(self) -> None:
        package = PackageUpdate(
            name="paru-bin",
            current_version="2.0",
            new_version="2.1",
            source=UpdateSource.AUR,
            source_metadata=AurPackageMetadata(repository="AUR"),
            homepage="https://aur.archlinux.org/packages/paru-bin",
            download_size="2.4 MiB",
            installed_size="8.1 MiB",
            dependencies=["pacman", "git"],
        )

        self.panel.set_package(
            package,
            source_text="AUR",
            unavailable_text="Unavailable",
            no_description_text="No description available.",
        )

        self.assertIn("https://aur.archlinux.org/packages/paru-bin", self.panel._detail_homepage.text())
        self.assertEqual(self.panel._metric_cards["current"][2].text(), "2.0")
        self.assertEqual(self.panel._metric_cards["new"][2].text(), "2.1")
        self.assertEqual(self.panel._metric_cards["download"][2].text(), "2.4 MiB")
        self.assertEqual(self.panel._metric_cards["installed"][2].text(), "8.1 MiB")
        self.assertFalse(self.panel._list_sections["dependencies"][0].isHidden())
        self.assertTrue(self.panel._list_sections["dependencies"][2].isHidden())
        self.assertIn("Dependencies (2)", self.panel._list_section_toggles["dependencies"].text())
        self.assertEqual(
            self.panel._list_section_toggles["dependencies"].arrowType(),
            Qt.ArrowType.RightArrow,
        )

    def test_external_metadata_is_rendered_as_plain_text_and_homepage_is_sanitized(self) -> None:
        package = PackageUpdate(
            name="<b>not-bold</b>",
            current_version="1",
            new_version="2",
            source=UpdateSource.AUR,
            source_metadata=AurPackageMetadata(),
            description="<i>plain description</i>",
            homepage='javascript:alert("bad")',
            dependencies=["<script>alert(1)</script>"],
        )

        self.panel.set_package(
            package,
            source_text="AUR",
            unavailable_text="Unavailable",
            no_description_text="No description available.",
        )

        self.assertEqual(self.panel._detail_name.textFormat(), Qt.TextFormat.PlainText)
        self.assertEqual(self.panel._detail_description.textFormat(), Qt.TextFormat.PlainText)
        self.assertTrue(self.panel._detail_homepage.isHidden())
        self.panel._list_section_toggles["dependencies"].click()
        chips_layout = self.panel._list_sections["dependencies"][3]
        first_chip = chips_layout.itemAt(0).widget()
        assert first_chip is not None
        self.assertEqual(first_chip.textFormat(), Qt.TextFormat.PlainText)
        self.assertEqual(first_chip.text(), "<script>alert(1)</script>")

    def test_https_homepage_is_escaped_before_becoming_link(self) -> None:
        package = PackageUpdate(
            name="safe",
            current_version="1",
            new_version="2",
            source=UpdateSource.AUR,
            source_metadata=AurPackageMetadata(),
            homepage='https://example.test/?q=<tag>&x="quote"',
        )

        self.panel.set_package(
            package,
            source_text="AUR",
            unavailable_text="Unavailable",
            no_description_text="No description available.",
        )

        link_text = self.panel._detail_homepage.text()
        self.assertIn("&lt;tag&gt;", link_text)
        self.assertIn("&quot;quote&quot;", link_text)
        self.assertNotIn('x="quote"', link_text)

    def test_https_homepage_without_host_is_hidden(self) -> None:
        package = PackageUpdate(
            name="unsafe",
            current_version="1",
            new_version="2",
            source=UpdateSource.AUR,
            source_metadata=AurPackageMetadata(),
            homepage="https:missing-host",
        )

        self.panel.set_package(
            package,
            source_text="AUR",
            unavailable_text="Unavailable",
            no_description_text="No description available.",
        )

        self.assertTrue(self.panel._detail_homepage.isHidden())

    def test_selecting_package_resets_details_scroll_to_top(self) -> None:
        package = PackageUpdate(
            name="linux",
            current_version="1",
            new_version="2",
            source=UpdateSource.SYSTEM,
            source_metadata=SystemPackageMetadata(),
            description="Kernel",
            dependencies=[f"dep-{index}" for index in range(30)],
        )
        self.panel.resize(420, 240)
        self.panel.show()
        self.panel.set_package(
            package,
            source_text="Pacman",
            unavailable_text="Unavailable",
            no_description_text="No description available.",
        )
        self._process_events()
        scrollbar = self.panel._details_scroll.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())
        self.assertGreater(scrollbar.value(), 0)

        QTimer.singleShot(0, lambda: None)
        self.panel.set_package(
            PackageUpdate(
                name="mesa",
                current_version="1",
                new_version="2",
                source=UpdateSource.SYSTEM,
                source_metadata=SystemPackageMetadata(),
                description="Graphics stack",
            ),
            source_text="Pacman",
            unavailable_text="Unavailable",
            no_description_text="No description available.",
        )
        self._process_events()

        self.assertEqual(scrollbar.value(), 0)

    def test_details_panel_does_not_create_horizontal_overflow(self) -> None:
        package = PackageUpdate(
            name="linux-cachyos-lts-headers",
            current_version="6.18.28-2",
            new_version="6.18.29-1",
            source=UpdateSource.SYSTEM,
            source_metadata=SystemPackageMetadata(repository="cachyos-znver4"),
            description=(
                "Headers and scripts for building modules for the Linux BORE + Cachy Sauce "
                "Kernel by CachyOS with other patches and improvements - Long Term Service kernel"
            ),
            download_size="58.62 MiB",
            installed_size="266.03 MiB",
            current_installed_size="266.03 MiB",
            size_diff="0 B",
            dependencies=[
                f"very-long-dependency-name-{index}-with-extra-details-and-version>=1.2.3"
                for index in range(12)
            ],
        )

        self.panel.resize(420, 360)
        self.panel.show()
        self.panel.set_package(
            package,
            source_text="Pacman",
            unavailable_text="Unavailable",
            no_description_text="No description available.",
        )
        self._process_events()
        self.panel._list_section_toggles["dependencies"].click()
        self._process_events()

        self.assertEqual(self.panel._details_scroll.horizontalScrollBar().maximum(), 0)
        self.assertLessEqual(
            self.panel._details_widget.width(),
            self.panel._details_scroll.viewport().width(),
        )

    def test_dependency_chips_are_sized_to_their_text(self) -> None:
        package = PackageUpdate(
            name="linux-cachyos-lts-headers",
            current_version="1",
            new_version="2",
            source=UpdateSource.SYSTEM,
            source_metadata=SystemPackageMetadata(),
            dependencies=["binutils", "glibc", "linux-cachyos-lts"],
        )

        self.panel.resize(830, 520)
        self.panel.show()
        self.panel.set_package(
            package,
            source_text="Pacman",
            unavailable_text="Unavailable",
            no_description_text="No description available.",
        )
        self._process_events()
        self.panel._list_section_toggles["dependencies"].click()
        self._process_events()

        chips_layout = self.panel._list_sections["dependencies"][3]
        first_chip = chips_layout.itemAt(0).widget()

        assert first_chip is not None
        self.assertLess(first_chip.width(), self.panel._details_scroll.viewport().width() // 3)

    def test_optional_dependencies_are_collapsed_by_default_and_expandable(self) -> None:
        package = PackageUpdate(
            name="example",
            current_version="1",
            new_version="2",
            source=UpdateSource.SYSTEM,
            source_metadata=SystemPackageMetadata(),
            optional_dependencies=["python: scripts", "git: source checkout"],
        )

        self.panel.set_package(
            package,
            source_text="Pacman",
            unavailable_text="Unavailable",
            no_description_text="No description available.",
        )

        section, caption, chips_widget, chips_layout = self.panel._list_sections["optional_dependencies"]
        toggle = self.panel._list_section_toggles["optional_dependencies"]

        self.assertFalse(section.isHidden())
        self.assertIn("(2)", caption.text())
        self.assertTrue(chips_widget.isHidden())
        self.assertEqual(toggle.arrowType(), Qt.ArrowType.RightArrow)
        self.assertIn("Optional Dependencies (2)", toggle.text())

        toggle.click()
        self._process_events()

        self.assertFalse(chips_widget.isHidden())
        self.assertEqual(toggle.arrowType(), Qt.ArrowType.DownArrow)
        self.assertEqual(chips_layout.count(), 2)

    def test_aur_build_dependency_sections_are_collapsed_by_default_and_expandable(self) -> None:
        package = PackageUpdate(
            name="example-aur",
            current_version="1",
            new_version="2",
            source=UpdateSource.AUR,
            source_metadata=AurPackageMetadata(
                make_dependencies=["rust", "cmake"],
                check_dependencies=["python-pytest"],
            ),
        )

        self.panel.set_package(
            package,
            source_text="AUR",
            unavailable_text="Unavailable",
            no_description_text="No description available.",
        )

        for key, title, count in (
            ("make_dependencies", "Make Dependencies", 2),
            ("check_dependencies", "Check Dependencies", 1),
        ):
            section, _caption, chips_widget, chips_layout = self.panel._list_sections[key]
            toggle = self.panel._list_section_toggles[key]

            self.assertFalse(section.isHidden())
            self.assertTrue(chips_widget.isHidden())
            self.assertEqual(toggle.arrowType(), Qt.ArrowType.RightArrow)
            self.assertIn(f"{title} ({count})", toggle.text())

            toggle.click()
            self._process_events()

            self.assertFalse(chips_widget.isHidden())
            self.assertEqual(toggle.arrowType(), Qt.ArrowType.DownArrow)
            self.assertEqual(chips_layout.count(), count)

    def test_collapsible_dependency_sections_reset_when_package_changes(self) -> None:
        first = PackageUpdate(
            name="first",
            current_version="1",
            new_version="2",
            source=UpdateSource.AUR,
            source_metadata=AurPackageMetadata(
                make_dependencies=["rust"],
                check_dependencies=["python-pytest"],
            ),
            dependencies=["glibc"],
        )
        second = PackageUpdate(
            name="second",
            current_version="1",
            new_version="2",
            source=UpdateSource.AUR,
            source_metadata=AurPackageMetadata(
                make_dependencies=["cmake"],
                check_dependencies=["pytest"],
            ),
            dependencies=["mesa"],
        )

        for package in (first, second):
            self.panel.set_package(
                package,
                source_text="AUR",
                unavailable_text="Unavailable",
                no_description_text="No description available.",
            )
            if package is first:
                for key in ("dependencies", "make_dependencies", "check_dependencies"):
                    self.panel._list_section_toggles[key].click()
                self._process_events()

        for key in ("dependencies", "make_dependencies", "check_dependencies"):
            self.assertTrue(self.panel._list_sections[key][2].isHidden())
            self.assertEqual(
                self.panel._list_section_toggles[key].arrowType(),
                Qt.ArrowType.RightArrow,
            )

    def test_optional_dependencies_reappear_after_package_without_optional_deps(self) -> None:
        empty = PackageUpdate(
            name="empty",
            current_version="1",
            new_version="2",
            source=UpdateSource.SYSTEM,
            source_metadata=SystemPackageMetadata(),
        )
        with_optional = PackageUpdate(
            name="with-optional",
            current_version="1",
            new_version="2",
            source=UpdateSource.SYSTEM,
            source_metadata=SystemPackageMetadata(),
            optional_dependencies=["python: scripts"],
        )

        for package in (empty, with_optional):
            self.panel.set_package(
                package,
                source_text="Pacman",
                unavailable_text="Unavailable",
                no_description_text="No description available.",
            )

        section, _caption, chips_widget, chips_layout = self.panel._list_sections[
            "optional_dependencies"
        ]
        toggle = self.panel._list_section_toggles["optional_dependencies"]

        self.assertFalse(section.isHidden())
        self.assertTrue(chips_widget.isHidden())
        self.assertEqual(chips_layout.count(), 1)
        self.assertIn("Optional Dependencies (1)", toggle.text())
        self.assertEqual(toggle.arrowType(), Qt.ArrowType.RightArrow)

    def _process_events(self) -> None:
        for _ in range(30):
            self._app.processEvents()


if __name__ == "__main__":
    unittest.main()
