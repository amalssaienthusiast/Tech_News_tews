"""
Live Activity Log Widget
Real-time log display with color-coded levels

Features:
- Real-time log display with color-coded levels
- Shows: DEBUG, INFO, SUCCESS, WARNING, ERROR
- Timestamps for each entry
- Icons for each log level
- Auto-scroll and maximum entry limit
"""

from datetime import datetime
from typing import Optional, List
from dataclasses import dataclass
from enum import Enum
from collections import deque
import logging

from PyQt6.QtWidgets import (
    QFrame, QVBoxLayout, QHBoxLayout, QLabel, 
    QScrollArea, QWidget, QPlainTextEdit, QTextEdit,
    QSizePolicy
)
from PyQt6.QtCore import Qt, QTimer, QObject, pyqtSignal
from PyQt6.QtGui import QColor, QFont, QTextCursor, QTextCharFormat

from ..theme import COLORS, Fonts


class LogLevel(Enum):
    """Log level enumeration"""
    DEBUG = "DEBUG"
    INFO = "INFO"
    SUCCESS = "SUCCESS"
    WARNING = "WARNING"
    ERROR = "ERROR"


@dataclass
class LogEntry:
    """Single log entry"""
    timestamp: datetime
    level: LogLevel
    message: str
    source: str = ""


class LogLevelFormatter:
    """Handles formatting for different log levels"""
    
    LEVEL_CONFIG = {
        LogLevel.DEBUG: {
            "icon": "🐛",
            "color": COLORS.comment,
            "bg_color": COLORS.bg_dark,
        },
        LogLevel.INFO: {
            "icon": "ℹ",
            "color": COLORS.blue,
            "bg_color": COLORS.bg_highlight,
        },
        LogLevel.SUCCESS: {
            "icon": "✓",
            "color": COLORS.green,
            "bg_color": COLORS.bg_highlight,
        },
        LogLevel.WARNING: {
            "icon": "⚠",
            "color": COLORS.yellow,
            "bg_color": COLORS.bg_highlight,
        },
        LogLevel.ERROR: {
            "icon": "✗",
            "color": COLORS.red,
            "bg_color": COLORS.bg_visual,
        },
    }
    
    @classmethod
    def get_format(cls, level: LogLevel) -> dict:
        return cls.LEVEL_CONFIG.get(level, cls.LEVEL_CONFIG[LogLevel.INFO])
    
    @classmethod
    def format_entry(cls, entry: LogEntry) -> str:
        """Format a log entry as HTML"""
        config = cls.get_format(entry.level)
        time_str = entry.timestamp.strftime("%H:%M:%S")
        source = f"[{entry.source}] " if entry.source else ""
        
        return f"""
        <div style="
            margin: 2px 0;
            padding: 4px 8px;
            border-radius: 4px;
            background-color: {config['bg_color']};
            border-left: 3px solid {config['color']};
            font-family: 'SF Mono', Consolas, monospace;
            font-size: 12px;
        ">
            <span style="color: {COLORS.comment};">{time_str}</span>
            <span style="color: {config['color']}; font-weight: bold;">
                {config['icon']} {entry.level.value}
            </span>
            <span style="color: {COLORS.cyan};">{source}</span>
            <span style="color: {COLORS.fg};">{entry.message}</span>
        </div>
        """


class QtLogHandler(logging.Handler):
    """A logging.Handler that forwards real Python log records into a
    LiveActivityLog widget.

    Delivery goes through a Qt signal rather than calling the widget
    directly, so this is safe to attach to loggers used from background
    threads (e.g. the async scraper pipeline) — Qt marshals the signal
    onto the widget's own (GUI) thread automatically.
    """

    _LEVEL_MAP = {
        "DEBUG": "debug",
        "INFO": "info",
        "WARNING": "warning",
        "ERROR": "error",
        "CRITICAL": "error",
    }

    class _Bridge(QObject):
        record_ready = pyqtSignal(str, str, str)  # message, levelname, source

    def __init__(self, widget: "LiveActivityLog", level=logging.INFO):
        super().__init__(level)
        self._bridge = QtLogHandler._Bridge()
        self._bridge.record_ready.connect(self._deliver)
        self._widget = widget

    def _deliver(self, message: str, levelname: str, source: str):
        method_name = self._LEVEL_MAP.get(levelname, "info")
        getattr(self._widget, method_name)(message, source)

    def emit(self, record: logging.LogRecord):
        try:
            message = self.format(record)
            self._bridge.record_ready.emit(message, record.levelname, record.name)
        except Exception:
            self.handleError(record)


class LiveActivityLog(QFrame):
    """
    Live activity log widget
    
    Signals:
        entry_clicked(LogEntry): Emitted when a log entry is clicked
    """
    
    entry_clicked = pyqtSignal(object)
    
    def __init__(self, max_entries: int = 200, show_demo_data: bool = False, parent=None):
        super().__init__(parent)
        self._max_entries = max_entries
        self._entries: deque = deque(maxlen=max_entries)
        self._auto_scroll = True
        self._paused = False
        self._filter_level: Optional[LogLevel] = None
        
        self.setObjectName("cardFrame")
        self.setFrameStyle(QFrame.Shape.StyledPanel | QFrame.Shadow.Plain)
        self._setup_ui()
        self._apply_styles()
        
        # Demo data is opt-in only (isolated widget preview/testing). In the
        # real app, call attach_to_logger() to stream genuine log records in.
        if show_demo_data:
            self._init_demo_logs()
        
        # Preview-only randomized stream; never started automatically.
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._simulate_log_entry)
    
    def _setup_ui(self):
        """Build the log UI"""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)
        
        # Header
        header_layout = QHBoxLayout()
        
        title = QLabel("📝 Activity Log")
        title.setObjectName("headerLabel")
        title.setFont(Fonts.get_qfont('md', 'bold'))
        header_layout.addWidget(title)
        
        header_layout.addStretch()
        
        # Level filters
        self.filter_buttons = {}
        for level in LogLevel:
            btn = QLabel(level.value[:1])
            btn.setFont(Fonts.get_qfont('xs', 'bold'))
            btn.setAlignment(Qt.AlignmentFlag.AlignCenter)
            btn.setFixedSize(24, 24)
            btn.setStyleSheet(f"""
                QLabel {{
                    background-color: {LogLevelFormatter.get_format(level)['color']};
                    color: {COLORS.black};
                    border-radius: 4px;
                }}
            """)
            btn.setToolTip(f"Filter: {level.value}")
            btn.mousePressEvent = lambda e, l=level: self._toggle_filter(l)
            self.filter_buttons[level] = btn
            header_layout.addWidget(btn)
        
        # Pause button
        self.pause_btn = QLabel("⏸")
        self.pause_btn.setFont(Fonts.get_qfont('sm'))
        self.pause_btn.setStyleSheet(f"""
            QLabel {{
                color: {COLORS.cyan};
                padding: 2px 6px;
                border: 1px solid {COLORS.cyan};
                border-radius: 4px;
            }}
        """)
        self.pause_btn.mousePressEvent = lambda e: self.toggle_pause()
        self.pause_btn.setToolTip("Pause/Resume")
        header_layout.addWidget(self.pause_btn)
        
        layout.addLayout(header_layout)
        
        # Log text area with HTML support
        self.log_display = QTextEdit()
        self.log_display.setReadOnly(True)
        self.log_display.setLineWrapMode(QTextEdit.LineWrapMode.WidgetWidth)
        self.log_display.setStyleSheet(f"""
            QTextEdit {{
                background-color: {COLORS.bg};
                border: 1px solid {COLORS.terminal_black};
                border-radius: 6px;
                padding: 8px;
            }}
        """)
        
        # Set monospace font
        font = QFont("SF Mono" if __import__('sys').platform == 'darwin' else "Consolas")
        font.setPointSize(10)
        self.log_display.setFont(font)
        
        layout.addWidget(self.log_display)
        
        # Footer
        footer_layout = QHBoxLayout()
        
        # Entry count
        self.count_label = QLabel("0 entries")
        self.count_label.setFont(Fonts.get_qfont('xs'))
        self.count_label.setStyleSheet(f"color: {COLORS.comment};")
        footer_layout.addWidget(self.count_label)
        
        footer_layout.addStretch()
        
        # Auto-scroll indicator
        self.autoscroll_label = QLabel("⬇ Auto")
        self.autoscroll_label.setFont(Fonts.get_qfont('xs'))
        self.autoscroll_label.setStyleSheet(f"color: {COLORS.green};")
        footer_layout.addWidget(self.autoscroll_label)
        
        # Clear button
        self.clear_btn = QLabel("🗑 Clear")
        self.clear_btn.setFont(Fonts.get_qfont('xs'))
        self.clear_btn.setStyleSheet(f"""
            QLabel {{
                color: {COLORS.red};
                padding: 2px 8px;
                border: 1px solid {COLORS.red};
                border-radius: 4px;
            }}
        """)
        self.clear_btn.mousePressEvent = lambda e: self.clear()
        footer_layout.addWidget(self.clear_btn)
        
        layout.addLayout(footer_layout)
    
    def _apply_styles(self):
        """Apply widget styles"""
        self.setStyleSheet(f"""
            LiveActivityLog {{
                background-color: {COLORS.bg_highlight};
                border: 1px solid {COLORS.terminal_black};
                border-radius: 8px;
            }}
        """)
    
    def _init_demo_logs(self):
        """Initialize with demo log entries"""
        demo_entries = [
            LogEntry(datetime.now(), LogLevel.INFO, "Application started", "System"),
            LogEntry(datetime.now(), LogLevel.SUCCESS, "Connected to database", "Database"),
            LogEntry(datetime.now(), LogLevel.INFO, "Loading sources configuration", "Config"),
            LogEntry(datetime.now(), LogLevel.SUCCESS, "Loaded 10 news sources", "Sources"),
            LogEntry(datetime.now(), LogLevel.DEBUG, "Initializing pipeline stages", "Pipeline"),
            LogEntry(datetime.now(), LogLevel.INFO, "Starting article discovery", "Discovery"),
            LogEntry(datetime.now(), LogLevel.SUCCESS, "Found 24 new articles", "Discovery"),
            LogEntry(datetime.now(), LogLevel.WARNING, "Rate limit approaching for Reddit API", "Reddit"),
        ]
        
        for entry in demo_entries:
            self.add_entry(entry)
    
    def _toggle_filter(self, level: LogLevel):
        """Toggle filter for a log level"""
        if self._filter_level == level:
            self._filter_level = None
            # Reset all button styles
            for l, btn in self.filter_buttons.items():
                btn.setStyleSheet(f"""
                    QLabel {{
                        background-color: {LogLevelFormatter.get_format(l)['color']};
                        color: {COLORS.black};
                        border-radius: 4px;
                    }}
                """)
        else:
            self._filter_level = level
            # Highlight selected button
            for l, btn in self.filter_buttons.items():
                if l == level:
                    btn.setStyleSheet(f"""
                        QLabel {{
                            background-color: {LogLevelFormatter.get_format(l)['color']};
                            color: {COLORS.black};
                            border-radius: 4px;
                            border: 2px solid {COLORS.fg};
                        }}
                    """)
                else:
                    btn.setStyleSheet(f"""
                        QLabel {{
                            background-color: {COLORS.bg_dark};
                            color: {LogLevelFormatter.get_format(l)['color']};
                            border: 1px solid {COLORS.terminal_black};
                            border-radius: 4px;
                        }}
                    """)
        
        self._refresh_display()
    
    def add_entry(self, entry: LogEntry):
        """Add a log entry"""
        if self._paused:
            return
        
        self._entries.append(entry)
        
        # Only display if passes filter
        if self._filter_level is None or entry.level == self._filter_level:
            html = LogLevelFormatter.format_entry(entry)
            self.log_display.append(html.strip())
            
            if self._auto_scroll:
                scrollbar = self.log_display.verticalScrollBar()
                scrollbar.setValue(scrollbar.maximum())
        
        self._update_count()
    
    def log(self, message: str, level: LogLevel = LogLevel.INFO, source: str = ""):
        """Convenience method to add a log message"""
        entry = LogEntry(datetime.now(), level, message, source)
        self.add_entry(entry)

    def attach_to_logger(self, logger_name: str = "", level: int = logging.INFO) -> QtLogHandler:
        """Stream real Python log records from `logger_name` (default: root
        logger, i.e. everything) into this widget. Call this once after the
        widget is created to replace simulated entries with genuine
        application activity, e.g.:

            self.activity_log.attach_to_logger()             # everything
            self.activity_log.attach_to_logger("scraper")    # just scraper.*
        """
        handler = QtLogHandler(self, level=level)
        handler.setFormatter(logging.Formatter("%(message)s"))
        logging.getLogger(logger_name).addHandler(handler)
        return handler
    
    def debug(self, message: str, source: str = ""):
        """Log debug message"""
        self.log(message, LogLevel.DEBUG, source)
    
    def info(self, message: str, source: str = ""):
        """Log info message"""
        self.log(message, LogLevel.INFO, source)
    
    def success(self, message: str, source: str = ""):
        """Log success message"""
        self.log(message, LogLevel.SUCCESS, source)
    
    def warning(self, message: str, source: str = ""):
        """Log warning message"""
        self.log(message, LogLevel.WARNING, source)
    
    def error(self, message: str, source: str = ""):
        """Log error message"""
        self.log(message, LogLevel.ERROR, source)
    
    def _refresh_display(self):
        """Refresh the display with current filter"""
        self.log_display.clear()
        
        for entry in self._entries:
            if self._filter_level is None or entry.level == self._filter_level:
                html = LogLevelFormatter.format_entry(entry)
                self.log_display.append(html.strip())
        
        if self._auto_scroll:
            scrollbar = self.log_display.verticalScrollBar()
            scrollbar.setValue(scrollbar.maximum())
    
    def _update_count(self):
        """Update entry count"""
        total = len(self._entries)
        if self._filter_level:
            filtered = sum(1 for e in self._entries if e.level == self._filter_level)
            self.count_label.setText(f"{filtered}/{total} entries")
        else:
            self.count_label.setText(f"{total} entries")
    
    def toggle_pause(self):
        """Toggle pause state"""
        self._paused = not self._paused
        if self._paused:
            self.pause_btn.setText("▶")
            self.pause_btn.setStyleSheet(f"""
                QLabel {{
                    color: {COLORS.yellow};
                    padding: 2px 6px;
                    border: 1px solid {COLORS.yellow};
                    border-radius: 4px;
                }}
            """)
            self._timer.stop()
        else:
            self.pause_btn.setText("⏸")
            self.pause_btn.setStyleSheet(f"""
                QLabel {{
                    color: {COLORS.cyan};
                    padding: 2px 6px;
                    border: 1px solid {COLORS.cyan};
                    border-radius: 4px;
                }}
            """)
        # self._timer.start()  # DEMO TIMER DISABLED BY OPENCODE
    
    def set_auto_scroll(self, enabled: bool):
        """Enable/disable auto-scroll"""
        self._auto_scroll = enabled
        if enabled:
            self.autoscroll_label.setText("⬇ Auto")
            self.autoscroll_label.setStyleSheet(f"color: {COLORS.green};")
        else:
            self.autoscroll_label.setText("⬇ Manual")
            self.autoscroll_label.setStyleSheet(f"color: {COLORS.comment};")
    
    def clear(self):
        """Clear all log entries"""
        self._entries.clear()
        self.log_display.clear()
        self._update_count()
    
    def get_entries(self, level: Optional[LogLevel] = None) -> List[LogEntry]:
        """Get log entries, optionally filtered by level"""
        if level:
            return [e for e in self._entries if e.level == level]
        return list(self._entries)
    
    def _simulate_log_entry(self):
        """Simulate new log entries"""
        import random
        
        messages = [
            (LogLevel.INFO, "Processing batch of articles", "Pipeline"),
            (LogLevel.DEBUG, "Fetching feed from API", "Fetcher"),
            (LogLevel.SUCCESS, "Successfully parsed 5 articles", "Parser"),
            (LogLevel.INFO, "Scoring articles for tech relevance", "Scorer"),
            (LogLevel.WARNING, "Slow response from news source", "Fetcher"),
            (LogLevel.DEBUG, "Cache hit for source configuration", "Config"),
            (LogLevel.SUCCESS, "Article passed quality filter", "Filter"),
            (LogLevel.INFO, "Updating article display", "UI"),
            (LogLevel.ERROR, "Failed to connect to source", "Fetcher"),
            (LogLevel.SUCCESS, "Batch processing complete", "Pipeline"),
        ]
        
        level, message, source = random.choice(messages)
        
        # Occasionally add variations
        if random.random() < 0.3:
            message += f" #{random.randint(100, 999)}"
        
        self.log(message, level, source)
