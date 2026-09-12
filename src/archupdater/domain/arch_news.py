from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(slots=True)
class ArchNewsItem:
    item_id: str
    title: str
    published_at: datetime | None = None
    url: str | None = None
    summary: str = ""
    read: bool = False
