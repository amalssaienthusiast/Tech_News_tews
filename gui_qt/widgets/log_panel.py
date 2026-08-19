"""
Log Panel Widget for Tech News Scraper
Real-time activity log display matching tkinter gui/app.py
"""

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPlainTextEdit,
    QLabel, QPushButton, QFrame, QComboBox
)
from PyQt6.QtCore import pyqtSignal, Qt, QTimer
from PyQt6.QtGui import QTextCharFormat, QColor, QFont

from datetime import datetime
from ..theme import COLORS, Fonts


class LogPanel(QFrame):
    """Real-time activity log panel
    
    Displays system events with timestamps and color-coded severity levels.
    Auto-scrolls to newest entries. Supports filtering by log level.
    
    Signals:
        entry_added(str): Emitted when new log entry is added
    """
    
    entry_added = pyqtSignal(str)
    
    # Severity levels with colors
    LEVELS = {
        'DEBUG': ('🔍', COLORS.comment),
        'INFO': ('ℹ️', COLORS.blue),
        'SUCCESS': ('✅', COLORS.green),
        'WARNING': ('⚠️', COLORS.yellow),
        'ERROR': ('❌', COLORS.red),
        'CRITICAL': ('🔥', COLORS.red),
    }
    
    def __init__(self, parent=None, max_entries: int = 1000):
        super().__init__(parent)
        
        self._max_entries = max_entries
        self._entries = []
        self._current_filter = 'ALL'
        
        self._setup_ui()
        self._setup_styles()
    
    def _setup_ui(self):
        """Build the log panel UI"""
        self.setObjectName("logPanel")
        
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        
        # Header
        header = QWidget()
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(10, 8, 10, 8)
        
        # Title
        title = QLabel("📋 Activity Log")
        title.setStyleSheet(f"font-weight: bold; color: {COLORS.cyan};")
        header_layout.addWidget(title)
        
        # Entry count
        self.count_label = QLabel("0 entries")
        self.count_label.setStyleSheet(f"color: {COLORS.comment}; font-size: 11px;")
        header_layout.addWidget(self.count_label)
        
        header_layout.addStretch()
        
        # Filter dropdown
        filter_label = QLabel("Filter:")
        filter_label.setStyleSheet(f"color: {COLORS.fg_dark};")
        header_layout.addWidget(filter_label)
        
        self.filter_combo = QComboBox()
        self.filter_combo.addItems(['ALL', 'DEBUG', 'INFO', 'SUCCESS', 'WARNING', 'ERROR'])
        self.filter_combo.currentTextChanged.connect(self._on_filter_changed)
        self.filter_combo.setStyleSheet(f"""
            QComboBox {{
                background-color: {COLORS.bg_input};
                color: {COLORS.fg};
                border: 1px solid {COLORS.terminal_black};
                padding: 4px 8px;
            }}
        """)
        header_layout.addWidget(self.filter_combo)
        
        # Clear button
        clear_btn = QPushButton("🗑️ Clear")
        clear_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {COLORS.bg_highlight};
                color: {COLORS.fg};
                border: 1px solid {COLORS.terminal_black};
                padding: 4px 8px;
                font-size: 11px;
            }}
        """)
        clear_btn.clicked.connect(self.clear)
        header_layout.addWidget(clear_btn)
        
        layout.addWidget(header)
        
        # Log display
        self.log_display = QPlainTextEdit()
        self.log_display.setReadOnly(True)
        self.log_display.setLineWrapMode(QPlainTextEdit.LineWrapMode.WidgetWidth)
        self.log_display.setMaximumBlockCount(self._max_entries)
        layout.addWidget(self.log_display)
        
        # Setup text formats
        self._setup_text_formats()
    
    def _setup_text_formats(self):
        """Setup text formats for different log levels"""
        self.formats = {}
        
        # Timestamp format
        timestamp_fmt = QTextCharFormat()
        timestamp_fmt.setForeground(QColor(COLORS.comment))
        timestamp_fmt.setFontFamily(Fonts.MONO)
        timestamp_fmt.setFontPointSize(Fonts.get_size('xs'))
        self.formats['TIMESTAMP'] = timestamp_fmt
        
        # Level formats
        for level, (icon, color) in self.LEVELS.items():
            fmt = QTextCharFormat()
            fmt.setForeground(QColor(color))
            fmt.setFontWeight(QFont.Weight.Bold)
            self.formats[level] = fmt
        
        # Normal text format
        normal_fmt = QTextCharFormat()
        normal_fmt.setForeground(QColor(COLORS.fg))
        self.formats['NORMAL'] = normal_fmt
    
    def _setup_styles(self):
        """Apply styles to the widget"""
        self.setStyleSheet(f"""
            QFrame#logPanel {{
                background-color: {COLORS.bg_dark};
                border: 1px solid {COLORS.terminal_black};
                border-radius: 8px;
            }}
            QPlainTextEdit {{
                background-color: {COLORS.bg};
                color: {COLORS.fg};
                border: none;
                padding: 10px;
                font-family: {Fonts.MONO};
                font-size: {Fonts.get_size('sm')}px;
            }}
            QScrollBar:vertical {{
                background-color: {COLORS.bg_dark};
                width: 12px;
                border-radius: 6px;
            }}
            QScrollBar::handle:vertical {{
                background-color: {COLORS.terminal_black};
                border-radius: 6px;
            }}
        """)
    
    def add_entry(self, message: str, level: str = 'INFO'):
        """Add a log entry
        
        Args:
            message: Log message text
            level: Log level (DEBUG, INFO, SUCCESS, WARNING, ERROR, CRITICAL)
        """
        timestamp = datetime.now().strftime("%H:%M:%S")
        level = level.upper()
        
        if level not in self.LEVELS:
            level = 'INFO'
        
        # Store entry
        entry = {
            'timestamp': timestamp,
            'level': level,
            'message': message
        }
        self._entries.append(entry)
        
        # Trim if exceeds max
        if len(self._entries) > self._max_entries:
            self._entries.pop(0)
        
        # Check filter
        if self._current_filter != 'ALL' and level != self._current_filter:
            return
        
        # Add to display
        self._append_to_display(entry)
        self._update_count()
        
        # Emit signal
        self.entry_added.emit(f"[{timestamp}] [{level}] {message}")
    
    def _append_to_display(self, entry: dict):
        """Append formatted entry to display"""
        cursor = self.log_display.textCursor()
        cursor.movePosition(cursor.End)
        
        # Timestamp
        cursor.insertText(f"[{entry['timestamp']}] ", self.formats['TIMESTAMP'])
        
        # Level with icon
        icon, _ = self.LEVELS[entry['level']]
        cursor.insertText(f"{icon} {entry['level']:8} ", self.formats[entry['level']])
        
        # Message
        cursor.insertText(f"{entry['message']}\n", self.formats['NORMAL'])
        
        # Auto-scroll
        self.log_display.setTextCursor(cursor)
        self.log_display.ensureCursorVisible()
    
    def _update_count(self):
        """Update entry count label"""
        visible = len([e for e in self._entries 
                      if self._current_filter == 'ALL' or e['level'] == self._current_filter])
        total = len(self._entries)
        self.count_label.setText(f"{visible}/{total} entries")
    
    def _on_filter_changed(self, filter_text: str):
        """Handle filter change"""
        self._current_filter = filter_text
        self._refresh_display()
    
    def _refresh_display(self):
        """Refresh display based on current filter"""
        self.log_display.clear()
        
        for entry in self._entries:
            if self._current_filter == 'ALL' or entry['level'] == self._current_filter:
                self._append_to_display(entry)
        
        self._update_count()
    
    def clear(self):
        """Clear all log entries"""
        self._entries.clear()
        self.log_display.clear()
        self._update_count()
    
    def log_debug(self, message: str):
        """Log debug message"""
        self.add_entry(message, 'DEBUG')
    
    def log_info(self, message: str):
        """Log info message"""
        self.add_entry(message, 'INFO')
    
    def log_success(self, message: str):
        """Log success message"""
        self.add_entry(message, 'SUCCESS')
    
    def log_warning(self, message: str):
        """Log warning message"""
        self.add_entry(message, 'WARNING')
    
    def log_error(self, message: str):
        """Log error message"""
        self.add_entry(message, 'ERROR')
    
    def log_critical(self, message: str):
        """Log critical message"""
        self.add_entry(message, 'CRITICAL')
    
    def export_to_file(self, filepath: str):
        """Export log to file
        
        Args:
            filepath: Path to export file
        """
        try:
            with open(filepath, 'w') as f:
                for entry in self._entries:
                    f.write(f"[{entry['timestamp']}] [{entry['level']}] {entry['message']}\n")
            return True
        except Exception as e:
            self.log_error(f"Failed to export log: {e}")
            return False
