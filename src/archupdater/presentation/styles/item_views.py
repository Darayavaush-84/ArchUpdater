from __future__ import annotations

from .palette import ThemeColors, mix_colors


def build_styles(c: ThemeColors) -> str:
    return f"""        QTreeWidget {{
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
            background: {mix_colors(c.accent, c.text, 0.12).name()};
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
            background: {mix_colors(c.surface, c.window, 0.38 if c.window.lightness() < 128 else 0.18).name()};
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
"""
