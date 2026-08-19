"""
Disruptive News Dialog — Tech News Scraper v8.0
Shows high-criticality and disruptive articles from the database,
color-coded by criticality level.
"""

from __future__ import annotations

import logging
import webbrowser
from typing import Any, Dict, List, Optional

from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtWidgets import (
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSplitter,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from ..theme import COLORS, Fonts

logger = logging.getLogger(__name__)


def _criticality_color(criticality: float) -> str:
    """Map 0-1 criticality to a theme color."""
    if criticality >= 0.8:
        return COLORS.red
    if criticality >= 0.6:
        return COLORS.orange
    if criticality >= 0.4:
        return COLORS.yellow
    return COLORS.cyan


class ArticleCard(QFrame):
    """Compact card for a disruptive / high-priority article."""

    open_url_requested = pyqtSignal(str)

    def __init__(
        self, article: Dict[str, Any], parent: Optional[QWidget] = None
    ) -> None:
        super().__init__(parent)
        self._article = article
        self._setup_ui()

    def _setup_ui(self) -> None:
        criticality = float(self._article.get("criticality", 0) or 0)
        color = _criticality_color(criticality)

        self.setStyleSheet(
            f"""
            ArticleCard {{
                background-color: {COLORS.bg_highlight};
                border-left: 4px solid {color};
                border-radius: 6px;
            }}
            ArticleCard:hover {{
                background-color: {COLORS.bg_visual};
            }}
            """
        )

        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 10, 14, 10)
        layout.setSpacing(6)

        # Title row
        title_row = QHBoxLayout()
        title = QLabel(self._article.get("title", "Untitled"))
        title.setFont(Fonts.get_qfont("sm", "bold"))
        title.setStyleSheet(f"color: {COLORS.fg}; background: transparent;")
        title.setWordWrap(True)
        title_row.addWidget(title, 1)

        crit_badge = QLabel(f"⚡ {criticality:.0%}")
        crit_badge.setStyleSheet(
            f"color: {color}; font-weight: bold; font-size: 11px; background: transparent;"
        )
        title_row.addWidget(crit_badge)
        layout.addLayout(title_row)

        # Source + sentiment row
        source = self._article.get("source", "Unknown")
        sentiment = self._article.get("sentiment", "")
        meta_text = f"🔗 {source}"
        if sentiment:
            meta_text += f"  |  💬 {sentiment}"
        meta = QLabel(meta_text)
        meta.setStyleSheet(
            f"color: {COLORS.comment}; font-size: 11px; background: transparent;"
        )
        layout.addWidget(meta)

        # Justification
        justification = self._article.get("justification", "")
        if justification:
            just_label = QLabel(justification)
            just_label.setWordWrap(True)
            just_label.setStyleSheet(
                f"color: {COLORS.fg_dark}; font-size: 11px; background: transparent;"
            )
            layout.addWidget(just_label)

        # Affected items
        markets = self._article.get("affected_markets", [])
        companies = self._article.get("affected_companies", [])
        if markets or companies:
            tags = (markets or []) + (companies or [])
            tags_text = "  ".join(f"[{t}]" for t in tags[:6])
            tags_label = QLabel(tags_text)
            tags_label.setStyleSheet(
                f"color: {COLORS.blue}; font-size: 10px; background: transparent;"
            )
            layout.addWidget(tags_label)

        # Open button
        url = self._article.get("url", "")
        if url:
            open_btn = QPushButton("🔗 Open Article")
            open_btn.setCursor(Qt.CursorShape.PointingHandCursor)
            open_btn.setFixedHeight(28)
            open_btn.setStyleSheet(
                f"""
                QPushButton {{
                    background-color: {COLORS.bg_visual};
                    color: {COLORS.cyan};
                    border: 1px solid {COLORS.cyan};
                    border-radius: 4px;
                    font-size: 11px;
                    padding: 0 10px;
                }}
                QPushButton:hover {{
                    background-color: {COLORS.cyan};
                    color: {COLORS.bg_dark};
                }}
                """
            )
            open_btn.clicked.connect(lambda: self.open_url_requested.emit(url))
            btn_row = QHBoxLayout()
            btn_row.addStretch()
            btn_row.addWidget(open_btn)
            layout.addLayout(btn_row)


class _ArticleListPane(QWidget):
    """Scrollable list of ArticleCard widgets."""

    def __init__(
        self, articles: List[Dict[str, Any]], parent: Optional[QWidget] = None
    ) -> None:
        super().__init__(parent)
        self._articles = articles
        self._setup_ui()

    def _setup_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet("QScrollArea { border: none; background: transparent; }")
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        container = QWidget()
        container.setStyleSheet("background: transparent;")
        vbox = QVBoxLayout(container)
        vbox.setContentsMargins(8, 8, 8, 8)
        vbox.setSpacing(10)

        if not self._articles:
            empty = QLabel("No articles found.")
            empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
            empty.setStyleSheet(f"color: {COLORS.comment}; font-size: 14px;")
            vbox.addWidget(empty)
        else:
            for article in self._articles:
                card = ArticleCard(article, container)
                card.open_url_requested.connect(webbrowser.open)
                vbox.addWidget(card)

        vbox.addStretch()
        scroll.setWidget(container)
        outer.addWidget(scroll)


class DisruptiveNewsDialog(QDialog):
    """
    Dialog showing disruptive and high-criticality articles.

    Can be seeded with in-memory pre-scored articles (preferred) and
    also tries the DB as a fallback.

    Tabs:
      • 🔥 Disruptive  — articles where _disruptive=True or disruptive=1
      • 🔴 High Priority — articles where _criticality >= 0.4 or criticality >= 0.7
    """

    def __init__(
        self,
        parent: Optional[QWidget] = None,
        in_memory_articles: Optional[List[Dict[str, Any]]] = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("🔥 Disruptive News")
        self.setMinimumSize(800, 600)
        self.resize(900, 650)

        self._in_memory_articles = in_memory_articles or []
        self._disruptive: List[Dict[str, Any]] = []
        self._high_priority: List[Dict[str, Any]] = []

        self._setup_ui()
        self._apply_styles()

        # Load data after show so the dialog appears immediately
        QTimer.singleShot(50, self._load_data)

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        # Header
        header_row = QHBoxLayout()
        header_icon = QLabel("🔥")
        header_icon.setStyleSheet("font-size: 24px;")
        header_row.addWidget(header_icon)

        header_title = QLabel("Disruptive News")
        header_title.setStyleSheet(
            f"font-size: 20px; font-weight: bold; color: {COLORS.orange};"
        )
        header_row.addWidget(header_title)
        header_row.addStretch()

        self.refresh_btn = QPushButton("🔄 Refresh")
        self.refresh_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.refresh_btn.clicked.connect(self._load_data)
        self.refresh_btn.setStyleSheet(
            f"""
            QPushButton {{
                background-color: {COLORS.bg_visual};
                color: {COLORS.cyan};
                border: 1px solid {COLORS.cyan};
                border-radius: 6px;
                padding: 6px 14px;
            }}
            QPushButton:hover {{
                background-color: {COLORS.cyan};
                color: {COLORS.bg_dark};
            }}
            """
        )
        header_row.addWidget(self.refresh_btn)
        layout.addLayout(header_row)

        desc = QLabel(
            "High-impact articles flagged by the AI intelligence engine, "
            "sorted by criticality score."
        )
        desc.setWordWrap(True)
        desc.setStyleSheet(f"color: {COLORS.comment}; font-size: 12px;")
        layout.addWidget(desc)

        # Tabs
        self.tabs = QTabWidget()
        layout.addWidget(self.tabs)

        self._disruptive_tab = _ArticleListPane([])
        self.tabs.addTab(self._disruptive_tab, "🔥 Disruptive (0)")

        self._high_priority_tab = _ArticleListPane([])
        self.tabs.addTab(self._high_priority_tab, "🔴 High Priority (0)")

        # Close button
        btn_row = QHBoxLayout()
        btn_row.addStretch()
        close_btn = QPushButton("✕ Close")
        close_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        close_btn.clicked.connect(self.reject)
        close_btn.setStyleSheet(
            f"""
            QPushButton {{
                background-color: {COLORS.bg_highlight};
                color: {COLORS.fg};
                border: 1px solid {COLORS.border};
                border-radius: 6px;
                padding: 8px 18px;
            }}
            QPushButton:hover {{
                background-color: {COLORS.bg_visual};
            }}
            """
        )
        btn_row.addWidget(close_btn)
        layout.addLayout(btn_row)

    def _apply_styles(self) -> None:
        self.setStyleSheet(
            f"""
            QDialog {{
                background-color: {COLORS.bg};
            }}
            QTabWidget::pane {{
                border: 1px solid {COLORS.border};
                background-color: {COLORS.bg};
            }}
            QTabBar::tab {{
                background-color: {COLORS.bg_highlight};
                color: {COLORS.fg_dark};
                padding: 8px 16px;
                border-top-left-radius: 6px;
                border-top-right-radius: 6px;
                margin-right: 2px;
            }}
            QTabBar::tab:selected {{
                background-color: {COLORS.bg_visual};
                color: {COLORS.fg};
                border-bottom: 2px solid {COLORS.orange};
            }}
            """
        )

    def _load_data(self) -> None:
        """Build article lists from in-memory scored articles, falling back to DB."""
        if self._in_memory_articles:
            # Use in-memory scored articles (faster, no DB needed)
            self._disruptive = sorted(
                [a for a in self._in_memory_articles if a.get("_disruptive")],
                key=lambda a: float(a.get("_criticality", 0) or 0),
                reverse=True,
            )
            self._high_priority = sorted(
                [
                    a
                    for a in self._in_memory_articles
                    if float(a.get("_criticality", 0) or 0) >= 0.4
                    or float(a.get("tech_score", 0) or 0) >= 8.0
                ],
                key=lambda a: float(a.get("_criticality", 0) or 0),
                reverse=True,
            )
        else:
            self._disruptive = []
            self._high_priority = []

        self._rebuild_tab(0, self._disruptive, "🔥 Disruptive")
        self._rebuild_tab(1, self._high_priority, "🔴 High Priority")

    def _rebuild_tab(
        self, index: int, articles: List[Dict[str, Any]], label: str
    ) -> None:
        """Replace tab contents with a fresh ArticleListPane."""
        pane = _ArticleListPane(articles)
        self.tabs.removeTab(index)
        self.tabs.insertTab(index, pane, f"{label} ({len(articles)})")
        self.tabs.setCurrentIndex(index)
