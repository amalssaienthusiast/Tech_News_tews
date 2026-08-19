"""
Live Article Stream Preview Widget
Real-time article feed with scrollable list

Features:
- Shows articles as they arrive in real-time
- Scrollable list showing last 20-50 articles
- Displays title, source, and timestamp
- Color coding for different sources
- Auto-scroll to newest
"""

from datetime import datetime
from typing import Dict, List, Optional, Any
from dataclasses import dataclass
from collections import deque

from PyQt6.QtWidgets import (
    QFrame, QVBoxLayout, QHBoxLayout, QLabel, 
    QScrollArea, QWidget, QSizePolicy, QSpacerItem
)
from PyQt6.QtCore import Qt, QTimer, pyqtSignal, QPropertyAnimation, QEasingCurve
from PyQt6.QtGui import QColor, QFont

from ..theme import COLORS, Fonts


@dataclass
class StreamArticle:
    """Article data for stream display"""
    title: str
    source: str
    timestamp: datetime
    score: float
    url: str = ""
    id: str = ""


class ArticleStreamItem(QFrame):
    """Single article item in the stream"""
    
    clicked = pyqtSignal(object)  # Emits StreamArticle
    
    # Source color mapping
    SOURCE_COLORS = {
        "hacker news": COLORS.orange,
        "github": COLORS.comment,
        "reddit": COLORS.red,
        "dev.to": COLORS.black,
        "medium": COLORS.black,
        "techcrunch": COLORS.green,
        "the verge": COLORS.blue,
        "ars technica": COLORS.yellow,
        "wired": COLORS.black,
        "stack overflow": COLORS.orange,
        "default": COLORS.cyan
    }
    
    def __init__(self, article: StreamArticle, parent=None):
        super().__init__(parent)
        self._article = article
        self._opacity = 1.0
        self.setObjectName("streamItem")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._setup_ui()
        self._apply_styles()
        
        # Entry animation
        self._entry_animation()
    
    def _setup_ui(self):
        """Build the article item UI"""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.setSpacing(4)
        
        # Title row
        title_layout = QHBoxLayout()
        title_layout.setSpacing(8)
        
        # Source indicator dot
        source_color = self._get_source_color(self._article.source)
        self.source_dot = QLabel("●")
        self.source_dot.setStyleSheet(f"color: {source_color}; font-size: 10px;")
        title_layout.addWidget(self.source_dot)
        
        # Title
        self.title_label = QLabel(self._article.title)
        self.title_label.setFont(Fonts.get_qfont('sm', 'medium'))
        self.title_label.setWordWrap(True)
        self.title_label.setStyleSheet(f"color: {COLORS.fg};")
        title_layout.addWidget(self.title_label, 1)
        
        layout.addLayout(title_layout)
        
        # Meta row
        meta_layout = QHBoxLayout()
        meta_layout.setSpacing(12)
        
        # Source name
        self.source_label = QLabel(self._article.source)
        self.source_label.setFont(Fonts.get_qfont('xs'))
        self.source_label.setStyleSheet(f"color: {source_color};")
        meta_layout.addWidget(self.source_label)
        
        # Score badge
        score_color = self._get_score_color(self._article.score)
        self.score_label = QLabel(f"★ {self._article.score:.1f}")
        self.score_label.setFont(Fonts.get_qfont('xs', 'bold'))
        self.score_label.setStyleSheet(f"""
            color: {score_color};
            background-color: {COLORS.bg_dark};
            padding: 1px 6px;
            border-radius: 3px;
        """)
        meta_layout.addWidget(self.score_label)
        
        meta_layout.addStretch()
        
        # Timestamp
        time_str = self._format_time(self._article.timestamp)
        self.time_label = QLabel(time_str)
        self.time_label.setFont(Fonts.get_qfont('xs'))
        self.time_label.setStyleSheet(f"color: {COLORS.comment};")
        meta_layout.addWidget(self.time_label)
        
        layout.addLayout(meta_layout)
    
    def _get_source_color(self, source: str) -> str:
        """Get color for source"""
        source_lower = source.lower()
        for key, color in self.SOURCE_COLORS.items():
            if key in source_lower:
                return color
        return self.SOURCE_COLORS["default"]
    
    def _get_score_color(self, score: float) -> str:
        """Get color for score"""
        if score >= 8.0:
            return COLORS.green
        elif score >= 6.5:
            return COLORS.cyan
        elif score >= 5.0:
            return COLORS.yellow
        else:
            return COLORS.red
    
    def _format_time(self, timestamp: datetime) -> str:
        """Format timestamp relative to now"""
        now = datetime.now()
        diff = now - timestamp
        
        if diff.total_seconds() < 60:
            return "just now"
        elif diff.total_seconds() < 3600:
            minutes = int(diff.total_seconds() / 60)
            return f"{minutes}m ago"
        elif diff.total_seconds() < 86400:
            hours = int(diff.total_seconds() / 3600)
            return f"{hours}h ago"
        else:
            return timestamp.strftime("%b %d")
    
    def _apply_styles(self):
        """Apply item styles"""
        self.setStyleSheet(f"""
            ArticleStreamItem {{
                background-color: {COLORS.bg_highlight};
                border-left: 3px solid {COLORS.terminal_black};
                border-radius: 0px;
            }}
            ArticleStreamItem:hover {{
                background-color: {COLORS.bg_visual};
                border-left: 3px solid {COLORS.blue};
            }}
        """)
    
    def _entry_animation(self):
        """Animate entry of new item"""
        self.setStyleSheet(self.styleSheet() + f"""
            ArticleStreamItem {{
                background-color: {COLORS.bg_visual};
                border-left: 3px solid {COLORS.green};
            }}
        """)
        
        # Reset after delay
        QTimer.singleShot(1000, self._apply_styles)
    
    def mousePressEvent(self, event):
        """Handle click"""
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit(self._article)
        super().mousePressEvent(event)
    
    def get_article(self) -> StreamArticle:
        return self._article


class LiveArticleStreamPreview(QFrame):
    """
    Live article stream preview widget
    
    Signals:
        article_clicked(StreamArticle): Emitted when an article is clicked
    """
    
    article_clicked = pyqtSignal(object)
    
    def __init__(self, max_items: int = 30, show_demo_data: bool = False, parent=None):
        super().__init__(parent)
        self._max_items = max_items
        self._articles: deque = deque(maxlen=max_items)
        self._auto_scroll = True
        self._add_timestamps: deque = deque(maxlen=50)  # for a real articles/min figure
        
        self.setObjectName("cardFrame")
        self.setFrameStyle(QFrame.Shape.StyledPanel | QFrame.Shadow.Plain)
        self._setup_ui()
        self._apply_styles()
        
        # Demo data is opt-in only (e.g. for isolated widget preview/testing).
        # In the real app this starts empty and fills in as add_article() is
        # called with genuine scraped articles.
        if show_demo_data:
            self._init_demo_articles()
        self._update_empty_state()
        
        # `_simulate_new_article` below is preview-only machinery and is never
        # started automatically — see set_demo_mode() if you want it for a demo.
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._simulate_new_article)
    
    def _setup_ui(self):
        """Build the stream UI"""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)
        
        # Header
        header_layout = QHBoxLayout()
        
        title = QLabel("📰 Live Article Stream")
        title.setObjectName("headerLabel")
        title.setFont(Fonts.get_qfont('md', 'bold'))
        header_layout.addWidget(title)
        
        header_layout.addStretch()
        
        # Article count
        self.count_label = QLabel("0 articles")
        self.count_label.setFont(Fonts.get_qfont('sm'))
        self.count_label.setStyleSheet(f"color: {COLORS.comment};")
        header_layout.addWidget(self.count_label)
        
        layout.addLayout(header_layout)
        
        # Scroll area for articles
        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.scroll_area.setStyleSheet(f"""
            QScrollArea {{
                background-color: {COLORS.bg};
                border: 1px solid {COLORS.terminal_black};
                border-radius: 6px;
            }}
        """)
        
        # Container widget
        self.container = QWidget()
        self.container_layout = QVBoxLayout(self.container)
        self.container_layout.setContentsMargins(6, 6, 6, 6)
        self.container_layout.setSpacing(4)
        self.container_layout.addStretch()
        
        self.scroll_area.setWidget(self.container)
        layout.addWidget(self.scroll_area)
        
        # Shown only while no real articles have arrived yet
        self.empty_label = QLabel("Waiting for live articles...")
        self.empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.empty_label.setFont(Fonts.get_qfont('sm'))
        self.empty_label.setStyleSheet(f"color: {COLORS.comment}; padding: 24px;")
        self.container_layout.insertWidget(0, self.empty_label)
        
        # Footer controls
        footer_layout = QHBoxLayout()
        
        # Auto-scroll toggle
        self.autoscroll_label = QLabel("⬇ Auto-scroll ON")
        self.autoscroll_label.setFont(Fonts.get_qfont('xs'))
        self.autoscroll_label.setStyleSheet(f"color: {COLORS.green};")
        footer_layout.addWidget(self.autoscroll_label)
        
        footer_layout.addStretch()
        
        # Throughput indicator
        self.throughput_label = QLabel("\U0001F4CA -- articles/min")
        self.throughput_label.setFont(Fonts.get_qfont('xs'))
        self.throughput_label.setStyleSheet(f"color: {COLORS.cyan};")
        footer_layout.addWidget(self.throughput_label)
        
        layout.addLayout(footer_layout)
    
    def _apply_styles(self):
        """Apply widget styles"""
        self.setStyleSheet(f"""
            LiveArticleStreamPreview {{
                background-color: {COLORS.bg_highlight};
                border: 1px solid {COLORS.terminal_black};
                border-radius: 8px;
            }}
        """)
    
    def _init_demo_articles(self):
        """Initialize with demo articles"""
        demo_articles = [
            StreamArticle(
                "Python 3.13 Released with Major Performance Improvements",
                "Hacker News", datetime.now(), 9.2
            ),
            StreamArticle(
                "New AI Model Achieves Human-Level Code Understanding",
                "GitHub Trending", datetime.now(), 8.7
            ),
            StreamArticle(
                "Rust vs Go: A Comprehensive Performance Analysis",
                "Reddit r/programming", datetime.now(), 7.8
            ),
            StreamArticle(
                "Building Scalable Microservices with Kubernetes",
                "Dev.to", datetime.now(), 7.5
            ),
            StreamArticle(
                "The Future of WebAssembly in Browser Applications",
                "Medium", datetime.now(), 6.9
            ),
        ]
        
        for article in reversed(demo_articles):
            self.add_article(article, animate=False)
    
    def add_article(self, article: StreamArticle, animate: bool = True):
        """Add a new article to the stream"""
        # Remove oldest if at max
        if len(self._articles) >= self._max_items:
            self._remove_oldest()
        
        # Add to tracking
        self._articles.append(article)
        self._add_timestamps.append(datetime.now())
        
        # Create and add widget
        item = ArticleStreamItem(article, self)
        item.clicked.connect(self.article_clicked.emit)
        
        # Insert at top (before the stretch, after the empty-state label)
        insert_idx = self.container_layout.count() - 1
        self.container_layout.insertWidget(insert_idx, item)
        
        # Auto-scroll if enabled
        if self._auto_scroll:
            QTimer.singleShot(100, self._scroll_to_top)
        
        # Update count / throughput / empty-state
        self._update_count()
        self._update_throughput()
        self._update_empty_state()
    
    def _remove_oldest(self):
        """Remove the oldest article widget"""
        # Find the first non-stretch widget
        for i in range(self.container_layout.count() - 1):
            widget = self.container_layout.itemAt(i).widget()
            if widget and isinstance(widget, ArticleStreamItem):
                widget.deleteLater()
                break
    
    def _scroll_to_top(self):
        """Scroll to show newest articles"""
        scrollbar = self.scroll_area.verticalScrollBar()
        scrollbar.setValue(scrollbar.minimum())
    
    def _scroll_to_bottom(self):
        """Scroll to bottom"""
        scrollbar = self.scroll_area.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())
    
    def _update_count(self):
        """Update article count display"""
        count = len(self._articles)
        self.count_label.setText(f"{count} articles")

    def _update_throughput(self):
        """Compute a real articles/min figure from actual add() timestamps
        (replaces the previous random.uniform() placeholder)."""
        now = datetime.now()
        recent = [t for t in self._add_timestamps if (now - t).total_seconds() <= 60]
        if len(self._add_timestamps) < 2:
            self.throughput_label.setText("\U0001F4CA -- articles/min")
            return
        span = (now - self._add_timestamps[0]).total_seconds()
        rate = len(recent) if span <= 60 else (len(self._add_timestamps) / span) * 60
        self.throughput_label.setText(f"\U0001F4CA {rate:.1f} articles/min")

    def _update_empty_state(self):
        """Show/hide the 'waiting for articles' placeholder."""
        self.empty_label.setVisible(len(self._articles) == 0)
    
    def _simulate_new_article(self):
        """Simulate new articles arriving"""
        import random
        
        sample_titles = [
            ("Revolutionary AI Hardware Breakthrough Announced", "TechCrunch", random.uniform(8.0, 9.5)),
            ("Linux Kernel 6.10 Release: What's New", "Hacker News", random.uniform(7.5, 8.8)),
            ("TypeScript 5.5 Brings Performance Enhancements", "Dev.to", random.uniform(7.0, 8.5)),
            ("Machine Learning Trends to Watch in 2025", "Medium", random.uniform(6.5, 8.0)),
            ("Docker Desktop Updates with New Features", "GitHub Trending", random.uniform(7.0, 8.5)),
            ("React Server Components: Complete Guide", "Reddit r/programming", random.uniform(7.5, 9.0)),
            ("AWS Lambda Now Supports Python 3.12", "The Verge", random.uniform(6.5, 7.5)),
            ("Vim vs Emacs: The Eternal Debate Continues", "Stack Overflow", random.uniform(5.0, 7.0)),
        ]
        
        title, source, score = random.choice(sample_titles)
        
        article = StreamArticle(
            title=title,
            source=source,
            timestamp=datetime.now(),
            score=score
        )
        
        self.add_article(article)

    def set_demo_mode(self, enabled: bool):
        """Explicitly opt in/out of the randomized preview stream (for isolated
        widget demos only — never enabled automatically)."""
        if enabled:
            self._timer.start(3000)
        else:
            self._timer.stop()
    
    def set_auto_scroll(self, enabled: bool):
        """Enable/disable auto-scroll"""
        self._auto_scroll = enabled
        if enabled:
            self.autoscroll_label.setText("⬇ Auto-scroll ON")
            self.autoscroll_label.setStyleSheet(f"color: {COLORS.green};")
            self._scroll_to_top()
        else:
            self.autoscroll_label.setText("⬇ Auto-scroll OFF")
            self.autoscroll_label.setStyleSheet(f"color: {COLORS.comment};")
    
    def toggle_auto_scroll(self):
        """Toggle auto-scroll"""
        self.set_auto_scroll(not self._auto_scroll)
    
    def clear(self):
        """Clear all articles"""
        # Remove all article items
        for i in range(self.container_layout.count() - 1, -1, -1):
            widget = self.container_layout.itemAt(i).widget()
            if widget and isinstance(widget, ArticleStreamItem):
                widget.deleteLater()
        
        self._articles.clear()
        self._add_timestamps.clear()
        self._update_count()
        self._update_throughput()
        self._update_empty_state()
    
    def get_articles(self) -> List[StreamArticle]:
        """Get all articles in stream"""
        return list(self._articles)
