from __future__ import annotations

import json

from PySide6.QtCore import QSettings


class WidgetMatchCache:
    SETTINGS_KEY = "widgets/match_cache_v1"

    def __init__(self, settings: QSettings | None = None) -> None:
        self._settings = settings or QSettings()

    def resolve(self, package_kind: str, plugin_id: str | None) -> str | None:
        if not plugin_id:
            return None
        return self._load().get(self._entry_key(package_kind, plugin_id))

    def remember(self, package_kind: str, plugin_id: str | None, content_id: str) -> None:
        if not plugin_id or not content_id:
            return
        data = self._load()
        data[self._entry_key(package_kind, plugin_id)] = content_id
        self._settings.setValue(self.SETTINGS_KEY, json.dumps(data, sort_keys=True))
        self._settings.sync()

    def _load(self) -> dict[str, str]:
        raw_value = self._settings.value(self.SETTINGS_KEY, "{}")
        try:
            payload = json.loads(str(raw_value or "{}"))
        except (TypeError, ValueError, json.JSONDecodeError):
            return {}
        if not isinstance(payload, dict):
            return {}
        result: dict[str, str] = {}
        for key, value in payload.items():
            if isinstance(key, str) and isinstance(value, str) and key and value:
                result[key] = value
        return result

    def _entry_key(self, package_kind: str, plugin_id: str) -> str:
        return f"{package_kind}:{plugin_id}"
