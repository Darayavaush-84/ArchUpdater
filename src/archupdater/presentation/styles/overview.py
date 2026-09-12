from __future__ import annotations

from .palette import ThemeColors


def build_styles(c: ThemeColors) -> str:
    return f"""        QLabel#warningText {{
            color: {c.warning_text.name()};
            background: {c.warning_bg.name()};
            border: 1px solid {c.warning_border.name()};
            border-radius: 12px;
            padding: 10px 12px;
        }}
        QLabel#statusLabel {{
            color: {c.text.name()};
            font-weight: 600;
        }}
        QLabel#progressPercent {{
            color: {c.text.name()};
            font-weight: 700;
            min-width: 38px;
        }}
        QLabel#counterValue {{
            font-size: 23px;
            font-weight: 700;
            color: {c.text.name()};
        }}
        QLabel#counterTitle {{
            color: {c.muted.name()};
            font-size: 11px;
            font-weight: 600;
        }}
        QLabel#counterDetails {{
            color: {c.muted.name()};
            font-size: 10px;
            font-weight: 500;
        }}
        QFrame#counterCard[filterActive="true"] {{
            border: 2px solid {c.accent.name()};
            background: {c.accent_soft.name()};
        }}
        QLabel#counterFilterBadge {{
            background: {c.accent.name()};
            color: {c.accent_text.name()};
            border-radius: 8px;
            padding: 2px 7px;
            font-size: 10px;
            font-weight: 700;
        }}
        QLabel#counterLogoBadge, QLabel#counterBadge {{
            background: {c.surface_alt.name()};
            border: 1px solid {c.border.name()};
            border-radius: 11px;
            min-width: 26px;
            min-height: 26px;
            max-width: 26px;
            max-height: 26px;
            padding: 0;
        }}
        QLabel#searchIcon {{
            color: {c.muted.name()};
            min-width: 20px;
            min-height: 20px;
            max-width: 20px;
            max-height: 20px;
            font-size: 20px;
        }}
        QLabel#counterBadge {{
            font-size: 11px;
            font-weight: 700;
        }}
        QLineEdit#updatesSearchInput {{
            background: {c.surface.name()};
            color: {c.text.name()};
            border: 1px solid {c.border.name()};
            border-radius: 10px;
            padding: 7px 12px;
            min-height: 18px;
        }}
        QLineEdit#updatesSearchInput:focus {{
            border-color: {c.accent.name()};
        }}
        QLabel#counterBadge[badgeKind="aur"] {{
            background: {c.accent_soft.name()};
            color: {c.text.name()};
            border: 1px solid {c.border.name()};
        }}
        QLabel#counterBadge[badgeKind="widgets"] {{
            background: {c.surface_alt.name()};
            color: {c.text.name()};
            border: 1px solid {c.border.name()};
        }}
        QFrame#counterCard[filterActive="true"] QLabel#counterTitle,
        QFrame#counterCard[filterActive="true"] QLabel#counterValue {{
            color: {c.text.name()};
        }}
        QFrame#counterCard[filterActive="true"] QLabel#counterLogoBadge,
        QFrame#counterCard[filterActive="true"] QLabel#counterBadge {{
            border-color: {c.accent.name()};
        }}
"""
