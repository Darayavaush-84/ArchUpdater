from __future__ import annotations

from PySide6.QtGui import QPalette

from archupdater.presentation.styles import (
    controls,
    foundation,
    item_views,
    layout,
    overview,
    preferences,
    progress,
)
from archupdater.presentation.styles.palette import derive_theme_colors


def build_application_stylesheet(palette: QPalette) -> str:
    """Compose sections in cascade order; layout rules override the shared controls."""
    colors = derive_theme_colors(palette)
    return "".join(
        section.build_styles(colors)
        for section in (
            foundation,
            progress,
            overview,
            controls,
            preferences,
            item_views,
            layout,
        )
    )
