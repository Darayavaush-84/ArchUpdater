from __future__ import annotations

import sys
import json
import unittest
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from PySide6.QtCore import QSettings

from archupdater.domain.arch_news import ArchNewsItem
from archupdater.infrastructure.app_state_cache import AppStateCache


class AppStateCacheTests(unittest.TestCase):
    def setUp(self) -> None:
        self.settings = QSettings(QSettings.Format.IniFormat, QSettings.Scope.UserScope, "ArchUpdaterTests", self.id())
        self.settings.clear()
        self.cache = AppStateCache(self.settings)

    def tearDown(self) -> None:
        self.settings.clear()
        self.settings.sync()

    def test_arch_news_read_ids_round_trip(self) -> None:
        self.cache.save_read_arch_news_ids({"news-2", "news-1"})

        self.assertEqual(self.cache.load_read_arch_news_ids(), {"news-1", "news-2"})

    def test_arch_news_history_round_trip(self) -> None:
        self.cache.store_arch_news_items(
            [
                ArchNewsItem(
                    item_id="news-1",
                    title="Manual intervention",
                    published_at=datetime(2026, 4, 2, 9, 0, 0),
                    url="https://archlinux.org/news/news-1/",
                    summary="Read before updating.",
                    read=True,
                )
            ]
        )

        restored = self.cache.load_arch_news_items()

        self.assertEqual(len(restored), 1)
        self.assertEqual(restored[0].item_id, "news-1")
        self.assertEqual(restored[0].published_at, datetime(2026, 4, 2, 9, 0, 0))
        self.assertTrue(restored[0].read)

    def test_arch_news_history_merges_new_items_without_losing_existing_items(self) -> None:
        self.cache.store_arch_news_items(
            [
                ArchNewsItem(
                    "news-1",
                    "Older news",
                    published_at=datetime(2026, 4, 1, 9, 0, 0),
                )
            ]
        )
        self.cache.store_arch_news_items(
            [
                ArchNewsItem(
                    "news-2",
                    "Newer news",
                    published_at=datetime(2026, 4, 3, 9, 0, 0),
                )
            ]
        )

        self.assertEqual(
            [item.item_id for item in self.cache.load_arch_news_items()],
            ["news-2", "news-1"],
        )

    def test_cached_string_false_is_not_treated_as_read(self) -> None:
        self.settings.setValue(
            AppStateCache.ARCH_NEWS_ITEMS_KEY,
            json.dumps([{"item_id": "news-1", "title": "News", "read": "false"}]),
        )

        restored = self.cache.load_arch_news_items()

        self.assertEqual(len(restored), 1)
        self.assertFalse(restored[0].read)

    def test_arch_news_sorting_accepts_mixed_timezone_and_missing_dates(self) -> None:
        self.cache.store_arch_news_items(
            [
                ArchNewsItem("undated", "Undated"),
                ArchNewsItem(
                    "dated",
                    "Dated",
                    published_at=datetime(2026, 4, 3, 9, 0, tzinfo=timezone.utc),
                ),
            ]
        )

        self.assertEqual(
            [item.item_id for item in self.cache.load_arch_news_items()],
            ["dated", "undated"],
        )

    def test_deleted_arch_news_items_are_hidden_and_not_reintroduced(self) -> None:
        self.cache.store_arch_news_items(
            [
                ArchNewsItem("news-1", "Keep"),
                ArchNewsItem("news-2", "Delete"),
            ]
        )

        self.cache.delete_arch_news_items({"news-2"})
        self.cache.store_arch_news_items([ArchNewsItem("news-2", "Delete")])

        self.assertEqual([item.item_id for item in self.cache.load_arch_news_items()], ["news-1"])
        self.assertEqual(self.cache.load_deleted_arch_news_ids(), {"news-2"})

    def test_arch_news_tracking_sets_are_bounded(self) -> None:
        identifiers = {f"news-{index:04d}" for index in range(650)}

        self.cache.save_read_arch_news_ids(identifiers)
        self.cache.save_deleted_arch_news_ids(identifiers)

        self.assertEqual(
            len(self.cache.load_read_arch_news_ids()),
            AppStateCache.MAX_TRACKED_ARCH_NEWS_IDS,
        )
        self.assertEqual(
            len(self.cache.load_deleted_arch_news_ids()),
            AppStateCache.MAX_TRACKED_ARCH_NEWS_IDS,
        )

    def test_new_tracking_id_is_not_immediately_dropped_by_lexical_sorting(self) -> None:
        existing = {f"z-news-{index:04d}" for index in range(500)}
        self.cache.save_deleted_arch_news_ids(existing)

        self.cache.save_deleted_arch_news_ids(existing | {"a-new-deletion"})

        tracked = self.cache.load_deleted_arch_news_ids()
        self.assertEqual(len(tracked), AppStateCache.MAX_TRACKED_ARCH_NEWS_IDS)
        self.assertIn("a-new-deletion", tracked)

    def test_update_session_flag_round_trip(self) -> None:
        self.assertFalse(self.cache.has_unclean_update_session())

        self.cache.mark_update_session_started()
        self.assertTrue(self.cache.has_unclean_update_session())

        self.cache.clear_update_session()
        self.assertFalse(self.cache.has_unclean_update_session())



if __name__ == "__main__":
    unittest.main()
