from __future__ import annotations

from typing import Protocol


class WidgetMatchCache(Protocol):
    def resolve(self, package_kind: str, plugin_id: str | None) -> str | None: ...

    def remember(self, package_kind: str, plugin_id: str | None, content_id: str) -> None: ...


class MemoryWidgetMatchCache:
    def __init__(self) -> None:
        self._entries: dict[tuple[str, str], str] = {}

    def resolve(self, package_kind: str, plugin_id: str | None) -> str | None:
        if not plugin_id:
            return None
        return self._entries.get((package_kind, plugin_id))

    def remember(self, package_kind: str, plugin_id: str | None, content_id: str) -> None:
        if plugin_id and content_id:
            self._entries[(package_kind, plugin_id)] = content_id
