"""
Article Popup Dialog for Tech News Scraper
Detailed article view matching tkinter gui/app.py
"""

from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QScrollArea, QWidget, QFrame,
    QTextBrowser, QGridLayout
)
from PyQt6.QtCore import Qt, QUrl
from PyQt6.QtGui import QDesktopServices, QFont

from datetime import datetime
from ..theme import COLORS, Fonts


class ArticlePopup(QDialog):
    """Detailed article popup dialog
    
    Displays full article details including:
    - Title and source
    - Tech score with visual indicator
    - Published date
    - Summary
    - Keywords/tags
    - Categories
    - External link button
    
    Usage:
        popup = ArticlePopup(parent, article)
        popup.exec()
    """
    
    def __init__(self, parent=None, article=None):
        super().__init__(parent)
        
        self.article = article
        self._article_url = None
        
        self._setup_window()
        self._setup_ui()
        
        if article:
            self._populate_data(article)
    
    def _setup_window(self):
        """Configure dialog window"""
        self.setWindowTitle("Article Details")
        self.setMinimumSize(600, 500)
        self.setMaximumSize(800, 700)
        
        # Remove window frame for custom styling
        self.setWindowFlags(
            Qt.WindowType.Dialog | 
            Qt.WindowType.WindowCloseButtonHint |
            Qt.WindowType.WindowMaximizeButtonHint
        )
    
    def _setup_ui(self):
        """Build the popup UI"""
        # Main layout
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(20, 20, 20, 20)
        main_layout.setSpacing(15)
        
        # Header section
        header = self._create_header()
        main_layout.addWidget(header)
        
        # Scrollable content area
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        
        content_widget = QWidget()
        content_layout = QVBoxLayout(content_widget)
        content_layout.setSpacing(15)
        
        # Article content
        self.content_section = self._create_content_section()
        content_layout.addWidget(self.content_section)
        
        # Tags and keywords
        self.tags_section = self._create_tags_section()
        content_layout.addWidget(self.tags_section)
        
        # Metadata grid
        self.meta_section = self._create_meta_section()
        content_layout.addWidget(self.meta_section)
        
        content_layout.addStretch()
        scroll.setWidget(content_widget)
        main_layout.addWidget(scroll)
        
        # Footer with action buttons
        footer = self._create_footer()
        main_layout.addWidget(footer)
        
        # Apply styles
        self._apply_styles()
    
    def _create_header(self):
        """Create header with title and score"""
        header = QFrame()
        header.setObjectName("articleHeader")
        header.setStyleSheet(f"""
            QFrame#articleHeader {{
                background-color: {COLORS.bg_highlight};
                border-radius: 8px;
                padding: 15px;
            }}
        """)
        
        layout = QVBoxLayout(header)
        layout.setSpacing(10)
        
        # Title
        self.title_label = QLabel("Loading...")
        self.title_label.setWordWrap(True)
        self.title_label.setStyleSheet(f"""
            font-size: 20px;
            font-weight: bold;
            color: {COLORS.cyan};
        """)
        layout.addWidget(self.title_label)
        
        # Source and score row
        source_row = QHBoxLayout()
        
        # Source
        self.source_label = QLabel("📰 Unknown Source")
        self.source_label.setStyleSheet(f"color: {COLORS.fg_dark};")
        source_row.addWidget(self.source_label)
        
        source_row.addStretch()
        
        # Score badge
        self.score_frame = QFrame()
        self.score_frame.setStyleSheet(f"""
            background-color: {COLORS.bg_visual};
            border-radius: 12px;
            padding: 4px 12px;
        """)
        score_layout = QHBoxLayout(self.score_frame)
        score_layout.setContentsMargins(8, 4, 8, 4)
        
        self.score_label = QLabel("Tech Score: --")
        self.score_label.setStyleSheet(f"color: {COLORS.green}; font-weight: bold;")
        score_layout.addWidget(self.score_label)
        
        source_row.addWidget(self.score_frame)
        
        layout.addLayout(source_row)
        
        return header
    
    def _create_content_section(self):
        """Create content section with summary"""
        section = QFrame()
        section.setObjectName("contentSection")
        
        layout = QVBoxLayout(section)
        layout.setSpacing(10)
        
        # Summary label
        summary_header = QLabel("📝 Summary")
        summary_header.setStyleSheet(f"""
            font-size: 16px;
            font-weight: bold;
            color: {COLORS.blue};
        """)
        layout.addWidget(summary_header)
        
        # Summary text
        self.summary_text = QTextBrowser()
        self.summary_text.setOpenExternalLinks(False)
        self.summary_text.anchorClicked.connect(self._on_link_clicked)
        self.summary_text.setStyleSheet(f"""
            QTextBrowser {{
                background-color: {COLORS.bg};
                color: {COLORS.fg};
                border: 1px solid {COLORS.terminal_black};
                border-radius: 6px;
                padding: 10px;
                font-size: {Fonts.get_size('md')}px;
                line-height: 1.6;
            }}
        """)
        self.summary_text.setMinimumHeight(150)
        layout.addWidget(self.summary_text)
        
        return section
    
    def _create_tags_section(self):
        """Create tags and keywords section"""
        section = QFrame()
        
        layout = QVBoxLayout(section)
        layout.setSpacing(10)
        
        # Keywords
        keywords_header = QLabel("🏷️ Keywords")
        keywords_header.setStyleSheet(f"""
            font-size: 14px;
            font-weight: bold;
            color: {COLORS.magenta};
        """)
        layout.addWidget(keywords_header)
        
        self.keywords_container = QWidget()
        self.keywords_layout = QHBoxLayout(self.keywords_container)
        self.keywords_layout.setSpacing(6)
        self.keywords_layout.setContentsMargins(0, 0, 0, 0)
        self.keywords_layout.setAlignment(Qt.AlignmentFlag.AlignLeft)
        layout.addWidget(self.keywords_container)
        
        # Categories
        categories_header = QLabel("📂 Categories")
        categories_header.setStyleSheet(f"""
            font-size: 14px;
            font-weight: bold;
            color: {COLORS.yellow};
            margin-top: 10px;
        """)
        layout.addWidget(categories_header)
        
        self.categories_container = QWidget()
        self.categories_layout = QHBoxLayout(self.categories_container)
        self.categories_layout.setSpacing(6)
        self.categories_layout.setContentsMargins(0, 0, 0, 0)
        self.categories_layout.setAlignment(Qt.AlignmentFlag.AlignLeft)
        layout.addWidget(self.categories_container)
        
        return section
    
    def _create_meta_section(self):
        """Create metadata section with grid"""
        section = QFrame()
        section.setObjectName("metaSection")
        section.setStyleSheet(f"""
            QFrame#metaSection {{
                background-color: {COLORS.bg_dark};
                border-radius: 8px;
                padding: 10px;
            }}
        """)
        
        layout = QGridLayout(section)
        layout.setSpacing(10)
        
        # Metadata labels
        self.published_label = self._create_meta_item("📅 Published:", "Unknown")
        self.fetched_label = self._create_meta_item("⏱️ Fetched:", "Unknown")
        self.id_label = self._create_meta_item("🆔 Article ID:", "N/A")
        
        layout.addWidget(self.published_label[0], 0, 0)
        layout.addWidget(self.published_label[1], 0, 1)
        layout.addWidget(self.fetched_label[0], 1, 0)
        layout.addWidget(self.fetched_label[1], 1, 1)
        layout.addWidget(self.id_label[0], 2, 0)
        layout.addWidget(self.id_label[1], 2, 1)
        
        return section
    
    def _create_meta_item(self, label_text, value_text):
        """Create a metadata label-value pair"""
        label = QLabel(label_text)
        label.setStyleSheet(f"color: {COLORS.comment};")
        
        value = QLabel(value_text)
        value.setStyleSheet(f"color: {COLORS.fg};")
        value.setWordWrap(True)
        
        return label, value
    
    def _create_footer(self):
        """Create footer with action buttons"""
        footer = QWidget()
        layout = QHBoxLayout(footer)
        layout.setSpacing(10)
        
        # Close button
        close_btn = QPushButton("✕ Close")
        close_btn.clicked.connect(self.reject)
        layout.addWidget(close_btn)
        
        layout.addStretch()
        
        # Copy link button
        copy_btn = QPushButton("📋 Copy Link")
        copy_btn.setToolTip("Copy article URL to clipboard")
        copy_btn.clicked.connect(self._copy_link)
        layout.addWidget(copy_btn)
        
        # Open in browser button
        open_btn = QPushButton("🔗 Open in Browser")
        open_btn.setObjectName("primaryButton")
        open_btn.setToolTip("Open article in default web browser")
        open_btn.clicked.connect(self._open_in_browser)
        layout.addWidget(open_btn)
        
        return footer
    
    def _apply_styles(self):
        """Apply dialog styles"""
        self.setStyleSheet(f"""
            QDialog {{
                background-color: {COLORS.bg};
            }}
            QLabel {{
                color: {COLORS.fg};
            }}
            QPushButton {{
                background-color: {COLORS.bg_highlight};
                color: {COLORS.fg};
                border: 1px solid {COLORS.terminal_black};
                border-radius: 6px;
                padding: 8px 16px;
            }}
            QPushButton:hover {{
                background-color: {COLORS.bg_visual};
            }}
            QPushButton#primaryButton {{
                background-color: {COLORS.blue};
                color: {COLORS.black};
                border: none;
                font-weight: bold;
            }}
            QPushButton#primaryButton:hover {{
                background-color: {COLORS.bright_blue};
            }}
        """)
    
    def _populate_data(self, article):
        """Populate dialog with article data
        
        Args:
            article: Article object with attributes:
                - title
                - source
                - tech_score (with score attribute)
                - published_at
                - fetched_at
                - url
                - summary
                - keywords (list)
                - categories (list)
                - article_id or id
        """
        # Title
        title = getattr(article, 'title', 'Untitled Article')
        self.title_label.setText(title)
        self.setWindowTitle(f"Article: {title[:50]}...")
        
        # Source
        source = getattr(article, 'source', 'Unknown')
        self.source_label.setText(f"📰 {source}")
        
        # Score
        tech_score = getattr(article, 'tech_score', None)
        if tech_score:
            score = getattr(tech_score, 'score', 0)
            self.score_label.setText(f"Tech Score: {score:.1f}")
            
            # Color code based on score
            if score >= 8:
                color = COLORS.green
            elif score >= 5:
                color = COLORS.yellow
            else:
                color = COLORS.red
            self.score_label.setStyleSheet(f"color: {color}; font-weight: bold;")
        else:
            self.score_label.setText("Tech Score: N/A")
        
        # Summary
        summary = getattr(article, 'summary', '') or getattr(article, 'content', '')
        if summary:
            # Convert URLs to clickable links
            import re
            url_pattern = r'(https?://[^\s]+)'
            summary_linked = re.sub(url_pattern, r'<a href="\1">\1</a>', summary)
            self.summary_text.setHtml(f"<p style='line-height: 1.6;'>{summary_linked}</p>")
        else:
            self.summary_text.setHtml("<p style='color: #565f89; font-style: italic;'>No summary available</p>")
        
        # Keywords
        keywords = getattr(article, 'keywords', []) or []
        self._populate_tags(self.keywords_layout, keywords, COLORS.magenta)
        
        # Categories
        categories = getattr(article, 'categories', []) or []
        self._populate_tags(self.categories_layout, categories, COLORS.yellow)
        
        # Metadata
        published = getattr(article, 'published_at', None)
        if published:
            if isinstance(published, datetime):
                published_str = published.strftime("%Y-%m-%d %H:%M")
            else:
                published_str = str(published)
            self.published_label[1].setText(published_str)
        
        fetched = getattr(article, 'fetched_at', None)
        if fetched:
            if isinstance(fetched, datetime):
                fetched_str = fetched.strftime("%Y-%m-%d %H:%M")
            else:
                fetched_str = str(fetched)
            self.fetched_label[1].setText(fetched_str)
        
        # Article ID
        article_id = getattr(article, 'article_id', None) or getattr(article, 'id', None) or 'N/A'
        self.id_label[1].setText(str(article_id))
        
        # Store URL
        self._article_url = getattr(article, 'url', None)
    
    def _populate_tags(self, layout, tags, color):
        """Populate tags into layout"""
        # Clear existing
        while layout.count():
            item = layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        
        if not tags:
            empty_label = QLabel("None")
            empty_label.setStyleSheet(f"color: {COLORS.comment}; font-style: italic;")
            layout.addWidget(empty_label)
            return
        
        for tag in tags[:10]:  # Limit to 10 tags
            tag_label = QLabel(f"  {tag}  ")
            tag_label.setStyleSheet(f"""
                background-color: {COLORS.bg_visual};
                color: {color};
                border-radius: 10px;
                padding: 2px 8px;
                font-size: {Fonts.get_size('sm')}px;
            """)
            layout.addWidget(tag_label)
        
        if len(tags) > 10:
            more_label = QLabel(f"+{len(tags) - 10} more")
            more_label.setStyleSheet(f"color: {COLORS.comment}; font-size: {Fonts.get_size('xs')}px;")
            layout.addWidget(more_label)
        
        layout.addStretch()
    
    def _on_link_clicked(self, url):
        """Handle link click in summary"""
        QDesktopServices.openUrl(url)
    
    def _copy_link(self):
        """Copy article URL to clipboard"""
        if self._article_url:
            from PyQt6.QtWidgets import QApplication
            clipboard = QApplication.clipboard()
            clipboard.setText(self._article_url)
            self.set_status("✅ Link copied to clipboard")
    
    def _open_in_browser(self):
        """Open article in default browser"""
        if self._article_url:
            QDesktopServices.openUrl(QUrl(self._article_url))
    
    def set_status(self, message: str, timeout: int = 3000):
        """Show status message in window title temporarily"""
        original_title = self.windowTitle()
        self.setWindowTitle(message)
        
        # Reset after timeout
        from PyQt6.QtCore import QTimer
        QTimer.singleShot(timeout, lambda: self.setWindowTitle(original_title))
