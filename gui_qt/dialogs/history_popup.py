"""
History Popup Dialog for Tech News Scraper
Article history view matching tkinter gui/app.py
"""

from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QTableWidget, QTableWidgetItem,
    QHeaderView, QLineEdit, QComboBox, QDateEdit,
    QFrame, QAbstractItemView, QWidget
)
from PyQt6.QtCore import Qt, QDate
from PyQt6.QtGui import QFont

from datetime import datetime, timedelta
from ..theme import COLORS, Fonts


class HistoryPopup(QDialog):
    """Article history popup dialog
    
    Displays previously fetched articles with:
    - Search and filtering
    - Date range selection
    - Sortable table view
    - Export functionality
    - Article details on click
    
    Usage:
        popup = HistoryPopup(parent, articles)
        popup.exec()
    """
    
    def __init__(self, parent=None, articles=None):
        super().__init__(parent)
        
        self._articles = articles or []
        self._filtered_articles = self._articles.copy()
        
        self._setup_window()
        self._setup_ui()
        self._populate_table()
    
    def _setup_window(self):
        """Configure dialog window"""
        self.setWindowTitle("📜 Article History")
        self.setMinimumSize(800, 600)
        self.setMaximumSize(1200, 800)
        
        self.setWindowFlags(
            Qt.WindowType.Dialog |
            Qt.WindowType.WindowCloseButtonHint |
            Qt.WindowType.WindowMaximizeButtonHint
        )
    
    def _setup_ui(self):
        """Build the history popup UI"""
        layout = QVBoxLayout(self)
        layout.setSpacing(15)
        
        # Header
        header = self._create_header()
        layout.addWidget(header)
        
        # Filter bar
        filter_bar = self._create_filter_bar()
        layout.addWidget(filter_bar)
        
        # Results table
        self._create_table()
        layout.addWidget(self.table)
        
        # Footer
        footer = self._create_footer()
        layout.addWidget(footer)
        
        # Apply styles
        self._apply_styles()
    
    def _create_header(self):
        """Create header section"""
        header = QFrame()
        header.setObjectName("historyHeader")
        header.setStyleSheet(f"""
            QFrame#historyHeader {{
                background-color: {COLORS.bg_highlight};
                border-radius: 8px;
                padding: 15px;
            }}
        """)
        
        layout = QHBoxLayout(header)
        
        # Title
        title = QLabel("📜 Article History")
        title.setStyleSheet(f"""
            font-size: 20px;
            font-weight: bold;
            color: {COLORS.cyan};
        """)
        layout.addWidget(title)
        
        layout.addStretch()
        
        # Stats
        self.stats_label = QLabel(f"Showing {len(self._filtered_articles)} of {len(self._articles)} articles")
        self.stats_label.setStyleSheet(f"color: {COLORS.comment};")
        layout.addWidget(self.stats_label)
        
        return header
    
    def _create_filter_bar(self):
        """Create filter/search bar"""
        filter_frame = QFrame()
        filter_frame.setStyleSheet(f"""
            QFrame {{
                background-color: {COLORS.bg_dark};
                border-radius: 6px;
                padding: 5px;
            }}
        """)
        
        layout = QHBoxLayout(filter_frame)
        layout.setSpacing(10)
        
        # Search
        layout.addWidget(QLabel("🔍"))
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("Search history...")
        self.search_input.setMinimumWidth(200)
        self.search_input.textChanged.connect(self._apply_filters)
        layout.addWidget(self.search_input)
        
        # Source filter
        layout.addWidget(QLabel("Source:"))
        self.source_filter = QComboBox()
        self.source_filter.addItem("All Sources")
        self._populate_source_filter()
        self.source_filter.currentTextChanged.connect(self._apply_filters)
        layout.addWidget(self.source_filter)
        
        # Date range
        layout.addWidget(QLabel("From:"))
        self.date_from = QDateEdit()
        self.date_from.setCalendarPopup(True)
        self.date_from.setDate(QDate.currentDate().addDays(-7))
        self.date_from.dateChanged.connect(self._apply_filters)
        layout.addWidget(self.date_from)
        
        layout.addWidget(QLabel("To:"))
        self.date_to = QDateEdit()
        self.date_to.setCalendarPopup(True)
        self.date_to.setDate(QDate.currentDate())
        self.date_to.dateChanged.connect(self._apply_filters)
        layout.addWidget(self.date_to)
        
        layout.addStretch()
        
        # Clear filters
        clear_btn = QPushButton("✕ Clear")
        clear_btn.clicked.connect(self._clear_filters)
        layout.addWidget(clear_btn)
        
        return filter_frame
    
    def _create_table(self):
        """Create article table"""
        self.table = QTableWidget()
        self.table.setColumnCount(6)
        self.table.setHorizontalHeaderLabels([
            "Title", "Source", "Published", "Fetched", "Score", "Actions"
        ])
        
        # Configure table
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setAlternatingRowColors(True)
        self.table.verticalHeader().setVisible(False)
        
        # Header style
        header = self.table.horizontalHeader()
        header.setStretchLastSection(True)
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(5, QHeaderView.ResizeMode.ResizeToContents)
        
        # Connect double-click
        self.table.doubleClicked.connect(self._on_row_double_clicked)
    
    def _create_footer(self):
        """Create footer with action buttons"""
        footer = QWidget()
        layout = QHBoxLayout(footer)
        
        # Export button
        export_btn = QPushButton("📤 Export")
        export_btn.clicked.connect(self._export_history)
        layout.addWidget(export_btn)
        
        # Refresh button
        refresh_btn = QPushButton("🔄 Refresh")
        refresh_btn.clicked.connect(self._refresh_history)
        layout.addWidget(refresh_btn)
        
        layout.addStretch()
        
        # Selected count
        self.selected_label = QLabel("Selected: 0")
        self.selected_label.setStyleSheet(f"color: {COLORS.comment};")
        layout.addWidget(self.selected_label)
        
        # Close button
        close_btn = QPushButton("✕ Close")
        close_btn.clicked.connect(self.reject)
        layout.addWidget(close_btn)
        
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
            QLineEdit, QComboBox, QDateEdit {{
                background-color: {COLORS.bg_input};
                color: {COLORS.fg};
                border: 1px solid {COLORS.terminal_black};
                border-radius: 4px;
                padding: 6px;
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
            QTableWidget {{
                background-color: {COLORS.bg_dark};
                color: {COLORS.fg};
                border: 1px solid {COLORS.terminal_black};
                gridline-color: {COLORS.terminal_black};
                selection-background-color: {COLORS.bg_visual};
            }}
            QTableWidget::item:selected {{
                background-color: {COLORS.bg_visual};
                color: {COLORS.cyan};
            }}
            QHeaderView::section {{
                background-color: {COLORS.bg_highlight};
                color: {COLORS.cyan};
                padding: 8px;
                border: 1px solid {COLORS.terminal_black};
                font-weight: bold;
            }}
            QTableWidget::item {{
                padding: 8px;
            }}
        """)
    
    @staticmethod
    def _get_val(obj, key, default=None):
        if isinstance(obj, dict):
            return obj.get(key, default)
        return getattr(obj, key, default)

    def _populate_source_filter(self):
        """Populate source filter dropdown"""
        sources = set()
        for article in self._articles:
            source = self._get_val(article, 'source', 'Unknown')
            if source:
                sources.add(source)
        
        for source in sorted(sources):
            self.source_filter.addItem(source)
    
    def _populate_table(self):
        """Populate table with articles"""
        self.table.setRowCount(len(self._filtered_articles))
        
        for row, article in enumerate(self._filtered_articles):
            # Title
            title = self._get_val(article, 'title', 'Untitled') or 'Untitled'
            title_item = QTableWidgetItem(title[:80] + ('...' if len(title) > 80 else ''))
            title_item.setToolTip(title)
            title_item.setData(Qt.ItemDataRole.UserRole, article)  # Store article object
            self.table.setItem(row, 0, title_item)
            
            # Source
            source = self._get_val(article, 'source', 'Unknown') or 'Unknown'
            self.table.setItem(row, 1, QTableWidgetItem(source))
            
            # Published date
            published = self._get_val(article, 'published_at', None) or self._get_val(article, 'scraped_at', None)
            if published:
                if isinstance(published, datetime):
                    published_str = published.strftime("%Y-%m-%d %H:%M")
                else:
                    published_str = str(published)[:16]
            else:
                published_str = "Unknown"
            self.table.setItem(row, 2, QTableWidgetItem(published_str))
            
            # Fetched date
            fetched = self._get_val(article, 'scraped_at', None) or self._get_val(article, 'fetched_at', None)
            if fetched:
                if isinstance(fetched, datetime):
                    fetched_str = fetched.strftime("%Y-%m-%d %H:%M")
                else:
                    fetched_str = str(fetched)[:16]
            else:
                fetched_str = "Recent"
            self.table.setItem(row, 3, QTableWidgetItem(fetched_str))
            
            # Tech score
            tech_score = self._get_val(article, 'tech_score', None) or self._get_val(article, '_criticality', None)
            if tech_score is not None:
                score = getattr(tech_score, 'score', tech_score) if not isinstance(tech_score, (int, float)) else float(tech_score)
                score_str = f"{float(score):.1f}"
                score_item = QTableWidgetItem(score_str)
                
                # Color code based on score
                if float(score) >= 0.7 or float(score) >= 7:
                    score_item.setForeground(QColor(COLORS.green))
                elif float(score) >= 0.4 or float(score) >= 4:
                    score_item.setForeground(QColor(COLORS.yellow))
                else:
                    score_item.setForeground(QColor(COLORS.red))
            else:
                score_item = QTableWidgetItem("N/A")
            
            self.table.setItem(row, 4, score_item)
            
            # Actions placeholder
            actions_item = QTableWidgetItem("👁️ View")
            actions_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.table.setItem(row, 5, actions_item)
        
        # Update stats
        self.stats_label.setText(f"Showing {len(self._filtered_articles)} of {len(self._articles)} articles")
    
    def _apply_filters(self):
        """Apply filters to article list"""
        search_text = self.search_input.text().lower()
        source_filter = self.source_filter.currentText()
        date_from = self.date_from.date().toPyDate()
        date_to = self.date_to.date().toPyDate()

        
        filtered = []
        for article in self._articles:
            # Search filter
            if search_text:
                title = str(self._get_val(article, 'title', '')).lower()
                summary = str(self._get_val(article, 'summary', '')).lower()
                if search_text not in title and search_text not in summary:
                    continue
            
            # Source filter
            if source_filter != "All Sources":
                source = str(self._get_val(article, 'source', ''))
                if source != source_filter:
                    continue
            
            # Date filter
            published = self._get_val(article, 'published_at', None)
            if published and isinstance(published, datetime):
                if published.date() < date_from or published.date() > date_to:
                    continue
            
            filtered.append(article)
        
        self._filtered_articles = filtered
        self._populate_table()

    
    def _clear_filters(self):
        """Clear all filters"""
        self.search_input.clear()
        self.source_filter.setCurrentIndex(0)
        self.date_from.setDate(QDate.currentDate().addDays(-7))
        self.date_to.setDate(QDate.currentDate())
        self._apply_filters()
    
    def _on_row_double_clicked(self, index):
        """Handle row double-click"""
        row = index.row()
        if row < len(self._filtered_articles):
            article = self._filtered_articles[row]
            # TODO: Open article popup
            print(f"Opening article: {getattr(article, 'title', 'Untitled')}")
    
    def _export_history(self):
        """Export history to file"""
        from PyQt6.QtWidgets import QFileDialog
        
        filepath, _ = QFileDialog.getSaveFileName(
            self,
            "Export History",
            "article_history.csv",
            "CSV Files (*.csv);;JSON Files (*.json);;All Files (*.*)"
        )
        
        if filepath:
            try:
                if filepath.endswith('.json'):
                    import json
                    data = []
                    for article in self._filtered_articles:
                        data.append({
                            'title': getattr(article, 'title', ''),
                            'source': getattr(article, 'source', ''),
                            'url': getattr(article, 'url', ''),
                            'published': str(getattr(article, 'published_at', '')),
                        })
                    with open(filepath, 'w') as f:
                        json.dump(data, f, indent=2)
                else:
                    # CSV export
                    import csv
                    with open(filepath, 'w', newline='') as f:
                        writer = csv.writer(f)
                        writer.writerow(['Title', 'Source', 'URL', 'Published', 'Score'])
                        for article in self._filtered_articles:
                            writer.writerow([
                                getattr(article, 'title', ''),
                                getattr(article, 'source', ''),
                                getattr(article, 'url', ''),
                                getattr(article, 'published_at', ''),
                                getattr(article, 'tech_score', None) and getattr(article.tech_score, 'score', 0)
                            ])
                
                from PyQt6.QtWidgets import QMessageBox
                QMessageBox.information(self, "Export Complete", f"History exported to {filepath}")
            except Exception as e:
                from PyQt6.QtWidgets import QMessageBox
                QMessageBox.critical(self, "Export Error", f"Failed to export: {e}")
    
    def _refresh_history(self):
        """Refresh history data"""
        # TODO: Reload from database
        self._apply_filters()
    
    def set_articles(self, articles):
        """Set articles to display
        
        Args:
            articles: List of article objects
        """
        self._articles = articles or []
        self._filtered_articles = self._articles.copy()
        self._populate_source_filter()
        self._populate_table()


# Import QColor for the score coloring
from PyQt6.QtGui import QColor
