"""
Web Crawler Control Panel Dialog for Tech News Scraper
PyQt6 version matching tkinter gui/app.py functionality

Features:
- Configuration tab with URL seeds, depth, max pages, options
- Progress tab with progress bar, stats, and current URL
- Log tab with real-time color-coded output
- Results tab showing crawled articles table
- Start/Stop/Pause controls
"""

from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QTabWidget, QWidget, QTextEdit, QSlider, QSpinBox,
    QCheckBox, QProgressBar, QGroupBox, QTableWidget,
    QTableWidgetItem, QHeaderView, QMessageBox, QSplitter,
    QFrame, QScrollArea, QFileDialog, QComboBox
)
from PyQt6.QtCore import Qt, QTimer, pyqtSignal as Signal, pyqtSlot as Slot
from PyQt6.QtGui import QColor, QTextCharFormat, QTextCursor, QFont
from datetime import datetime
from typing import Optional, List, Dict, Any
import asyncio
import logging

logger = logging.getLogger(__name__)

from ..theme import COLORS, Fonts


class ColoredLogTextEdit(QTextEdit):
    """Text edit with color-coded log output support"""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setReadOnly(True)
        self.setFont(Fonts.get_qfont('xs', mono=True))
        
    def append_colored(self, message: str, level: str = "info"):
        """Append a colored message to the log"""
        colors = {
            "info": QColor(COLORS.fg),
            "success": QColor(COLORS.green),
            "warning": QColor(COLORS.yellow),
            "error": QColor(COLORS.red),
            "crawl": QColor(COLORS.cyan),
            "debug": QColor(COLORS.comment)
        }
        
        color = colors.get(level, QColor(COLORS.fg))
        
        # Create timestamp
        timestamp = datetime.now().strftime("%H:%M:%S")
        
        # Move cursor to end
        cursor = self.textCursor()
        cursor.movePosition(QTextCursor.End)
        
        # Insert timestamp
        fmt_timestamp = QTextCharFormat()
        fmt_timestamp.setForeground(QColor(COLORS.comment))
        fmt_timestamp.setFont(Fonts.get_qfont('xs', mono=True))
        cursor.insertText(f"[{timestamp}] ", fmt_timestamp)
        
        # Insert message with color
        fmt_message = QTextCharFormat()
        fmt_message.setForeground(color)
        fmt_message.setFont(Fonts.get_qfont('xs', mono=True))
        cursor.insertText(f"{message}\n", fmt_message)
        
        # Scroll to bottom
        self.setTextCursor(cursor)
        self.ensureCursorVisible()


class CrawlerDialog(QDialog):
    """
    Web Crawler Control Panel Dialog
    
    Comprehensive crawling interface with:
    - Configuration settings
    - Real-time progress tracking
    - Color-coded log output
    - Results table
    
    Usage:
        dialog = CrawlerDialog(parent, orchestrator)
        dialog.show()
    """
    
    # Signals for async operations
    crawl_started = Signal()
    crawl_stopped = Signal()
    crawl_completed = Signal(list)  # List of articles
    progress_updated = Signal(int, int)  # current, total
    log_message = Signal(str, str)  # message, level
    
    def __init__(self, parent=None, orchestrator=None):
        super().__init__(parent)
        
        self._orchestrator = orchestrator
        self._is_running = False
        self._is_paused = False
        self._crawl_task = None
        self._current_stats = {
            "pages_crawled": 0,
            "articles_found": 0,
            "errors": 0,
            "current_url": ""
        }
        self._found_articles: List[Dict[str, Any]] = []
        
        self._setup_window()
        self._setup_ui()
        self._apply_styles()
        self._connect_signals()
    
    def _setup_window(self):
        """Configure dialog window properties"""
        self.setWindowTitle("🕷️ Web Crawler Control Panel")
        self.setMinimumSize(800, 650)
        self.setMaximumSize(1200, 900)
        self.setWindowFlags(
            Qt.WindowType.Dialog |
            Qt.WindowType.WindowCloseButtonHint |
            Qt.WindowType.WindowMaximizeButtonHint |
            Qt.WindowType.WindowMinimizeButtonHint
        )
    
    def _setup_ui(self):
        """Build the complete UI"""
        # Main layout
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)
        
        # Header
        header = self._create_header()
        main_layout.addWidget(header)
        
        # Tab widget
        self.tab_widget = QTabWidget()
        self.tab_widget.setDocumentMode(True)
        main_layout.addWidget(self.tab_widget, stretch=1)
        
        # Create tabs
        self._setup_config_tab()
        self._setup_progress_tab()
        self._setup_log_tab()
        self._setup_results_tab()
        
        # Footer with controls
        footer = self._create_footer()
        main_layout.addWidget(footer)
    
    def _create_header(self) -> QFrame:
        """Create the header with title and status"""
        header = QFrame()
        header.setObjectName("headerFrame")
        header.setFixedHeight(70)
        
        layout = QHBoxLayout(header)
        layout.setContentsMargins(20, 10, 20, 10)
        
        # Icon and title
        icon_label = QLabel("🕷️")
        icon_label.setStyleSheet(f"font-size: 28px; color: {COLORS.magenta};")
        layout.addWidget(icon_label)
        
        title_label = QLabel("WEB CRAWLER")
        title_label.setObjectName("headerLabel")
        title_label.setStyleSheet(f"""
            QLabel {{
                font-size: 20px;
                font-weight: bold;
                color: {COLORS.fg};
            }}
        """)
        layout.addWidget(title_label)
        
        layout.addStretch()
        
        # Status indicator
        self.status_label = QLabel("Ready")
        self.status_label.setStyleSheet(f"""
            QLabel {{
                font-size: 14px;
                font-weight: bold;
                color: {COLORS.green};
                padding: 5px 15px;
                background-color: {COLORS.bg_highlight};
                border-radius: 15px;
            }}
        """)
        layout.addWidget(self.status_label)
        
        return header
    
    def _setup_config_tab(self):
        """Setup the Configuration tab"""
        config_widget = QWidget()
        config_layout = QVBoxLayout(config_widget)
        config_layout.setContentsMargins(20, 20, 20, 20)
        config_layout.setSpacing(15)
        
        # URL Seeds Section
        url_group = QGroupBox(" Seed URL(s)")
        url_group.setStyleSheet(self._groupbox_style(COLORS.cyan))
        url_layout = QVBoxLayout(url_group)
        
        self.url_text = QTextEdit()
        self.url_text.setPlaceholderText("Enter one URL per line...")
        self.url_text.setText("https://techcrunch.com")
        self.url_text.setMaximumHeight(100)
        self.url_text.setStyleSheet(f"""
            QTextEdit {{
                background-color: {COLORS.bg_visual};
                color: {COLORS.fg};
                border: 1px solid {COLORS.terminal_black};
                border-radius: 6px;
                padding: 8px;
                font-family: {Fonts.MONO};
            }}
        """)
        url_layout.addWidget(self.url_text)
        
        hint_label = QLabel("Enter one URL per line for multiple seed URLs")
        hint_label.setStyleSheet(f"color: {COLORS.comment}; font-size: 11px;")
        url_layout.addWidget(hint_label)
        
        config_layout.addWidget(url_group)
        
        # Settings Section
        settings_group = QGroupBox(" Crawl Settings")
        settings_group.setStyleSheet(self._groupbox_style(COLORS.orange))
        settings_layout = QVBoxLayout(settings_group)
        
        # Depth slider
        depth_layout = QHBoxLayout()
        depth_label = QLabel("Max Depth:")
        depth_label.setFixedWidth(100)
        depth_layout.addWidget(depth_label)
        
        self.depth_slider = QSlider(Qt.Orientation.Horizontal)
        self.depth_slider.setMinimum(1)
        self.depth_slider.setMaximum(5)
        self.depth_slider.setValue(2)
        self.depth_slider.setTickPosition(QSlider.TickPosition.TicksBelow)
        self.depth_slider.setTickInterval(1)
        self.depth_slider.setStyleSheet(self._slider_style())
        depth_layout.addWidget(self.depth_slider, stretch=1)
        
        self.depth_value_label = QLabel("2")
        self.depth_value_label.setFixedWidth(30)
        self.depth_value_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.depth_value_label.setStyleSheet(f"""
            QLabel {{
                background-color: {COLORS.bg_visual};
                color: {COLORS.orange};
                border-radius: 4px;
                padding: 2px 8px;
                font-weight: bold;
            }}
        """)
        depth_layout.addWidget(self.depth_value_label)
        
        hint = QLabel("(1=shallow, 5=deep)")
        hint.setStyleSheet(f"color: {COLORS.comment}; font-size: 11px;")
        depth_layout.addWidget(hint)
        
        settings_layout.addLayout(depth_layout)
        
        # Connect slider to label
        self.depth_slider.valueChanged.connect(
            lambda v: self.depth_value_label.setText(str(v))
        )
        
        # Max pages spinbox
        pages_layout = QHBoxLayout()
        pages_label = QLabel("Max Pages:")
        pages_label.setFixedWidth(100)
        pages_layout.addWidget(pages_label)
        
        self.pages_spinbox = QSpinBox()
        self.pages_spinbox.setMinimum(10)
        self.pages_spinbox.setMaximum(1000)
        self.pages_spinbox.setValue(50)
        self.pages_spinbox.setSingleStep(10)
        self.pages_spinbox.setFixedWidth(100)
        self.pages_spinbox.setStyleSheet(f"""
            QSpinBox {{
                background-color: {COLORS.bg_visual};
                color: {COLORS.fg};
                border: 1px solid {COLORS.terminal_black};
                border-radius: 6px;
                padding: 5px;
            }}
        """)
        pages_layout.addWidget(self.pages_spinbox)
        pages_layout.addStretch()
        
        settings_layout.addLayout(pages_layout)
        
        config_layout.addWidget(settings_group)
        
        # Options checkboxes
        options_group = QGroupBox(" Crawler Options")
        options_group.setStyleSheet(self._groupbox_style(COLORS.blue))
        options_layout = QHBoxLayout(options_group)
        
        self.follow_redirects_cb = QCheckBox("Follow redirects")
        self.follow_redirects_cb.setChecked(True)
        self.follow_redirects_cb.setStyleSheet(self._checkbox_style())
        options_layout.addWidget(self.follow_redirects_cb)
        
        self.respect_robots_cb = QCheckBox("Respect robots.txt")
        self.respect_robots_cb.setChecked(True)
        self.respect_robots_cb.setStyleSheet(self._checkbox_style())
        options_layout.addWidget(self.respect_robots_cb)
        
        self.extract_articles_cb = QCheckBox("Extract articles")
        self.extract_articles_cb.setChecked(True)
        self.extract_articles_cb.setStyleSheet(self._checkbox_style())
        options_layout.addWidget(self.extract_articles_cb)
        
        self.use_javascript_cb = QCheckBox("Use JavaScript")
        self.use_javascript_cb.setChecked(False)
        self.use_javascript_cb.setStyleSheet(self._checkbox_style())
        options_layout.addWidget(self.use_javascript_cb)
        
        options_layout.addStretch()
        
        config_layout.addWidget(options_group)
        
        # Advanced options
        advanced_group = QGroupBox(" Advanced Options")
        advanced_group.setStyleSheet(self._groupbox_style(COLORS.purple))
        advanced_layout = QHBoxLayout(advanced_group)
        
        self.dedup_cb = QCheckBox("Deduplicate content")
        self.dedup_cb.setChecked(True)
        self.dedup_cb.setStyleSheet(self._checkbox_style())
        advanced_layout.addWidget(self.dedup_cb)
        
        self.stay_domain_cb = QCheckBox("Stay on domain")
        self.stay_domain_cb.setChecked(True)
        self.stay_domain_cb.setStyleSheet(self._checkbox_style())
        advanced_layout.addWidget(self.stay_domain_cb)
        
        self.parse_sitemap_cb = QCheckBox("Parse sitemaps")
        self.parse_sitemap_cb.setChecked(True)
        self.parse_sitemap_cb.setStyleSheet(self._checkbox_style())
        advanced_layout.addWidget(self.parse_sitemap_cb)
        
        advanced_layout.addStretch()
        
        config_layout.addWidget(advanced_group)
        config_layout.addStretch()
        
        self.tab_widget.addTab(config_widget, "⚙️ Configuration")
    
    def _setup_progress_tab(self):
        """Setup the Progress & Stats tab"""
        progress_widget = QWidget()
        progress_layout = QVBoxLayout(progress_widget)
        progress_layout.setContentsMargins(20, 20, 20, 20)
        progress_layout.setSpacing(15)
        
        # Progress Section
        progress_group = QGroupBox(" Crawl Progress")
        progress_group.setStyleSheet(self._groupbox_style(COLORS.green))
        progress_vlayout = QVBoxLayout(progress_group)
        
        # Current URL display
        url_layout = QHBoxLayout()
        url_layout.addWidget(QLabel("Current URL:"))
        self.current_url_label = QLabel("Ready to start...")
        self.current_url_label.setStyleSheet(f"""
            QLabel {{
                color: {COLORS.cyan};
                font-family: {Fonts.MONO};
                font-size: 12px;
            }}
        """)
        self.current_url_label.setWordWrap(True)
        url_layout.addWidget(self.current_url_label, stretch=1)
        progress_vlayout.addLayout(url_layout)
        
        # Progress bar
        self.progress_bar = QProgressBar()
        self.progress_bar.setMinimum(0)
        self.progress_bar.setMaximum(100)
        self.progress_bar.setValue(0)
        self.progress_bar.setTextVisible(True)
        self.progress_bar.setFormat("%p%")
        self.progress_bar.setStyleSheet(f"""
            QProgressBar {{
                background-color: {COLORS.bg_dark};
                border: none;
                border-radius: 4px;
                height: 25px;
                text-align: center;
                color: {COLORS.fg};
                font-weight: bold;
            }}
            QProgressBar::chunk {{
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                    stop:0 {COLORS.blue}, stop:1 {COLORS.cyan});
                border-radius: 4px;
            }}
        """)
        progress_vlayout.addWidget(self.progress_bar)
        
        # Stats grid
        stats_layout = QHBoxLayout()
        
        # Pages crawled
        self.pages_stat = self._create_stat_card("📄 Pages Crawled", "0", COLORS.blue)
        stats_layout.addWidget(self.pages_stat)
        
        # Articles found
        self.articles_stat = self._create_stat_card("📰 Articles Found", "0", COLORS.green)
        stats_layout.addWidget(self.articles_stat)
        
        # Errors
        self.errors_stat = self._create_stat_card("❌ Errors", "0", COLORS.red)
        stats_layout.addWidget(self.errors_stat)
        
        progress_vlayout.addLayout(stats_layout)
        progress_layout.addWidget(progress_group)
        
        # Mini log for quick view
        mini_log_group = QGroupBox(" Activity Log (Recent)")
        mini_log_group.setStyleSheet(self._groupbox_style(COLORS.cyan))
        mini_log_layout = QVBoxLayout(mini_log_group)
        
        self.mini_log = ColoredLogTextEdit()
        self.mini_log.setMaximumHeight(150)
        mini_log_layout.addWidget(self.mini_log)
        
        progress_layout.addWidget(mini_log_group)
        progress_layout.addStretch()
        
        self.tab_widget.addTab(progress_widget, "📊 Progress")
    
    def _setup_log_tab(self):
        """Setup the full Log tab"""
        log_widget = QWidget()
        log_layout = QVBoxLayout(log_widget)
        log_layout.setContentsMargins(20, 20, 20, 20)
        log_layout.setSpacing(10)
        
        # Log controls
        controls_layout = QHBoxLayout()
        
        self.log_level_combo = QComboBox()
        self.log_level_combo.addItems(["All", "Info", "Success", "Warning", "Error", "Debug"])
        self.log_level_combo.setCurrentText("All")
        self.log_level_combo.setStyleSheet(f"""
            QComboBox {{
                background-color: {COLORS.bg_highlight};
                color: {COLORS.fg};
                border: 1px solid {COLORS.terminal_black};
                border-radius: 4px;
                padding: 5px 10px;
                min-width: 100px;
            }}
        """)
        controls_layout.addWidget(QLabel("Filter:"))
        controls_layout.addWidget(self.log_level_combo)
        
        controls_layout.addStretch()
        
        clear_btn = QPushButton("🗑 Clear")
        clear_btn.setObjectName("ghostButton")
        clear_btn.clicked.connect(self._clear_log)
        controls_layout.addWidget(clear_btn)
        
        save_btn = QPushButton("💾 Save Log")
        save_btn.setObjectName("secondaryButton")
        save_btn.clicked.connect(self._save_log)
        controls_layout.addWidget(save_btn)
        
        log_layout.addLayout(controls_layout)
        
        # Full log text area
        self.full_log = ColoredLogTextEdit()
        log_layout.addWidget(self.full_log)
        
        self.tab_widget.addTab(log_widget, "📜 Log")
    
    def _setup_results_tab(self):
        """Setup the Results tab with article table"""
        results_widget = QWidget()
        results_layout = QVBoxLayout(results_widget)
        results_layout.setContentsMargins(20, 20, 20, 20)
        results_layout.setSpacing(10)
        
        # Results controls
        controls_layout = QHBoxLayout()
        
        self.results_count_label = QLabel("Found: 0 articles")
        self.results_count_label.setStyleSheet(f"color: {COLORS.cyan}; font-weight: bold;")
        controls_layout.addWidget(self.results_count_label)
        
        controls_layout.addStretch()
        
        export_btn = QPushButton("📤 Export Results")
        export_btn.setObjectName("secondaryButton")
        export_btn.clicked.connect(self._export_results)
        controls_layout.addWidget(export_btn)
        
        clear_results_btn = QPushButton("🗑 Clear")
        clear_results_btn.setObjectName("ghostButton")
        clear_results_btn.clicked.connect(self._clear_results)
        controls_layout.addWidget(clear_results_btn)
        
        results_layout.addLayout(controls_layout)
        
        # Results table
        self.results_table = QTableWidget()
        self.results_table.setColumnCount(5)
        self.results_table.setHorizontalHeaderLabels([
            "Title", "Source", "URL", "Score", "Published"
        ])
        
        # Style the table
        self.results_table.setStyleSheet(f"""
            QTableWidget {{
                background-color: {COLORS.bg_highlight};
                color: {COLORS.fg};
                border: 1px solid {COLORS.terminal_black};
                border-radius: 6px;
                gridline-color: {COLORS.terminal_black};
            }}
            QTableWidget::item {{
                padding: 8px;
                border-bottom: 1px solid {COLORS.terminal_black};
            }}
            QTableWidget::item:selected {{
                background-color: {COLORS.bg_visual};
                color: {COLORS.fg};
            }}
            QHeaderView::section {{
                background-color: {COLORS.bg_dark};
                color: {COLORS.cyan};
                padding: 10px;
                border: none;
                border-right: 1px solid {COLORS.terminal_black};
                border-bottom: 2px solid {COLORS.cyan};
                font-weight: bold;
            }}
        """)
        
        # Set column widths
        header = self.results_table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)  # Title
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)  # Source
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)  # URL
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)  # Score
        header.setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)  # Published
        
        self.results_table.setAlternatingRowColors(True)
        self.results_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.results_table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        
        results_layout.addWidget(self.results_table)
        
        self.tab_widget.addTab(results_widget, "📋 Results")
    
    def _create_footer(self) -> QFrame:
        """Create the footer with control buttons"""
        footer = QFrame()
        footer.setObjectName("statsFrame")
        footer.setFixedHeight(70)
        footer.setStyleSheet(f"""
            QFrame {{
                background-color: {COLORS.bg_highlight};
                border-top: 1px solid {COLORS.terminal_black};
            }}
        """)
        
        layout = QHBoxLayout(footer)
        layout.setContentsMargins(20, 10, 20, 10)
        
        # Control buttons
        self.start_btn = QPushButton("▶ Start Crawl")
        self.start_btn.setObjectName("primaryButton")
        self.start_btn.setFixedHeight(45)
        self.start_btn.setMinimumWidth(140)
        self.start_btn.clicked.connect(self._start_crawl)
        layout.addWidget(self.start_btn)
        
        self.pause_btn = QPushButton("⏸ Pause")
        self.pause_btn.setObjectName("cyanButton")
        self.pause_btn.setFixedHeight(45)
        self.pause_btn.setMinimumWidth(100)
        self.pause_btn.setEnabled(False)
        self.pause_btn.clicked.connect(self._pause_crawl)
        layout.addWidget(self.pause_btn)
        
        self.stop_btn = QPushButton("⏹ Stop")
        self.stop_btn.setObjectName("orangeButton")
        self.stop_btn.setFixedHeight(45)
        self.stop_btn.setMinimumWidth(100)
        self.stop_btn.setEnabled(False)
        self.stop_btn.clicked.connect(self._stop_crawl)
        layout.addWidget(self.stop_btn)
        
        layout.addStretch()
        
        self.close_btn = QPushButton("✕ Close")
        self.close_btn.setObjectName("dangerButton")
        self.close_btn.setFixedHeight(45)
        self.close_btn.setMinimumWidth(100)
        self.close_btn.clicked.connect(self._close_dialog)
        layout.addWidget(self.close_btn)
        
        return footer
    
    def _create_stat_card(self, title: str, value: str, color: str) -> QFrame:
        """Create a stat card widget"""
        card = QFrame()
        card.setStyleSheet(f"""
            QFrame {{
                background-color: {COLORS.bg_visual};
                border-radius: 8px;
                border: 1px solid {COLORS.terminal_black};
                padding: 10px;
            }}
        """)
        
        layout = QVBoxLayout(card)
        layout.setSpacing(5)
        
        title_label = QLabel(title)
        title_label.setStyleSheet(f"color: {COLORS.comment}; font-size: 12px;")
        layout.addWidget(title_label)
        
        value_label = QLabel(value)
        value_label.setStyleSheet(f"""
            QLabel {{
                color: {color};
                font-size: 24px;
                font-weight: bold;
            }}
        """)
        layout.addWidget(value_label)
        
        # Store reference to value label for updates
        card.value_label = value_label
        
        return card
    
    def _apply_styles(self):
        """Apply additional custom styles"""
        self.setStyleSheet(f"""
            QDialog {{
                background-color: {COLORS.bg};
            }}
            QTabWidget::pane {{
                border: none;
                background-color: {COLORS.bg};
            }}
        """)
    
    def _groupbox_style(self, color: str) -> str:
        """Generate QGroupBox style with accent color"""
        return f"""
            QGroupBox {{
                background-color: {COLORS.bg_highlight};
                border: 1px solid {COLORS.terminal_black};
                border-radius: 8px;
                margin-top: 12px;
                padding-top: 8px;
                padding: 15px;
                font-weight: bold;
            }}
            QGroupBox::title {{
                subcontrol-origin: margin;
                subcontrol-position: top left;
                left: 10px;
                padding: 0 6px;
                color: {color};
            }}
        """
    
    def _checkbox_style(self) -> str:
        """Generate checkbox style"""
        return f"""
            QCheckBox {{
                color: {COLORS.fg};
                spacing: 8px;
            }}
            QCheckBox::indicator {{
                width: 18px;
                height: 18px;
                border-radius: 3px;
                border: 1px solid {COLORS.terminal_black};
                background-color: {COLORS.bg_visual};
            }}
            QCheckBox::indicator:checked {{
                background-color: {COLORS.blue};
                border: 1px solid {COLORS.blue};
            }}
            QCheckBox::indicator:hover {{
                border: 1px solid {COLORS.comment};
            }}
        """
    
    def _slider_style(self) -> str:
        """Generate slider style"""
        return f"""
            QSlider::groove:horizontal {{
                background-color: {COLORS.bg_dark};
                height: 8px;
                border-radius: 4px;
            }}
            QSlider::handle:horizontal {{
                background-color: {COLORS.orange};
                width: 18px;
                height: 18px;
                margin: -5px 0;
                border-radius: 9px;
            }}
            QSlider::handle:horizontal:hover {{
                background-color: {COLORS.yellow};
            }}
            QSlider::sub-page:horizontal {{
                background-color: {COLORS.orange};
                border-radius: 4px;
            }}
        """
    
    def _connect_signals(self):
        """Connect internal signals"""
        self.progress_updated.connect(self._update_progress)
        self.log_message.connect(self._add_log_message)
    
    # ═════════════════════════════════════════════════════════════════
    # CRAWL OPERATIONS
    # ═════════════════════════════════════════════════════════════════
    
    def _start_crawl(self):
        """Start the web crawling operation"""
        if self._is_running:
            return
        
        # Get URLs
        urls_text = self.url_text.toPlainText().strip()
        urls = [url.strip() for url in urls_text.split('\n') if url.strip()]
        
        if not urls:
            QMessageBox.warning(self, "No URLs", "Please enter at least one seed URL")
            return
        
        # Validate URLs
        valid_urls = []
        for url in urls:
            if not url.startswith(('http://', 'https://')):
                url = 'https://' + url
            valid_urls.append(url)
        
        # Update UI state
        self._is_running = True
        self._is_paused = False
        self._found_articles.clear()
        self._current_stats = {
            "pages_crawled": 0,
            "articles_found": 0,
            "errors": 0,
            "current_url": ""
        }
        
        self.start_btn.setEnabled(False)
        self.start_btn.setText("🕷️ Crawling...")
        self.pause_btn.setEnabled(True)
        self.stop_btn.setEnabled(True)
        
        self.status_label.setText("Running")
        self.status_label.setStyleSheet(f"""
            QLabel {{
                font-size: 14px;
                font-weight: bold;
                color: {COLORS.black};
                padding: 5px 15px;
                background-color: {COLORS.orange};
                border-radius: 15px;
            }}
        """)
        
        # Clear previous results
        self.results_table.setRowCount(0)
        self.progress_bar.setValue(0)
        self._update_stats_display()
        
        # Log start
        self._log("🚀 Starting crawler...", "info")
        self._log(f"📍 Seed URLs: {len(valid_urls)}", "info")
        self._log(f"⚙️ Max depth: {self.depth_slider.value()}, Max pages: {self.pages_spinbox.value()}", "info")
        
        # Switch to progress tab
        self.tab_widget.setCurrentIndex(1)
        
        # Start crawl in async task
        if self._orchestrator:
            self._run_crawl_async(valid_urls)
        else:
            self._log("❌ No orchestrator available - running in demo mode", "warning")
            self._simulate_crawl(valid_urls)
    
    def _run_crawl_async(self, urls: List[str]):
        """Run the actual crawl using the orchestrator"""
        import threading
        
        async def do_crawl():
            try:
                results = []
                total_pages = self.pages_spinbox.value()
                
                for i, url in enumerate(urls):
                    if not self._is_running:
                        break
                    
                    if self._is_paused:
                        while self._is_paused and self._is_running:
                            await asyncio.sleep(0.5)
                    
                    self._current_stats["current_url"] = url
                    self.current_url_label.setText(url[:80] + "..." if len(url) > 80 else url)
                    
                    self._log(f"🕷️ Crawling {url}...", "crawl")
                    
                    try:
                        articles = await self._orchestrator.crawl_website(
                            url=url,
                            max_depth=self.depth_slider.value(),
                            max_pages=self.pages_spinbox.value(),
                            progress_callback=self._on_progress
                        )
                        
                        results.extend(articles)
                        self._current_stats["articles_found"] += len(articles)
                        self._current_stats["pages_crawled"] += 1
                        
                        self._log(f"  ✓ Found {len(articles)} articles", "success")
                        
                        # Add to results table
                        for article in articles:
                            self._add_article_to_table(article)
                        
                    except Exception as e:
                        self._current_stats["errors"] += 1
                        self._log(f"  ✗ Error: {str(e)}", "error")
                    
                    self._update_stats_display()
                    
                return results
                
            except Exception as e:
                self._log(f"❌ Crawl error: {str(e)}", "error")
                raise
        
        def on_complete(articles, error):
            self._is_running = False
            self.start_btn.setEnabled(True)
            self.start_btn.setText("▶ Start Crawl")
            self.pause_btn.setEnabled(False)
            self.stop_btn.setEnabled(False)
            
            if error:
                self.status_label.setText("Failed")
                self.status_label.setStyleSheet(f"""
                    QLabel {{
                        font-size: 14px;
                        font-weight: bold;
                        color: {COLORS.black};
                        padding: 5px 15px;
                        background-color: {COLORS.red};
                        border-radius: 15px;
                    }}
                """)
                self._log(f"❌ Crawl failed: {str(error)}", "error")
                QMessageBox.critical(self, "Crawl Error", str(error))
            else:
                self.status_label.setText("Complete")
                self.status_label.setStyleSheet(f"""
                    QLabel {{
                        font-size: 14px;
                        font-weight: bold;
                        color: {COLORS.black};
                        padding: 5px 15px;
                        background-color: {COLORS.green};
                        border-radius: 15px;
                    }}
                """)
                self.progress_bar.setValue(100)
                self._log(f"✅ Crawl complete! Found {len(articles)} total articles", "success")
                self.crawl_completed.emit(articles)
        
        # Use threading for async execution
        def run_in_thread():
            try:
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                articles = loop.run_until_complete(do_crawl())
                on_complete(articles, None)
            except Exception as e:
                on_complete([], e)
        
        thread = threading.Thread(target=run_in_thread, daemon=True)
        thread.start()
    
    def _simulate_crawl(self, urls: List[str]):
        """Simulate a crawl for demo purposes when no orchestrator is available"""
        import random
        import threading
        import time
        
        def simulate():
            total_pages = self.pages_spinbox.value()
            
            for i in range(min(len(urls) * 3, total_pages)):
                if not self._is_running:
                    break
                
                if self._is_paused:
                    while self._is_paused and self._is_running:
                        time.sleep(0.5)
                
                url = urls[i % len(urls)]
                self._current_stats["current_url"] = url
                self.current_url_label.setText(f"{url}/page-{i+1}")
                
                # Simulate finding articles
                articles_found = random.randint(0, 5)
                self._current_stats["articles_found"] += articles_found
                self._current_stats["pages_crawled"] += 1
                
                if random.random() < 0.1:  # 10% error rate
                    self._current_stats["errors"] += 1
                    self._log(f"⚠ Error on page {i+1}", "warning")
                else:
                    self._log(f"✓ Processed page {i+1}, found {articles_found} articles", "success")
                    
                    # Add dummy articles to table
                    for j in range(articles_found):
                        dummy_article = {
                            'title': f'Article {i}-{j} - Sample Tech News',
                            'source': 'techcrunch.com',
                            'url': f'{url}/article-{j}',
                            'score': random.uniform(5.0, 9.5),
                            'published': datetime.now().isoformat()
                        }
                        self._add_article_to_table(dummy_article)
                
                self._update_stats_display()
                
                # Update progress
                progress = int((i + 1) / total_pages * 100)
                self.progress_bar.setValue(progress)
                
                time.sleep(0.5)  # Simulate work
            
            self._is_running = False
            self.start_btn.setEnabled(True)
            self.start_btn.setText("▶ Start Crawl")
            self.pause_btn.setEnabled(False)
            self.stop_btn.setEnabled(False)
            
            self.status_label.setText("Complete")
            self.status_label.setStyleSheet(f"""
                QLabel {{
                    font-size: 14px;
                    font-weight: bold;
                    color: {COLORS.black};
                    padding: 5px 15px;
                    background-color: {COLORS.green};
                    border-radius: 15px;
                }}
            """)
            self.progress_bar.setValue(100)
            self._log(f"✅ Demo crawl complete! Found {self._current_stats['articles_found']} articles", "success")
        
        thread = threading.Thread(target=simulate, daemon=True)
        thread.start()
    
    def _pause_crawl(self):
        """Pause/resume the crawl"""
        if not self._is_running:
            return
        
        self._is_paused = not self._is_paused
        
        if self._is_paused:
            self.pause_btn.setText("▶ Resume")
            self.status_label.setText("Paused")
            self.status_label.setStyleSheet(f"""
                QLabel {{
                    font-size: 14px;
                    font-weight: bold;
                    color: {COLORS.black};
                    padding: 5px 15px;
                    background-color: {COLORS.yellow};
                    border-radius: 15px;
                }}
            """)
            self._log("⏸ Crawl paused", "warning")
        else:
            self.pause_btn.setText("⏸ Pause")
            self.status_label.setText("Running")
            self.status_label.setStyleSheet(f"""
                QLabel {{
                    font-size: 14px;
                    font-weight: bold;
                    color: {COLORS.black};
                    padding: 5px 15px;
                    background-color: {COLORS.orange};
                    border-radius: 15px;
                }}
            """)
            self._log("▶ Crawl resumed", "info")
    
    def _stop_crawl(self):
        """Stop the crawl operation"""
        if not self._is_running:
            return
        
        reply = QMessageBox.question(
            self,
            "Stop Crawl",
            "Are you sure you want to stop the crawl?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No
        )
        
        if reply == QMessageBox.Yes:
            self._is_running = False
            self._is_paused = False
            self._log("⏹ Stopping crawl...", "warning")
            
            self.start_btn.setEnabled(True)
            self.start_btn.setText("▶ Start Crawl")
            self.pause_btn.setEnabled(False)
            self.pause_btn.setText("⏸ Pause")
            self.stop_btn.setEnabled(False)
            
            self.status_label.setText("Stopped")
            self.status_label.setStyleSheet(f"""
                QLabel {{
                    font-size: 14px;
                    font-weight: bold;
                    color: {COLORS.black};
                    padding: 5px 15px;
                    background-color: {COLORS.red};
                    border-radius: 15px;
                }}
            """)
    
    def _on_progress(self, current: int, total: int):
        """Handle progress callback from orchestrator"""
        self.progress_updated.emit(current, total)
    
    def _update_progress(self, current: int, total: int):
        """Update progress bar"""
        if total > 0:
            progress = int((current / total) * 100)
            self.progress_bar.setValue(progress)
    
    def _log(self, message: str, level: str = "info"):
        """Add log message to both logs"""
        self.log_message.emit(message, level)
    
    def _add_log_message(self, message: str, level: str):
        """Add message to log displays"""
        self.mini_log.append_colored(message, level)
        self.full_log.append_colored(message, level)
    
    def _update_stats_display(self):
        """Update the stat cards"""
        self.pages_stat.value_label.setText(str(self._current_stats["pages_crawled"]))
        self.articles_stat.value_label.setText(str(self._current_stats["articles_found"]))
        self.errors_stat.value_label.setText(str(self._current_stats["errors"]))
        self.results_count_label.setText(f"Found: {self._current_stats['articles_found']} articles")
    
    def _add_article_to_table(self, article):
        """Add an article to the results table"""
        row = self.results_table.rowCount()
        self.results_table.insertRow(row)
        
        # Title
        title_item = QTableWidgetItem(article.get('title', 'Unknown')[:60])
        title_item.setToolTip(article.get('title', ''))
        self.results_table.setItem(row, 0, title_item)
        
        # Source
        source_item = QTableWidgetItem(article.get('source', 'Unknown'))
        self.results_table.setItem(row, 1, source_item)
        
        # URL
        url = article.get('url', '')
        url_item = QTableWidgetItem(url[:50] + "..." if len(url) > 50 else url)
        url_item.setToolTip(url)
        self.results_table.setItem(row, 2, url_item)
        
        # Score
        score = article.get('score', 0)
        score_item = QTableWidgetItem(f"{score:.1f}")
        
        # Color code by score
        if score >= 8.0:
            score_item.setForeground(QColor(COLORS.green))
        elif score >= 6.0:
            score_item.setForeground(QColor(COLORS.blue))
        elif score >= 4.0:
            score_item.setForeground(QColor(COLORS.yellow))
        else:
            score_item.setForeground(QColor(COLORS.red))
        
        score_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
        self.results_table.setItem(row, 3, score_item)
        
        # Published
        published = article.get('published', '')
        if isinstance(published, str):
            try:
                from datetime import datetime
                dt = datetime.fromisoformat(published.replace('Z', '+00:00'))
                published = dt.strftime("%Y-%m-%d")
            except Exception as e:
                logger.debug(f"_add_article_to_table: could not parse published date {published!r}: {e}")
        pub_item = QTableWidgetItem(str(published)[:10])
        self.results_table.setItem(row, 4, pub_item)
        
        # Scroll to new row
        self.results_table.scrollToBottom()
    
    def _clear_log(self):
        """Clear the full log"""
        self.full_log.clear()
        self._log("Log cleared", "info")
    
    def _save_log(self):
        """Save log to file"""
        from PyQt6.QtWidgets import QFileDialog
        
        filename, _ = QFileDialog.getSaveFileName(
            self,
            "Save Log",
            "crawler_log.txt",
            "Text Files (*.txt);;All Files (*)"
        )
        
        if filename:
            try:
                with open(filename, 'w', encoding='utf-8') as f:
                    f.write(self.full_log.toPlainText())
                self._log(f"✓ Log saved to {filename}", "success")
            except Exception as e:
                QMessageBox.critical(self, "Error", f"Failed to save log: {str(e)}")
    
    def _clear_results(self):
        """Clear results table"""
        reply = QMessageBox.question(
            self,
            "Clear Results",
            "Are you sure you want to clear all results?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No
        )
        
        if reply == QMessageBox.Yes:
            self.results_table.setRowCount(0)
            self._current_stats["articles_found"] = 0
            self._update_stats_display()
            self._log("Results cleared", "info")
    
    def _export_results(self):
        """Export results to file"""
        from PyQt6.QtWidgets import QFileDialog
        
        filename, _ = QFileDialog.getSaveFileName(
            self,
            "Export Results",
            "crawler_results.json",
            "JSON Files (*.json);;CSV Files (*.csv);;All Files (*)"
        )
        
        if filename:
            try:
                if filename.endswith('.json'):
                    import json
                    with open(filename, 'w', encoding='utf-8') as f:
                        json.dump(self._found_articles, f, indent=2)
                elif filename.endswith('.csv'):
                    import csv
                    with open(filename, 'w', newline='', encoding='utf-8') as f:
                        writer = csv.writer(f)
                        writer.writerow(['Title', 'Source', 'URL', 'Score', 'Published'])
                        for article in self._found_articles:
                            writer.writerow([
                                article.get('title', ''),
                                article.get('source', ''),
                                article.get('url', ''),
                                article.get('score', 0),
                                article.get('published', '')
                            ])
                
                self._log(f"✓ Results exported to {filename}", "success")
            except Exception as e:
                QMessageBox.critical(self, "Error", f"Failed to export results: {str(e)}")
    
    def _close_dialog(self):
        """Handle close button"""
        if self._is_running:
            reply = QMessageBox.question(
                self,
                "Crawl in Progress",
                "A crawl is still running. Stop and close?",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No
            )
            
            if reply == QMessageBox.No:
                return
            
            self._is_running = False
        
        self.close()
    
    def closeEvent(self, event):
        """Handle dialog close event"""
        if self._is_running:
            reply = QMessageBox.question(
                self,
                "Crawl in Progress",
                "A crawl is still running. Stop and close?",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No
            )
            
            if reply == QMessageBox.No:
                event.ignore()
                return
            
            self._is_running = False
        
        event.accept()
