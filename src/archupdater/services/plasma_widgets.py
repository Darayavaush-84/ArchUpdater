from __future__ import annotations

import json
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from packaging.version import InvalidVersion, Version
from PySide6.QtCore import QCoreApplication

from archupdater.domain.check_results import SourceCheckResult
from archupdater.domain.enums import UpdateSource
from archupdater.domain.package_metadata import PlasmaWidgetPackageMetadata
from archupdater.domain.packages import PackageUpdate
from archupdater.services.plasma_widgets_store import (
    PlasmaWidgetUserVisibleError,
    PlasmaWidgetsStoreClient,
    StoreWidgetDetail,
    StoreWidgetSummary,
)
from archupdater.services.widget_matching import MemoryWidgetMatchCache, WidgetMatchCache


@dataclass(frozen=True, slots=True)
class _LocalWidget:
    name: str
    version: str
    description: str
    plugin_id: str
    directory_name: str
    path: Path
    type_label: str
    icon_name: str


StoreFetcher = Callable[[], list[StoreWidgetSummary]]


@dataclass(slots=True)
class PlasmaWidgetsUpdateService:
    home_dir: Path = field(default_factory=Path.home)
    store_fetcher: StoreFetcher | None = None
    id_map_path: Path | None = None
    store_client: PlasmaWidgetsStoreClient = field(default_factory=PlasmaWidgetsStoreClient)
    match_cache: WidgetMatchCache = field(default_factory=MemoryWidgetMatchCache)

    def check_updates(self) -> SourceCheckResult:
        local_widgets = self._scan_local_widgets()
        if not local_widgets:
            return SourceCheckResult()

        result = SourceCheckResult()
        registry_ids = self._load_registry_ids()
        id_map = self._load_id_map()
        content_ids = self._known_content_ids(
            local_widgets,
            registry_ids=registry_ids,
            id_map=id_map,
        )
        if not content_ids and self.store_fetcher is None:
            return result
        try:
            store_widgets = self._load_store_widgets(content_ids)
        except (OSError, ET.ParseError, TimeoutError) as exc:
            result.warnings.append(self._user_message(exc))
            return result

        if not store_widgets:
            return result

        by_id = {widget.content_id: widget for widget in store_widgets}
        restart_warning = self._translate(
            "Some KDE Store add-ons may require restarting plasmashell after updating."
        )
        repository_label = self._translate("KDE Store")

        for widget in local_widgets:
            store_widget = self._match_store_widget(
                widget,
                by_id=by_id,
                registry_ids=registry_ids,
                id_map=id_map,
            )
            if store_widget is None:
                continue
            if not self._is_remote_version_newer(widget.version, store_widget.version):
                continue

            result.packages.append(
                PackageUpdate(
                    name=widget.name,
                    current_version=widget.version,
                    new_version=store_widget.version,
                    source=UpdateSource.PLASMA_WIDGET,
                    source_metadata=PlasmaWidgetPackageMetadata(
                        content_id=store_widget.content_id,
                        repository=repository_label,
                        package_kind=store_widget.type_label,
                        plugin_id=widget.plugin_id or widget.directory_name,
                    ),
                    backend_id=store_widget.content_id,
                    description=store_widget.summary or widget.description,
                    author=store_widget.author or None,
                    homepage=store_widget.detail_url or None,
                    icon_name=widget.icon_name or None,
                    warnings=[restart_warning],
                )
            )

        return result

    def _scan_local_widgets(self) -> list[_LocalWidget]:
        widgets: list[_LocalWidget] = []
        for root, type_label in self._widget_roots():
            if not root.exists():
                continue
            for package_dir in sorted(root.iterdir()):
                if not package_dir.is_dir():
                    continue
                widget = self._read_local_widget(package_dir, type_label)
                if widget is not None:
                    widgets.append(widget)
        return widgets

    def _widget_roots(self) -> list[tuple[Path, str]]:
        base = self.home_dir / ".local" / "share"
        return [
            (base / "plasma" / "plasmoids", "Plasma/Applet"),
            (base / "plasma" / "wallpapers", "Plasma/Wallpaper"),
            (base / "kwin" / "effects", "KWin/Effect"),
            (base / "kwin" / "scripts", "KWin/Script"),
        ]

    def _read_local_widget(self, package_dir: Path, type_label: str) -> _LocalWidget | None:
        metadata_path = package_dir / "metadata.json"
        if not metadata_path.is_file():
            return None

        try:
            payload = json.loads(metadata_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None

        plugin_data = payload.get("KPlugin")
        if not isinstance(plugin_data, dict):
            return None

        version = self._clean_version(plugin_data.get("Version"))
        if not version:
            return None

        name = str(plugin_data.get("Name") or package_dir.name).strip()
        plugin_id = str(plugin_data.get("Id") or package_dir.name).strip()
        description = str(plugin_data.get("Description") or "").strip()
        icon_name = str(plugin_data.get("Icon") or "").strip()
        return _LocalWidget(
            name=name or package_dir.name,
            version=version,
            description=description,
            plugin_id=plugin_id or package_dir.name,
            directory_name=package_dir.name,
            path=package_dir,
            type_label=type_label,
            icon_name=icon_name,
        )

    def _load_store_widgets(self, content_ids: set[str]) -> list[StoreWidgetSummary]:
        if self.store_fetcher is not None:
            return self.store_fetcher()
        return [
            self._summary_from_detail(self.store_client.fetch_details(content_id))
            for content_id in sorted(content_ids)
        ]

    def _known_content_ids(
        self,
        widgets: list[_LocalWidget],
        *,
        registry_ids: dict[str, str],
        id_map: dict[str, str],
    ) -> set[str]:
        content_ids: set[str] = set()
        for widget in widgets:
            for key in (self._normalize_path(widget.path), widget.directory_name):
                content_id = registry_ids.get(key)
                if content_id:
                    content_ids.add(content_id)
            cached = self.match_cache.resolve(widget.type_label, widget.plugin_id)
            if cached:
                content_ids.add(cached)
            for key in (widget.plugin_id, widget.directory_name):
                content_id = id_map.get(key)
                if content_id:
                    content_ids.add(content_id)
        return content_ids

    def _summary_from_detail(self, detail: StoreWidgetDetail) -> StoreWidgetSummary:
        return StoreWidgetSummary(
            content_id=detail.content_id,
            name=detail.name,
            version=detail.version,
            summary=detail.summary,
            type_label=detail.type_label,
            author=detail.author,
            detail_url=detail.detail_url,
        )

    def _load_registry_ids(self) -> dict[str, str]:
        registry_dir = self.home_dir / ".local" / "share" / "knewstuff3"
        if not registry_dir.exists():
            return {}

        mapping: dict[str, str] = {}
        for registry_file in sorted(registry_dir.glob("*.knsregistry")):
            try:
                root = ET.fromstring(registry_file.read_text(encoding="utf-8"))
            except (OSError, ET.ParseError):
                continue
            for stuff in root.findall(".//stuff"):
                content_id = (stuff.findtext("id") or "").strip()
                installed_file = (stuff.findtext("installedfile") or "").strip()
                if not content_id or not installed_file:
                    continue
                normalized_path = self._normalize_path(Path(installed_file))
                mapping[normalized_path] = content_id
                mapping[Path(normalized_path).name] = content_id
        return mapping

    def _load_id_map(self) -> dict[str, str]:
        path = self.id_map_path or (
            Path(__file__).resolve().parents[1] / "resources" / "data" / "plasma_widgets_id_map.txt"
        )
        if not path.is_file():
            return {}

        mapping: dict[str, str] = {}
        try:
            raw_text = path.read_text(encoding="utf-8")
        except OSError:
            return {}

        for raw_line in raw_text.splitlines():
            data_part, _separator, comment = raw_line.partition("#")
            if "ignored" in comment.casefold():
                continue
            line = data_part.strip()
            if not line:
                continue
            parts = line.split(maxsplit=1)
            if len(parts) != 2:
                continue
            content_id, plugin_id = parts
            mapping[plugin_id.strip()] = content_id.strip()
        return mapping

    def _match_store_widget(
        self,
        widget: _LocalWidget,
        *,
        by_id: dict[str, StoreWidgetSummary],
        registry_ids: dict[str, str],
        id_map: dict[str, str],
    ) -> StoreWidgetSummary | None:
        lookup_keys = [
            self._normalize_path(widget.path),
            widget.directory_name,
        ]
        for key in lookup_keys:
            content_id = registry_ids.get(key)
            candidate = self._typed_id_match(content_id, widget.type_label, by_id)
            if candidate is not None:
                return candidate

        cached_content_id = self.match_cache.resolve(widget.type_label, widget.plugin_id)
        if cached_content_id:
            cached_widget = by_id.get(cached_content_id)
            if cached_widget is not None and cached_widget.type_label == widget.type_label:
                return cached_widget

        for key in (widget.plugin_id, widget.directory_name):
            content_id = id_map.get(key)
            candidate = self._typed_id_match(content_id, widget.type_label, by_id)
            if candidate is not None:
                return candidate
        return None

    def _typed_id_match(
        self,
        content_id: str | None,
        type_label: str,
        by_id: dict[str, StoreWidgetSummary],
    ) -> StoreWidgetSummary | None:
        if not content_id:
            return None
        candidate = by_id.get(content_id)
        if candidate is None or candidate.type_label != type_label:
            return None
        return candidate

    def _clean_version(self, value: object) -> str:
        raw = str(value or "").strip()
        return raw

    def _is_remote_version_newer(self, current_version: str, remote_version: str) -> bool:
        if not current_version or not remote_version:
            return False
        try:
            return Version(remote_version) > Version(current_version)
        except InvalidVersion:
            return False

    def _normalize_path(self, value: Path) -> str:
        return value.expanduser().resolve().as_posix().rstrip("/")

    def _translate(self, text: str) -> str:
        return QCoreApplication.translate("PlasmaWidgetsUpdateService", text)

    def _user_message(self, exc: Exception) -> str:
        if isinstance(exc, PlasmaWidgetUserVisibleError):
            return exc.user_message
        details = str(exc).casefold()
        if "429" in details or "too many api requests" in details:
            return self._translate(
                "KDE Store is temporarily limiting requests. Try again in a few minutes."
            )
        return self._translate("KDE Store is temporarily unavailable. Try again later.")
