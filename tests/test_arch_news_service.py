from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from archupdater.services.arch_news import ArchNewsService


class ArchNewsServiceTests(unittest.TestCase):
    def test_fetch_parses_rss_items_and_read_state(self) -> None:
        xml = b"""<?xml version="1.0"?>
        <rss><channel><item>
          <title>Manual intervention required</title>
          <link>https://archlinux.org/news/example/</link>
          <guid>news-1</guid>
          <pubDate>Tue, 12 May 2026 10:00:00 +0000</pubDate>
          <description>&lt;p&gt;Read this before updating.&lt;/p&gt;</description>
        </item></channel></rss>"""
        service = ArchNewsService(open_url=lambda _url, _timeout: xml)

        result = service.fetch(read_ids={"news-1"})

        self.assertIsNone(result.warning)
        self.assertEqual(len(result.items), 1)
        self.assertEqual(result.items[0].title, "Manual intervention required")
        self.assertEqual(result.items[0].summary, "Read this before updating.")
        self.assertTrue(result.items[0].read)

    def test_fetch_returns_all_feed_items(self) -> None:
        items = "\n".join(
            f"""
            <item>
              <title>News {index}</title>
              <guid>news-{index}</guid>
              <description>Item {index}</description>
            </item>
            """
            for index in range(12)
        )
        xml = f"<?xml version='1.0'?><rss><channel>{items}</channel></rss>".encode()
        service = ArchNewsService(open_url=lambda _url, _timeout: xml)

        result = service.fetch()

        self.assertEqual(len(result.items), 12)
        self.assertEqual(result.items[-1].item_id, "news-11")

    def test_fetch_returns_warning_when_feed_cannot_be_read(self) -> None:
        def fail(_url: str, _timeout: float) -> bytes:
            raise OSError("network down")

        result = ArchNewsService(open_url=fail).fetch()

        self.assertEqual(result.items, [])
        self.assertIn("network down", result.warning or "")

    def test_fetch_reports_warning_when_feed_is_too_large(self) -> None:
        def too_large(_url: str, _timeout: float) -> bytes:
            raise OSError("Arch Linux news feed is too large.")

        result = ArchNewsService(open_url=too_large).fetch()

        self.assertEqual(result.items, [])
        self.assertIn("too large", result.warning or "")


if __name__ == "__main__":
    unittest.main()
