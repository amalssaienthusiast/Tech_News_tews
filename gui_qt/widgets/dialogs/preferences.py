"""
Preferences Dialog - Tabbed settings for user preferences.

Features:
- Topics tab (interests, keywords)
- Watchlist tab (companies to track)
- Storage tab (mode selection)
- Display tab (theme options)
"""

from typing import Callable, Optional

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QFormLayout, QHBoxLayout,
    QLabel, QLineEdit, QListWidget, QListWidgetItem, QPushButton,
    QTabWidget, QVBoxLayout, QWidget, QTextEdit, QSpinBox
)

from gui_qt.theme import COLORS


class PreferencesDialog(QDialog):
    """User preferences dialog with tabbed interface."""
    
    preferences_changed = pyqtSignal(dict)
    
    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        
        self.setWindowTitle("⚙️ Preferences")
        self.setMinimumSize(600, 500)
        self.setModal(True)
        
        self._setup_ui()
        self._load_preferences()
    
    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(16)
        
        # Header
        header = QLabel("⚙️ User Preferences")
        header.setStyleSheet(f"font-size: 20px; font-weight: bold; color: {COLORS.fg};")
        layout.addWidget(header)
        
        # Tabs
        self.tabs = QTabWidget()
        self.tabs.addTab(self._create_topics_tab(), "📚 Topics")
        self.tabs.addTab(self._create_watchlist_tab(), "🔔 Watchlist")
        self.tabs.addTab(self._create_storage_tab(), "💾 Storage")
        self.tabs.addTab(self._create_display_tab(), "🎨 Display")
        layout.addWidget(self.tabs)
        
        # Buttons
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()
        
        cancel_btn = QPushButton("Cancel")
        cancel_btn.clicked.connect(self.reject)
        btn_layout.addWidget(cancel_btn)
        
        save_btn = QPushButton("Save")
        save_btn.setProperty("class", "primary")
        save_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {COLORS.cyan};
                color: {COLORS.black};
                border: none;
                border-radius: 6px;
                padding: 10px 24px;
                font-weight: bold;
            }}
            QPushButton:hover {{
                background-color: {COLORS.blue};
            }}
        """)
        save_btn.clicked.connect(self._save_preferences)
        btn_layout.addWidget(save_btn)
        
        layout.addLayout(btn_layout)
    
    def _create_topics_tab(self) -> QWidget:
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setSpacing(16)
        
        # Topic checkboxes
        topics_label = QLabel("Select topics you're interested in:")
        topics_label.setStyleSheet(f"color: {COLORS.fg}; font-weight: bold;")
        layout.addWidget(topics_label)
        
        self.topic_checkboxes = {}
        topics = [
            ("AI & Machine Learning", "ai"),
            ("Cybersecurity", "security"),
            ("Cloud Computing", "cloud"),
            ("Startups & Funding", "startups"),
            ("Programming", "programming"),
            ("Hardware & Chips", "hardware"),
            ("Blockchain & Crypto", "crypto"),
            ("Mobile Development", "mobile"),
        ]
        
        for label, key in topics:
            cb = QCheckBox(label)
            self.topic_checkboxes[key] = cb
            layout.addWidget(cb)
        
        # Keywords
        layout.addSpacing(16)
        keywords_label = QLabel("Custom Keywords (comma-separated):")
        keywords_label.setStyleSheet(f"color: {COLORS.fg}; font-weight: bold;")
        layout.addWidget(keywords_label)
        
        self.keywords_input = QLineEdit()
        self.keywords_input.setPlaceholderText("e.g., Tesla, advanced computing, OpenAI")
        layout.addWidget(self.keywords_input)
        
        layout.addStretch()
        return tab
    
    def _create_watchlist_tab(self) -> QWidget:
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setSpacing(12)
        
        label = QLabel("Companies to track:")
        label.setStyleSheet(f"color: {COLORS.fg}; font-weight: bold;")
        layout.addWidget(label)
        
        # Company list
        self.company_list = QListWidget()
        self.company_list.setStyleSheet(f"""
            QListWidget {{
                background-color: {COLORS.bg_input};
                border: 1px solid {COLORS.border};
                border-radius: 6px;
            }}
            QListWidget::item {{
                padding: 8px;
                border-bottom: 1px solid {COLORS.border};
            }}
            QListWidget::item:selected {{
                background-color: {COLORS.bg_visual};
            }}
        """)
        layout.addWidget(self.company_list)
        
        # Add company
        add_layout = QHBoxLayout()
        self.new_company_input = QLineEdit()
        self.new_company_input.setPlaceholderText("Enter company name...")
        add_layout.addWidget(self.new_company_input)
        
        add_btn = QPushButton("+ Add")
        add_btn.clicked.connect(self._add_company)
        add_layout.addWidget(add_btn)
        
        remove_btn = QPushButton("- Remove")
        remove_btn.clicked.connect(self._remove_company)
        add_layout.addWidget(remove_btn)
        
        layout.addLayout(add_layout)
        
        return tab
    
    def _create_storage_tab(self) -> QWidget:
        tab = QWidget()
        layout = QFormLayout(tab)
        layout.setSpacing(16)
        
        # Storage mode
        self.storage_mode = QComboBox()
        self.storage_mode.addItems(["⚡ Ephemeral", "🔄 Hybrid", "💿 Persistent"])
        self.storage_mode.setCurrentIndex(1)
        layout.addRow("Storage Mode:", self.storage_mode)
        
        # TTL
        self.ttl_spinbox = QSpinBox()
        self.ttl_spinbox.setRange(1, 48)
        self.ttl_spinbox.setValue(2)
        self.ttl_spinbox.setSuffix(" hours")
        layout.addRow("Article TTL:", self.ttl_spinbox)
        
        # Max articles
        self.max_articles = QSpinBox()
        self.max_articles.setRange(50, 2000)
        self.max_articles.setValue(500)
        layout.addRow("Max Articles:", self.max_articles)
        
        # Redis
        self.redis_enabled = QCheckBox("Enable Redis Cache")
        self.redis_enabled.setChecked(True)
        layout.addRow("", self.redis_enabled)
        
        return tab
    
    def _create_display_tab(self) -> QWidget:
        tab = QWidget()
        layout = QFormLayout(tab)
        layout.setSpacing(16)
        
        # Theme
        self.theme_combo = QComboBox()
        self.theme_combo.addItems(["Tokyo Night", "Tokyo Night Storm", "Tokyo Night Day"])
        layout.addRow("Theme:", self.theme_combo)
        
        # Card style
        self.card_style = QComboBox()
        self.card_style.addItems(["Compact", "Standard", "Detailed"])
        self.card_style.setCurrentIndex(1)
        layout.addRow("Card Style:", self.card_style)
        
        # Show scores
        self.show_scores = QCheckBox("Show Tech Scores")
        self.show_scores.setChecked(True)
        layout.addRow("", self.show_scores)
        
        # Show AI summaries
        self.show_summaries = QCheckBox("Show AI Summaries")
        self.show_summaries.setChecked(True)
        layout.addRow("", self.show_summaries)
        
        return tab
    
    def _add_company(self) -> None:
        company = self.new_company_input.text().strip()
        if company:
            self.company_list.addItem(company)
            self.new_company_input.clear()
    
    def _remove_company(self) -> None:
        current = self.company_list.currentRow()
        if current >= 0:
            self.company_list.takeItem(current)
    
    def _load_preferences(self) -> None:
        """Load preferences from storage."""
        # Default values - would normally load from UserPreferences
        default_companies = ["Apple", "Google", "Microsoft", "OpenAI", "Tesla"]
        for company in default_companies:
            self.company_list.addItem(company)
        
        # Default topics
        self.topic_checkboxes.get("ai", QCheckBox()).setChecked(True)
        self.topic_checkboxes.get("security", QCheckBox()).setChecked(True)
    
    def _save_preferences(self) -> None:
        """Save preferences and emit signal."""
        prefs = {
            "topics": [k for k, cb in self.topic_checkboxes.items() if cb.isChecked()],
            "keywords": [k.strip() for k in self.keywords_input.text().split(",") if k.strip()],
            "watchlist": [self.company_list.item(i).text() for i in range(self.company_list.count())],
            "storage": {
                "mode": ["ephemeral", "hybrid", "persistent"][self.storage_mode.currentIndex()],
                "ttl_hours": self.ttl_spinbox.value(),
                "max_articles": self.max_articles.value(),
                "redis_enabled": self.redis_enabled.isChecked(),
            },
            "display": {
                "theme": self.theme_combo.currentText(),
                "card_style": self.card_style.currentText().lower(),
                "show_scores": self.show_scores.isChecked(),
                "show_summaries": self.show_summaries.isChecked(),
            },
        }
        
        self.preferences_changed.emit(prefs)
        self.accept()


class StatisticsDialog(QDialog):
    """Statistics popup showing scraping metrics."""
    
    def __init__(
        self,
        stats: dict = None,
        parent: Optional[QWidget] = None
    ) -> None:
        super().__init__(parent)
        
        self.stats = stats or {}
        self.setWindowTitle("📊 Statistics")
        self.setMinimumSize(500, 400)
        
        self._setup_ui()
    
    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(16)
        
        # Header
        header = QLabel("📊 Scraping Statistics")
        header.setStyleSheet(f"font-size: 20px; font-weight: bold; color: {COLORS.fg};")
        layout.addWidget(header)
        
        # Stats grid
        stats_widget = QWidget()
        stats_widget.setStyleSheet(f"""
            background-color: {COLORS.bg_highlight};
            border-radius: 8px;
            padding: 16px;
        """)
        stats_layout = QVBoxLayout(stats_widget)
        stats_layout.setSpacing(12)
        
        # Add stat rows
        self._add_stat_row(stats_layout, "📰 Total Articles", self.stats.get("total_articles", 0))
        self._add_stat_row(stats_layout, "🔗 Unique Sources", self.stats.get("sources", 0))
        self._add_stat_row(stats_layout, "✅ Successful Fetches", self.stats.get("successful", 0))
        self._add_stat_row(stats_layout, "❌ Failed Fetches", self.stats.get("failed", 0))
        self._add_stat_row(stats_layout, "💾 Saved Articles", self.stats.get("saved", 0))
        self._add_stat_row(stats_layout, "🔄 Dedup Rate", f"{self.stats.get('dedup_rate', 0):.1f}%")
        self._add_stat_row(stats_layout, "⏱️ Avg Fetch Time", f"{self.stats.get('avg_fetch_ms', 0):.0f}ms")
        
        layout.addWidget(stats_widget)
        
        layout.addStretch()
        
        # Close button
        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.accept)
        layout.addWidget(close_btn, alignment=Qt.AlignmentFlag.AlignCenter)
    
    def _add_stat_row(self, layout: QVBoxLayout, label: str, value) -> None:
        row = QHBoxLayout()
        
        lbl = QLabel(label)
        lbl.setStyleSheet(f"color: {COLORS.fg}; font-size: 14px;")
        row.addWidget(lbl)
        
        row.addStretch()
        
        val = QLabel(str(value))
        val.setStyleSheet(f"color: {COLORS.cyan}; font-size: 14px; font-weight: bold;")
        row.addWidget(val)
        
        layout.addLayout(row)
