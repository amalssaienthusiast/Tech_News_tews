"""
Live Dashboard Panel - Real-time monitoring of scraping activity.

Features:
- Source heartbeat monitor (status grid)
- Article stream preview (recent arrivals)
- Fetch statistics with live updates
"""

from datetime import datetime
from typing import Any, Dict, List, Optional

from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtWidgets import (
    QFrame, QGridLayout, QHBoxLayout, QLabel, QPushButton,
    QProgressBar, QScrollArea, QSizePolicy, QVBoxLayout, QWidget
)

from gui_qt.theme import COLORS


class SourceStatus(QFrame):
    """Individual source status indicator."""
    
    def __init__(
        self,
        name: str,
        parent: Optional[QWidget] = None
    ) -> None:
        super().__init__(parent)
        self.name = name
        self.status = "idle"
        self.last_fetch = None
        self.article_count = 0
        
        self._setup_ui()
    
    def _setup_ui(self) -> None:
        self.setStyleSheet(f"""
            SourceStatus {{
                background-color: {COLORS.bg_highlight};
                border-radius: 8px;
                padding: 8px;
            }}
        """)
        self.setFixedHeight(70)
        
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 8, 12, 8)
        layout.setSpacing(4)
        
        # Header: name + status dot
        header = QHBoxLayout()
        
        self.name_label = QLabel(self.name)
        self.name_label.setStyleSheet(f"color: {COLORS.fg}; font-weight: bold; font-size: 12px;")
        header.addWidget(self.name_label)
        
        header.addStretch()
        
        self.status_dot = QLabel("●")
        self.status_dot.setStyleSheet(f"color: {COLORS.comment}; font-size: 10px;")
        header.addWidget(self.status_dot)
        
        layout.addLayout(header)
        
        # Stats: articles count
        self.stats_label = QLabel("0 articles")
        self.stats_label.setStyleSheet(f"color: {COLORS.comment}; font-size: 11px;")
        layout.addWidget(self.stats_label)
    
    def update_status(self, status: str, articles: int = 0, latency_ms: int = 0) -> None:
        """Update source status."""
        self.status = status
        self.article_count = articles
        
        # Status colors
        colors = {
            "active": COLORS.green,
            "fetching": COLORS.cyan,
            "error": COLORS.red,
            "idle": COLORS.comment,
        }
        
        color = colors.get(status, COLORS.comment)
        self.status_dot.setStyleSheet(f"color: {color}; font-size: 10px;")
        self.stats_label.setText(f"{articles} articles")


class SourceHeartbeatGrid(QFrame):
    """Grid of source status monitors."""
    
    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.sources: Dict[str, SourceStatus] = {}
        
        self._setup_ui()
        self._add_default_sources()
    
    def _setup_ui(self) -> None:
        self.setStyleSheet(f"""
            background-color: {COLORS.bg};
            border: 1px solid {COLORS.border};
            border-radius: 8px;
        """)
        
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(12, 12, 12, 12)
        main_layout.setSpacing(8)
        
        # Header
        header = QLabel("📡 Source Status")
        header.setStyleSheet(f"color: {COLORS.cyan}; font-weight: bold; font-size: 13px;")
        main_layout.addWidget(header)
        
        # Grid
        self.grid = QGridLayout()
        self.grid.setSpacing(8)
        main_layout.addLayout(self.grid)
    
    def _add_default_sources(self) -> None:
        """Add default source monitors."""
        sources = [
            "TechCrunch", "The Verge", "Wired", "Ars Technica",
            "Hacker News", "Reddit", "Google News", "DuckDuckGo"
        ]
        
        for i, name in enumerate(sources):
            source = SourceStatus(name)
            self.sources[name] = source
            row, col = divmod(i, 4)
            self.grid.addWidget(source, row, col)
    
    def update_source(self, name: str, status: str, articles: int = 0) -> None:
        """Update a source's status."""
        if name in self.sources:
            self.sources[name].update_status(status, articles)


class ArticleStreamPreview(QFrame):
    """Preview of recently arrived articles."""
    
    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.articles: List[Dict] = []
        self.max_items = 8
        
        self._setup_ui()
    
    def _setup_ui(self) -> None:
        self.setStyleSheet(f"""
            background-color: {COLORS.bg};
            border: 1px solid {COLORS.border};
            border-radius: 8px;
        """)
        
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)
        
        # Header
        header = QHBoxLayout()
        title = QLabel("🔴 Live Stream")
        title.setStyleSheet(f"color: {COLORS.red}; font-weight: bold; font-size: 13px;")
        header.addWidget(title)
        
        header.addStretch()
        
        self.count_label = QLabel("0 new")
        self.count_label.setStyleSheet(f"color: {COLORS.comment}; font-size: 11px;")
        header.addWidget(self.count_label)
        
        layout.addLayout(header)
        
        # Article list
        self.list_layout = QVBoxLayout()
        self.list_layout.setSpacing(4)
        layout.addLayout(self.list_layout)
        
        layout.addStretch()
    
    def add_article(self, article: Dict) -> None:
        """Add article to preview."""
        # Create mini card
        card = QFrame()
        card.setStyleSheet(f"""
            background-color: {COLORS.bg_highlight};
            border-radius: 4px;
            padding: 6px;
        """)
        
        card_layout = QHBoxLayout(card)
        card_layout.setContentsMargins(8, 6, 8, 6)
        card_layout.setSpacing(8)
        
        # Source dot
        source = article.get("source", "")[:2].upper()
        source_label = QLabel(source)
        source_label.setStyleSheet(f"""
            background-color: {COLORS.cyan};
            color: {COLORS.black};
            font-size: 9px;
            font-weight: bold;
            padding: 2px 4px;
            border-radius: 2px;
        """)
        source_label.setFixedWidth(24)
        card_layout.addWidget(source_label)
        
        # Title (truncated)
        title = article.get("title", "Untitled")[:60]
        if len(article.get("title", "")) > 60:
            title += "..."
        title_label = QLabel(title)
        title_label.setStyleSheet(f"color: {COLORS.fg}; font-size: 11px;")
        card_layout.addWidget(title_label, 1)
        
        # Insert at top
        self.list_layout.insertWidget(0, card)
        self.articles.insert(0, article)
        
        # Limit items
        while self.list_layout.count() > self.max_items:
            item = self.list_layout.takeAt(self.list_layout.count() - 1)
            if item.widget():
                item.widget().deleteLater()
            if self.articles:
                self.articles.pop()
        
        self.count_label.setText(f"{len(self.articles)} new")


class FetchStatsPanel(QFrame):
    """Live fetch statistics panel."""
    
    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        
        self._setup_ui()
    
    def _setup_ui(self) -> None:
        self.setStyleSheet(f"""
            background-color: {COLORS.bg};
            border: 1px solid {COLORS.border};
            border-radius: 8px;
        """)
        
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)
        
        # Header
        header = QLabel("📊 Fetch Stats")
        header.setStyleSheet(f"color: {COLORS.cyan}; font-weight: bold; font-size: 13px;")
        layout.addWidget(header)
        
        # Stats
        self.stats = {}
        stats_data = [
            ("total", "📰 Total Articles", "0"),
            ("rss", "📡 RSS Feeds", "0"),
            ("api", "🔌 API Sources", "0"),
            ("dedup", "🔄 Dedup Rate", "0%"),
        ]
        
        for key, label, default in stats_data:
            row = QHBoxLayout()
            lbl = QLabel(label)
            lbl.setStyleSheet(f"color: {COLORS.fg}; font-size: 12px;")
            row.addWidget(lbl)
            row.addStretch()
            val = QLabel(default)
            val.setStyleSheet(f"color: {COLORS.cyan}; font-weight: bold; font-size: 12px;")
            row.addWidget(val)
            self.stats[key] = val
            layout.addLayout(row)
        
        # Progress bar for current fetch
        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self.progress.setFixedHeight(4)
        self.progress.setTextVisible(False)
        layout.addWidget(self.progress)
    
    def update_stats(
        self,
        total: int = 0,
        rss: int = 0,
        api: int = 0,
        dedup_rate: float = 0
    ) -> None:
        """Update displayed statistics."""
        self.stats["total"].setText(str(total))
        self.stats["rss"].setText(str(rss))
        self.stats["api"].setText(str(api))
        self.stats["dedup"].setText(f"{dedup_rate:.1f}%")
    
    def set_progress(self, value: int) -> None:
        """Set progress bar value (0-100)."""
        self.progress.setValue(value)


class LiveDashboardPanel(QFrame):
    """Complete live dashboard panel."""
    
    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        
        self._setup_ui()
    
    def _setup_ui(self) -> None:
        self.setStyleSheet(f"""
            background-color: {COLORS.bg_dark};
            border-left: 1px solid {COLORS.border};
        """)
        self.setFixedWidth(380)
        
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 16, 12, 16)
        layout.setSpacing(16)
        
        # Header
        header = QHBoxLayout()
        title = QLabel("🖥️ Live Dashboard")
        title.setStyleSheet(f"color: {COLORS.fg}; font-size: 16px; font-weight: bold;")
        header.addWidget(title)
        header.addStretch()
        layout.addLayout(header)
        
        # Source status grid
        self.source_grid = SourceHeartbeatGrid()
        layout.addWidget(self.source_grid)
        
        # Article stream
        self.stream_preview = ArticleStreamPreview()
        layout.addWidget(self.stream_preview)
        
        # Fetch stats
        self.fetch_stats = FetchStatsPanel()
        layout.addWidget(self.fetch_stats)
        
        layout.addStretch()
    
    def update_source(self, name: str, status: str, articles: int = 0) -> None:
        """Update source status."""
        self.source_grid.update_source(name, status, articles)
    
    def add_article(self, article: Dict) -> None:
        """Add article to stream preview."""
        self.stream_preview.add_article(article)
    
    def update_stats(self, **kwargs) -> None:
        """Update fetch statistics."""
        self.fetch_stats.update_stats(**kwargs)
    
    def set_progress(self, value: int) -> None:
        """Set fetch progress."""
        self.fetch_stats.set_progress(value)
