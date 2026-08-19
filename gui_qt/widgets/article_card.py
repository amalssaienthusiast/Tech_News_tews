"""
Article Card Widget - Beautiful card display for tech news articles.

Features:
- Tokyo Night themed cards with hover effects
- Tech score progress bar with tier badges
- Source and timestamp display
- Save button and click-to-open URL
"""

from datetime import datetime
from typing import Any, Callable, Dict, Optional

from PyQt6.QtCore import Qt, pyqtSignal, QUrl
from PyQt6.QtGui import QCursor, QDesktopServices, QFont
from PyQt6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QMenu,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
    QProgressBar,
)

from gui_qt.theme import COLORS


class TechScoreBar(QWidget):
    """Visual tech score indicator."""

    def __init__(self, score: float = 0.0, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.score = min(max(score, 0), 100)
        self._setup_ui()

    def _setup_ui(self) -> None:
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        # Progress bar
        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setValue(int(self.score))
        self.progress.setTextVisible(False)
        self.progress.setFixedHeight(6)
        self.progress.setFixedWidth(80)

        # Color based on score
        if self.score >= 80:
            color = COLORS.green
        elif self.score >= 60:
            color = COLORS.cyan
        elif self.score >= 40:
            color = COLORS.orange
        else:
            color = COLORS.fg_dark

        self.progress.setStyleSheet(f"""
            QProgressBar {{
                background-color: {COLORS.bg_dark};
                border: none;
                border-radius: 3px;
            }}
            QProgressBar::chunk {{
                background-color: {color};
                border-radius: 3px;
            }}
        """)

        # Score label
        self.score_label = QLabel(f"{self.score:.0f}")
        self.score_label.setStyleSheet(
            f"color: {color}; font-weight: bold; font-size: 12px;"
        )

        layout.addWidget(self.progress)
        layout.addWidget(self.score_label)
        layout.addStretch()


class TierBadge(QLabel):
    """Tier indicator badge (S/A/B/C)."""

    TIER_COLORS = {
        "S": COLORS.magenta,
        "A": COLORS.green,
        "B": COLORS.cyan,
        "C": COLORS.orange,
        "D": COLORS.fg_dark,
    }

    def __init__(self, tier: str = "C", parent: Optional[QWidget] = None) -> None:
        super().__init__(tier, parent)
        color = self.TIER_COLORS.get(tier, COLORS.fg_dark)

        self.setStyleSheet(f"""
            background-color: {color};
            color: {COLORS.black};
            font-weight: bold;
            font-size: 11px;
            padding: 2px 8px;
            border-radius: 4px;
        """)
        self.setFixedHeight(20)


class ArticleCard(QFrame):
    """
    Beautiful article card widget.

    Displays article title, source, tech score, and action buttons.
    """

    # Signals
    clicked = pyqtSignal(dict)  # Article data
    saved = pyqtSignal(str, bool)  # (article_id, is_saved)
    archive_requested = pyqtSignal(str) # article_id
    def __init__(
        self,
        article: Dict[str, Any],
        on_save: Optional[Callable[[str, bool], None]] = None,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self.article = article
        self.on_save_callback = on_save
        self.is_saved = False

        self._setup_ui()

    def _setup_ui(self) -> None:
        self.setProperty("class", "card")
        self.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(self._show_context_menu)
        self.setStyleSheet(f"""
            ArticleCard {{
                background-color: {COLORS.bg_highlight};
                border: 1px solid {COLORS.border};
                border-radius: 8px;
                padding: 12px;
            }}
            ArticleCard:hover {{
                border-color: {COLORS.cyan};
                background-color: {COLORS.bg_visual};
            }}
        """)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(10)

        # Header row: Source + Tier + Timestamp
        header = QHBoxLayout()
        header.setSpacing(8)

        # Source
        source = self.article.get("source", "Unknown")
        source_label = QLabel(f"📰 {source}")
        source_label.setStyleSheet(
            f"color: {COLORS.cyan}; font-size: 11px; font-weight: 500;"
        )
        header.addWidget(source_label)

        # Tier badge
        tech_score = self.article.get("tech_score", 50)
        tier = self._get_tier(tech_score)
        tier_badge = TierBadge(tier)
        header.addWidget(tier_badge)

        header.addStretch()

        # Timestamp / Relative Liveness
        rel_time = self.article.get("relative_time")
        published = self.article.get("published") or self.article.get("published_at")
        if rel_time:
            time_text = rel_time
        elif published:
            if isinstance(published, str):
                time_text = published[:16]
            else:
                time_text = published.strftime("%H:%M")
        else:
            time_text = "Recent"

        time_label = QLabel(f"🕐 {time_text}")
        time_label.setStyleSheet(f"color: {COLORS.comment}; font-size: 11px; font-weight: 500;")
        header.addWidget(time_label)


        layout.addLayout(header)

        # Title
        title = self.article.get("title", "Untitled")
        title_label = QLabel(title)
        title_label.setWordWrap(True)
        title_label.setStyleSheet(f"""
            color: {COLORS.fg};
            font-size: 15px;
            font-weight: 600;
            line-height: 1.4;
        """)
        title_label.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred
        )
        layout.addWidget(title_label)

        # Summary (if available)
        summary = self.article.get("ai_summary", "")
        if summary:
            summary_label = QLabel(
                summary[:200] + "..." if len(summary) > 200 else summary
            )
            summary_label.setWordWrap(True)
            summary_label.setStyleSheet(f"color: {COLORS.fg_dark}; font-size: 12px;")
            layout.addWidget(summary_label)

        # Footer row: Tech score + Actions
        footer = QHBoxLayout()
        footer.setSpacing(12)

        # Tech score bar
        score_widget = TechScoreBar(tech_score)
        footer.addWidget(score_widget)

        footer.addStretch()

        # Save button
        self.save_btn = QPushButton("💾")
        self.save_btn.setFixedSize(32, 32)
        self.save_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {COLORS.bg_dark};
                border: 1px solid {COLORS.border};
                border-radius: 6px;
                font-size: 14px;
            }}
            QPushButton:hover {{
                background-color: {COLORS.bg_visual};
                border-color: {COLORS.cyan};
            }}
        """)
        self.save_btn.clicked.connect(self._on_save_clicked)
        footer.addWidget(self.save_btn)

        # Open URL button
        open_btn = QPushButton("🔗")
        open_btn.setFixedSize(32, 32)
        open_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {COLORS.bg_dark};
                border: 1px solid {COLORS.border};
                border-radius: 6px;
                font-size: 14px;
            }}
            QPushButton:hover {{
                background-color: {COLORS.cyan};
                color: {COLORS.black};
            }}
        """)
        open_btn.clicked.connect(self._open_url)
        footer.addWidget(open_btn)

        layout.addLayout(footer)

    def _get_tier(self, score: float) -> str:
        """Get tier letter from score."""
        # Handle None or invalid scores
        if score is None:
            return "C"

        try:
            score = float(score)
            if score >= 90:
                return "S"
            elif score >= 75:
                return "A"
            elif score >= 50:
                return "B"
            elif score >= 25:
                return "C"
            else:
                return "D"
        except (TypeError, ValueError):
            return "C"

    def _on_save_clicked(self) -> None:
        """Handle save button click."""
        self.is_saved = not self.is_saved

        if self.is_saved:
            self.save_btn.setText("✅")
            self.save_btn.setStyleSheet(f"""
                QPushButton {{
                    background-color: {COLORS.green};
                    border: none;
                    border-radius: 6px;
                    font-size: 14px;
                }}
            """)
        else:
            self.save_btn.setText("💾")
            self.save_btn.setStyleSheet(f"""
                QPushButton {{
                    background-color: {COLORS.bg_dark};
                    border: 1px solid {COLORS.border};
                    border-radius: 6px;
                    font-size: 14px;
                }}
                QPushButton:hover {{
                    background-color: {COLORS.bg_visual};
                    border-color: {COLORS.cyan};
                }}
            """)

        article_id = self.article.get("id", self.article.get("url", ""))
        self.saved.emit(article_id, self.is_saved)

        if self.on_save_callback:
            self.on_save_callback(article_id, self.is_saved)

    def _open_url(self) -> None:
        """Open article URL in browser."""
        url = self.article.get("url")
        if url:
            QDesktopServices.openUrl(QUrl(url))

    def _show_context_menu(self, pos) -> None:
        """Show right-click context menu."""
        menu = QMenu(self)
        menu.setStyleSheet(f"""
            QMenu {{
                background-color: {COLORS.bg_highlight};
                color: {COLORS.fg};
                border: 1px solid {COLORS.border};
                border-radius: 6px;
                padding: 4px;
            }}
            QMenu::item {{
                padding: 8px 20px;
                border-radius: 4px;
            }}
            QMenu::item:selected {{
                background-color: {COLORS.cyan};
                color: {COLORS.black};
            }}
        """)

        bypass_action = menu.addAction("🔓 Advanced Paywall Bypass")
        bypass_action.triggered.connect(self._quantum_bypass)

        open_action = menu.addAction("🔗 Open in Browser")
        open_action.triggered.connect(self._open_url)

        archive_action = menu.addAction("📥 Archive")
        archive_action.triggered.connect(self._archive_article)

        menu.exec(self.mapToGlobal(pos))

    def _archive_article(self) -> None:
        """Emit archive event."""
        article_id = self.article.get("id")
        if article_id:
            self.archive_requested.emit(article_id)

    def _quantum_bypass(self) -> None:
        """Open article URL via a 12ft.io-style paywall bypass."""
        url = self.article.get("url")
        if url:
            bypass_url = f"https://12ft.io/proxy?q={url}"
            QDesktopServices.openUrl(QUrl(bypass_url))

    def mousePressEvent(self, event) -> None:
        """Handle card click."""
        super().mousePressEvent(event)
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit(self.article)

