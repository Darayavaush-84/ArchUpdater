from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtGui import QColor, QPalette


def mix_colors(a: QColor, b: QColor, ratio: float) -> QColor:
    ratio = max(0.0, min(1.0, ratio))
    inv = 1.0 - ratio
    return QColor(
        round(a.red() * inv + b.red() * ratio),
        round(a.green() * inv + b.green() * ratio),
        round(a.blue() * inv + b.blue() * ratio),
        round(a.alpha() * inv + b.alpha() * ratio),
    )


@dataclass(frozen=True, slots=True)
class ThemeColors:
    window: QColor
    panel: QColor
    surface: QColor
    surface_alt: QColor
    border: QColor
    text: QColor
    muted: QColor
    accent: QColor
    accent_text: QColor
    accent_soft: QColor
    button: QColor
    button_hover: QColor
    button_disabled: QColor
    button_text_disabled: QColor
    warning_bg: QColor
    warning_border: QColor
    warning_text: QColor
    log_bg: QColor
    log_text: QColor


def derive_theme_colors(palette: QPalette) -> ThemeColors:
    window = palette.color(QPalette.ColorRole.Window)
    base = palette.color(QPalette.ColorRole.Base)
    text = palette.color(QPalette.ColorRole.WindowText)
    button = palette.color(QPalette.ColorRole.Button)
    highlight = palette.color(QPalette.ColorRole.Highlight)
    highlighted_text = palette.color(QPalette.ColorRole.HighlightedText)

    dark = window.lightness() < 128
    panel = mix_colors(base, window, 0.20 if dark else 0.45)
    surface = mix_colors(base, window, 0.08 if dark else 0.18)
    surface_alt = mix_colors(surface, text, 0.04 if dark else 0.02)
    border = mix_colors(window, text, 0.18 if dark else 0.12)
    muted = mix_colors(text, window, 0.45 if dark else 0.52)
    accent_soft = mix_colors(highlight, window, 0.78 if dark else 0.85)
    button_hover = mix_colors(button, highlight, 0.18 if dark else 0.10)
    button_disabled = mix_colors(button, window, 0.55 if dark else 0.50)
    button_text_disabled = mix_colors(text, window, 0.55 if dark else 0.62)
    warning_base = QColor("#c97a1f")
    warning_bg = mix_colors(warning_base, window, 0.82 if dark else 0.90)
    warning_border = mix_colors(warning_base, window, 0.58 if dark else 0.72)
    warning_text = mix_colors(warning_base, text, 0.20)
    log_bg = mix_colors(base, text, 0.16 if dark else 0.88)
    log_text = mix_colors(text, window, 0.05 if dark else 0.92)

    return ThemeColors(
        window=window,
        panel=panel,
        surface=surface,
        surface_alt=surface_alt,
        border=border,
        text=text,
        muted=muted,
        accent=highlight,
        accent_text=highlighted_text,
        accent_soft=accent_soft,
        button=button,
        button_hover=button_hover,
        button_disabled=button_disabled,
        button_text_disabled=button_text_disabled,
        warning_bg=warning_bg,
        warning_border=warning_border,
        warning_text=warning_text,
        log_bg=log_bg,
        log_text=log_text,
    )
