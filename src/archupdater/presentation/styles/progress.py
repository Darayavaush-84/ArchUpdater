from __future__ import annotations

from .palette import ThemeColors, mix_colors


def build_styles(c: ThemeColors) -> str:
    return f"""        QDialog#updateProgressDialog {{
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
            border: 1px solid {mix_colors(c.accent, c.window, 0.55 if c.window.lightness() < 128 else 0.72).name()};
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
"""
