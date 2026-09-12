from __future__ import annotations

from .palette import ThemeColors, mix_colors


def build_styles(c: ThemeColors) -> str:
    return f"""        QPushButton#updateButton {{
            background: {c.accent.name()};
            color: {c.accent_text.name()};
            border: 1px solid {c.accent.name()};
            border-radius: 9px;
            min-height: 42px;
            padding: 0 20px;
            font-size: 14px;
            font-weight: 700;
        }}
        QPushButton#updateButton:hover {{
            background: {mix_colors(c.accent, c.text, 0.10).name()};
        }}
        QPushButton#updateButton:disabled {{
            background: {c.button_disabled.name()};
            color: {c.button_text_disabled.name()};
            border-color: {c.border.name()};
        }}
        QPushButton#checkButton {{
            min-height: 42px;
            padding: 0 18px;
            font-size: 13px;
            font-weight: 600;
        }}
        QPushButton#preferencesButton {{
            min-height: 40px;
            padding: 0 14px;
        }}
        QPushButton#githubButton {{
            min-height: 38px;
            padding: 0 8px;
            font-size: 12px;
            font-weight: 600;
        }}
        QPushButton#githubButton[updateAvailable="true"]:enabled {{
            color: {"#31d174" if c.window.lightness() < 128 else "#16803c"};
        }}
        QPushButton#utilityButton {{
            min-height: 38px;
            padding: 0 12px;
        }}
    """
