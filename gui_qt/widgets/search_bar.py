"""
Search Bar Widget for Tech News Scraper
Matches searchbar from tkinter gui/app.py
"""

from PyQt6.QtWidgets import (
    QWidget, QHBoxLayout, QLineEdit, QPushButton,
    QComboBox, QLabel, QFrame
)
from PyQt6.QtCore import pyqtSignal, Qt, QTimer
from PyQt6.QtGui import QFont

from ..theme import COLORS, Fonts


class SearchBar(QWidget):
    """Search bar with input, button, and optional filters
    
    Signals:
        search_triggered(str): Emitted when search is activated (Enter or button click)
        search_cleared(): Emitted when search is cleared
        filter_changed(str, str): Emitted when filter changes (filter_type, value)
    """
    
    search_triggered = pyqtSignal(str)
    search_cleared = pyqtSignal()
    filter_changed = pyqtSignal(str, str)
    
    def __init__(
        self, 
        parent=None, 
        placeholder: str = "🔍 Search tech news...",
        show_filters: bool = False,
        debounce_ms: int = 300
    ):
        super().__init__(parent)
        
        self._placeholder = placeholder
        self._show_filters = show_filters
        self._debounce_ms = debounce_ms
        self._debounce_timer = QTimer(self)
        self._debounce_timer.setSingleShot(True)
        self._debounce_timer.timeout.connect(self._emit_search)
        
        self._setup_ui()
        self._connect_signals()
    
    def _setup_ui(self):
        """Build the search bar UI"""
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        
        # Container frame
        self.container = QFrame(self)
        self.container.setStyleSheet(f"""
            QFrame {{
                background-color: {COLORS.bg_highlight};
                border: 1px solid {COLORS.terminal_black};
                border-radius: 8px;
                padding: 4px 8px;
            }}
            QFrame:focus-within {{
                border: 1px solid {COLORS.cyan};
            }}
        """)
        
        container_layout = QHBoxLayout(self.container)
        container_layout.setContentsMargins(8, 4, 8, 4)
        container_layout.setSpacing(8)
        
        # Search icon label
        self.icon_label = QLabel("🔍", self.container)
        self.icon_label.setStyleSheet(f"color: {COLORS.comment}; font-size: 14px;")
        container_layout.addWidget(self.icon_label)
        
        # Search input
        self.input = QLineEdit(self.container)
        self.input.setPlaceholderText(self._placeholder.replace("🔍 ", ""))
        self.input.setStyleSheet(f"""
            QLineEdit {{
                background-color: transparent;
                color: {COLORS.fg};
                border: none;
                padding: 6px 0;
                font-size: {Fonts.get_size('md')}px;
            }}
            QLineEdit::placeholder {{
                color: {COLORS.comment};
            }}
        """)
        self.input.setFont(Fonts.get_qfont('md'))
        container_layout.addWidget(self.input, 1)  # Stretch
        
        # Clear button (hidden initially)
        self.clear_btn = QPushButton("✕", self.container)
        self.clear_btn.setFixedSize(24, 24)
        self.clear_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: transparent;
                color: {COLORS.comment};
                border: none;
                font-size: 12px;
                border-radius: 12px;
            }}
            QPushButton:hover {{
                background-color: {COLORS.bg_visual};
                color: {COLORS.fg};
            }}
        """)
        self.clear_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.clear_btn.hide()
        container_layout.addWidget(self.clear_btn)
        
        layout.addWidget(self.container, 1)  # Stretch
        
        # Search button
        self.search_btn = QPushButton("Search", self)
        self.search_btn.setObjectName("primaryButton")
        self.search_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.search_btn.setFont(Fonts.get_qfont('sm', 'bold'))
        self.search_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {COLORS.cyan};
                color: {COLORS.black};
                border: none;
                border-radius: 8px;
                padding: 10px 20px;
                font-weight: bold;
            }}
            QPushButton:hover {{
                background-color: {COLORS.bright_cyan};
            }}
            QPushButton:pressed {{
                background-color: {COLORS.blue};
            }}
        """)
        layout.addWidget(self.search_btn)
        
        # Optional filters
        if self._show_filters:
            self._add_filters(layout)
    
    def _add_filters(self, layout):
        """Add filter dropdowns"""
        # Source filter
        self.source_filter = QComboBox(self)
        self.source_filter.addItems([
            "All Sources",
            "TechCrunch",
            "Hacker News",
            "The Verge",
            "Ars Technica",
            "Wired"
        ])
        layout.addWidget(self.source_filter)
        
        # Score filter
        self.score_filter = QComboBox(self)
        self.score_filter.addItems([
            "Any Score",
            "Score ≥ 8.0",
            "Score ≥ 6.5",
            "Score ≥ 5.0"
        ])
        layout.addWidget(self.score_filter)
    
    def _connect_signals(self):
        """Connect internal signals"""
        # Enter key triggers search
        self.input.returnPressed.connect(self._on_search_triggered)
        
        # Button clicks
        self.search_btn.clicked.connect(self._on_search_triggered)
        self.clear_btn.clicked.connect(self._on_clear)
        
        # Text changes for debounced auto-search
        self.input.textChanged.connect(self._on_text_changed)
        
        # Filter changes
        if self._show_filters:
            self.source_filter.currentTextChanged.connect(
                lambda v: self.filter_changed.emit("source", v)
            )
            self.score_filter.currentTextChanged.connect(
                lambda v: self.filter_changed.emit("score", v)
            )
    
    def _on_text_changed(self, text: str):
        """Handle text input changes"""
        # Show/hide clear button
        self.clear_btn.setVisible(bool(text))
        
        # Update icon color
        if text:
            self.icon_label.setStyleSheet(f"color: {COLORS.cyan}; font-size: 14px;")
        else:
            self.icon_label.setStyleSheet(f"color: {COLORS.comment}; font-size: 14px;")
        
        # Start debounce timer (optional live search)
        if self._debounce_ms > 0:
            self._debounce_timer.start(self._debounce_ms)
    
    def _on_search_triggered(self):
        """Handle explicit search trigger (Enter or button)"""
        self._debounce_timer.stop()
        self._emit_search()
    
    def _emit_search(self):
        """Emit search signal with current query"""
        query = self.input.text().strip()
        self.search_triggered.emit(query)
    
    def _on_clear(self):
        """Clear search input"""
        self.input.clear()
        self.input.setFocus()
        self.search_cleared.emit()
    
    # Public API
    def get_query(self) -> str:
        """Get current search query"""
        return self.input.text().strip()
    
    def set_query(self, query: str):
        """Set search query programmatically"""
        self.input.setText(query)
    
    def clear(self):
        """Clear the search bar"""
        self._on_clear()
    
    def set_searching(self, searching: bool):
        """Show/hide searching state"""
        if searching:
            self.search_btn.setText("⏳")
            self.search_btn.setEnabled(False)
        else:
            self.search_btn.setText("Search")
            self.search_btn.setEnabled(True)
    
    def focus(self):
        """Focus the search input"""
        self.input.setFocus()
