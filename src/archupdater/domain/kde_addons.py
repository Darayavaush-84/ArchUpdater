from __future__ import annotations

from collections.abc import Callable

Translate = Callable[[str], str]

KDE_ADDON_CATEGORY_QUERY = "705x715x719x720"

KDE_ADDON_TYPE_BY_CATEGORY = {
    "705": "Plasma/Applet",
    "706": "Plasma/Applet",
    "715": "Plasma/Wallpaper",
    "719": "KWin/Effect",
    "720": "KWin/Script",
}


def kde_addon_type_label(package_kind: str | None, translate: Translate) -> str:
    labels = {
        "Plasma/Applet": translate("Plasma Widget"),
        "Plasma/Wallpaper": translate("Wallpaper"),
        "KWin/Effect": translate("KWin Effect"),
        "KWin/Script": translate("KWin Script"),
    }
    kind = (package_kind or "").strip()
    return labels.get(kind, kind)


def kde_addon_source_label(translate: Translate) -> str:
    return translate("KDE Store Add-ons")
