from __future__ import annotations

from PySide6.QtGui import QColor

from .palette import ThemeColors, mix_colors


def build_styles(c: ThemeColors) -> str:
    return f"""        QTabWidget#preferencesTabs::pane {{
            border: 1px solid {c.border.name()};
            border-radius: 16px;
            background: {c.surface.name()};
            margin-top: 10px;
            padding: 14px;
        }}
        QTabWidget#preferencesTabs QTabBar::tab {{
            background: {c.surface_alt.name()};
            color: {c.muted.name()};
            border: 1px solid {c.border.name()};
            border-bottom: none;
            border-top-left-radius: 10px;
            border-top-right-radius: 10px;
            padding: 9px 14px;
            margin-right: 6px;
            font-weight: 600;
        }}
        QTabWidget#preferencesTabs QTabBar::tab:selected {{
            background: {c.panel.name()};
            color: {c.text.name()};
            border-color: {c.border.name()};
        }}
        QTabWidget#preferencesTabs QTabBar::tab:hover:!selected {{
            color: {c.text.name()};
            background: {c.button_hover.name()};
        }}
        QFrame#optionalSourcesList {{
            background: {c.panel.name()};
            border: 1px solid {c.border.name()};
            border-radius: 16px;
        }}
        QFrame#optionalSourceRow {{
            background: transparent;
            border: none;
        }}
        QFrame#optionalSourceDivider {{
            background: {c.border.name()};
            border: none;
        }}
        QLabel#optionalSourceIconBadge {{
            background: {c.surface_alt.name()};
            border: 1px solid {c.border.name()};
            border-radius: 14px;
            min-width: 32px;
            min-height: 32px;
            max-width: 32px;
            max-height: 32px;
            color: {c.text.name()};
            font-size: 12px;
            font-weight: 700;
        }}
        QLabel#optionalSourceTitle {{
            color: {c.text.name()};
            font-size: 14px;
            font-weight: 700;
        }}
        QLabel#optionalSourceSummary {{
            color: {c.muted.name()};
            font-size: 12px;
            padding-top: 1px;
        }}
        QLabel#optionalSourceMeta {{
            color: {c.muted.name()};
            font-size: 12px;
            padding-top: 2px;
        }}
        QLabel#optionalSourcesStatus {{
            color: {c.muted.name()};
            padding: 2px 0 0 0;
        }}
        QLabel#sourceStateBadge {{
            padding: 1px 7px;
            border-radius: 7px;
            font-size: 9px;
            font-weight: 700;
        }}
        QLabel#optionalSourcePlaceholder {{
            color: {c.muted.name()};
            padding-top: 2px;
        }}
        QLabel#sourceStateBadge[stateKind="enabled"] {{
            background: {mix_colors(QColor("#2f8f5b"), c.window, 0.78 if c.window.lightness() < 128 else 0.86).name()};
            color: {mix_colors(QColor("#a6f0c5"), c.text, 0.15).name()};
            border: 1px solid {mix_colors(QColor("#2f8f5b"), c.window, 0.54 if c.window.lightness() < 128 else 0.68).name()};
        }}
        QLabel#sourceStateBadge[stateKind="disabled"] {{
            background: {c.surface_alt.name()};
            color: {c.text.name()};
            border: 1px solid {c.border.name()};
        }}
"""
