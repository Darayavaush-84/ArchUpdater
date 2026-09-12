from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtGui import QColor, QPalette


def _mix(a: QColor, b: QColor, ratio: float) -> QColor:
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


def _derive_theme_colors(palette: QPalette) -> ThemeColors:
    window = palette.color(QPalette.ColorRole.Window)
    base = palette.color(QPalette.ColorRole.Base)
    text = palette.color(QPalette.ColorRole.WindowText)
    button = palette.color(QPalette.ColorRole.Button)
    highlight = palette.color(QPalette.ColorRole.Highlight)
    highlighted_text = palette.color(QPalette.ColorRole.HighlightedText)

    dark = window.lightness() < 128
    panel = _mix(base, window, 0.20 if dark else 0.45)
    surface = _mix(base, window, 0.08 if dark else 0.18)
    surface_alt = _mix(surface, text, 0.04 if dark else 0.02)
    border = _mix(window, text, 0.18 if dark else 0.12)
    muted = _mix(text, window, 0.45 if dark else 0.52)
    accent_soft = _mix(highlight, window, 0.78 if dark else 0.85)
    button_hover = _mix(button, highlight, 0.18 if dark else 0.10)
    button_disabled = _mix(button, window, 0.55 if dark else 0.50)
    button_text_disabled = _mix(text, window, 0.55 if dark else 0.62)
    warning_base = QColor("#c97a1f")
    warning_bg = _mix(warning_base, window, 0.82 if dark else 0.90)
    warning_border = _mix(warning_base, window, 0.58 if dark else 0.72)
    warning_text = _mix(warning_base, text, 0.20)
    log_bg = _mix(base, text, 0.16 if dark else 0.88)
    log_text = _mix(text, window, 0.05 if dark else 0.92)

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


def build_application_stylesheet(palette: QPalette) -> str:
    c = _derive_theme_colors(palette)
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
            border: 1px solid {_mix(c.accent, c.window, 0.58 if c.window.lightness() < 128 else 0.70).name()};
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
            background: {_mix(c.surface, c.window, 0.32).name()};
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
        QDialog#updateProgressDialog {{
            background: {c.window.name()};
        }}
        QWidget#trayNotificationPopup {{
            background: transparent;
        }}
        QFrame#trayNotificationCard {{
            background: {c.panel.name()};
            border: 1px solid {c.border.name()};
            border-radius: 14px;
        }}
        QLabel#trayNotificationTitle {{
            color: {c.text.name()};
            font-size: 16px;
            font-weight: 700;
        }}
        QLabel#trayNotificationMessage {{
            color: {c.text.name()};
            font-size: 14px;
        }}
        QPushButton#trayNotificationClose {{
            background: transparent;
            border: none;
            color: {c.muted.name()};
            font-size: 22px;
            font-weight: 400;
            min-width: 24px;
            min-height: 24px;
            padding: 0;
        }}
        QPushButton#trayNotificationClose:hover {{
            color: {c.text.name()};
        }}
        QFrame#updateHeroCard, QFrame#updateStepsCard, QFrame#updateStepRow, QFrame#updateSummaryCard, QFrame#updateLogPanel {{
            background: {c.panel.name()};
            border: 1px solid {c.border.name()};
            border-radius: 8px;
        }}
        QScrollArea#updateProgressLeftScroll {{
            background: transparent;
            border: none;
        }}
        QWidget#updateProgressLeftPanel {{
            background: transparent;
        }}
        QFrame#updateNoticeCard {{
            background: {c.accent_soft.name()};
            border: 1px solid {_mix(c.accent, c.window, 0.55 if c.window.lightness() < 128 else 0.72).name()};
            border-radius: 16px;
        }}
        QLabel#updateNoticeIcon {{
            background: {c.accent.name()};
            color: {c.accent_text.name()};
            border-radius: 12px;
            font-size: 13px;
            font-weight: 700;
            min-width: 24px;
            max-width: 24px;
            min-height: 24px;
            max-height: 24px;
        }}
        QLabel#updateNoticeTitle {{
            color: {c.text.name()};
            font-size: 13px;
            font-weight: 700;
        }}
        QLabel#updateNoticeText {{
            color: {c.text.name()};
            font-size: 13px;
        }}
        QLabel#updateHeroTitle {{
            color: {c.text.name()};
            font-size: 24px;
            font-weight: 700;
        }}
        QLabel#updateHeroSubtitle {{
            color: {c.muted.name()};
            font-size: 14px;
        }}
        QLabel#updateHeroPercent {{
            color: {c.text.name()};
            font-weight: 700;
            min-width: 42px;
        }}
        QProgressBar#updateProgressBar {{
            border: none;
            background: {c.surface_alt.name()};
            border-radius: 6px;
        }}
        QLabel#updateStepTitle {{
            color: {c.text.name()};
            font-size: 13px;
            font-weight: 600;
        }}
        QLabel#updateStepMeta {{
            color: {c.muted.name()};
            font-size: 11px;
            font-weight: 600;
            letter-spacing: 0.3px;
        }}
        QLabel#updateStepBadge {{
            border-radius: 14px;
            font-weight: 700;
            color: {c.text.name()};
            background: {c.surface_alt.name()};
        }}
        QLabel#updateStepState {{
            color: {c.muted.name()};
            font-size: 12px;
            font-weight: 600;
        }}
        QLabel#updateLogCaption {{
            color: {c.muted.name()};
            font-size: 11px;
            font-weight: 600;
            letter-spacing: 0.3px;
        }}
        QLabel#updateSummaryHeading {{
            color: {c.text.name()};
            font-size: 12px;
            font-weight: 700;
        }}
        QLabel#updateSummaryText {{
            color: {c.muted.name()};
            font-size: 13px;
        }}
        QToolButton#updateStepToggle {{
            background: {c.surface_alt.name()};
            color: {c.text.name()};
            border: 1px solid {c.border.name()};
            border-radius: 10px;
            padding: 6px 10px;
            font-weight: 600;
        }}
        QToolButton#updateStepToggle:hover {{
            background: {c.accent_soft.name()};
        }}
        QFrame#updateStepRow[stepState="running"] {{
            border-color: {c.accent.name()};
        }}
        QFrame#updateStepRow[stepState="failed"] {{
            border-color: {c.warning_border.name()};
        }}
        QFrame#updateStepRow[stepState="incomplete"] {{
            border-color: {c.warning_border.name()};
        }}
        QLabel#updateStepBadge[stepState="pending"] {{
            background: {c.surface_alt.name()};
            color: {c.muted.name()};
        }}
        QLabel#updateStepBadge[stepState="running"] {{
            background: {c.accent.name()};
            color: {c.accent_text.name()};
        }}
        QLabel#updateStepBadge[stepState="completed"] {{
            background: {c.accent_soft.name()};
            color: {c.text.name()};
        }}
        QLabel#updateStepBadge[stepState="incomplete"] {{
            background: {c.warning_border.name()};
            color: {c.window.name()};
        }}
        QLabel#updateStepBadge[stepState="failed"] {{
            background: {c.warning_border.name()};
            color: {c.window.name()};
        }}
        QLabel#updateStepBadge[stepState="not_executed"] {{
            background: {c.surface_alt.name()};
            color: {c.muted.name()};
        }}
        QLabel#updateStepState[stepState="running"] {{
            color: {c.accent.name()};
        }}
        QLabel#updateStepState[stepState="completed"] {{
            color: {c.text.name()};
        }}
        QLabel#updateStepState[stepState="incomplete"] {{
            color: {c.warning_text.name()};
        }}
        QLabel#updateStepState[stepState="failed"] {{
            color: {c.warning_text.name()};
        }}
        QLabel#updateStepState[stepState="not_executed"] {{
            color: {c.muted.name()};
        }}
        QLabel#updateStepMeta[stepState="running"] {{
            color: {c.accent.name()};
        }}
        QLabel#updateStepMeta[stepState="incomplete"] {{
            color: {c.warning_text.name()};
        }}
        QLabel#updateStepMeta[stepState="failed"] {{
            color: {c.warning_text.name()};
        }}
        QLabel#updateStepMeta[stepState="not_executed"] {{
            color: {c.muted.name()};
        }}
        QLabel#warningText {{
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
        QPushButton, QDialogButtonBox QPushButton {{
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
            background: {_mix(c.accent, c.window, 0.84 if c.window.lightness() < 128 else 0.92).name()};
            color: {c.text.name()};
            border-color: {_mix(c.accent, c.window, 0.46 if c.window.lightness() < 128 else 0.66).name()};
        }}
        QPushButton[newsState="unread"] {{
            background: {_mix(QColor("#256d85"), c.window, 0.70 if c.window.lightness() < 128 else 0.88).name()};
            color: {c.text.name()};
            border-color: {_mix(QColor("#38bdf8"), c.window, 0.36 if c.window.lightness() < 128 else 0.58).name()};
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
            border-color: {_mix(QColor("#2f8f5b"), c.window, 0.42 if c.window.lightness() < 128 else 0.62).name()};
        }}
        QPushButton[actionKind="remove"] {{
            background: {c.button.name()};
            color: {c.text.name()};
            border-color: {_mix(QColor("#a84d4d"), c.window, 0.42 if c.window.lightness() < 128 else 0.62).name()};
        }}
        QPushButton[uiRole="sourceAction"][actionKind="install"] {{
            background: {c.surface_alt.name()};
            color: {_mix(QColor("#9fdcb7"), c.text, 0.18).name()};
            border-color: {_mix(QColor("#2f8f5b"), c.window, 0.56 if c.window.lightness() < 128 else 0.70).name()};
        }}
        QPushButton[uiRole="sourceAction"][actionKind="remove"] {{
            background: {c.surface_alt.name()};
            color: {_mix(QColor("#e0b0b0"), c.text, 0.20).name()};
            border-color: {_mix(QColor("#a84d4d"), c.window, 0.56 if c.window.lightness() < 128 else 0.72).name()};
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
            background: {_mix(QColor("#2f8f5b"), c.window, 0.18 if c.window.lightness() < 128 else 0.42).name()};
            color: {QColor("#f5fff9").name()};
            border-color: {_mix(QColor("#2f8f5b"), c.window, 0.42 if c.window.lightness() < 128 else 0.62).name()};
        }}
        QPushButton[actionKind="remove"]:hover:!disabled {{
            background: {_mix(QColor("#a84d4d"), c.window, 0.18 if c.window.lightness() < 128 else 0.42).name()};
            color: {QColor("#fff6f6").name()};
            border-color: {_mix(QColor("#a84d4d"), c.window, 0.42 if c.window.lightness() < 128 else 0.62).name()};
        }}
        QPushButton[actionKind="primary"]:hover:!disabled, QDialogButtonBox QPushButton[actionKind="primary"]:hover:!disabled {{
            background: {_mix(c.accent, c.window, 0.68 if c.window.lightness() < 128 else 0.80).name()};
            border-color: {_mix(c.accent, c.window, 0.42 if c.window.lightness() < 128 else 0.62).name()};
        }}
        QPushButton[newsState="unread"]:hover:!disabled {{
            background: {_mix(QColor("#256d85"), c.window, 0.54 if c.window.lightness() < 128 else 0.78).name()};
            border-color: {_mix(QColor("#38bdf8"), c.window, 0.28 if c.window.lightness() < 128 else 0.52).name()};
        }}
        QPushButton[uiRole="sourceAction"][actionKind="install"]:hover:!disabled {{
            background: {_mix(QColor("#2f8f5b"), c.window, 0.88 if c.window.lightness() < 128 else 0.94).name()};
            color: {QColor("#f5fff9").name()};
        }}
        QPushButton[uiRole="sourceAction"][actionKind="remove"]:hover:!disabled {{
            background: {_mix(QColor("#a84d4d"), c.window, 0.89 if c.window.lightness() < 128 else 0.95).name()};
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
        QTabWidget#preferencesTabs::pane {{
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
            background: {_mix(QColor("#2f8f5b"), c.window, 0.78 if c.window.lightness() < 128 else 0.86).name()};
            color: {_mix(QColor("#a6f0c5"), c.text, 0.15).name()};
            border: 1px solid {_mix(QColor("#2f8f5b"), c.window, 0.54 if c.window.lightness() < 128 else 0.68).name()};
        }}
        QLabel#sourceStateBadge[stateKind="disabled"] {{
            background: {c.surface_alt.name()};
            color: {c.text.name()};
            border: 1px solid {c.border.name()};
        }}
        QTreeWidget {{
            border: 1px solid {c.border.name()};
            border-radius: 14px;
            background: {c.surface.name()};
            color: {c.text.name()};
            alternate-background-color: {c.surface_alt.name()};
            padding: 6px;
            outline: 0;
            show-decoration-selected: 1;
        }}
        QTreeWidget::item {{
            color: {c.text.name()};
            background: transparent;
            padding: 6px 8px;
        }}
        QTreeWidget::item:selected,
        QTreeWidget::item:selected:active,
        QTreeWidget::item:selected:!active {{
            background: {c.accent.name()};
            color: {c.accent_text.name()};
        }}
        QTreeWidget::item:hover:!selected {{
            background: {c.accent_soft.name()};
        }}
        QTreeWidget::indicator {{
            width: 18px;
            height: 18px;
            min-width: 18px;
            max-width: 18px;
            min-height: 18px;
            max-height: 18px;
            margin-left: 2px;
            margin-right: 6px;
        }}
        QTreeWidget::indicator:unchecked,
        QTreeWidget::indicator:checked {{
            border: 1px solid {c.border.name()};
            border-radius: 4px;
            background: {c.surface_alt.name()};
        }}
        QTreeWidget::indicator:unchecked:hover {{
            border: 1px solid {c.accent.name()};
            background: {c.accent_soft.name()};
        }}
        QTreeWidget::indicator:checked {{
            border: 1px solid {c.accent.name()};
            background: {c.accent.name()};
        }}
        QTreeWidget::indicator:checked:hover {{
            border: 1px solid {c.accent.name()};
            background: {_mix(c.accent, c.text, 0.12).name()};
        }}
        QTreeWidget#packageUpdatesTree::indicator:unchecked,
        QTreeWidget#packageUpdatesTree::indicator:checked,
        QTreeWidget#packageUpdatesTree::indicator:unchecked:hover,
        QTreeWidget#packageUpdatesTree::indicator:checked:hover {{
            border: none;
            background: transparent;
        }}
        QHeaderView {{
            background: {c.surface_alt.name()};
        }}
        QHeaderView::section {{
            background: {c.surface_alt.name()};
            color: {c.text.name()};
            border: none;
            border-bottom: 1px solid {c.border.name()};
            padding: 10px 8px;
            font-weight: 600;
        }}
        QTableCornerButton::section {{
            background: {c.surface_alt.name()};
            border: none;
            border-bottom: 1px solid {c.border.name()};
        }}
        QTextEdit, QPlainTextEdit#updateStepLog, QPlainTextEdit#updateConsoleLog {{
            background: {_mix(c.surface, c.window, 0.38 if c.window.lightness() < 128 else 0.18).name()};
            color: {c.text.name()};
            border: 1px solid {c.border.name()};
            border-radius: 8px;
            padding: 10px;
            font-family: "JetBrains Mono", "Fira Code", monospace;
        }}
        QProgressBar {{
            border: none;
            background: {c.surface_alt.name()};
            border-radius: 6px;
        }}
        QProgressBar#headerProgressBar {{
            background: {c.surface_alt.name()};
        }}
        QProgressBar::chunk {{
            background: {c.accent.name()};
            border-radius: 6px;
        }}
        QFrame#statusHero, QFrame#actionBar {{
            background: transparent;
            border: none;
        }}
        QWidget#statusSummary, QWidget#counterArea {{
            background: transparent;
        }}
        QFrame#statusHero QLabel#systemStatus {{
            color: {c.text.name()};
            font-size: 24px;
            font-weight: 700;
        }}
        QLabel#statusMeta {{
            color: {c.muted.name()};
            font-size: 12px;
        }}
        QFrame#counterCard {{
            background: {c.panel.name()};
            border: 1px solid {c.border.name()};
            border-radius: 9px;
        }}
        QFrame#counterCard:hover {{
            background: {c.surface_alt.name()};
            border-color: {c.accent.name()};
        }}
        QFrame#counterCard:focus, QFrame#counterCard[filterActive="true"] {{
            background: {c.accent_soft.name()};
            border: 1px solid {c.accent.name()};
        }}
        QLabel#counterTitle {{
            color: {c.text.name()};
            font-size: 12px;
            font-weight: 500;
        }}
        QLabel#counterValue {{
            color: {c.text.name()};
            font-size: 15px;
            font-weight: 700;
        }}
        QLabel#counterFilterBadge {{
            background: transparent;
            color: {c.accent.name()};
            border: none;
            padding: 0;
            font-size: 14px;
        }}
        QLabel#counterLogoBadge {{
            background: transparent;
            border: none;
            color: {c.muted.name()};
            font-size: 9px;
            font-weight: 700;
        }}
        QStackedWidget#updatesContentStack {{
            background: transparent;
            border: none;
        }}
        QWidget#updatesEmptyState {{
            background: {c.surface.name()};
            border: 1px solid {c.border.name()};
            border-radius: 14px;
        }}
        QLabel#updatesEmptyIllustration {{
            background: transparent;
            border: none;
        }}
        QLabel#updatesEmptyTitle {{
            color: {c.text.name()};
            font-size: 19px;
            font-weight: 700;
        }}
        QLabel#updatesEmptyMessage {{
            color: {c.muted.name()};
            font-size: 13px;
        }}
        QFrame#overviewCard {{
            background: {c.panel.name()};
            border: 1px solid {c.border.name()};
            border-radius: 14px;
        }}
        QLabel#sectionTitleSmall {{
            color: {c.text.name()};
            font-size: 15px;
            font-weight: 700;
        }}
        QFrame#overviewMetricRow {{
            background: transparent;
            border: none;
        }}
        QFrame#overviewRowDivider, QFrame#overviewSectionDivider {{
            background: {c.border.name()};
            border: none;
        }}
        QLabel#overviewIconBadge {{
            background: rgba(42, 112, 205, 70);
            border: 1px solid rgba(64, 141, 241, 75);
            border-radius: 12px;
        }}
        QLabel#overviewIconBadge[tone="green"] {{
            background: rgba(38, 162, 91, 70);
            border-color: rgba(51, 211, 116, 80);
        }}
        QLabel#overviewIconBadge[tone="purple"] {{
            background: rgba(111, 64, 187, 80);
            border-color: rgba(157, 105, 245, 90);
        }}
        QLabel#overviewIconBadge[tone="lime"] {{
            background: rgba(125, 173, 31, 70);
            border-color: rgba(157, 211, 51, 80);
        }}
        QLabel#overviewMetricTitle {{
            color: {c.text.name()};
            font-size: 13px;
        }}
        QLabel#overviewMetricValue {{
            color: #43a0ff;
            font-size: 12px;
        }}
        QLabel#overviewMetricValue[tone="green"],
        QLabel#overviewMetricValue[tone="lime"] {{
            color: #31d174;
        }}
        QLabel#overviewMetricValue[tone="purple"] {{
            color: #a878f4;
        }}
        QPushButton#updateButton {{
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
            background: {_mix(c.accent, c.text, 0.10).name()};
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
