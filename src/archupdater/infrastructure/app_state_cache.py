from __future__ import annotations

import json
from datetime import datetime, timezone

from PySide6.QtCore import QSettings

from archupdater.domain.arch_news import ArchNewsItem


class AppStateCache:
    UPDATE_SESSION_ACTIVE_KEY = "cache/update_session_active"
    ARCH_NEWS_ITEMS_KEY = "cache/arch_news_items_v1"
    ARCH_NEWS_READ_IDS_KEY = "cache/arch_news_read_ids_v1"
    ARCH_NEWS_DELETED_IDS_KEY = "cache/arch_news_deleted_ids_v1"
    MAX_ARCH_NEWS_ITEMS = 50
    MAX_TRACKED_ARCH_NEWS_IDS = 500
    MAX_NEWS_CACHE_CHARACTERS = 2 * 1024 * 1024
    MAX_TRACKED_IDS_CHARACTERS = 1024 * 1024

    def __init__(self, settings: QSettings | None = None) -> None:
        self._settings = settings or QSettings()

    def load_arch_news_items(self) -> list[ArchNewsItem]:
        raw_value = self._settings.value(self.ARCH_NEWS_ITEMS_KEY, "")
        raw_text = str(raw_value or "").strip()
        if not raw_text or len(raw_text) > self.MAX_NEWS_CACHE_CHARACTERS:
            return []
        try:
            payload = json.loads(raw_text)
        except json.JSONDecodeError:
            return []
        if not isinstance(payload, list):
            return []

        deleted_ids = self.load_deleted_arch_news_ids()
        items: list[ArchNewsItem] = []
        for raw_item in payload:
            item = self._deserialize_news_item(raw_item)
            if item is not None and item.item_id not in deleted_ids:
                items.append(item)
        return items

    def store_arch_news_items(self, items: list[ArchNewsItem]) -> None:
        deleted_ids = self.load_deleted_arch_news_ids()
        merged: dict[str, ArchNewsItem] = {
            item.item_id: item for item in self.load_arch_news_items() if item.item_id
        }
        for item in items:
            if item.item_id and item.item_id not in deleted_ids:
                merged[item.item_id] = item
        ordered_items = sorted(
            merged.values(),
            key=self._arch_news_sort_key,
            reverse=True,
        )[: self.MAX_ARCH_NEWS_ITEMS]
        self._write_arch_news_items(ordered_items)

    def delete_arch_news_items(self, item_ids: set[str]) -> None:
        normalized_ids = {str(item_id).strip() for item_id in item_ids if str(item_id).strip()}
        if not normalized_ids:
            return
        self.save_deleted_arch_news_ids(self.load_deleted_arch_news_ids() | normalized_ids)
        remaining_items = [
            item for item in self.load_arch_news_items() if item.item_id not in normalized_ids
        ]
        self._write_arch_news_items(remaining_items)

    def load_read_arch_news_ids(self) -> set[str]:
        return set(self._load_tracked_ids(self.ARCH_NEWS_READ_IDS_KEY))

    def save_read_arch_news_ids(self, item_ids: set[str]) -> None:
        self._settings.setValue(
            self.ARCH_NEWS_READ_IDS_KEY,
            json.dumps(
                self._bounded_ids(self.ARCH_NEWS_READ_IDS_KEY, item_ids),
                ensure_ascii=False,
            ),
        )
        self._settings.sync()

    def mark_arch_news_read(self, items: list[ArchNewsItem]) -> None:
        item_ids = self.load_read_arch_news_ids()
        item_ids.update(item.item_id for item in items if item.item_id)
        self.save_read_arch_news_ids(item_ids)

    def load_deleted_arch_news_ids(self) -> set[str]:
        return set(self._load_tracked_ids(self.ARCH_NEWS_DELETED_IDS_KEY))

    def save_deleted_arch_news_ids(self, item_ids: set[str]) -> None:
        self._settings.setValue(
            self.ARCH_NEWS_DELETED_IDS_KEY,
            json.dumps(
                self._bounded_ids(self.ARCH_NEWS_DELETED_IDS_KEY, item_ids),
                ensure_ascii=False,
            ),
        )
        self._settings.sync()

    def mark_update_session_started(self) -> None:
        self._settings.setValue(self.UPDATE_SESSION_ACTIVE_KEY, True)
        self._settings.sync()

    def clear_update_session(self) -> None:
        self._settings.remove(self.UPDATE_SESSION_ACTIVE_KEY)
        self._settings.sync()

    def has_unclean_update_session(self) -> bool:
        value = self._settings.value(self.UPDATE_SESSION_ACTIVE_KEY, False)
        if isinstance(value, bool):
            return value
        return str(value).strip().lower() in {"1", "true", "yes", "on"}

    def _write_arch_news_items(self, items: list[ArchNewsItem]) -> None:
        self._settings.setValue(
            self.ARCH_NEWS_ITEMS_KEY,
            json.dumps(
                [self._serialize_news_item(item) for item in items],
                ensure_ascii=False,
            ),
        )
        self._settings.sync()

    def _serialize_news_item(self, item: ArchNewsItem) -> dict[str, object]:
        return {
            "item_id": item.item_id,
            "title": item.title,
            "published_at": item.published_at.isoformat() if item.published_at else None,
            "url": item.url,
            "summary": item.summary,
            "read": item.read,
        }

    def _deserialize_news_item(self, value: object) -> ArchNewsItem | None:
        if not isinstance(value, dict):
            return None
        item_id = str(value.get("item_id") or "").strip()
        title = str(value.get("title") or "").strip()
        if not item_id or not title or len(item_id) > 512 or len(title) > 512:
            return None
        url = self._optional_str(value.get("url"))
        summary = str(value.get("summary") or "").strip()
        if (url is not None and len(url) > 4096) or len(summary) > 8192:
            return None
        return ArchNewsItem(
            item_id=item_id,
            title=title,
            published_at=self._datetime_or_none(value.get("published_at")),
            url=url,
            summary=summary,
            read=self._bool_value(value.get("read", False)),
        )

    def _datetime_or_none(self, value: object) -> datetime | None:
        text = str(value).strip() if value is not None else ""
        if not text:
            return None
        try:
            return datetime.fromisoformat(text)
        except ValueError:
            return None

    def _optional_str(self, value: object) -> str | None:
        text = str(value).strip() if value is not None else ""
        return text or None

    def _bool_value(self, value: object) -> bool:
        if isinstance(value, bool):
            return value
        return str(value).strip().casefold() in {"1", "true", "yes", "on"}

    def _arch_news_sort_key(self, item: ArchNewsItem) -> tuple[datetime, str]:
        published_at = item.published_at
        if published_at is None:
            published_at = datetime.min.replace(tzinfo=timezone.utc)
        elif published_at.tzinfo is None:
            published_at = published_at.replace(tzinfo=timezone.utc)
        else:
            published_at = published_at.astimezone(timezone.utc)
        return (published_at, item.item_id)

    def _load_tracked_ids(self, key: str) -> list[str]:
        raw_value = self._settings.value(key, "")
        raw_text = str(raw_value or "").strip()
        if not raw_text or len(raw_text) > self.MAX_TRACKED_IDS_CHARACTERS:
            return []
        try:
            payload = json.loads(raw_text)
        except json.JSONDecodeError:
            return []
        if not isinstance(payload, list):
            return []

        ordered: list[str] = []
        for raw_item in payload:
            item_id = str(raw_item).strip()
            if item_id and item_id not in ordered:
                ordered.append(item_id)
        return ordered[-self.MAX_TRACKED_ARCH_NEWS_IDS :]

    def _bounded_ids(self, key: str, item_ids: set[str]) -> list[str]:
        normalized = {
            str(item_id).strip() for item_id in item_ids if str(item_id).strip()
        }
        ordered = [
            item_id for item_id in self._load_tracked_ids(key) if item_id in normalized
        ]
        ordered.extend(sorted(normalized.difference(ordered)))
        return ordered[-self.MAX_TRACKED_ARCH_NEWS_IDS :]
