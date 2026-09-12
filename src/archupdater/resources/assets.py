from __future__ import annotations

from pathlib import Path


_LOGO_DIR = Path(__file__).resolve().parent / "img" / "logos"
_ILLUSTRATION_DIR = Path(__file__).resolve().parent / "img" / "illustrations"
_COUNTER_LOGOS = {
    "system": "system.svg",
    "aur": "aur.svg",
    "flatpak": "flatpak.svg",
    "plasma_widgets": "plasma_widgets.svg",
    "firmware": "firmware.svg",
}


def counter_logo_path(key: str) -> Path | None:
    filename = _COUNTER_LOGOS.get(key)
    if not filename:
        return None

    logo_path = _LOGO_DIR / filename
    if logo_path.exists():
        return logo_path
    return None


def illustration_path(name: str) -> Path | None:
    illustration = _ILLUSTRATION_DIR / name
    if illustration.exists():
        return illustration
    return None


def github_logo_path(*, dark: bool) -> Path:
    return _LOGO_DIR / ("github-white.svg" if dark else "github-black.svg")
