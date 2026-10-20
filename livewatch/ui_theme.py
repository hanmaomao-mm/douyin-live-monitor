# -*- coding: utf-8 -*-
"""界面主题（深色）与通用样式。"""

# 调色板
BG = "#161a22"
BG_PANEL = "#1d222c"
BG_ELEV = "#242a36"
BORDER = "#2f3746"
TEXT = "#e6e9f0"
TEXT_DIM = "#98a1b3"
ACCENT = "#4a9eff"
DANGER = "#ff4d4f"
SUCCESS = "#39c07a"
WARN = "#ff9f43"

QSS = f"""
QWidget {{
    background-color: {BG};
    color: {TEXT};
    font-family: "Microsoft YaHei UI", "Microsoft YaHei", "Segoe UI", sans-serif;
    font-size: 13px;
}}
QMainWindow, QDialog {{ background-color: {BG}; }}

QLabel {{ background: transparent; }}
QLabel#Title {{ font-size: 17px; font-weight: 600; }}
QLabel#Subtitle {{ color: {TEXT_DIM}; font-size: 12px; }}
QLabel#Hint {{ color: {TEXT_DIM}; font-size: 12px; }}

QGroupBox {{
    background-color: {BG_PANEL};
    border: 1px solid {BORDER};
    border-radius: 8px;
    margin-top: 14px;
    padding: 12px 12px 10px 12px;
    font-weight: 600;
}}
QGroupBox::title {{
    subcontrol-origin: margin;
    subcontrol-position: top left;
    left: 12px;
    padding: 0 6px;
    color: {TEXT_DIM};
}}

QLineEdit, QSpinBox, QComboBox, QPlainTextEdit, QTextEdit {{
    background-color: {BG_ELEV};
    border: 1px solid {BORDER};
    border-radius: 6px;
    padding: 6px 9px;
    selection-background-color: {ACCENT};
    selection-color: #ffffff;
}}
QLineEdit:focus, QSpinBox:focus, QComboBox:focus, QPlainTextEdit:focus {{
    border: 1px solid {ACCENT};
}}
QLineEdit:disabled, QSpinBox:disabled, QComboBox:disabled {{
    color: {TEXT_DIM};
    background-color: #1a1f28;
}}
QLineEdit[readOnly="true"] {{ color: {TEXT_DIM}; }}

QComboBox::drop-down {{ border: none; width: 22px; }}
QComboBox QAbstractItemView {{
    background-color: {BG_ELEV};
    border: 1px solid {BORDER};
    selection-background-color: {ACCENT};
    outline: none;
}}
QSpinBox::up-button, QSpinBox::down-button {{
    background-color: {BG_ELEV};
    border: none;
    width: 16px;
}}

QPushButton {{
    background-color: {BG_ELEV};
    border: 1px solid {BORDER};
    border-radius: 6px;
    padding: 7px 14px;
    color: {TEXT};
}}
QPushButton:hover {{ background-color: #2c3442; border-color: #3d4759; }}
QPushButton:pressed {{ background-color: #232a36; }}
QPushButton:disabled {{ color: #5d6675; background-color: #1a1f28; border-color: #262d3a; }}

QPushButton#Primary {{
    background-color: {ACCENT};
    border: 1px solid {ACCENT};
    color: #ffffff;
    font-weight: 600;
}}
QPushButton#Primary:hover {{ background-color: #5aa9ff; }}
QPushButton#Primary:disabled {{ background-color: #2b3444; border-color: #2b3444; color: #6b7484; }}

QPushButton#Start {{
    background-color: {SUCCESS};
    border: 1px solid {SUCCESS};
    color: #0c1017;
    font-weight: 600;
    padding: 8px 18px;
}}
QPushButton#Start:hover {{ background-color: #46d38a; }}

QPushButton#Stop {{
    background-color: transparent;
    border: 1px solid {DANGER};
    color: {DANGER};
    font-weight: 600;
    padding: 8px 18px;
}}
QPushButton#Stop:hover {{ background-color: rgba(255, 77, 79, 0.15); }}

QPushButton#Link {{
    background: transparent;
    border: none;
    color: {ACCENT};
    padding: 2px 4px;
    text-align: left;
}}
QPushButton#Link:hover {{ color: #7dbcff; text-decoration: underline; }}

QPushButton#RowAction {{
    background-color: transparent;
    border: 1px solid {BORDER};
    border-radius: 5px;
    padding: 3px 10px;
    color: {TEXT_DIM};
    font-size: 12px;
}}
QPushButton#RowAction:hover {{ color: {DANGER}; border-color: {DANGER}; }}

QTableWidget {{
    background-color: {BG_PANEL};
    alternate-background-color: #1a1f28;
    border: 1px solid {BORDER};
    border-radius: 8px;
    gridline-color: transparent;
    outline: none;
}}
QTableWidget::item {{ padding: 4px 6px; border: none; }}
QTableWidget::item:selected {{ background-color: rgba(74, 158, 255, 0.18); color: {TEXT}; }}
QHeaderView::section {{
    background-color: {BG_ELEV};
    color: {TEXT_DIM};
    border: none;
    border-bottom: 1px solid {BORDER};
    padding: 8px 6px;
    font-weight: 600;
}}
QTableCornerButton::section {{ background-color: {BG_ELEV}; border: none; }}

QTabWidget::pane {{
    border: 1px solid {BORDER};
    border-radius: 8px;
    background-color: {BG_PANEL};
    top: -1px;
}}
QTabBar::tab {{
    background: transparent;
    color: {TEXT_DIM};
    padding: 8px 18px;
    border: 1px solid transparent;
    border-top-left-radius: 7px;
    border-top-right-radius: 7px;
}}
QTabBar::tab:selected {{
    background-color: {BG_PANEL};
    color: {TEXT};
    border: 1px solid {BORDER};
    border-bottom-color: {BG_PANEL};
}}

QScrollBar:vertical {{ background: transparent; width: 10px; margin: 2px; }}
QScrollBar::handle:vertical {{ background: #3a4354; border-radius: 5px; min-height: 30px; }}
QScrollBar::handle:vertical:hover {{ background: #4b566b; }}
QScrollBar:horizontal {{ background: transparent; height: 10px; margin: 2px; }}
QScrollBar::handle:horizontal {{ background: #3a4354; border-radius: 5px; min-width: 30px; }}
QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; width: 0; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}

QCheckBox {{ spacing: 6px; }}
QCheckBox::indicator {{
    width: 15px; height: 15px;
    border: 1px solid {BORDER};
    border-radius: 4px;
    background: {BG_ELEV};
}}
QCheckBox::indicator:checked {{ background: {ACCENT}; border-color: {ACCENT}; }}

QSplitter::handle {{ background-color: transparent; height: 8px; }}
QStatusBar {{ color: {TEXT_DIM}; border-top: 1px solid {BORDER}; }}
QStatusBar::item {{ border: none; }}

QToolTip {{
    background-color: {BG_ELEV};
    color: {TEXT};
    border: 1px solid {BORDER};
    padding: 4px 6px;
}}
"""

LOG_COLORS = {
    "DEBUG": "#7d8798",
    "INFO": "#c3cad8",
    "WARNING": "#ff9f43",
    "ERROR": "#ff6b6d",
    "CRITICAL": "#ff4d4f",
}
