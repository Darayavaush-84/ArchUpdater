from __future__ import annotations

import html
import re
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
import urllib.parse
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from email.utils import parsedate_to_datetime

from PySide6.QtCore import QCoreApplication

from archupdater import __version__
from archupdater.domain.arch_news import ArchNewsItem
from archupdater.services.io_limits import read_limited


OpenUrl = Callable[[str, float], bytes]


def _default_open_url(url: str, timeout: float) -> bytes:
    request = urllib.request.Request(
        url,
        headers={"User-Agent": f"ArchUpdater/{__version__}"},
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        try:
            return read_limited(response, ArchNewsService.MAX_FEED_BYTES)
        except ValueError as exc:
            raise OSError("Arch Linux news feed is too large.") from exc


@dataclass(slots=True)
class ArchNewsResult:
    items: list[ArchNewsItem] = field(default_factory=list)
    warning: str | None = None


@dataclass(slots=True)
class ArchNewsService:
    open_url: OpenUrl = _default_open_url

    FEED_URL = "https://archlinux.org/feeds/news/"
    TIMEOUT_SECONDS = 12.0
    MAX_FEED_BYTES = 2 * 1024 * 1024
    MAX_ITEMS = 100

    def fetch(self, *, read_ids: set[str] | None = None) -> ArchNewsResult:
        try:
            raw_xml = self.open_url(self.FEED_URL, self.TIMEOUT_SECONDS)
        except (OSError, urllib.error.URLError, TimeoutError) as exc:
            return ArchNewsResult(warning=self._warning(str(exc)))

        try:
            root = ET.fromstring(raw_xml)
        except ET.ParseError as exc:
            return ArchNewsResult(warning=self._warning(str(exc)))

        read_ids = read_ids or set()
        items: list[ArchNewsItem] = []
        for raw_item in root.findall("./channel/item"):
            item = self._parse_item(raw_item, read_ids=read_ids)
            if item is not None:
                items.append(item)
            if len(items) >= self.MAX_ITEMS:
                break
        return ArchNewsResult(items=items)

    def _parse_item(self, raw_item: ET.Element, *, read_ids: set[str]) -> ArchNewsItem | None:
        title = self._text(raw_item, "title")[:512]
        if not title:
            return None
        url = self._text(raw_item, "link")
        if url and not self._valid_news_url(url):
            url = ""
        guid = self._text(raw_item, "guid")[:512]
        item_id = guid or url or title
        return ArchNewsItem(
            item_id=item_id,
            title=title,
            published_at=self._published_at(self._text(raw_item, "pubDate")),
            url=url or None,
            summary=self._summary(self._text(raw_item, "description")),
            read=item_id in read_ids,
        )

    def _text(self, item: ET.Element, tag: str) -> str:
        child = item.find(tag)
        return (child.text or "").strip()[:8192] if child is not None else ""

    def _valid_news_url(self, value: str) -> bool:
        parsed = urllib.parse.urlsplit(value)
        return parsed.scheme == "https" and parsed.hostname in {
            "archlinux.org",
            "www.archlinux.org",
        }

    def _published_at(self, value: str) -> datetime | None:
        if not value:
            return None
        try:
            parsed = parsedate_to_datetime(value)
        except (TypeError, ValueError):
            return None
        if parsed.tzinfo is not None:
            parsed = parsed.astimezone().replace(tzinfo=None)
        return parsed

    def _summary(self, value: str) -> str:
        text = html.unescape(value)
        text = re.sub(r"<[^>]+>", " ", text)
        text = re.sub(r"\s+", " ", text).strip()
        return text

    def _warning(self, details: str) -> str:
        return QCoreApplication.translate(
            "ArchNewsService",
            "Arch Linux news could not be checked: {details}",
        ).format(details=details or QCoreApplication.translate("ArchNewsService", "Unknown error."))
