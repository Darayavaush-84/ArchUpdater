from __future__ import annotations

from .palette import ThemeColors, mix_colors


def build_styles(c: ThemeColors) -> str:
    return f"""
        QWidget {{
            color: {c.text.name()};
        }}
        QMainWindow, QWidget#central, QDialog {{
            background: {c.window.name()};
            color: {c.text.name()};
        }}
        QLabel {{
            color: {c.text.name()};
            background: transparent;
        }}
        QFrame#card, QFrame#counterCard {{
            background: {c.panel.name()};
            border: 1px solid {c.border.name()};
            border-radius: 18px;
        }}
        QSplitter::handle {{
            background: transparent;
        }}
        QSplitter::handle:horizontal {{
            width: 10px;
            margin: 16px 0;
            border-radius: 5px;
        }}
        QSplitter::handle:horizontal:hover {{
            background: {c.surface_alt.name()};
        }}
        QSplitter::handle:horizontal:pressed {{
            background: {c.border.name()};
        }}
        QLabel#sectionCaption {{
            color: {c.muted.name()};
            font-size: 11px;
            font-weight: 600;
            letter-spacing: 0.4px;
            text-transform: uppercase;
        }}
        QToolButton#packageDetailsExpanderButton {{
            color: {c.muted.name()};
            background: transparent;
            border: none;
            padding: 0;
            font-size: 11px;
            font-weight: 600;
            letter-spacing: 0.4px;
            text-transform: uppercase;
        }}
        QToolButton#packageDetailsExpanderButton:hover {{
            color: {c.text.name()};
        }}
        QLabel#sectionTitle {{
            color: {c.text.name()};
            font-size: 18px;
            font-weight: 700;
        }}
        QLabel#systemStatus {{
            font-size: 28px;
            font-weight: 700;
            color: {c.accent.name()};
        }}
        QLabel#mutedText, QLabel#placeholderText {{
            color: {c.muted.name()};
        }}
        QLabel#placeholderText {{
            font-size: 15px;
            padding: 8px 0;
        }}
        QLabel#emptyStateTitle {{
            color: {c.text.name()};
            font-size: 24px;
            font-weight: 700;
        }}
        QLabel#detailsEmptyStateTitle {{
            color: {c.text.name()};
            font-size: 20px;
            font-weight: 700;
        }}
        QLabel#emptyStateMessage {{
            color: {c.muted.name()};
            font-size: 15px;
            padding: 4px 0;
        }}
        QLabel#detailsEmptyStateMessage {{
            color: {c.muted.name()};
            font-size: 15px;
            padding: 0;
        }}
        QLabel#emptyStateIcon {{
            min-width: 52px;
            min-height: 52px;
            max-width: 52px;
            max-height: 52px;
        }}
        QLabel#detailFieldLabel {{
            color: {c.muted.name()};
            font-size: 12px;
            font-weight: 600;
            padding-top: 2px;
        }}
        QLabel#detailValueText, QLabel#detailLinkText, QLabel#detailText {{
            color: {c.text.name()};
            line-height: 1.4;
        }}
        QLabel#detailLinkText {{
            color: {c.accent.name()};
        }}
        QScrollArea#packageDetailsScroll, QWidget#packageDetailsContent {{
            background: transparent;
            border: none;
        }}
        QFrame#packageDetailsHeader, QFrame#packageDetailsSection {{
            background: {c.surface.name()};
            border: 1px solid {c.border.name()};
            border-radius: 8px;
        }}
        QLabel#packageDetailsIcon {{
            background: {c.surface_alt.name()};
            border: 1px solid {c.border.name()};
            border-radius: 8px;
        }}
        QLabel#packageDetailsName {{
            color: {c.text.name()};
            font-size: 19px;
            font-weight: 700;
        }}
        QLabel#packageDetailsBadge {{
            background: {c.accent_soft.name()};
            color: {c.accent.name()};
            border: 1px solid {mix_colors(c.accent, c.window, 0.58 if c.window.lightness() < 128 else 0.70).name()};
            border-radius: 7px;
            padding: 2px 8px;
            font-size: 10px;
            font-weight: 700;
        }}
        QFrame#packageMetricCard {{
            background: {c.surface.name()};
            border: 1px solid {c.border.name()};
            border-radius: 8px;
            min-height: 54px;
        }}
        QFrame#packageMetricCard[metricState="empty"] {{
            background: {mix_colors(c.surface, c.window, 0.32).name()};
        }}
        QLabel#packageMetricTitle {{
            color: {c.muted.name()};
            font-size: 11px;
            font-weight: 700;
        }}
        QLabel#packageMetricValue {{
            color: {c.text.name()};
            font-size: 14px;
            font-weight: 700;
        }}
        QLabel#packageDetailChip {{
            background: {c.surface_alt.name()};
            color: {c.text.name()};
            border: 1px solid {c.border.name()};
            border-radius: 7px;
            padding: 3px 7px;
            font-size: 11px;
        }}
"""
