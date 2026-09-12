from __future__ import annotations

import sys
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from archupdater.services.plasma_widgets_store import (
    PlasmaWidgetsStoreClient,
    StoreWidgetDetail,
    StoreWidgetDownload,
)


class PlasmaWidgetsStoreClientTests(unittest.TestCase):
    def setUp(self) -> None:
        self.client = PlasmaWidgetsStoreClient()

    def _detail(self, downloads: list[StoreWidgetDownload]) -> StoreWidgetDetail:
        return StoreWidgetDetail(
            content_id="5555",
            name="Example Widget",
            version="1.3.0",
            summary="Store summary",
            type_label="Plasma/Applet",
            author="example-author",
            detail_url="https://store.kde.org/p/5555",
            downloads=downloads,
        )

    def test_choose_download_returns_single_available_download(self) -> None:
        detail = self._detail(
            [
                StoreWidgetDownload(
                    url="https://example.test/widget.zip",
                    name="widget.zip",
                    version="",
                )
            ]
        )

        chosen = self.client.choose_download(detail)

        self.assertEqual(chosen.url, "https://example.test/widget.zip")

    def test_choose_download_rejects_single_download_with_mismatched_version(self) -> None:
        detail = self._detail(
            [
                StoreWidgetDownload(
                    url="https://example.test/widget.zip",
                    name="widget.zip",
                    version="1.2.0",
                )
            ]
        )

        with self.assertRaisesRegex(OSError, "does not match the advertised update"):
            self.client.choose_download(detail)

    def test_choose_download_requires_unique_exact_version_match(self) -> None:
        detail = self._detail(
            [
                StoreWidgetDownload(
                    url="https://example.test/widget-v1.zip",
                    name="widget-v1.zip",
                    version="1.3.0",
                ),
                StoreWidgetDownload(
                    url="https://example.test/widget-v2.zip",
                    name="widget-v2.zip",
                    version="1.3.0",
                ),
            ]
        )

        with self.assertRaisesRegex(OSError, "could not choose one safely"):
            self.client.choose_download(detail)

    def test_choose_download_rejects_ambiguous_downloads_without_exact_match(self) -> None:
        detail = self._detail(
            [
                StoreWidgetDownload(
                    url="https://example.test/widget-a.zip",
                    name="widget-a.zip",
                    version="1.2.9",
                ),
                StoreWidgetDownload(
                    url="https://example.test/widget-b.zip",
                    name="widget-b.zip",
                    version="",
                ),
            ]
        )

        with self.assertRaisesRegex(OSError, "could not choose one safely"):
            self.client.choose_download(detail)

    def test_clean_version_preserves_prerelease_tokens(self) -> None:
        self.assertEqual(self.client._clean_version("v2.0-beta1"), "2.0-beta1")

    def test_fetch_listing_rejects_repeated_pages(self) -> None:
        page = ET.fromstring(
            """
            <ocs>
              <meta><statuscode>100</statuscode><totalitems>2</totalitems></meta>
              <data><content><id>5555</id><name>Widget</name><version>1.0</version></content></data>
            </ocs>
            """
        )
        self.client._fetch_xml = lambda _url: page  # type: ignore[method-assign]

        with self.assertRaisesRegex(OSError, "temporarily unavailable"):
            self.client.fetch_listing()

    def test_fetch_details_rejects_invalid_content_id_before_network_access(self) -> None:
        with self.assertRaisesRegex(OSError, "incomplete or incompatible"):
            self.client.fetch_details("../unexpected")


if __name__ == "__main__":
    unittest.main()
