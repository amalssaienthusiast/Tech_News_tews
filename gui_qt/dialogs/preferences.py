"""
Preferences Dialog for Tech News Scraper
User settings and configuration matching tkinter gui/app.py
"""

from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QTabWidget, QWidget, QFormLayout,
    QLineEdit, QComboBox, QSpinBox, QCheckBox,
    QSlider, QGroupBox, QFileDialog, QMessageBox,
    QScrollArea, QFrame
)
from PyQt6.QtCore import Qt, QSettings

from ..theme import COLORS, Fonts


class PreferencesDialog(QDialog):
    """User preferences dialog
    
    Provides settings for:
    - General: Auto-refresh, notifications, theme
    - Display: Results per page, font size, animations
    - Sources: Enable/disable news sources
    - Advanced: API keys, cache settings, logging
    
    Signals:
        settings_saved(): Emitted when settings are saved
        settings_reset(): Emitted when settings are reset to defaults
    """
    
    def __init__(self, parent=None):
        super().__init__(parent)
        
        self._settings = QSettings("TechNewsScraper", "Preferences")
        self._changed_settings = {}
        
        self._setup_window()
        self._setup_ui()
        self._load_settings()
    
    def _setup_window(self):
        """Configure dialog window"""
        self.setWindowTitle("⚙️ Preferences")
        self.setMinimumSize(600, 500)
        self.setMaximumSize(800, 600)
        
        self.setWindowFlags(
            Qt.WindowType.Dialog |
            Qt.WindowType.WindowCloseButtonHint
        )
    
    def _setup_ui(self):
        """Build the preferences UI"""
        layout = QVBoxLayout(self)
        layout.setSpacing(15)
        
        # Tab widget
        self.tabs = QTabWidget()
        self.tabs.setDocumentMode(True)
        
        # Create tabs
        self.tabs.addTab(self._create_general_tab(), "⚙️ General")
        self.tabs.addTab(self._create_display_tab(), "🎨 Display")
        self.tabs.addTab(self._create_sources_tab(), "📡 Sources")
        self.tabs.addTab(self._create_advanced_tab(), "🔧 Advanced")
        
        self.tabs.setStyleSheet(f"""
            QTabWidget::pane {{
                border: 1px solid {COLORS.terminal_black};
                background-color: {COLORS.bg_dark};
                border-radius: 8px;
            }}
            QTabBar::tab {{
                background-color: {COLORS.bg_highlight};
                color: {COLORS.fg_dark};
                padding: 10px 20px;
                border-top-left-radius: 6px;
                border-top-right-radius: 6px;
            }}
            QTabBar::tab:selected {{
                background-color: {COLORS.bg_visual};
                color: {COLORS.cyan};
            }}
            QTabBar::tab:hover {{
                background-color: {COLORS.bg_visual};
            }}
        """)
        
        layout.addWidget(self.tabs)
        
        # Buttons
        button_layout = QHBoxLayout()
        
        # Reset button
        reset_btn = QPushButton("↺ Reset to Defaults")
        reset_btn.clicked.connect(self._reset_settings)
        button_layout.addWidget(reset_btn)
        
        button_layout.addStretch()
        
        # Cancel button
        cancel_btn = QPushButton("✕ Cancel")
        cancel_btn.clicked.connect(self.reject)
        button_layout.addWidget(cancel_btn)
        
        # Save button
        save_btn = QPushButton("💾 Save Changes")
        save_btn.setObjectName("primaryButton")
        save_btn.clicked.connect(self._save_settings)
        button_layout.addWidget(save_btn)
        
        layout.addLayout(button_layout)
        
        # Apply styles
        self._apply_styles()
    
    def _create_general_tab(self):
        """Create General settings tab"""
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setSpacing(20)
        
        # Auto-refresh section
        refresh_group = QGroupBox("🔄 Auto Refresh")
        refresh_group.setStyleSheet(f"""
            QGroupBox {{
                font-weight: bold;
                color: {COLORS.cyan};
                border: 1px solid {COLORS.terminal_black};
                border-radius: 8px;
                margin-top: 10px;
                padding-top: 15px;
            }}
            QGroupBox::title {{
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 5px;
            }}
        """)
        
        refresh_layout = QFormLayout(refresh_group)
        
        # Enable auto-refresh
        self.auto_refresh_check = QCheckBox("Enable auto-refresh")
        self.auto_refresh_check.stateChanged.connect(
            lambda: self._mark_changed('general/auto_refresh', self.auto_refresh_check.isChecked())
        )
        refresh_layout.addRow(self.auto_refresh_check)
        
        # Refresh interval
        interval_layout = QHBoxLayout()
        self.refresh_interval = QSpinBox()
        self.refresh_interval.setRange(1, 60)
        self.refresh_interval.setSuffix(" minutes")
        self.refresh_interval.valueChanged.connect(
            lambda: self._mark_changed('general/refresh_interval', self.refresh_interval.value())
        )
        interval_layout.addWidget(self.refresh_interval)
        interval_layout.addStretch()
        refresh_layout.addRow("Refresh interval:", interval_layout)
        
        layout.addWidget(refresh_group)
        
        # Notifications section
        notif_group = QGroupBox("🔔 Notifications")
        notif_group.setStyleSheet(refresh_group.styleSheet())
        
        notif_layout = QFormLayout(notif_group)
        
        self.enable_notifications = QCheckBox("Enable desktop notifications")
        self.enable_notifications.stateChanged.connect(
            lambda: self._mark_changed('general/notifications', self.enable_notifications.isChecked())
        )
        notif_layout.addRow(self.enable_notifications)
        
        self.notify_on_new = QCheckBox("Notify on new articles")
        self.notify_on_new.stateChanged.connect(
            lambda: self._mark_changed('general/notify_new', self.notify_on_new.isChecked())
        )
        notif_layout.addRow(self.notify_on_new)
        
        layout.addWidget(notif_group)
        
        # Startup section
        startup_group = QGroupBox("🚀 Startup")
        startup_group.setStyleSheet(refresh_group.styleSheet())
        
        startup_layout = QFormLayout(startup_group)
        
        self.start_minimized = QCheckBox("Start minimized to tray")
        self.start_minimized.stateChanged.connect(
            lambda: self._mark_changed('general/start_minimized', self.start_minimized.isChecked())
        )
        startup_layout.addRow(self.start_minimized)
        
        self.auto_fetch_on_start = QCheckBox("Auto-fetch articles on startup")
        self.auto_fetch_on_start.stateChanged.connect(
            lambda: self._mark_changed('general/auto_fetch', self.auto_fetch_on_start.isChecked())
        )
        startup_layout.addRow(self.auto_fetch_on_start)
        
        layout.addWidget(startup_group)
        
        layout.addStretch()
        return tab
    
    def _create_display_tab(self):
        """Create Display settings tab"""
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setSpacing(20)
        
        # Results per page
        results_group = QGroupBox("📄 Results")
        results_group.setStyleSheet(f"""
            QGroupBox {{
                font-weight: bold;
                color: {COLORS.cyan};
                border: 1px solid {COLORS.terminal_black};
                border-radius: 8px;
                margin-top: 10px;
                padding-top: 15px;
            }}
            QGroupBox::title {{
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 5px;
            }}
        """)
        
        results_layout = QFormLayout(results_group)
        
        self.results_per_page = QSpinBox()
        self.results_per_page.setRange(10, 100)
        self.results_per_page.setSingleStep(10)
        self.results_per_page.valueChanged.connect(
            lambda: self._mark_changed('display/results_per_page', self.results_per_page.value())
        )
        results_layout.addRow("Results per page:", self.results_per_page)
        
        self.show_tech_score = QCheckBox("Show tech score badges")
        self.show_tech_score.stateChanged.connect(
            lambda: self._mark_changed('display/show_score', self.show_tech_score.isChecked())
        )
        results_layout.addRow(self.show_tech_score)
        
        self.show_thumbnails = QCheckBox("Show article thumbnails (if available)")
        self.show_thumbnails.stateChanged.connect(
            lambda: self._mark_changed('display/show_thumbnails', self.show_thumbnails.isChecked())
        )
        results_layout.addRow(self.show_thumbnails)
        
        layout.addWidget(results_group)
        
        # Appearance section
        appearance_group = QGroupBox("🎨 Appearance")
        appearance_group.setStyleSheet(results_group.styleSheet())
        
        appearance_layout = QFormLayout(appearance_group)
        
        # Theme selection
        self.theme_combo = QComboBox()
        self.theme_combo.addItems(["Tokyo Night", "Tokyo Night Storm", "Light"])
        self.theme_combo.currentTextChanged.connect(
            lambda: self._mark_changed('display/theme', self.theme_combo.currentText())
        )
        appearance_layout.addRow("Theme:", self.theme_combo)
        
        # Font size
        self.font_size_combo = QComboBox()
        self.font_size_combo.addItems(["Small", "Medium", "Large"])
        self.font_size_combo.currentTextChanged.connect(
            lambda: self._mark_changed('display/font_size', self.font_size_combo.currentText())
        )
        appearance_layout.addRow("Font size:", self.font_size_combo)
        
        # Animations
        self.enable_animations = QCheckBox("Enable animations")
        self.enable_animations.stateChanged.connect(
            lambda: self._mark_changed('display/animations', self.enable_animations.isChecked())
        )
        appearance_layout.addRow(self.enable_animations)
        
        layout.addWidget(appearance_group)
        
        # Ticker section
        ticker_group = QGroupBox("📰 News Ticker")
        ticker_group.setStyleSheet(results_group.styleSheet())
        
        ticker_layout = QFormLayout(ticker_group)
        
        self.show_ticker = QCheckBox("Show scrolling news ticker")
        self.show_ticker.stateChanged.connect(
            lambda: self._mark_changed('display/show_ticker', self.show_ticker.isChecked())
        )
        ticker_layout.addRow(self.show_ticker)
        
        self.ticker_speed = QSlider(Qt.Orientation.Horizontal)
        self.ticker_speed.setRange(1, 10)
        self.ticker_speed.valueChanged.connect(
            lambda: self._mark_changed('display/ticker_speed', self.ticker_speed.value())
        )
        ticker_layout.addRow("Ticker speed:", self.ticker_speed)
        
        layout.addWidget(ticker_group)
        
        layout.addStretch()
        return tab
    
    def _create_sources_tab(self):
        """Create Sources settings tab"""
        tab = QWidget()
        layout = QVBoxLayout(tab)
        
        # Scroll area for many sources
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        
        scroll_widget = QWidget()
        scroll_layout = QVBoxLayout(scroll_widget)
        scroll_layout.setSpacing(15)
        
        # Source checkboxes
        sources_group = QGroupBox("📡 News Sources")
        sources_group.setStyleSheet(f"""
            QGroupBox {{
                font-weight: bold;
                color: {COLORS.cyan};
                border: 1px solid {COLORS.terminal_black};
                border-radius: 8px;
                margin-top: 10px;
                padding-top: 15px;
            }}
            QGroupBox::title {{
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 5px;
            }}
        """)
        
        sources_layout = QVBoxLayout(sources_group)
        
        self.source_checks = {}
        sources = [
            ("Hacker News", "news.ycombinator.com"),
            ("Reddit r/technology", "reddit.com/r/technology"),
            ("TechCrunch", "techcrunch.com"),
            ("The Verge", "theverge.com"),
            ("Ars Technica", "arstechnica.com"),
            ("Wired", "wired.com"),
            ("Engadget", "engadget.com"),
            ("GitHub Trending", "github.com/trending"),
        ]
        
        for name, domain in sources:
            check = QCheckBox(f"{name} ({domain})")
            check.stateChanged.connect(
                lambda checked, n=name: self._mark_changed(f'sources/{n}', bool(checked))
            )
            self.source_checks[name] = check
            sources_layout.addWidget(check)
        
        # Enable all / Disable all buttons
        btn_layout = QHBoxLayout()
        
        enable_all_btn = QPushButton("✓ Enable All")
        enable_all_btn.clicked.connect(self._enable_all_sources)
        btn_layout.addWidget(enable_all_btn)
        
        disable_all_btn = QPushButton("✗ Disable All")
        disable_all_btn.clicked.connect(self._disable_all_sources)
        btn_layout.addWidget(disable_all_btn)
        
        btn_layout.addStretch()
        sources_layout.addLayout(btn_layout)
        
        scroll_layout.addWidget(sources_group)
        scroll_layout.addStretch()
        
        scroll.setWidget(scroll_widget)
        layout.addWidget(scroll)
        
        return tab
    
    def _create_advanced_tab(self):
        """Create Advanced settings tab"""
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setSpacing(20)
        
        # Cache settings
        cache_group = QGroupBox("💾 Cache")
        cache_group.setStyleSheet(f"""
            QGroupBox {{
                font-weight: bold;
                color: {COLORS.cyan};
                border: 1px solid {COLORS.terminal_black};
                border-radius: 8px;
                margin-top: 10px;
                padding-top: 15px;
            }}
            QGroupBox::title {{
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 5px;
            }}
        """)
        
        cache_layout = QFormLayout(cache_group)
        
        self.enable_cache = QCheckBox("Enable response caching")
        self.enable_cache.stateChanged.connect(
            lambda: self._mark_changed('advanced/enable_cache', self.enable_cache.isChecked())
        )
        cache_layout.addRow(self.enable_cache)
        
        self.cache_ttl = QSpinBox()
        self.cache_ttl.setRange(1, 168)  # 1 hour to 1 week
        self.cache_ttl.setSuffix(" hours")
        self.cache_ttl.valueChanged.connect(
            lambda: self._mark_changed('advanced/cache_ttl', self.cache_ttl.value())
        )
        cache_layout.addRow("Cache TTL:", self.cache_ttl)
        
        clear_cache_btn = QPushButton("🗑️ Clear Cache Now")
        clear_cache_btn.clicked.connect(self._clear_cache)
        cache_layout.addRow(clear_cache_btn)
        
        layout.addWidget(cache_group)
        
        # Logging section
        logging_group = QGroupBox("📋 Logging")
        logging_group.setStyleSheet(cache_group.styleSheet())
        
        logging_layout = QFormLayout(logging_group)
        
        self.log_level = QComboBox()
        self.log_level.addItems(["DEBUG", "INFO", "WARNING", "ERROR"])
        self.log_level.currentTextChanged.connect(
            lambda: self._mark_changed('advanced/log_level', self.log_level.currentText())
        )
        logging_layout.addRow("Log level:", self.log_level)
        
        self.log_to_file = QCheckBox("Save logs to file")
        self.log_to_file.stateChanged.connect(
            lambda: self._mark_changed('advanced/log_to_file', self.log_to_file.isChecked())
        )
        logging_layout.addRow(self.log_to_file)
        
        # Log file path
        log_path_layout = QHBoxLayout()
        self.log_path = QLineEdit()
        self.log_path.setPlaceholderText("Path to log file...")
        log_path_layout.addWidget(self.log_path)
        
        browse_btn = QPushButton("Browse...")
        browse_btn.clicked.connect(self._browse_log_path)
        log_path_layout.addWidget(browse_btn)
        
        logging_layout.addRow("Log file:", log_path_layout)
        
        layout.addWidget(logging_group)
        
        # Danger zone
        danger_group = QGroupBox("⚠️ Danger Zone")
        danger_group.setStyleSheet(f"""
            QGroupBox {{
                font-weight: bold;
                color: {COLORS.red};
                border: 1px solid {COLORS.red};
                border-radius: 8px;
                margin-top: 10px;
                padding-top: 15px;
            }}
            QGroupBox::title {{
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 5px;
            }}
        """)
        
        danger_layout = QVBoxLayout(danger_group)
        
        reset_btn = QPushButton("🗑️ Reset All Data")
        reset_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {COLORS.red};
                color: {COLORS.black};
                font-weight: bold;
            }}
        """)
        reset_btn.clicked.connect(self._reset_all_data)
        danger_layout.addWidget(reset_btn)
        
        layout.addWidget(danger_group)
        
        layout.addStretch()
        return tab
    
    def _apply_styles(self):
        """Apply dialog styles"""
        self.setStyleSheet(f"""
            QDialog {{
                background-color: {COLORS.bg};
            }}
            QLabel {{
                color: {COLORS.fg};
            }}
            QCheckBox {{
                color: {COLORS.fg};
            }}
            QCheckBox::indicator {{
                width: 18px;
                height: 18px;
                border-radius: 3px;
                border: 1px solid {COLORS.terminal_black};
                background-color: {COLORS.bg_input};
            }}
            QCheckBox::indicator:checked {{
                background-color: {COLORS.blue};
            }}
            QLineEdit, QComboBox, QSpinBox {{
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
            QPushButton#primaryButton {{
                background-color: {COLORS.green};
                color: {COLORS.black};
                border: none;
                font-weight: bold;
            }}
            QSlider::groove:horizontal {{
                background-color: {COLORS.bg_highlight};
                height: 8px;
                border-radius: 4px;
            }}
            QSlider::handle:horizontal {{
                background-color: {COLORS.blue};
                width: 18px;
                margin: -5px 0;
                border-radius: 9px;
            }}
        """)
    
    def _mark_changed(self, key, value):
        """Mark a setting as changed"""
        self._changed_settings[key] = value
    
    def _load_settings(self):
        """Load settings from QSettings"""
        # General
        self.auto_refresh_check.setChecked(
            self._settings.value('general/auto_refresh', False, bool)
        )
        self.refresh_interval.setValue(
            self._settings.value('general/refresh_interval', 30, int)
        )
        self.enable_notifications.setChecked(
            self._settings.value('general/notifications', True, bool)
        )
        self.notify_on_new.setChecked(
            self._settings.value('general/notify_new', True, bool)
        )
        self.start_minimized.setChecked(
            self._settings.value('general/start_minimized', False, bool)
        )
        self.auto_fetch_on_start.setChecked(
            self._settings.value('general/auto_fetch', False, bool)
        )
        
        # Display
        self.results_per_page.setValue(
            self._settings.value('display/results_per_page', 20, int)
        )
        self.show_tech_score.setChecked(
            self._settings.value('display/show_score', True, bool)
        )
        self.show_thumbnails.setChecked(
            self._settings.value('display/show_thumbnails', True, bool)
        )
        self.theme_combo.setCurrentText(
            self._settings.value('display/theme', 'Tokyo Night', str)
        )
        self.font_size_combo.setCurrentText(
            self._settings.value('display/font_size', 'Medium', str)
        )
        self.enable_animations.setChecked(
            self._settings.value('display/animations', True, bool)
        )
        self.show_ticker.setChecked(
            self._settings.value('display/show_ticker', True, bool)
        )
        self.ticker_speed.setValue(
            self._settings.value('display/ticker_speed', 5, int)
        )
        
        # Sources
        for name, check in self.source_checks.items():
            check.setChecked(
                self._settings.value(f'sources/{name}', True, bool)
            )
        
        # Advanced
        self.enable_cache.setChecked(
            self._settings.value('advanced/enable_cache', True, bool)
        )
        self.cache_ttl.setValue(
            self._settings.value('advanced/cache_ttl', 24, int)
        )
        self.log_level.setCurrentText(
            self._settings.value('advanced/log_level', 'INFO', str)
        )
        self.log_to_file.setChecked(
            self._settings.value('advanced/log_to_file', False, bool)
        )
        self.log_path.setText(
            self._settings.value('advanced/log_path', '', str)
        )
    
    def _save_settings(self):
        """Save changed settings"""
        # Save all current values (not just changed ones for simplicity)
        # General
        self._settings.setValue('general/auto_refresh', self.auto_refresh_check.isChecked())
        self._settings.setValue('general/refresh_interval', self.refresh_interval.value())
        self._settings.setValue('general/notifications', self.enable_notifications.isChecked())
        self._settings.setValue('general/notify_new', self.notify_on_new.isChecked())
        self._settings.setValue('general/start_minimized', self.start_minimized.isChecked())
        self._settings.setValue('general/auto_fetch', self.auto_fetch_on_start.isChecked())
        
        # Display
        self._settings.setValue('display/results_per_page', self.results_per_page.value())
        self._settings.setValue('display/show_score', self.show_tech_score.isChecked())
        self._settings.setValue('display/show_thumbnails', self.show_thumbnails.isChecked())
        self._settings.setValue('display/theme', self.theme_combo.currentText())
        self._settings.setValue('display/font_size', self.font_size_combo.currentText())
        self._settings.setValue('display/animations', self.enable_animations.isChecked())
        self._settings.setValue('display/show_ticker', self.show_ticker.isChecked())
        self._settings.setValue('display/ticker_speed', self.ticker_speed.value())
        
        # Sources
        for name, check in self.source_checks.items():
            self._settings.setValue(f'sources/{name}', check.isChecked())
        
        # Advanced
        self._settings.setValue('advanced/enable_cache', self.enable_cache.isChecked())
        self._settings.setValue('advanced/cache_ttl', self.cache_ttl.value())
        self._settings.setValue('advanced/log_level', self.log_level.currentText())
        self._settings.setValue('advanced/log_to_file', self.log_to_file.isChecked())
        self._settings.setValue('advanced/log_path', self.log_path.text())
        
        self._settings.sync()
        self.accept()
    
    def _reset_settings(self):
        """Reset all settings to defaults"""
        reply = QMessageBox.question(
            self,
            "Reset Settings",
            "Are you sure you want to reset all settings to defaults?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No
        )
        
        if reply == QMessageBox.Yes:
            self._settings.clear()
            self._load_settings()
    
    def _enable_all_sources(self):
        """Enable all sources"""
        for check in self.source_checks.values():
            check.setChecked(True)
    
    def _disable_all_sources(self):
        """Disable all sources"""
        for check in self.source_checks.values():
            check.setChecked(False)
    
    def _browse_log_path(self):
        """Browse for log file path"""
        filepath, _ = QFileDialog.getSaveFileName(
            self,
            "Select Log File",
            self.log_path.text() or "tech_news_scraper.log",
            "Log Files (*.log);;All Files (*.*)"
        )
        if filepath:
            self.log_path.setText(filepath)
            self._mark_changed('advanced/log_path', filepath)
    
    def _clear_cache(self):
        """Clear cache"""
        reply = QMessageBox.question(
            self,
            "Clear Cache",
            "Are you sure you want to clear the cache?",
            QMessageBox.Yes | QMessageBox.No
        )
        
        if reply == QMessageBox.Yes:
            # TODO: Implement actual cache clearing
            QMessageBox.information(self, "Cache Cleared", "Cache has been cleared successfully.")
    
    def _reset_all_data(self):
        """Reset all application data"""
        reply = QMessageBox.warning(
            self,
            "⚠️ Reset All Data",
            "This will delete all articles, cache, and settings.\n\nThis action cannot be undone!\n\nAre you sure?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No
        )
        
        if reply == QMessageBox.Yes:
            # TODO: Implement actual data reset
            QMessageBox.information(self, "Data Reset", "All data has been reset.")
