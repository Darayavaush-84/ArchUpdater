from __future__ import annotations

import urllib.error
import urllib.request
import re
import unicodedata
import xml.etree.ElementTree as ET
from dataclasses import dataclass

from packaging.version import InvalidVersion, Version
from PySide6.QtCore import QCoreApplication

from archupdater import __version__
from archupdater.services.io_limits import read_limited
from archupdater.domain.kde_addons import KDE_ADDON_CATEGORY_QUERY, KDE_ADDON_TYPE_BY_CATEGORY


@dataclass(frozen=True, slots=True)
class StoreWidgetSummary:
    content_id: str
    name: str
    version: str
    summary: str
    type_label: str
    author: str
    detail_url: str


@dataclass(frozen=True, slots=True)
class StoreWidgetDownload:
    url: str
    name: str
    version: str


@dataclass(frozen=True, slots=True)
class StoreWidgetDetail:
    content_id: str
    name: str
    version: str
    summary: str
    type_label: str
    author: str
    detail_url: str
    downloads: list[StoreWidgetDownload]


class PlasmaWidgetUserVisibleError(OSError):
    def __init__(self, user_message: str, technical_message: str | None = None) -> None:
        super().__init__(user_message)
        self.user_message = user_message
        self.technical_message = technical_message or user_message


class PlasmaWidgetsStoreClient:
    _CATEGORY_QUERY = KDE_ADDON_CATEGORY_QUERY
    _PAGE_SIZE = 100
    _TYPE_BY_CATEGORY = KDE_ADDON_TYPE_BY_CATEGORY
    _MAX_XML_BYTES = 4 * 1024 * 1024
    _MAX_LISTING_PAGES = 100
    _MAX_LISTING_ITEMS = _PAGE_SIZE * _MAX_LISTING_PAGES
    _CONTENT_ID_RE = re.compile(r"^[A-Za-z0-9._-]{1,128}$")

    def fetch_listing(self) -> list[StoreWidgetSummary]:
        widgets: list[StoreWidgetSummary] = []
        page = 0
        total_items: int | None = None
        seen_content_ids: set[str] = set()

        while total_items is None or len(widgets) < total_items:
            if page >= self._MAX_LISTING_PAGES:
                raise PlasmaWidgetUserVisibleError(
                    self._translate("KDE Store is temporarily unavailable. Try again later."),
                    "KDE Store listing exceeded the pagination safety limit.",
                )
            root = self._fetch_xml(
                "https://api.kde-look.org/ocs/v1/content/data"
                f"?categories={self._CATEGORY_QUERY}&sort=new&page={page}&pagesize={self._PAGE_SIZE}"
            )
            meta, data = self._meta_and_data(root)
            status_code = (meta.findtext("statuscode") or "").strip()
            if status_code not in {"100", ""}:
                self._raise_ocs_error(meta, status_code)

            if total_items is None:
                total_value = (meta.findtext("totalitems") or "").strip()
                total_items = int(total_value) if total_value.isdigit() else 0
                if total_items > self._MAX_LISTING_ITEMS:
                    raise PlasmaWidgetUserVisibleError(
                        self._translate("KDE Store is temporarily unavailable. Try again later."),
                        "KDE Store listing exceeded the item safety limit.",
                    )

            page_items = self._parse_listing_page(data)
            if not page_items:
                break
            new_items = [
                item for item in page_items if item.content_id not in seen_content_ids
            ]
            if not new_items:
                raise PlasmaWidgetUserVisibleError(
                    self._translate("KDE Store is temporarily unavailable. Try again later."),
                    "KDE Store returned a repeated listing page.",
                )
            for item in new_items:
                seen_content_ids.add(item.content_id)
            widgets.extend(new_items)
            if len(widgets) > self._MAX_LISTING_ITEMS:
                raise PlasmaWidgetUserVisibleError(
                    self._translate("KDE Store is temporarily unavailable. Try again later."),
                    "KDE Store listing exceeded the item safety limit.",
                )
            page += 1

        return widgets

    def fetch_details(self, content_id: str) -> StoreWidgetDetail:
        if not self._CONTENT_ID_RE.fullmatch(content_id):
            raise PlasmaWidgetUserVisibleError(
                self._translate("The downloaded KDE Store add-on package is incomplete or incompatible."),
                "Invalid KDE Store content id.",
            )
        root = self._fetch_xml(f"https://api.kde-look.org/ocs/v1/content/data/{content_id}")
        meta, data = self._meta_and_data(root)
        status_code = (meta.findtext("statuscode") or "").strip()
        if status_code not in {"100", ""}:
            self._raise_ocs_error(meta, status_code)

        content = data.find("content")
        if content is None:
            raise PlasmaWidgetUserVisibleError(
                self._translate("The downloaded KDE Store add-on package is incomplete or incompatible."),
                "Missing OCS content node.",
            )

        resolved_id = (content.findtext("id") or "").strip() or content_id
        version = self._clean_version(content.findtext("version"))
        name = self._clean_display_text(content.findtext("name"), limit=512)
        if not self._CONTENT_ID_RE.fullmatch(resolved_id) or not version or not name:
            raise PlasmaWidgetUserVisibleError(
                self._translate("The downloaded KDE Store add-on package is incomplete or incompatible."),
                "Incomplete KDE Store metadata.",
            )

        type_id = (content.findtext("typeid") or "").strip()
        return StoreWidgetDetail(
            content_id=resolved_id,
            name=name,
            version=version,
            summary=self._clean_display_text(content.findtext("summary"), limit=8192),
            type_label=self._TYPE_BY_CATEGORY.get(type_id, "Plasma/Applet"),
            author=self._author_text(content),
            detail_url=self._clean_display_text(
                content.findtext("detailpage") or content.findtext("homepage"),
                limit=4096,
            ),
            downloads=self._parse_downloads(content),
        )

    def choose_download(self, detail: StoreWidgetDetail) -> StoreWidgetDownload:
        if not detail.downloads:
            raise PlasmaWidgetUserVisibleError(
                self._translate("The downloaded KDE Store add-on package is incomplete or incompatible."),
                "No download files available for widget.",
            )

        if len(detail.downloads) == 1:
            download = detail.downloads[0]
            if download.version and not self._versions_match(download.version, detail.version):
                raise PlasmaWidgetUserVisibleError(
                    self._translate(
                        "The KDE Store download version does not match the advertised update."
                    ),
                    (
                        f"Download version {download.version} does not match "
                        f"content version {detail.version}."
                    ),
                )
            return download

        exact = [
            download
            for download in detail.downloads
            if download.version and self._versions_match(download.version, detail.version)
        ]
        if len(exact) == 1:
            return exact[0]
        if len(exact) > 1:
            raise PlasmaWidgetUserVisibleError(
                self._translate(
                    "This widget publishes multiple package files, and ArchUpdater could not choose one safely."
                ),
                f"Multiple download files match version {detail.version}.",
            )

        raise PlasmaWidgetUserVisibleError(
            self._translate(
                "This widget publishes multiple package files, and ArchUpdater could not choose one safely."
            ),
            f"Could not determine the correct download for version {detail.version}.",
        )

    def _fetch_xml(self, url: str) -> ET.Element:
        request = urllib.request.Request(
            url,
            headers={
                "Accept": "application/xml",
                "User-Agent": f"ArchUpdater/{__version__}",
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=20) as response:
                xml_text = self._read_limited_response(response, self._MAX_XML_BYTES)
        except urllib.error.HTTPError as exc:
            if exc.code == 429:
                raise PlasmaWidgetUserVisibleError(
                    self._translate(
                        "KDE Store is temporarily limiting requests. Try again in a few minutes."
                    ),
                    f"HTTP {exc.code} while fetching KDE Store XML.",
                ) from exc
            raise PlasmaWidgetUserVisibleError(
                self._translate("KDE Store is temporarily unavailable. Try again later."),
                f"HTTP {exc.code} while fetching KDE Store XML.",
            ) from exc
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise PlasmaWidgetUserVisibleError(
                self._translate("KDE Store is temporarily unavailable. Try again later."),
                f"Failed to fetch KDE Store XML: {exc}",
            ) from exc

        try:
            return ET.fromstring(xml_text)
        except ET.ParseError as exc:
            raise PlasmaWidgetUserVisibleError(
                self._translate("KDE Store is temporarily unavailable. Try again later."),
                "Failed to parse KDE Store XML.",
            ) from exc

    def _read_limited_response(self, response, limit: int) -> bytes:  # noqa: ANN001
        try:
            return read_limited(response, limit)
        except ValueError as exc:
            raise PlasmaWidgetUserVisibleError(
                self._translate("KDE Store is temporarily unavailable. Try again later."),
                f"KDE Store XML response is larger than {limit} bytes.",
            ) from exc

    def _meta_and_data(self, root: ET.Element) -> tuple[ET.Element, ET.Element]:
        meta = root.find("./meta")
        if meta is None:
            meta = root.find("./ocs/meta")
        data = root.find("./data")
        if data is None:
            data = root.find("./ocs/data")
        if meta is None or data is None:
            raise PlasmaWidgetUserVisibleError(
                self._translate("KDE Store is temporarily unavailable. Try again later."),
                "Missing OCS meta/data nodes.",
            )
        return meta, data

    def _raise_ocs_error(self, meta: ET.Element, status_code: str) -> None:
        status_message = (meta.findtext("message") or "").strip()
        if status_code == "429" or "too many api requests" in status_message.casefold():
            raise PlasmaWidgetUserVisibleError(
                self._translate(
                    "KDE Store is temporarily limiting requests. Try again in a few minutes."
                ),
                f"Unexpected OCS status code: {status_code} ({status_message})",
            )
        raise PlasmaWidgetUserVisibleError(
            self._translate("KDE Store is temporarily unavailable. Try again later."),
            f"Unexpected OCS status code: {status_code} ({status_message})",
        )

    def _parse_listing_page(self, data: ET.Element) -> list[StoreWidgetSummary]:
        widgets: list[StoreWidgetSummary] = []
        for content in data.findall("content"):
            content_id = (content.findtext("id") or "").strip()
            name = self._clean_display_text(content.findtext("name"), limit=512)
            version = self._clean_version(content.findtext("version"))
            if not self._CONTENT_ID_RE.fullmatch(content_id) or not name or not version:
                continue
            type_id = (content.findtext("typeid") or "").strip()
            widgets.append(
                StoreWidgetSummary(
                    content_id=content_id,
                    name=name,
                    version=version,
                    summary=self._clean_display_text(content.findtext("summary"), limit=8192),
                    type_label=self._TYPE_BY_CATEGORY.get(type_id, "Plasma/Applet"),
                    author=self._author_text(content),
                    detail_url=self._clean_display_text(
                        content.findtext("detailpage") or content.findtext("homepage"),
                        limit=4096,
                    ),
                )
            )
        return widgets

    def _parse_downloads(self, content: ET.Element) -> list[StoreWidgetDownload]:
        downloads: list[StoreWidgetDownload] = []
        for index in range(1, 10):
            url = (content.findtext(f"downloadlink{index}") or "").strip()
            if not url:
                continue
            downloads.append(
                StoreWidgetDownload(
                    url=url,
                    name=self._clean_display_text(
                        content.findtext(f"downloadname{index}"),
                        limit=255,
                    ),
                    version=self._clean_version(content.findtext(f"download_version{index}")),
                )
            )
        return downloads

    def _translate(self, text: str) -> str:
        return QCoreApplication.translate("PlasmaWidgetsStoreClient", text)

    def _clean_version(self, value: object) -> str:
        raw = self._clean_display_text(value, limit=512)
        return raw.removeprefix("v").removeprefix("V").strip()

    def _clean_display_text(self, value: object, *, limit: int) -> str:
        raw = str(value or "")[:limit]
        cleaned = "".join(
            " "
            if unicodedata.category(character) == "Cc"
            else ""
            if unicodedata.category(character) in {"Cf", "Cs"}
            else character
            for character in raw
        )
        return " ".join(cleaned.split())

    def _versions_match(self, first: object, second: object) -> bool:
        first_text = self._clean_version(first)
        second_text = self._clean_version(second)
        if not first_text or not second_text:
            return first_text == second_text
        try:
            return Version(first_text) == Version(second_text)
        except InvalidVersion:
            return first_text == second_text

    def _author_text(self, content: ET.Element) -> str:
        for key in ("personname", "username", "author", "personid"):
            value = (content.findtext(key) or "").strip()
            if value:
                return self._clean_display_text(value, limit=512)
        return ""
