"""
Live Feed Container Widget
Manages switching between welcome, loading, and article views
Uses QStackedWidget for smooth transitions
"""

from typing import List, Dict, Any

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QStackedWidget, QLabel
)
from PyQt6.QtCore import pyqtSignal, Qt

from ..theme import COLORS, Fonts
from .welcome_screen import WelcomeScreen
from .loading_spinner import LoadingScreen
from .article_list import ArticleListView


class LiveFeedContainer(QWidget):
    """Container that manages feed state transitions
    
    States:
        0 - Welcome screen (initial)
        1 - Loading screen
        2 - Article list (feed active)
    
    Signals:
        start_live_feed(): User clicked start
        article_clicked(dict): Article was clicked
        article_double_clicked(dict): Article was double-clicked
        view_history(): User wants to view history
        view_monitor(): User wants live monitor
    """
    
    # Signals
    start_live_feed = pyqtSignal()
    article_clicked = pyqtSignal(dict)
    article_double_clicked = pyqtSignal(dict)
    view_history = pyqtSignal()
    view_monitor = pyqtSignal()
    
    # State indices
    STATE_WELCOME = 0
    STATE_LOADING = 1
    STATE_ARTICLES = 2
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self._current_state = self.STATE_WELCOME
        self._setup_ui()
        self._connect_signals()
    
    def _setup_ui(self):
        """Build the container UI"""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        
        # Stacked widget for state management
        self.stack = QStackedWidget(self)
        layout.addWidget(self.stack)
        
        # State 0: Welcome screen
        self.welcome = WelcomeScreen(self)
        self.stack.addWidget(self.welcome)
        
        # State 1: Loading screen
        self.loading = LoadingScreen(self)
        self.stack.addWidget(self.loading)
        
        # State 2: Article list
        self.article_list = ArticleListView(self)
        self.stack.addWidget(self.article_list)
        
        # Start on welcome
        self.stack.setCurrentIndex(self.STATE_WELCOME)
        
        # Background
        self.setStyleSheet(f"""
            QWidget {{
                background-color: {COLORS.bg};
            }}
        """)
    
    def _connect_signals(self):
        """Connect internal signals"""
        # Welcome screen signals
        self.welcome.start_live_feed_clicked.connect(self._on_start_clicked)
        self.welcome.view_history_clicked.connect(self.view_history.emit)
        self.welcome.view_monitor_clicked.connect(self.view_monitor.emit)
        
        # Article list signals
        self.article_list.article_clicked.connect(self.article_clicked.emit)
        self.article_list.article_double_clicked.connect(self.article_double_clicked.emit)
    
    def _on_start_clicked(self):
        """Handle start live feed click"""
        self.show_loading("Fetching tech news...")
        self.start_live_feed.emit()
    
    # Public API - State Management
    def show_welcome(self):
        """Show welcome screen"""
        self._current_state = self.STATE_WELCOME
        self.loading.stop()
        self.stack.setCurrentIndex(self.STATE_WELCOME)
    
    def show_loading(self, text: str = "Loading..."):
        """Show loading screen"""
        self._current_state = self.STATE_LOADING
        self.loading.set_status(text)
        self.loading.start()
        self.stack.setCurrentIndex(self.STATE_LOADING)
    
    def show_articles(self):
        """Show article list"""
        self._current_state = self.STATE_ARTICLES
        self.loading.stop()
        self.stack.setCurrentIndex(self.STATE_ARTICLES)
    
    def get_state(self) -> int:
        """Get current state"""
        return self._current_state
    
    def is_feed_active(self) -> bool:
        """Check if feed is active (showing articles)"""
        return self._current_state == self.STATE_ARTICLES
    
    # Public API - Article Management
    def set_articles(self, articles: List[Dict[str, Any]]):
        """Set articles and switch to article view"""
        self.article_list.set_articles(articles)
        self.show_articles()
    
    def add_article(self, article: Dict[str, Any], prepend: bool = True):
        """Add single article to list"""
        # Auto-switch to articles if on loading screen
        if self._current_state == self.STATE_LOADING:
            self.show_articles()
        
        self.article_list.add_article(article, prepend)
    
    def add_articles(self, articles: List[Dict[str, Any]], prepend: bool = True):
        """Add multiple articles to list"""
        if self._current_state == self.STATE_LOADING:
            self.show_articles()
        
        self.article_list.add_articles(articles, prepend)
    
    def clear_articles(self):
        """Clear all articles"""
        self.article_list.clear()
    
    def get_article_count(self) -> int:
        """Get number of articles"""
        return self.article_list.count()
    
    def get_article_list(self) -> ArticleListView:
        """Get the article list widget"""
        return self.article_list
    
    def update_loading_status(self, status: str, substatus: str = None):
        """Update loading screen status"""
        if self._current_state == self.STATE_LOADING:
            self.loading.set_status(status, substatus)
    
    def scroll_to_top(self):
        """Scroll article list to top"""
        self.article_list.scroll_to_top()
