from __future__ import annotations

from PySide6.QtGui import QColor

from .palette import ThemeColors, mix_colors


def build_styles(c: ThemeColors) -> str:
    return f"""        QPushButton, QDialogButtonBox QPushButton {{
            background: {c.button.name()};
            color: {c.text.name()};
            border: 1px solid {c.border.name()};
            border-radius: 12px;
            padding: 10px 16px;
            font-weight: 600;
        }}
        QPushButton[actionKind="neutral"] {{
            background: {c.surface_alt.name()};
            color: {c.text.name()};
            border-color: {c.border.name()};
        }}
        QPushButton[actionKind="primary"], QDialogButtonBox QPushButton[actionKind="primary"] {{
            background: {mix_colors(c.accent, c.window, 0.84 if c.window.lightness() < 128 else 0.92).name()};
            color: {c.text.name()};
            border-color: {mix_colors(c.accent, c.window, 0.46 if c.window.lightness() < 128 else 0.66).name()};
        }}
        QPushButton[newsState="unread"] {{
            background: {mix_colors(QColor("#256d85"), c.window, 0.70 if c.window.lightness() < 128 else 0.88).name()};
            color: {c.text.name()};
            border-color: {mix_colors(QColor("#38bdf8"), c.window, 0.36 if c.window.lightness() < 128 else 0.58).name()};
        }}
        QPushButton[density="compact"], QDialogButtonBox QPushButton[density="compact"] {{
            border-radius: 9px;
            padding: 5px 10px;
            font-weight: 600;
        }}
        QPushButton[uiRole="dialogFooter"], QDialogButtonBox QPushButton[uiRole="dialogFooter"] {{
            min-height: 26px;
            padding: 5px 12px;
            border-radius: 10px;
            font-size: 12px;
        }}
        QPushButton[uiRole="sourceAction"] {{
            border-radius: 7px;
            padding: 3px 8px;
            font-size: 11px;
            font-weight: 600;
        }}
        QPushButton[actionKind="install"] {{
            background: {c.button.name()};
            color: {c.text.name()};
            border-color: {mix_colors(QColor("#2f8f5b"), c.window, 0.42 if c.window.lightness() < 128 else 0.62).name()};
        }}
        QPushButton[actionKind="remove"] {{
            background: {c.button.name()};
            color: {c.text.name()};
            border-color: {mix_colors(QColor("#a84d4d"), c.window, 0.42 if c.window.lightness() < 128 else 0.62).name()};
        }}
        QPushButton[uiRole="sourceAction"][actionKind="install"] {{
            background: {c.surface_alt.name()};
            color: {mix_colors(QColor("#9fdcb7"), c.text, 0.18).name()};
            border-color: {mix_colors(QColor("#2f8f5b"), c.window, 0.56 if c.window.lightness() < 128 else 0.70).name()};
        }}
        QPushButton[uiRole="sourceAction"][actionKind="remove"] {{
            background: {c.surface_alt.name()};
            color: {mix_colors(QColor("#e0b0b0"), c.text, 0.20).name()};
            border-color: {mix_colors(QColor("#a84d4d"), c.window, 0.56 if c.window.lightness() < 128 else 0.72).name()};
        }}
        QPushButton:disabled, QDialogButtonBox QPushButton:disabled {{
            background: {c.button_disabled.name()};
            color: {c.button_text_disabled.name()};
            border-color: {c.border.name()};
        }}
        QPushButton:hover:!disabled, QDialogButtonBox QPushButton:hover:!disabled {{
            background: {c.button_hover.name()};
        }}
        QPushButton[actionKind="install"]:hover:!disabled {{
            background: {mix_colors(QColor("#2f8f5b"), c.window, 0.18 if c.window.lightness() < 128 else 0.42).name()};
            color: {QColor("#f5fff9").name()};
            border-color: {mix_colors(QColor("#2f8f5b"), c.window, 0.42 if c.window.lightness() < 128 else 0.62).name()};
        }}
        QPushButton[actionKind="remove"]:hover:!disabled {{
            background: {mix_colors(QColor("#a84d4d"), c.window, 0.18 if c.window.lightness() < 128 else 0.42).name()};
            color: {QColor("#fff6f6").name()};
            border-color: {mix_colors(QColor("#a84d4d"), c.window, 0.42 if c.window.lightness() < 128 else 0.62).name()};
        }}
        QPushButton[actionKind="primary"]:hover:!disabled, QDialogButtonBox QPushButton[actionKind="primary"]:hover:!disabled {{
            background: {mix_colors(c.accent, c.window, 0.68 if c.window.lightness() < 128 else 0.80).name()};
            border-color: {mix_colors(c.accent, c.window, 0.42 if c.window.lightness() < 128 else 0.62).name()};
        }}
        QPushButton[newsState="unread"]:hover:!disabled {{
            background: {mix_colors(QColor("#256d85"), c.window, 0.54 if c.window.lightness() < 128 else 0.78).name()};
            border-color: {mix_colors(QColor("#38bdf8"), c.window, 0.28 if c.window.lightness() < 128 else 0.52).name()};
        }}
        QPushButton[uiRole="sourceAction"][actionKind="install"]:hover:!disabled {{
            background: {mix_colors(QColor("#2f8f5b"), c.window, 0.88 if c.window.lightness() < 128 else 0.94).name()};
            color: {QColor("#f5fff9").name()};
        }}
        QPushButton[uiRole="sourceAction"][actionKind="remove"]:hover:!disabled {{
            background: {mix_colors(QColor("#a84d4d"), c.window, 0.89 if c.window.lightness() < 128 else 0.95).name()};
            color: {QColor("#fff6f6").name()};
        }}
        QToolButton {{
            background: transparent;
            color: {c.text.name()};
            border: none;
            font-weight: 600;
            padding: 8px 10px;
        }}
        QComboBox {{
            background: {c.surface.name()};
            color: {c.text.name()};
            border: 1px solid {c.border.name()};
            border-radius: 10px;
            min-height: 20px;
            padding: 6px 12px;
            padding-right: 32px;
        }}
        QComboBox::drop-down {{
            subcontrol-origin: padding;
            subcontrol-position: top right;
            width: 28px;
            border: none;
            background: transparent;
        }}
        QComboBox::down-arrow {{
            width: 10px;
            height: 10px;
        }}
        QComboBox QAbstractItemView {{
            background: {c.panel.name()};
            color: {c.text.name()};
            border: 1px solid {c.border.name()};
            selection-background-color: {c.accent.name()};
            selection-color: {c.accent_text.name()};
        }}
"""
