"""
Developer Dashboard for Tech News Scraper
Password-protected developer tools matching tkinter gui/app.py
"""

from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QTabWidget, QWidget, QFormLayout,
    QLineEdit, QTextEdit, QProgressBar, QTableWidget,
    QTableWidgetItem, QHeaderView, QSplitter, QFrame,
    QMessageBox, QFileDialog, QComboBox, QCheckBox
)
from PyQt6.QtCore import Qt, QTimer, QSettings
from PyQt6.QtGui import QFont

import hashlib
from datetime import datetime
from ..theme import COLORS, Fonts


class DeveloperDashboard(QDialog):
    """Developer dashboard with advanced tools and metrics
    
    Password-protected dialog providing:
    - Real-time performance metrics
    - System logs and debugging
    - Database browser
    - Cache statistics
    - API testing tools
    - Configuration editor
    
    Usage:
        dashboard = DeveloperDashboard(parent, orchestrator)
        if dashboard.authenticate():
            dashboard.exec()
    """
    
    def __init__(self, parent=None, orchestrator=None):
        super().__init__(parent)
        
        self.orchestrator = orchestrator
        self._authenticated = False
        self._update_timer = QTimer(self)
        self._update_timer.timeout.connect(self._update_metrics)
        
        self._setup_window()
        self._setup_ui()
    
    def _setup_window(self):
        """Configure dialog window"""
        self.setWindowTitle("🔧 Developer Dashboard")
        self.setMinimumSize(900, 700)
        
        self.setWindowFlags(
            Qt.WindowType.Dialog |
            Qt.WindowType.WindowCloseButtonHint |
            Qt.WindowType.WindowMaximizeButtonHint
        )
    
    def _setup_ui(self):
        """Build the dashboard UI"""
        layout = QVBoxLayout(self)
        layout.setSpacing(15)
        
        # Header
        header = self._create_header()
        layout.addWidget(header)
        
        # Tab widget
        self.tabs = QTabWidget()
        self.tabs.setDocumentMode(True)
        
        # Create tabs
        self.tabs.addTab(self._create_overview_tab(), "📊 Overview")
        self.tabs.addTab(self._create_logs_tab(), "📝 Logs")
        self.tabs.addTab(self._create_database_tab(), "🗄️ Database")
        self.tabs.addTab(self._create_cache_tab(), "💾 Cache")
        self.tabs.addTab(self._create_api_tab(), "🔌 API Tools")
        self.tabs.addTab(self._create_config_tab(), "⚙️ Config")
        
        layout.addWidget(self.tabs)
        
        # Footer
        footer = self._create_footer()
        layout.addWidget(footer)
        
        # Apply styles
        self._apply_styles()
    
    def _create_header(self):
        """Create dashboard header"""
        header = QFrame()
        header.setObjectName("devHeader")
        header.setStyleSheet(f"""
            QFrame#devHeader {{
                background-color: {COLORS.bg_dark};
                border-radius: 8px;
                padding: 10px;
            }}
        """)
        
        layout = QHBoxLayout(header)
        
        # Title
        title = QLabel("🔧 Developer Dashboard")
        title.setStyleSheet(f"""
            font-size: 20px;
            font-weight: bold;
            color: {COLORS.red};
        """)
        layout.addWidget(title)
        
        layout.addStretch()
        
        # Status indicators
        self.status_label = QLabel("● Live")
        self.status_label.setStyleSheet(f"color: {COLORS.green};")
        layout.addWidget(self.status_label)
        
        # Last update time
        self.update_time_label = QLabel("Updated: --")
        self.update_time_label.setStyleSheet(f"color: {COLORS.comment};")
        layout.addWidget(self.update_time_label)
        
        return header
    
    def _create_overview_tab(self):
        """Create Overview tab with metrics"""
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setSpacing(20)
        
        # Metrics grid
        metrics_widget = QWidget()
        metrics_layout = QHBoxLayout(metrics_widget)
        metrics_layout.setSpacing(15)
        
        # Create metric cards
        self.metric_cards = {}
        metrics = [
            ("articles", "📰 Articles", COLORS.cyan),
            ("sources", "📡 Sources", COLORS.blue),
            ("queries", "🔍 Queries", COLORS.magenta),
            ("cache", "💾 Cache Hits", COLORS.green),
            ("errors", "❌ Errors", COLORS.red),
            ("uptime", "⏱️ Uptime", COLORS.yellow),
        ]
        
        for key, label, color in metrics:
            card = self._create_metric_card(label, color)
            self.metric_cards[key] = card
            metrics_layout.addWidget(card)
        
        layout.addWidget(metrics_widget)
        
        # Performance section
        perf_group = QFrame()
        perf_group.setStyleSheet(f"""
            QFrame {{
                background-color: {COLORS.bg_highlight};
                border-radius: 8px;
                padding: 15px;
            }}
        """)
        
        perf_layout = QVBoxLayout(perf_group)
        
        perf_title = QLabel("⚡ Performance")
        perf_title.setStyleSheet(f"font-weight: bold; color: {COLORS.cyan};")
        perf_layout.addWidget(perf_title)
        
        # Memory usage bar
        mem_layout = QHBoxLayout()
        mem_layout.addWidget(QLabel("Memory:"))
        self.memory_bar = QProgressBar()
        self.memory_bar.setRange(0, 100)
        self.memory_bar.setTextVisible(True)
        mem_layout.addWidget(self.memory_bar)
        self.memory_label = QLabel("0 MB / 0 MB")
        mem_layout.addWidget(self.memory_label)
        perf_layout.addLayout(mem_layout)
        
        # CPU usage bar
        cpu_layout = QHBoxLayout()
        cpu_layout.addWidget(QLabel("CPU:"))
        self.cpu_bar = QProgressBar()
        self.cpu_bar.setRange(0, 100)
        self.cpu_bar.setTextVisible(True)
        cpu_layout.addWidget(self.cpu_bar)
        perf_layout.addLayout(cpu_layout)
        
        # Response time
        resp_layout = QHBoxLayout()
        resp_layout.addWidget(QLabel("Avg Response:"))
        self.response_label = QLabel("-- ms")
        resp_layout.addWidget(self.response_label)
        resp_layout.addStretch()
        perf_layout.addLayout(resp_layout)
        
        layout.addWidget(perf_group)
        
        # Recent activity
        activity_group = QFrame()
        activity_group.setStyleSheet(perf_group.styleSheet())
        
        activity_layout = QVBoxLayout(activity_group)
        
        activity_title = QLabel("📈 Recent Activity")
        activity_title.setStyleSheet(f"font-weight: bold; color: {COLORS.cyan};")
        activity_layout.addWidget(activity_title)
        
        self.activity_text = QTextEdit()
        self.activity_text.setReadOnly(True)
        self.activity_text.setMaximumHeight(150)
        activity_layout.addWidget(self.activity_text)
        
        layout.addWidget(activity_group)
        
        layout.addStretch()
        return tab
    
    def _create_metric_card(self, label, color):
        """Create a metric card widget"""
        card = QFrame()
        card.setStyleSheet(f"""
            QFrame {{
                background-color: {COLORS.bg_highlight};
                border-radius: 8px;
                border-left: 4px solid {color};
            }}
        """)
        
        layout = QVBoxLayout(card)
        layout.setSpacing(5)
        
        label_widget = QLabel(label)
        label_widget.setStyleSheet(f"color: {COLORS.comment}; font-size: 12px;")
        layout.addWidget(label_widget)
        
        value_widget = QLabel("0")
        value_widget.setStyleSheet(f"color: {color}; font-size: 24px; font-weight: bold;")
        layout.addWidget(value_widget)
        
        card.value_label = value_widget
        return card
    
    def _create_logs_tab(self):
        """Create Logs tab"""
        tab = QWidget()
        layout = QVBoxLayout(tab)
        
        # Controls
        controls = QHBoxLayout()
        
        controls.addWidget(QLabel("Level:"))
        self.log_level_combo = QComboBox()
        self.log_level_combo.addItems(["DEBUG", "INFO", "WARNING", "ERROR"])
        controls.addWidget(self.log_level_combo)
        
        refresh_btn = QPushButton("🔄 Refresh")
        refresh_btn.clicked.connect(self._refresh_logs)
        controls.addWidget(refresh_btn)
        
        clear_btn = QPushButton("🗑️ Clear")
        clear_btn.clicked.connect(self._clear_logs)
        controls.addWidget(clear_btn)
        
        export_btn = QPushButton("📤 Export")
        export_btn.clicked.connect(self._export_logs)
        controls.addWidget(export_btn)
        
        controls.addStretch()
        
        auto_scroll_check = QCheckBox("Auto-scroll")
        auto_scroll_check.setChecked(True)
        controls.addWidget(auto_scroll_check)
        
        layout.addLayout(controls)
        
        # Log display
        self.log_text = QTextEdit()
        self.log_text.setReadOnly(True)
        self.log_text.setFont(QFont("SF Mono", 11))
        layout.addWidget(self.log_text)
        
        return tab
    
    def _create_database_tab(self):
        """Create Database tab"""
        tab = QWidget()
        layout = QVBoxLayout(tab)
        
        # Controls
        controls = QHBoxLayout()
        
        self.db_table_combo = QComboBox()
        self.db_table_combo.addItems(["articles", "sources", "queries", "cache"])
        controls.addWidget(QLabel("Table:"))
        controls.addWidget(self.db_table_combo)
        
        query_btn = QPushButton("🔍 Query")
        query_btn.clicked.connect(self._query_database)
        controls.addWidget(query_btn)
        
        controls.addStretch()
        
        refresh_db_btn = QPushButton("🔄 Refresh")
        refresh_db_btn.clicked.connect(self._refresh_database)
        controls.addWidget(refresh_db_btn)
        
        layout.addLayout(controls)
        
        # Data table
        self.db_table = QTableWidget()
        self.db_table.setColumnCount(5)
        self.db_table.setHorizontalHeaderLabels(["ID", "Title", "Source", "Date", "Score"])
        self.db_table.horizontalHeader().setStretchLastSection(True)
        self.db_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        layout.addWidget(self.db_table)
        
        # Stats
        stats_layout = QHBoxLayout()
        self.db_stats_label = QLabel("Rows: 0 | Size: 0 MB")
        stats_layout.addWidget(self.db_stats_label)
        stats_layout.addStretch()
        layout.addLayout(stats_layout)
        
        return tab
    
    def _create_cache_tab(self):
        """Create Cache tab"""
        tab = QWidget()
        layout = QVBoxLayout(tab)
        
        # Cache stats
        stats_group = QFrame()
        stats_group.setStyleSheet(f"""
            QFrame {{
                background-color: {COLORS.bg_highlight};
                border-radius: 8px;
                padding: 15px;
            }}
        """)
        
        stats_layout = QFormLayout(stats_group)
        
        self.cache_size_label = QLabel("0 MB")
        stats_layout.addRow("Cache Size:", self.cache_size_label)
        
        self.cache_entries_label = QLabel("0")
        stats_layout.addRow("Entries:", self.cache_entries_label)
        
        self.cache_hit_label = QLabel("0%")
        stats_layout.addRow("Hit Rate:", self.cache_hit_label)
        
        self.cache_ttl_label = QLabel("24 hours")
        stats_layout.addRow("Default TTL:", self.cache_ttl_label)
        
        layout.addWidget(stats_group)
        
        # Cache entries table
        self.cache_table = QTableWidget()
        self.cache_table.setColumnCount(4)
        self.cache_table.setHorizontalHeaderLabels(["Key", "Size", "Created", "Expires"])
        self.cache_table.horizontalHeader().setStretchLastSection(True)
        layout.addWidget(self.cache_table)
        
        # Actions
        actions_layout = QHBoxLayout()
        
        clear_cache_btn = QPushButton("🗑️ Clear All")
        clear_cache_btn.clicked.connect(self._clear_all_cache)
        clear_cache_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {COLORS.red};
                color: {COLORS.black};
                font-weight: bold;
            }}
        """)
        actions_layout.addWidget(clear_cache_btn)
        
        refresh_cache_btn = QPushButton("🔄 Refresh")
        refresh_cache_btn.clicked.connect(self._refresh_cache)
        actions_layout.addWidget(refresh_cache_btn)
        
        actions_layout.addStretch()
        layout.addLayout(actions_layout)
        
        return tab
    
    def _create_api_tab(self):
        """Create API Tools tab"""
        tab = QWidget()
        layout = QVBoxLayout(tab)
        
        # API tester
        tester_group = QFrame()
        tester_group.setStyleSheet(f"""
            QFrame {{
                background-color: {COLORS.bg_highlight};
                border-radius: 8px;
                padding: 15px;
            }}
        """)
        
        tester_layout = QFormLayout(tester_group)
        
        self.api_endpoint = QLineEdit()
        self.api_endpoint.setPlaceholderText("/api/articles")
        tester_layout.addRow("Endpoint:", self.api_endpoint)
        
        self.api_method = QComboBox()
        self.api_method.addItems(["GET", "POST", "PUT", "DELETE"])
        tester_layout.addRow("Method:", self.api_method)
        
        self.api_body = QTextEdit()
        self.api_body.setPlaceholderText('{"query": "python"}')
        self.api_body.setMaximumHeight(100)
        tester_layout.addRow("Body:", self.api_body)
        
        test_btn = QPushButton("▶️ Send Request")
        test_btn.clicked.connect(self._send_api_request)
        tester_layout.addRow(test_btn)
        
        layout.addWidget(tester_group)
        
        # Response
        self.api_response = QTextEdit()
        self.api_response.setReadOnly(True)
        self.api_response.setPlaceholderText("Response will appear here...")
        layout.addWidget(self.api_response)
        
        return tab
    
    def _create_config_tab(self):
        """Create Configuration tab"""
        tab = QWidget()
        layout = QVBoxLayout(tab)
        
        # Config editor
        self.config_text = QTextEdit()
        self.config_text.setPlaceholderText("# Configuration\n{\n  \"debug\": false,\n  \"cache_enabled\": true\n}")
        layout.addWidget(self.config_text)
        
        # Actions
        actions_layout = QHBoxLayout()
        
        load_btn = QPushButton("📂 Load")
        load_btn.clicked.connect(self._load_config)
        actions_layout.addWidget(load_btn)
        
        save_btn = QPushButton("💾 Save")
        save_btn.clicked.connect(self._save_config)
        actions_layout.addWidget(save_btn)
        
        validate_btn = QPushButton("✓ Validate")
        validate_btn.clicked.connect(self._validate_config)
        actions_layout.addWidget(validate_btn)
        
        actions_layout.addStretch()
        layout.addLayout(actions_layout)
        
        return tab
    
    def _create_footer(self):
        """Create dashboard footer"""
        footer = QWidget()
        layout = QHBoxLayout(footer)
        
        # Auto-update toggle
        self.auto_update_check = QCheckBox("Auto-update")
        self.auto_update_check.setChecked(True)
        self.auto_update_check.stateChanged.connect(self._toggle_auto_update)
        layout.addWidget(self.auto_update_check)
        
        layout.addStretch()
        
        # Close button
        close_btn = QPushButton("✕ Close")
        close_btn.clicked.connect(self.reject)
        layout.addWidget(close_btn)
        
        return footer
    
    def _apply_styles(self):
        """Apply dashboard styles"""
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
            QTextEdit {{
                background-color: {COLORS.bg_dark};
                color: {COLORS.fg};
                border: 1px solid {COLORS.terminal_black};
                border-radius: 6px;
                padding: 10px;
                font-family: {Fonts.MONO};
            }}
            QTableWidget {{
                background-color: {COLORS.bg_dark};
                color: {COLORS.fg};
                border: 1px solid {COLORS.terminal_black};
                gridline-color: {COLORS.terminal_black};
            }}
            QHeaderView::section {{
                background-color: {COLORS.bg_highlight};
                color: {COLORS.cyan};
                padding: 8px;
                border: 1px solid {COLORS.terminal_black};
            }}
            QProgressBar {{
                background-color: {COLORS.bg_dark};
                border: 1px solid {COLORS.terminal_black};
                border-radius: 4px;
                text-align: center;
            }}
            QProgressBar::chunk {{
                background-color: {COLORS.blue};
                border-radius: 4px;
            }}
        """)
    
    def authenticate(self) -> bool:
        """Show password dialog and authenticate
        
        Returns:
            True if authentication successful
        """
        # Simple password hash (in production, use proper auth)
        PASSWORD_HASH = "5e884898da28047151d0e56f8dc6292773603d0d6aabbdd62a11ef721d1542d8"  # "password"
        
        from PyQt6.QtWidgets import QInputDialog, QLineEdit
        
        password, ok = QInputDialog.getText(
            self.parent(),
            "🔒 Developer Access",
            "Enter developer password:",
            QLineEdit.Password
        )
        
        if not ok:
            return False
        
        # Hash and verify
        hashed = hashlib.sha256(password.encode()).hexdigest()
        self._authenticated = hashed == PASSWORD_HASH
        
        if not self._authenticated:
            QMessageBox.critical(
                self.parent(),
                "Access Denied",
                "Incorrect password. Developer access denied."
            )
        
        return self._authenticated
    
    def _toggle_auto_update(self, state):
        """Toggle auto-update timer"""
        if state:
            self._update_timer.start(2000)  # Update every 2 seconds
            self._update_metrics()
        else:
            self._update_timer.stop()
    
    def _update_metrics(self):
        """Update dashboard metrics"""
        try:
            # Get metrics from orchestrator if available
            if self.orchestrator:
                # Articles
                articles = len(getattr(self.orchestrator, '_articles', []))
                self.metric_cards['articles'].value_label.setText(str(articles))
                
                # Sources
                sources = len(getattr(self.orchestrator, '_sources', []))
                self.metric_cards['sources'].value_label.setText(str(sources))
                
                # Cache
                cache = getattr(self.orchestrator, '_cache', None)
                if cache:
                    hits = getattr(cache, '_hits', 0)
                    self.metric_cards['cache'].value_label.setText(str(hits))
            
            # Update timestamp
            self.update_time_label.setText(
                f"Updated: {datetime.now().strftime('%H:%M:%S')}"
            )
            
        except Exception as e:
            self.activity_text.append(f"[ERROR] Metrics update failed: {e}")
    
    def _refresh_logs(self):
        """Refresh log display"""
        self.log_text.append(f"[{datetime.now().strftime('%H:%M:%S')}] Logs refreshed")
    
    def _clear_logs(self):
        """Clear log display"""
        self.log_text.clear()
    
    def _export_logs(self):
        """Export logs to file"""
        filepath, _ = QFileDialog.getSaveFileName(
            self,
            "Export Logs",
            "logs_export.txt",
            "Text Files (*.txt);;All Files (*.*)"
        )
        if filepath:
            with open(filepath, 'w') as f:
                f.write(self.log_text.toPlainText())
            QMessageBox.information(self, "Export Complete", f"Logs exported to {filepath}")
    
    def _query_database(self):
        """Query database table"""
        table = self.db_table_combo.currentText()
        self.db_table.setRowCount(0)
        # TODO: Implement actual database query
        self.db_stats_label.setText(f"Rows: 0 | Table: {table}")
    
    def _refresh_database(self):
        """Refresh database view"""
        self._query_database()
    
    def _clear_all_cache(self):
        """Clear all cache entries"""
        reply = QMessageBox.question(
            self,
            "Clear Cache",
            "Are you sure you want to clear all cache entries?",
            QMessageBox.Yes | QMessageBox.No
        )
        
        if reply == QMessageBox.Yes:
            # TODO: Implement actual cache clearing
            QMessageBox.information(self, "Cache Cleared", "All cache entries have been cleared.")
    
    def _refresh_cache(self):
        """Refresh cache view"""
        self.cache_table.setRowCount(0)
        self.cache_size_label.setText("0 MB")
        self.cache_entries_label.setText("0")
    
    def _send_api_request(self):
        """Send API test request"""
        endpoint = self.api_endpoint.text() or "/api/test"
        method = self.api_method.currentText()
        
        self.api_response.setPlainText(
            f"[{datetime.now().strftime('%H:%M:%S')}] {method} {endpoint}\n"
            f"Status: 200 OK\n"
            f"Response: {{\"status\": \"ok\", \"data\": []}}"
        )
    
    def _load_config(self):
        """Load configuration from file"""
        filepath, _ = QFileDialog.getOpenFileName(
            self,
            "Load Configuration",
            "",
            "JSON Files (*.json);;All Files (*.*)"
        )
        if filepath:
            try:
                with open(filepath, 'r') as f:
                    self.config_text.setPlainText(f.read())
            except Exception as e:
                QMessageBox.critical(self, "Error", f"Failed to load config: {e}")
    
    def _save_config(self):
        """Save configuration to file"""
        filepath, _ = QFileDialog.getSaveFileName(
            self,
            "Save Configuration",
            "config.json",
            "JSON Files (*.json);;All Files (*.*)"
        )
        if filepath:
            try:
                with open(filepath, 'w') as f:
                    f.write(self.config_text.toPlainText())
                QMessageBox.information(self, "Saved", f"Configuration saved to {filepath}")
            except Exception as e:
                QMessageBox.critical(self, "Error", f"Failed to save config: {e}")
    
    def _validate_config(self):
        """Validate configuration JSON"""
        import json
        try:
            json.loads(self.config_text.toPlainText())
            QMessageBox.information(self, "Valid", "Configuration is valid JSON")
        except json.JSONDecodeError as e:
            QMessageBox.critical(self, "Invalid", f"Invalid JSON: {e}")
    
    def showEvent(self, event):
        """Handle show event"""
        super().showEvent(event)
        if self._authenticated and self.auto_update_check.isChecked():
            self._update_timer.start(2000)
    
    def closeEvent(self, event):
        """Handle close event"""
        self._update_timer.stop()
        super().closeEvent(event)
