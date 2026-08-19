"""
Tokyo Night Theme for PyQt6.

A beautiful dark theme inspired by the Tokyo Night color palette,
matching the original Tkinter application's aesthetic.

Usage:
    from gui_qt.theme import apply_theme, COLORS
    apply_theme(app)
"""

from PyQt6.QtWidgets import QApplication
from PyQt6.QtGui import QFont, QFontDatabase, QPalette, QColor
from PyQt6.QtCore import Qt


class TokyoNight:
    """Tokyo Night color palette."""

    # Backgrounds
    bg = "#1a1b26"
    bg_dark = "#16161e"
    bg_highlight = "#292e42"
    bg_visual = "#33467c"
    bg_input = "#24283b"

    # Foregrounds
    fg = "#c0caf5"
    fg_dark = "#565f89"
    comment = "#565f89"

    # Accent colors
    cyan = "#7dcfff"
    blue = "#7aa2f7"
    green = "#9ece6a"
    orange = "#ff9e64"
    red = "#f7768e"
    purple = "#bb9af7"
    magenta = "#ff007c"
    yellow = "#e0af68"

    # Utility
    black = "#15161e"
    white = "#c0caf5"
    border = "#3b4261"

    # Aliases required by widgets (must mirror specific bg/accent values)
    terminal_black = "#15161e"  # same as black; ported from an earlier PySide6 draft
    selection = "#33467c"  # same as bg_visual; used by custom_sources_dialog

    # Bright variants
    bright_red = "#ff7a93"
    bright_green = "#b9f27c"
    bright_yellow = "#ffc777"
    bright_blue = "#82aaff"
    bright_magenta = "#c099ff"  # kept as the final canonical value
    bright_cyan = "#86e1fc"
    bright_white = "#c8d3f5"

    # Specific UI elements
    bg_search = "#3b4261"


COLORS = TokyoNight()


class Fonts:
    """Font configurations for the application."""

    # Font families
    PRIMARY = "SF Pro Display, Segoe UI, Roboto, sans-serif"
    MONO = "JetBrains Mono, Fira Code, Consolas, monospace"

    # Font sizes
    SMALL = "11px"
    NORMAL = "13px"
    MEDIUM = "14px"
    LARGE = "16px"
    XLARGE = "18px"
    TITLE = "24px"

    _SIZE_MAP = {
        "xs": 10,
        "sm": 11,
        "md": 13,
        "lg": 16,
        "xl": 18,
        "2xl": 24,
        "3xl": 30,
        "4xl": 36,
    }

    @classmethod
    def get_size(cls, token: str) -> int:
        """Return numeric font size for theme token."""
        return cls._SIZE_MAP.get(token, cls._SIZE_MAP["md"])

    @classmethod
    def get_qfont(
        cls,
        token: str = "md",
        weight: str = "normal",
        mono: bool = False,
        family: str | None = None,
    ) -> QFont:
        """Return a configured QFont used by Qt widgets across dialogs."""
        size = cls.get_size(token)

        if family:
            family_name = family
        elif mono:
            family_name = "JetBrains Mono"
        else:
            families = QFontDatabase.families()
            if "SF Pro Display" in families:
                family_name = "SF Pro Display"
            elif "Segoe UI" in families:
                family_name = "Segoe UI"
            elif "Roboto" in families:
                family_name = "Roboto"
            else:
                family_name = "Sans Serif"

        font = QFont(family_name, size)
        weight_map = {
            "normal": QFont.Weight.Normal,
            "medium": QFont.Weight.Medium,
            "bold": QFont.Weight.Bold,
        }
        font.setWeight(weight_map.get(weight, QFont.Weight.Normal))
        return font


# Main QSS Stylesheet
STYLESHEET = f"""
/* ═══════════════════════════════════════════════════════════════
   GLOBAL STYLES
   ═══════════════════════════════════════════════════════════════ */

QWidget {{
    background-color: {COLORS.bg};
    color: {COLORS.fg};
    font-family: "SF Pro Display", "Segoe UI", "Roboto", sans-serif;
    font-size: 13px;
}}

QMainWindow {{
    background-color: {COLORS.bg};
}}

/* ═══════════════════════════════════════════════════════════════
   LABELS
   ═══════════════════════════════════════════════════════════════ */

QLabel {{
    background-color: transparent;
    color: {COLORS.fg};
}}

QLabel[class="title"] {{
    font-size: 24px;
    font-weight: bold;
    color: {COLORS.fg};
}}

QLabel[class="subtitle"] {{
    font-size: 14px;
    color: {COLORS.fg_dark};
}}

QLabel[class="accent"] {{
    color: {COLORS.cyan};
}}

/* ═══════════════════════════════════════════════════════════════
   BUTTONS
   ═══════════════════════════════════════════════════════════════ */

QPushButton {{
    background-color: {COLORS.bg_highlight};
    color: {COLORS.fg};
    border: 1px solid {COLORS.border};
    border-radius: 6px;
    padding: 8px 16px;
    font-weight: 500;
}}

QPushButton:hover {{
    background-color: {COLORS.bg_visual};
    border-color: {COLORS.cyan};
}}

QPushButton:pressed {{
    background-color: {COLORS.bg_dark};
}}

QPushButton:disabled {{
    background-color: {COLORS.bg_dark};
    color: {COLORS.comment};
}}

QPushButton[class="primary"] {{
    background-color: {COLORS.cyan};
    color: {COLORS.black};
    border: none;
    font-weight: bold;
}}

QPushButton[class="primary"]:hover {{
    background-color: {COLORS.blue};
}}

QPushButton[class="success"] {{
    background-color: {COLORS.green};
    color: {COLORS.black};
    border: none;
}}

QPushButton[class="danger"] {{
    background-color: {COLORS.red};
    color: {COLORS.black};
    border: none;
}}

/* ═══════════════════════════════════════════════════════════════
   INPUTS
   ═══════════════════════════════════════════════════════════════ */

QLineEdit {{
    background-color: {COLORS.bg_input};
    color: {COLORS.fg};
    border: 1px solid {COLORS.border};
    border-radius: 6px;
    padding: 8px 12px;
    selection-background-color: {COLORS.blue};
}}

QLineEdit:focus {{
    border-color: {COLORS.cyan};
}}

QLineEdit:disabled {{
    background-color: {COLORS.bg_dark};
    color: {COLORS.comment};
}}

QTextEdit, QPlainTextEdit {{
    background-color: {COLORS.bg_input};
    color: {COLORS.fg};
    border: 1px solid {COLORS.border};
    border-radius: 6px;
    padding: 8px;
    selection-background-color: {COLORS.blue};
}}

QTextEdit:focus, QPlainTextEdit:focus {{
    border-color: {COLORS.cyan};
}}

/* ═══════════════════════════════════════════════════════════════
   SCROLLBARS
   ═══════════════════════════════════════════════════════════════ */

QScrollBar:vertical {{
    background-color: {COLORS.bg_dark};
    width: 12px;
    border-radius: 6px;
    margin: 0;
}}

QScrollBar::handle:vertical {{
    background-color: {COLORS.bg_highlight};
    border-radius: 6px;
    min-height: 30px;
}}

QScrollBar::handle:vertical:hover {{
    background-color: {COLORS.bg_visual};
}}

QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
    height: 0;
}}

QScrollBar:horizontal {{
    background-color: {COLORS.bg_dark};
    height: 12px;
    border-radius: 6px;
}}

QScrollBar::handle:horizontal {{
    background-color: {COLORS.bg_highlight};
    border-radius: 6px;
    min-width: 30px;
}}

QScrollBar::handle:horizontal:hover {{
    background-color: {COLORS.bg_visual};
}}

/* ═══════════════════════════════════════════════════════════════
   FRAMES & CARDS
   ═══════════════════════════════════════════════════════════════ */

QFrame {{
    background-color: transparent;
    border: none;
}}

QFrame[class="card"] {{
    background-color: {COLORS.bg_highlight};
    border: 1px solid {COLORS.border};
    border-radius: 8px;
}}

QFrame[class="card"]:hover {{
    border-color: {COLORS.cyan};
}}

QFrame[class="sidebar"] {{
    background-color: {COLORS.bg_dark};
    border-right: 1px solid {COLORS.border};
}}

QFrame[class="header"] {{
    background-color: {COLORS.bg_dark};
    border-bottom: 1px solid {COLORS.border};
}}

/* ═══════════════════════════════════════════════════════════════
   TAB WIDGET
   ═══════════════════════════════════════════════════════════════ */

QTabWidget::pane {{
    background-color: {COLORS.bg};
    border: 1px solid {COLORS.border};
    border-radius: 4px;
    margin-top: -1px;
}}

QTabBar::tab {{
    background-color: {COLORS.bg_dark};
    color: {COLORS.fg_dark};
    padding: 10px 20px;
    border-top-left-radius: 4px;
    border-top-right-radius: 4px;
    margin-right: 2px;
}}

QTabBar::tab:selected {{
    background-color: {COLORS.bg};
    color: {COLORS.cyan};
    border-bottom: 2px solid {COLORS.cyan};
}}

QTabBar::tab:hover:!selected {{
    background-color: {COLORS.bg_highlight};
    color: {COLORS.fg};
}}

/* ═══════════════════════════════════════════════════════════════
   PROGRESS BAR
   ═══════════════════════════════════════════════════════════════ */

QProgressBar {{
    background-color: {COLORS.bg_dark};
    border: none;
    border-radius: 4px;
    height: 8px;
    text-align: center;
}}

QProgressBar::chunk {{
    background-color: {COLORS.cyan};
    border-radius: 4px;
}}

/* ═══════════════════════════════════════════════════════════════
   COMBO BOX
   ═══════════════════════════════════════════════════════════════ */

QComboBox {{
    background-color: {COLORS.bg_input};
    color: {COLORS.fg};
    border: 1px solid {COLORS.border};
    border-radius: 6px;
    padding: 6px 12px;
}}

QComboBox:hover {{
    border-color: {COLORS.cyan};
}}

QComboBox::drop-down {{
    border: none;
    padding-right: 10px;
}}

QComboBox QAbstractItemView {{
    background-color: {COLORS.bg_input};
    color: {COLORS.fg};
    border: 1px solid {COLORS.border};
    selection-background-color: {COLORS.bg_visual};
}}

/* ═══════════════════════════════════════════════════════════════
   CHECK BOX & RADIO BUTTON
   ═══════════════════════════════════════════════════════════════ */

QCheckBox, QRadioButton {{
    color: {COLORS.fg};
    spacing: 8px;
}}

QCheckBox::indicator, QRadioButton::indicator {{
    width: 18px;
    height: 18px;
    border-radius: 4px;
    background-color: {COLORS.bg_input};
    border: 1px solid {COLORS.border};
}}

QRadioButton::indicator {{
    border-radius: 9px;
}}

QCheckBox::indicator:checked {{
    background-color: {COLORS.cyan};
    border-color: {COLORS.cyan};
}}

QRadioButton::indicator:checked {{
    background-color: {COLORS.cyan};
    border-color: {COLORS.cyan};
}}

/* ═══════════════════════════════════════════════════════════════
   MENU & TOOLBAR
   ═══════════════════════════════════════════════════════════════ */

QMenuBar {{
    background-color: {COLORS.bg_dark};
    color: {COLORS.fg};
    border-bottom: 1px solid {COLORS.border};
    padding: 4px;
}}

QMenuBar::item:selected {{
    background-color: {COLORS.bg_highlight};
}}

QMenu {{
    background-color: {COLORS.bg_input};
    color: {COLORS.fg};
    border: 1px solid {COLORS.border};
    border-radius: 6px;
    padding: 4px;
}}

QMenu::item {{
    padding: 8px 24px;
    border-radius: 4px;
}}

QMenu::item:selected {{
    background-color: {COLORS.bg_visual};
}}

QMenu::separator {{
    height: 1px;
    background-color: {COLORS.border};
    margin: 4px 8px;
}}

QToolBar {{
    background-color: {COLORS.bg_dark};
    border: none;
    spacing: 4px;
    padding: 4px;
}}

/* ═══════════════════════════════════════════════════════════════
   TOOLTIPS
   ═══════════════════════════════════════════════════════════════ */

QToolTip {{
    background-color: {COLORS.bg_input};
    color: {COLORS.fg};
    border: 1px solid {COLORS.border};
    border-radius: 4px;
    padding: 6px 10px;
}}

/* ═══════════════════════════════════════════════════════════════
   SPLITTER
   ═══════════════════════════════════════════════════════════════ */

QSplitter::handle {{
    background-color: {COLORS.border};
}}

QSplitter::handle:horizontal {{
    width: 2px;
}}

QSplitter::handle:vertical {{
    height: 2px;
}}

QSplitter::handle:hover {{
    background-color: {COLORS.cyan};
}}

/* ═══════════════════════════════════════════════════════════════
   STATUS BAR
   ═══════════════════════════════════════════════════════════════ */

QStatusBar {{
    background-color: {COLORS.bg_dark};
    color: {COLORS.fg_dark};
    border-top: 1px solid {COLORS.border};
}}

QStatusBar::item {{
    border: none;
}}

/* ═══════════════════════════════════════════════════════════════
   DIALOG
   ═══════════════════════════════════════════════════════════════ */

QDialog {{
    background-color: {COLORS.bg};
}}

QDialogButtonBox QPushButton {{
    min-width: 80px;
}}
"""


def apply_theme(app: QApplication) -> None:
    """
    Apply Tokyo Night theme to the application.

    Args:
        app: QApplication instance
    """
    app.setStyleSheet(STYLESHEET)

    # Set application font - PyQt6 uses static methods
    families = QFontDatabase.families()

    if "SF Pro Display" in families:
        font = QFont("SF Pro Display", 13)
    elif "Segoe UI" in families:
        font = QFont("Segoe UI", 13)
    else:
        font = QFont("Roboto", 13)

    app.setFont(font)


def get_color(name: str) -> QColor:
    """Get QColor by name from theme."""
    return QColor(getattr(COLORS, name, COLORS.fg))


def get_score_color(score: float) -> str:
    """Map article score to color."""
    if score >= 8.0:
        return COLORS.green
    if score >= 6.5:
        return COLORS.cyan
    if score >= 5.0:
        return COLORS.yellow
    return COLORS.red


def get_tier_color(tier: str) -> str:
    """Map tier code to color."""
    tier = (tier or "").upper()
    if tier == "S":
        return COLORS.magenta
    if tier == "A":
        return COLORS.green
    if tier == "B":
        return COLORS.blue
    return COLORS.comment


def get_score_gradient(score: float) -> tuple[str, str]:
    """Return a simple two-color gradient for score visualizations."""
    base = get_score_color(score)
    return (base, COLORS.bg_highlight)


# Backward-compatible alias expected by tests and older imports.
TOKYO_NIGHT_QSS = STYLESHEET


__all__ = [
    "COLORS",
    "Fonts",
    "STYLESHEET",
    "TOKYO_NIGHT_QSS",
    "apply_theme",
    "get_color",
    "get_score_color",
    "get_tier_color",
    "get_score_gradient",
]
