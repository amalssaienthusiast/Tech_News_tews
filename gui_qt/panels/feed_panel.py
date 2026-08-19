"""
Feed Panel - Scrollable article feed with lazy loading.

Displays article cards in a scrollable vertical list with
smooth scrolling and efficient rendering. Matches Tkinter layout.
"""

from typing import Any, Callable, Dict, List, Optional

from PyQt6.QtCore import Qt, pyqtSignal, QTimer
from PyQt6.QtWidgets import (
    QFrame, QLabel, QScrollArea, QVBoxLayout, QWidget, QHBoxLayout,
    QPushButton, QSizePolicy, QApplication, QLineEdit
)

from gui_qt.theme import COLORS
from gui_qt.widgets.article_card import ArticleCard


class FeedPanel(QFrame):
    """
    Scrollable article feed panel.
    
    Features:
    - Smooth scrolling with native Qt scroll
    - Lazy loading for performance
    - Search and URL analysis inputs (matching Tkinter)
    - Article count display
    - Empty state handling
    """
    
    # Signals
    article_clicked = pyqtSignal(dict)
    article_saved = pyqtSignal(str, bool)
    article_archived = pyqtSignal(dict)
    search_requested = pyqtSignal(str)
    url_analysis_requested = pyqtSignal(str)
    refresh_requested = pyqtSignal()
    history_requested = pyqtSignal()
    advanced_feeds_toggled = pyqtSignal(bool)
    
    # Number of most-recent articles kept live-rendered at once; older articles
    # roll into browsable pages instead of growing the visible list forever.
    PAGE_SIZE = 50

    def __init__(
        self,
        on_save: Optional[Callable[[str, bool], None]] = None,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self.on_save = on_save
        self.articles: List[Dict[str, Any]] = []  # full history, newest-first
        self.cards: List[ArticleCard] = []  # cards for the currently rendered page only
        self._page = 0  # 0 = live/most-recent page
        self._pending_new_count = 0
        self._render_timer = QTimer(self)
        self._render_timer.timeout.connect(self._render_next_batch)
        
        self.setStyleSheet(f"background-color: {COLORS.bg}; border: none;")
        self._setup_ui()
    
    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(20)
        
        # ─── SEARCH & URL BAR ───
        # Matching Tkinter's "Search Section - Glass card style"
        search_card = QFrame()
        search_card.setStyleSheet(f"""
            background-color: {COLORS.bg_highlight};
            border-radius: 12px;
        """)
        search_layout = QVBoxLayout(search_card)
        search_layout.setContentsMargins(20, 18, 20, 18)
        search_layout.setSpacing(15)
        
        # Row 1: Search
        search_row = QHBoxLayout()
        search_row.setSpacing(12)
        
        search_icon = QLabel("🔍")
        search_icon.setStyleSheet(f"color: {COLORS.cyan}; font-size: 18px;")
        search_row.addWidget(search_icon)
        
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("Search tech news...")
        self.search_input.setStyleSheet(f"""
            QLineEdit {{
                background-color: {COLORS.bg_visual};
                color: {COLORS.fg};
                border: 2px solid {COLORS.border};
                border-radius: 6px;
                padding: 10px;
                font-size: 14px;
            }}
            QLineEdit:focus {{
                border: 2px solid {COLORS.cyan};
            }}
        """)
        self.search_input.returnPressed.connect(self._on_search)
        search_row.addWidget(self.search_input)
        
        search_btn = QPushButton("Search")
        search_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        search_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {COLORS.blue};
                color: {COLORS.fg};
                border: none;
                border-radius: 6px;
                padding: 10px 20px;
                font-weight: bold;
                font-size: 13px;
            }}
            QPushButton:hover {{
                background-color: {COLORS.bright_blue};
            }}
        """)
        search_btn.clicked.connect(self._on_search)
        search_row.addWidget(search_btn)
        
        refresh_btn = QPushButton("🔄")
        refresh_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        refresh_btn.setToolTip("Refresh Feed")
        refresh_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {COLORS.bg_visual};
                color: {COLORS.cyan};
                border: none;
                border-radius: 6px;
                padding: 10px;
                font-size: 16px;
            }}
            QPushButton:hover {{
                background-color: {COLORS.bg_search};
            }}
        """)
        refresh_btn.clicked.connect(self.refresh_requested.emit)
        search_row.addWidget(refresh_btn)
        
        history_btn = QPushButton("📜 History")
        history_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        history_btn.setToolTip("View Article History")
        history_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {COLORS.bg_visual};
                color: {COLORS.yellow};
                border: 1px solid {COLORS.yellow};
                border-radius: 6px;
                padding: 8px 14px;
                font-weight: bold;
                font-size: 13px;
            }}
            QPushButton:hover {{
                background-color: {COLORS.yellow};
                color: {COLORS.bg_dark};
            }}
        """)
        history_btn.clicked.connect(self.history_requested.emit)
        search_row.addWidget(history_btn)

        
        search_layout.addLayout(search_row)
        
        # Row 2: URL Analysis
        url_row = QHBoxLayout()
        url_row.setSpacing(12)
        
        url_icon = QLabel("🔗")
        url_icon.setStyleSheet(f"color: {COLORS.magenta}; font-size: 16px;")
        url_row.addWidget(url_icon)
        
        self.url_input = QLineEdit()
        self.url_input.setPlaceholderText("Paste article URL for deep analysis...")
        self.url_input.setStyleSheet(f"""
            QLineEdit {{
                background-color: {COLORS.bg_visual};
                color: {COLORS.fg_dark};
                border: 1px solid {COLORS.border};
                border-radius: 6px;
                padding: 8px;
                font-size: 12px;
            }}
            QLineEdit:focus {{
                border: 1px solid {COLORS.magenta};
            }}
        """)
        self.url_input.returnPressed.connect(self._on_url_analysis)
        url_row.addWidget(self.url_input)
        
        search_layout.addLayout(url_row)
        
        layout.addWidget(search_card)
        
        # ─── FEED HEADER ───
        feed_header = QHBoxLayout()
        
        self.count_label = QLabel("Waiting for content...")
        self.count_label.setStyleSheet(f"color: {COLORS.comment}; font-size: 13px; font-weight: bold;")
        feed_header.addWidget(self.count_label)
        
        feed_header.addStretch()

        # Shown when new articles arrive while the user is browsing an older page,
        # so incoming content never silently replaces what they're reading.
        self.new_articles_btn = QPushButton()
        self.new_articles_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.new_articles_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {COLORS.cyan};
                color: {COLORS.bg};
                border: none;
                border-radius: 6px;
                padding: 6px 14px;
                font-size: 12px;
                font-weight: bold;
            }}
            QPushButton:hover {{ background-color: {COLORS.bright_cyan}; }}
        """)
        self.new_articles_btn.clicked.connect(self._jump_to_live)
        self.new_articles_btn.setVisible(False)
        feed_header.addWidget(self.new_articles_btn)

        # Pagination: page 0 is the live/most-recent view; higher pages are older
        # articles that have rolled out of the live window.
        pager_style = f"""
            QPushButton {{
                background-color: {COLORS.bg_visual};
                color: {COLORS.fg};
                border: 1px solid {COLORS.border};
                border-radius: 6px;
                padding: 6px 12px;
                font-size: 12px;
            }}
            QPushButton:hover:!disabled {{ background-color: {COLORS.bg_search}; }}
            QPushButton:disabled {{ color: {COLORS.comment}; }}
        """
        self.prev_page_btn = QPushButton("‹ Newer")
        self.prev_page_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.prev_page_btn.setStyleSheet(pager_style)
        self.prev_page_btn.clicked.connect(self._go_newer)
        feed_header.addWidget(self.prev_page_btn)

        self.page_label = QLabel("")
        self.page_label.setStyleSheet(f"color: {COLORS.comment}; font-size: 12px; padding: 0 8px;")
        feed_header.addWidget(self.page_label)

        self.next_page_btn = QPushButton("Older ›")
        self.next_page_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.next_page_btn.setStyleSheet(pager_style)
        self.next_page_btn.clicked.connect(self._go_older)
        feed_header.addWidget(self.next_page_btn)
        
        feed_header.addSpacing(20)
        
        self.advanced_feeds_btn = QPushButton("🚀 Advanced Feeds")
        self.advanced_feeds_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.advanced_feeds_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {COLORS.purple};
                color: {COLORS.bg};
                border: none;
                border-radius: 6px;
                padding: 6px 12px;
                font-size: 12px;
                font-weight: bold;
            }}
            QPushButton:hover {{ background-color: {COLORS.magenta}; }}
            QPushButton:checked {{ background-color: {COLORS.green}; }}
        """)
        self.advanced_feeds_btn.setCheckable(True)
        self.advanced_feeds_btn.clicked.connect(self.advanced_feeds_toggled.emit)
        feed_header.addWidget(self.advanced_feeds_btn)
        
        layout.addLayout(feed_header)
        
        # ─── SCROLL AREA ───
        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.scroll_area.setStyleSheet(f"""
            QScrollArea {{
                background-color: transparent;
                border: none;
            }}
            QScrollBar:vertical {{
                background-color: {COLORS.bg};
                width: 10px;
                margin: 0px;
            }}
            QScrollBar::handle:vertical {{
                background-color: {COLORS.bg_highlight};
                min-height: 20px;
                border-radius: 5px;
            }}
        """)
        
        # Container for cards
        self.container = QWidget()
        self.container.setStyleSheet("background-color: transparent;")
        self.container_layout = QVBoxLayout(self.container)
        self.container_layout.setContentsMargins(0, 0, 0, 0)
        self.container_layout.setSpacing(12)
        self.container_layout.addStretch()
        
        self.scroll_area.setWidget(self.container)
        layout.addWidget(self.scroll_area)
        
        # Initial empty state
        self._show_empty_state()
    
    def _show_empty_state(self) -> None:
        """Show empty state message."""
        if hasattr(self, 'empty_widget') and self.empty_widget:
            return
        self.empty_widget = QFrame()
        self.empty_widget.setStyleSheet(f"""
            QFrame {{
                background-color: {COLORS.bg_highlight};
                border-radius: 12px;
            }}
        """)
        
        empty_layout = QVBoxLayout(self.empty_widget)
        empty_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        empty_layout.setContentsMargins(40, 60, 40, 60)
        
        icon = QLabel("📭")
        icon.setStyleSheet("font-size: 64px; margin-bottom: 20px;")
        icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        empty_layout.addWidget(icon)
        
        title = QLabel("Feed is Empty")
        title.setStyleSheet(f"color: {COLORS.fg}; font-size: 24px; font-weight: bold; margin-bottom: 10px;")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        empty_layout.addWidget(title)
        
        subtitle = QLabel("Click 'Start Live Feed' or use the search bar above\nto discover the latest technology news.")
        subtitle.setStyleSheet(f"color: {COLORS.comment}; font-size: 14px;")
        subtitle.setAlignment(Qt.AlignmentFlag.AlignCenter)
        empty_layout.addWidget(subtitle)
        
        self.container_layout.insertWidget(0, self.empty_widget)
        # Ensure it expands to fill available space visually
        self.empty_widget.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
    
    def _hide_empty_state(self) -> None:
        """Hide empty state message."""
        if hasattr(self, 'empty_widget') and self.empty_widget:
            self.container_layout.removeWidget(self.empty_widget)
            self.empty_widget.setParent(None)
            self.empty_widget.deleteLater()
            self.empty_widget = None

    
    def _on_search(self):
        """Handle search."""
        query = self.search_input.text().strip()
        if query:
            self.search_requested.emit(query)
    
    def _on_url_analysis(self):
        """Handle URL analysis."""
        url = self.url_input.text().strip()
        if url:
            self.url_analysis_requested.emit(url)
            self.url_input.clear()
            self.url_input.setPlaceholderText("Analysis started...")
            QTimer.singleShot(2000, lambda: self.url_input.setPlaceholderText("Paste article URL for deep analysis..."))
    
    def set_articles(self, articles: List[Dict[str, Any]]) -> None:
        """
        Replace the full article history and jump to the live (newest) page.
        Used for search results, initial load, and full refreshes.
        """
        self._render_timer.stop()
        self.articles = list(articles)
        self._pending_new_count = 0
        self.new_articles_btn.setVisible(False)
        self._render_page(0)

    def _total_pages(self) -> int:
        if not self.articles:
            return 1
        return -(-len(self.articles) // self.PAGE_SIZE)  # ceil division

    def _render_page(self, page: int) -> None:
        """Render one page of articles (bounded to PAGE_SIZE), batched to avoid
        freezing the UI on a large page."""
        for card in self.cards:
            self.container_layout.removeWidget(card)
            card.deleteLater()
        self.cards.clear()
        self._hide_empty_state()

        self._page = max(0, min(page, self._total_pages() - 1))
        start = self._page * self.PAGE_SIZE
        page_articles = self.articles[start:start + self.PAGE_SIZE]

        if not page_articles:
            self._show_empty_state()
            self.count_label.setText("No articles found")
            self._update_pagination_controls()
            return

        self._pending_render = list(page_articles)
        self._render_batch_index = 0
        self.count_label.setText(f"Loading {len(page_articles)} articles...")
        self._render_next_batch()

    def _render_next_batch(self, batch_size: int = 10) -> None:
        """Render up to batch_size cards from _pending_render, then return.
        Driven by _render_timer rather than processEvents to avoid Qt re-entrancy."""
        start = self._render_batch_index
        end = min(start + batch_size, len(self._pending_render))

        for article in self._pending_render[start:end]:
            card = ArticleCard(article, on_save=self.on_save)
            card.clicked.connect(self.article_clicked.emit)
            card.saved.connect(self.article_saved.emit)
            card.archive_requested.connect(self._handle_archive_requested)
            self.container_layout.insertWidget(self.container_layout.count() - 1, card)
            self.cards.append(card)

        self._render_batch_index = end

        if self._render_batch_index < len(self._pending_render):
            self._render_timer.start(10)
        else:
            self._render_timer.stop()
            self._pending_render = []
            self._update_count()
            self._update_pagination_controls()
            self.scroll_to_top()

    def _update_pagination_controls(self) -> None:
        total_pages = self._total_pages()
        show = total_pages > 1
        self.prev_page_btn.setVisible(show)
        self.next_page_btn.setVisible(show)
        self.page_label.setVisible(show)
        if show:
            self.prev_page_btn.setEnabled(self._page > 0)
            self.next_page_btn.setEnabled(self._page < total_pages - 1)
            self.page_label.setText(f"Page {self._page + 1} of {total_pages}")

    def _go_newer(self) -> None:
        """Move toward page 0 (more recent articles)."""
        if self._page > 0:
            self._render_page(self._page - 1)
            if self._page == 0:
                self._pending_new_count = 0
                self.new_articles_btn.setVisible(False)

    def _go_older(self) -> None:
        """Move toward higher pages (older articles)."""
        self._render_page(self._page + 1)

    def _jump_to_live(self) -> None:
        """Triggered by the 'N new articles' banner: jump back to page 0."""
        self._pending_new_count = 0
        self.new_articles_btn.setVisible(False)
        self._render_page(0)
    
    def add_article(self, article: Dict[str, Any], prepend: bool = True) -> None:
        """
        Add one new article to the top of the article history.

        If the user is currently viewing the live page (page 0), the card is
        inserted directly and the page is kept bounded to PAGE_SIZE (the
        oldest visible card rolls off into page 1). If the user is browsing
        an older page, the article is recorded but does not disturb what
        they're reading -- instead the 'N new articles' banner appears so
        they can jump back to the live view when ready.
        """
        if prepend:
            self.articles.insert(0, article)
        else:
            self.articles.append(article)

        if self._page != 0:
            self._pending_new_count += 1
            self.new_articles_btn.setText(
                f"\u2191 {self._pending_new_count} new article"
                f"{'s' if self._pending_new_count != 1 else ''}"
            )
            self.new_articles_btn.setVisible(True)
            self._update_count()
            self._update_pagination_controls()
            # Keep memory bounded
            if len(self.articles) > self.MAX_ARTICLES:
                self.articles = self.articles[:self.MAX_ARTICLES]
                self._update_pagination_controls()
            return

        self._hide_empty_state()

        if not prepend:
            # Rare path (explicit append): just re-render the live page so
            # ordering stays correct rather than special-casing tail-inserts.
            self._render_page(0)
            return

        card = ArticleCard(article, on_save=self.on_save)
        card.clicked.connect(self.article_clicked.emit)
        card.saved.connect(self.article_saved.emit)
        self.container_layout.insertWidget(0, card)
        self.cards.insert(0, card)

        # Keep the live page bounded -- the oldest visible card rolls into
        # page 1 (it's still in self.articles, just not directly rendered).
        if len(self.cards) > self.PAGE_SIZE:
            overflow_card = self.cards.pop()
            overflow_card.deleteLater()

        self._update_count()
        self._update_pagination_controls()
        self.scroll_to_top()
    
    def clear(self) -> None:
        """Clear all articles."""
        for card in self.cards:
            self.container_layout.removeWidget(card)
            card.deleteLater()
        
        self.cards.clear()
        self.articles.clear()
        self._page = 0
        self._pending_new_count = 0
        self.new_articles_btn.setVisible(False)
        self._show_empty_state()
        self._update_count()
        self._update_pagination_controls()
    
    def _update_count(self) -> None:
        """Update article count label."""
        total = len(self.articles)
        if total == 0:
            self.count_label.setText("No articles")
        elif self._total_pages() > 1:
            self.count_label.setText(f"Showing {len(self.cards)} of {total} articles")
        else:
            self.count_label.setText(f"Showing {total} Article{'s' if total != 1 else ''}")
    
    def scroll_to_top(self) -> None:
        """Scroll to top of feed."""
        self.scroll_area.verticalScrollBar().setValue(0)

    def _handle_archive_requested(self, article_id: str) -> None:
        """Handle archive event from a card."""
        self.article_archived.emit(article_id)
        # Remove from local list
        self.articles = [a for a in self.articles if a.get("id") != article_id]
        # Find and remove the card widget
        for card in self.cards:
            if card.article.get("id") == article_id:
                card.setParent(None)
                card.deleteLater()
                self.cards.remove(card)
                break
        self._update_count()
        self._update_pagination_controls()
