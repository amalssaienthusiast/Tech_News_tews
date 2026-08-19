"""
Live Source Heartbeat Monitor Widget
Monitors source status with latency and color-coded indicators

Features:
- Shows 10 sources with status indicators
- Displays latency for each source
- Color-coded status (green/red/yellow)
- Last updated timestamp
- Grid layout with source names
"""

from datetime import datetime
from typing import Dict, List, Optional
from dataclasses import dataclass

from PyQt6.QtWidgets import (
    QFrame, QVBoxLayout, QHBoxLayout, QLabel, 
    QGridLayout, QWidget, QSizePolicy
)
from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QColor

from ..theme import COLORS, Fonts


@dataclass
class SourceStatus:
    """Status information for a single source"""
    name: str
    status: str  # 'online', 'offline', 'warning', 'checking'
    latency: float  # in milliseconds
    last_updated: datetime
    articles_count: int = 0
    error_count: int = 0


class StatusIndicator(QFrame):
    """Circular status indicator with pulsing animation"""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self._status = 'offline'
        self._pulse_opacity = 1.0
        self.setFixedSize(12, 12)
        self.setStyleSheet(self._get_style())
    
    def _get_style(self) -> str:
        """Get stylesheet based on current status"""
        colors = {
            'online': COLORS.green,
            'offline': COLORS.red,
            'warning': COLORS.yellow,
            'checking': COLORS.cyan
        }
        color = colors.get(self._status, COLORS.red)
        
        return f"""
            StatusIndicator {{
                background-color: {color};
                border-radius: 6px;
                border: 2px solid {COLORS.bg_dark};
            }}
        """
    
    def set_status(self, status: str):
        """Update status indicator"""
        self._status = status
        self.setStyleSheet(self._get_style())
    
    def get_status(self) -> str:
        return self._status


class SourceRow(QFrame):
    """Single row displaying source status information"""
    
    def __init__(self, source_status: SourceStatus, parent=None):
        super().__init__(parent)
        self._status = source_status
        self.setObjectName("sourceRow")
        self._setup_ui()
        self._apply_styles()
    
    def _setup_ui(self):
        """Build the source row UI"""
        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 6, 8, 6)
        layout.setSpacing(12)
        
        # Status indicator
        self.indicator = StatusIndicator(self)
        layout.addWidget(self.indicator)
        
        # Source name
        self.name_label = QLabel(self._status.name)
        self.name_label.setFont(Fonts.get_qfont('sm', 'medium'))
        self.name_label.setMinimumWidth(100)
        layout.addWidget(self.name_label)
        
        # Spacer
        layout.addStretch()
        
        # Latency
        self.latency_label = QLabel(self._format_latency(self._status.latency))
        self.latency_label.setFont(Fonts.get_qfont('xs', mono=True))
        self.latency_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.latency_label.setMinimumWidth(60)
        layout.addWidget(self.latency_label)
        
        # Articles count
        self.count_label = QLabel(f"📄 {self._status.articles_count}")
        self.count_label.setFont(Fonts.get_qfont('xs'))
        self.count_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.count_label.setMinimumWidth(50)
        layout.addWidget(self.count_label)
    
    def _format_latency(self, latency: float) -> str:
        """Format latency with color coding"""
        if latency < 0:
            return "-- ms"
        elif latency < 200:
            return f"🟢 {latency:.0f}ms"
        elif latency < 500:
            return f"🟡 {latency:.0f}ms"
        else:
            return f"🔴 {latency:.0f}ms"
    
    def _apply_styles(self):
        """Apply row styles based on status"""
        status_colors = {
            'online': COLORS.green,
            'offline': COLORS.red,
            'warning': COLORS.yellow,
            'checking': COLORS.cyan
        }
        
        border_color = status_colors.get(self._status.status, COLORS.terminal_black)
        bg_alpha = "20" if self._status.status == 'online' else "10"
        
        self.setStyleSheet(f"""
            SourceRow {{
                background-color: {COLORS.bg_highlight};
                border: 1px solid {border_color};
                border-radius: 6px;
            }}
            SourceRow:hover {{
                background-color: {COLORS.bg_visual};
                border: 1px solid {COLORS.blue};
            }}
        """)
        
        # Update latency color
        if self._status.latency < 200:
            latency_color = COLORS.green
        elif self._status.latency < 500:
            latency_color = COLORS.yellow
        else:
            latency_color = COLORS.red
            
        self.latency_label.setStyleSheet(f"color: {latency_color};")
    
    def update_status(self, status: SourceStatus):
        """Update the row with new status data"""
        self._status = status
        self.indicator.set_status(status.status)
        self.latency_label.setText(self._format_latency(status.latency))
        self.count_label.setText(f"📄 {status.articles_count}")
        self._apply_styles()
    
    def get_status(self) -> SourceStatus:
        return self._status


class LiveSourceHeartbeatMonitor(QFrame):
    """
    Live source heartbeat monitor widget
    
    Signals:
        source_clicked(SourceStatus): Emitted when a source row is clicked
    """
    
    source_clicked = pyqtSignal(SourceStatus)
    
    def __init__(self, show_demo_data: bool = False, parent=None):
        super().__init__(parent)
        self._sources: Dict[str, SourceRow] = {}
        self._last_updated = datetime.now()
        
        self.setObjectName("cardFrame")
        self.setFrameStyle(QFrame.Shape.StyledPanel | QFrame.Shadow.Plain)
        self._setup_ui()
        self._apply_styles()
        
        # Demo data is opt-in only (isolated widget preview/testing); the real
        # app starts this empty and calls add_source()/update_source() with
        # genuine per-source health data.
        if show_demo_data:
            self._init_demo_sources()
        
        # Preview-only randomized stream; never started automatically.
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._simulate_updates)
    
    def _setup_ui(self):
        """Build the monitor UI"""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)
        
        # Header
        header_layout = QHBoxLayout()
        
        title = QLabel("🌐 Live Source Monitor")
        title.setObjectName("headerLabel")
        title.setFont(Fonts.get_qfont('md', 'bold'))
        header_layout.addWidget(title)
        
        header_layout.addStretch()
        
        # Status summary
        self.online_label = QLabel("🟢 0 Online")
        self.online_label.setFont(Fonts.get_qfont('sm'))
        self.online_label.setStyleSheet(f"color: {COLORS.green};")
        header_layout.addWidget(self.online_label)
        
        self.offline_label = QLabel("🔴 0 Offline")
        self.offline_label.setFont(Fonts.get_qfont('sm'))
        self.offline_label.setStyleSheet(f"color: {COLORS.red};")
        header_layout.addWidget(self.offline_label)
        
        layout.addLayout(header_layout)
        
        # Sources container
        self.sources_container = QFrame()
        self.sources_container.setStyleSheet(f"""
            QFrame {{
                background-color: {COLORS.bg};
                border: 1px solid {COLORS.terminal_black};
                border-radius: 6px;
            }}
        """)
        
        self.sources_layout = QVBoxLayout(self.sources_container)
        self.sources_layout.setContentsMargins(8, 8, 8, 8)
        self.sources_layout.setSpacing(6)
        
        layout.addWidget(self.sources_container)
        
        # Footer with timestamp
        footer_layout = QHBoxLayout()
        
        self.timestamp_label = QLabel("Last updated: --")
        self.timestamp_label.setFont(Fonts.get_qfont('xs'))
        self.timestamp_label.setStyleSheet(f"color: {COLORS.comment};")
        footer_layout.addWidget(self.timestamp_label)
        
        footer_layout.addStretch()
        
        # Refresh button
        self.refresh_btn = QLabel("⟳ Auto")
        self.refresh_btn.setFont(Fonts.get_qfont('xs'))
        self.refresh_btn.setStyleSheet(f"""
            QLabel {{
                color: {COLORS.cyan};
                padding: 2px 8px;
                border: 1px solid {COLORS.cyan};
                border-radius: 4px;
            }}
        """)
        footer_layout.addWidget(self.refresh_btn)
        
        layout.addLayout(footer_layout)
    
    def _apply_styles(self):
        """Apply widget styles"""
        self.setStyleSheet(f"""
            LiveSourceHeartbeatMonitor {{
                background-color: {COLORS.bg_highlight};
                border: 1px solid {COLORS.terminal_black};
                border-radius: 8px;
            }}
        """)
    
    def _init_demo_sources(self):
        """Initialize with demo sources"""
        demo_sources = [
            SourceStatus("Hacker News", "online", 45.2, datetime.now(), 12, 0),
            SourceStatus("GitHub Trending", "online", 120.5, datetime.now(), 8, 0),
            SourceStatus("Reddit r/programming", "online", 230.1, datetime.now(), 24, 1),
            SourceStatus("Dev.to", "online", 89.3, datetime.now(), 15, 0),
            SourceStatus("Medium", "warning", 450.7, datetime.now(), 6, 2),
            SourceStatus("TechCrunch", "online", 156.8, datetime.now(), 4, 0),
            SourceStatus("The Verge", "online", 198.4, datetime.now(), 3, 0),
            SourceStatus("Ars Technica", "offline", -1, datetime.now(), 0, 3),
            SourceStatus("Wired", "online", 134.2, datetime.now(), 7, 0),
            SourceStatus("Stack Overflow", "online", 67.9, datetime.now(), 18, 0),
        ]
        
        for source in demo_sources:
            self.add_source(source)
        
        self._update_summary()
    
    def add_source(self, source_status: SourceStatus):
        """Add a source to the monitor"""
        row = SourceRow(source_status, self)
        row.mousePressEvent = lambda e, s=source_status: self.source_clicked.emit(s)
        self._sources[source_status.name] = row
        self.sources_layout.addWidget(row)
    
    def remove_source(self, name: str):
        """Remove a source from the monitor"""
        if name in self._sources:
            row = self._sources.pop(name)
            row.deleteLater()
    
    def update_source(self, name: str, status: SourceStatus):
        """Update a source's status"""
        if name in self._sources:
            self._sources[name].update_status(status)
            self._update_summary()
            self._update_timestamp()
    
    def _update_summary(self):
        """Update online/offline summary"""
        online = sum(1 for s in self._sources.values() 
                    if s.get_status().status == 'online')
        offline = sum(1 for s in self._sources.values() 
                     if s.get_status().status == 'offline')
        warning = sum(1 for s in self._sources.values() 
                      if s.get_status().status == 'warning')
        
        self.online_label.setText(f"🟢 {online} Online")
        self.offline_label.setText(f"🔴 {offline} Offline")
        
        if warning > 0:
            self.offline_label.setText(f"🔴 {offline} Offline  🟡 {warning} Warning")
    
    def _update_timestamp(self):
        """Update last updated timestamp"""
        self._last_updated = datetime.now()
        self.timestamp_label.setText(
            f"Last updated: {self._last_updated.strftime('%H:%M:%S')}"
        )
    
    def _simulate_updates(self):
        """Simulate live updates for demo purposes"""
        import random
        
        for name, row in self._sources.items():
            status = row.get_status()
            
            # Randomly fluctuate latency
            if status.status == 'online':
                new_latency = max(20, status.latency + random.randint(-30, 40))
                new_latency = min(new_latency, 600)
            else:
                new_latency = status.latency
            
            # Occasionally change status
            if random.random() < 0.05:  # 5% chance
                if status.status == 'online':
                    new_status = random.choice(['warning', 'checking'])
                elif status.status == 'warning':
                    new_status = random.choice(['online', 'offline'])
                elif status.status == 'offline':
                    new_status = 'checking'
                else:
                    new_status = 'online'
            else:
                new_status = status.status
            
            # Update articles count
            new_count = status.articles_count
            if status.status == 'online' and random.random() < 0.3:
                new_count += random.randint(0, 2)
            
            new_status_obj = SourceStatus(
                name=name,
                status=new_status,
                latency=new_latency if new_status != 'offline' else -1,
                last_updated=datetime.now(),
                articles_count=new_count,
                error_count=status.error_count
            )
            
            row.update_status(new_status_obj)
        
        self._update_summary()
        self._update_timestamp()
    
    def get_sources(self) -> Dict[str, SourceStatus]:
        """Get all source statuses"""
        return {name: row.get_status() for name, row in self._sources.items()}
    
    def clear(self):
        """Clear all sources"""
        for row in self._sources.values():
            row.deleteLater()
        self._sources.clear()
