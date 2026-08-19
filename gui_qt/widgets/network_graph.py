"""
Network Throughput Graph Widget
Simple bar graph showing network activity in real-time

Features:
- Simple bar graph showing network activity
- Updates in real-time
- Shows throughput metrics
- Visual bars with gradient colors
"""

from typing import List, Optional, Deque
from dataclasses import dataclass
from collections import deque
from datetime import datetime

from PyQt6.QtWidgets import (
    QFrame, QVBoxLayout, QHBoxLayout, QLabel, 
    QWidget, QSizePolicy
)
from PyQt6.QtCore import Qt, QTimer, pyqtSignal, QRect
from PyQt6.QtGui import (
    QPainter, QLinearGradient, QColor, QPen, 
    QFont, QBrush, QFontMetrics
)

from ..theme import COLORS, Fonts


@dataclass
class ThroughputDataPoint:
    """Single throughput data point"""
    timestamp: datetime
    value: float  # bytes per second or similar metric
    label: str = ""


class BarGraphWidget(QWidget):
    """Custom widget for drawing bar graphs"""
    
    def __init__(self, max_bars: int = 30, parent=None):
        super().__init__(parent)
        self._max_bars = max_bars
        self._data: Deque[ThroughputDataPoint] = deque(maxlen=max_bars)
        self._max_value = 100.0  # Auto-scales
        self._bar_color_start = COLORS.blue
        self._bar_color_end = COLORS.magenta
        self._background_color = COLORS.bg_dark
        
        self.setMinimumHeight(150)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
    
    def set_gradient_colors(self, start: str, end: str):
        """Set gradient colors for bars"""
        self._bar_color_start = start
        self._bar_color_end = end
        self.update()
    
    def add_data_point(self, point: ThroughputDataPoint):
        """Add a data point to the graph"""
        self._data.append(point)
        
        # Auto-scale max value
        if point.value > self._max_value:
            self._max_value = point.value * 1.2  # Add 20% headroom
        elif self._max_value > 0 and point.value < self._max_value * 0.5:
            # Slowly decrease max if values are consistently lower
            self._max_value = max(point.value * 1.5, self._max_value * 0.95)
        
        self.update()
    
    def clear_data(self):
        """Clear all data points"""
        self._data.clear()
        self._max_value = 100.0
        self.update()
    
    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        
        # Fill background
        painter.fillRect(self.rect(), QColor(self._background_color))
        
        if not self._data:
            # Draw "No Data" text
            painter.setPen(QColor(COLORS.comment))
            font = Fonts.get_qfont('md', 'medium')
            painter.setFont(font)
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, "No Data")
            return
        
        # Calculate dimensions
        width = self.width()
        height = self.height()
        padding = 10
        graph_height = height - 2 * padding - 20  # Leave room for labels
        graph_width = width - 2 * padding
        
        # Draw grid lines
        painter.setPen(QPen(QColor(COLORS.terminal_black), 1, Qt.DotLine))
        for i in range(5):
            y = padding + (graph_height * i) / 4
            painter.drawLine(int(padding), int(y), int(width - padding), int(y))
        
        # Draw bars
        bar_width = graph_width / self._max_bars
        data_list = list(self._data)
        
        for i, point in enumerate(data_list):
            # Calculate bar dimensions
            bar_height = (point.value / self._max_value) * graph_height if self._max_value > 0 else 0
            x = padding + i * bar_width + 1  # Small gap between bars
            y = height - padding - 20 - bar_height
            
            # Create gradient
            gradient = QLinearGradient(x, y + bar_height, x, y)
            gradient.setColorAt(0, QColor(self._bar_color_start))
            gradient.setColorAt(1, QColor(self._bar_color_end))
            
            # Draw bar with rounded top
            bar_rect = QRect(int(x), int(y), int(bar_width - 2), int(bar_height))
            painter.fillRect(bar_rect, gradient)
            
            # Draw bar top highlight
            painter.setPen(QPen(QColor(self._bar_color_end), 1))
            painter.drawLine(int(x), int(y), int(x + bar_width - 3), int(y))
        
        # Draw baseline
        painter.setPen(QPen(QColor(COLORS.comment), 1))
        baseline_y = height - padding - 20
        painter.drawLine(int(padding), int(baseline_y), int(width - padding), int(baseline_y))
        
        # Draw labels
        painter.setPen(QColor(COLORS.fg_dark))
        font = Fonts.get_qfont('xs')
        painter.setFont(font)
        
        # Y-axis labels
        for i in range(5):
            value = self._max_value * (1 - i / 4)
            y = padding + (graph_height * i) / 4
            label_text = f"{value:.0f}"
            painter.drawText(2, int(y - 5), int(padding - 4), 10, Qt.AlignmentFlag.AlignRight, label_text)
        
        painter.end()
    
    def get_data(self) -> List[ThroughputDataPoint]:
        """Get all data points"""
        return list(self._data)


class NetworkThroughputGraph(QFrame):
    """
    Network throughput graph widget
    
    Signals:
        clicked(): Emitted when the graph is clicked
    """
    
    clicked = pyqtSignal()
    
    def __init__(self, show_demo_data: bool = False, parent=None):
        super().__init__(parent)
        self._current_value = 0.0
        self._peak_value = 0.0
        self._average_value = 0.0
        self._unit = "KB/s"
        
        self.setObjectName("cardFrame")
        self.setFrameStyle(QFrame.Shape.StyledPanel | QFrame.Shadow.Plain)
        self._setup_ui()
        self._apply_styles()
        
        # Demo data is opt-in only (isolated widget preview/testing); the real
        # app starts this at zero and calls add_data_point()/set_value() with
        # genuine measurements.
        if show_demo_data:
            self._init_demo_data()
        
        # Preview-only randomized stream; never started automatically.
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._simulate_data)
    
    def _setup_ui(self):
        """Build the graph UI"""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)
        
        # Header
        header_layout = QHBoxLayout()
        
        title = QLabel("📈 Network Throughput")
        title.setObjectName("headerLabel")
        title.setFont(Fonts.get_qfont('md', 'bold'))
        header_layout.addWidget(title)
        
        header_layout.addStretch()
        
        # Current value
        self.current_label = QLabel("0 KB/s")
        self.current_label.setFont(Fonts.get_qfont('lg', 'bold'))
        self.current_label.setStyleSheet(f"color: {COLORS.cyan};")
        header_layout.addWidget(self.current_label)
        
        layout.addLayout(header_layout)
        
        # Graph widget
        self.graph = BarGraphWidget(max_bars=40, parent=self)
        self.graph.set_gradient_colors(COLORS.blue, COLORS.magenta)
        layout.addWidget(self.graph, 1)
        
        # Stats row
        stats_layout = QHBoxLayout()
        
        # Peak
        peak_container = QFrame()
        peak_container.setStyleSheet(f"""
            QFrame {{
                background-color: {COLORS.bg_dark};
                border-radius: 4px;
                padding: 4px 8px;
            }}
        """)
        peak_layout = QHBoxLayout(peak_container)
        peak_layout.setContentsMargins(8, 4, 8, 4)
        peak_layout.setSpacing(6)
        
        peak_icon = QLabel("🚀")
        peak_icon.setFont(Fonts.get_qfont('xs'))
        peak_layout.addWidget(peak_icon)
        
        peak_text = QLabel("Peak:")
        peak_text.setFont(Fonts.get_qfont('xs'))
        peak_text.setStyleSheet(f"color: {COLORS.comment};")
        peak_layout.addWidget(peak_text)
        
        self.peak_label = QLabel("0 KB/s")
        self.peak_label.setFont(Fonts.get_qfont('xs', 'bold'))
        self.peak_label.setStyleSheet(f"color: {COLORS.magenta};")
        peak_layout.addWidget(self.peak_label)
        
        stats_layout.addWidget(peak_container)
        
        # Average
        avg_container = QFrame()
        avg_container.setStyleSheet(f"""
            QFrame {{
                background-color: {COLORS.bg_dark};
                border-radius: 4px;
                padding: 4px 8px;
            }}
        """)
        avg_layout = QHBoxLayout(avg_container)
        avg_layout.setContentsMargins(8, 4, 8, 4)
        avg_layout.setSpacing(6)
        
        avg_icon = QLabel("📊")
        avg_icon.setFont(Fonts.get_qfont('xs'))
        avg_layout.addWidget(avg_icon)
        
        avg_text = QLabel("Avg:")
        avg_text.setFont(Fonts.get_qfont('xs'))
        avg_text.setStyleSheet(f"color: {COLORS.comment};")
        avg_layout.addWidget(avg_text)
        
        self.avg_label = QLabel("0 KB/s")
        self.avg_label.setFont(Fonts.get_qfont('xs', 'bold'))
        self.avg_label.setStyleSheet(f"color: {COLORS.green};")
        avg_layout.addWidget(self.avg_label)
        
        stats_layout.addWidget(avg_container)
        
        # Total
        total_container = QFrame()
        total_container.setStyleSheet(f"""
            QFrame {{
                background-color: {COLORS.bg_dark};
                border-radius: 4px;
                padding: 4px 8px;
            }}
        """)
        total_layout = QHBoxLayout(total_container)
        total_layout.setContentsMargins(8, 4, 8, 4)
        total_layout.setSpacing(6)
        
        total_icon = QLabel("📥")
        total_icon.setFont(Fonts.get_qfont('xs'))
        total_layout.addWidget(total_icon)
        
        total_text = QLabel("Total:")
        total_text.setFont(Fonts.get_qfont('xs'))
        total_text.setStyleSheet(f"color: {COLORS.comment};")
        total_layout.addWidget(total_text)
        
        self.total_label = QLabel("0 MB")
        self.total_label.setFont(Fonts.get_qfont('xs', 'bold'))
        self.total_label.setStyleSheet(f"color: {COLORS.yellow};")
        total_layout.addWidget(self.total_label)
        
        stats_layout.addWidget(total_container)
        
        stats_layout.addStretch()
        
        layout.addLayout(stats_layout)
        
        # Legend/footer
        footer_layout = QHBoxLayout()
        footer_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        
        # Time range indicator
        self.time_range_label = QLabel("Last 20 seconds")
        self.time_range_label.setFont(Fonts.get_qfont('xs'))
        self.time_range_label.setStyleSheet(f"color: {COLORS.comment};")
        footer_layout.addWidget(self.time_range_label)
        
        layout.addLayout(footer_layout)
    
    def _apply_styles(self):
        """Apply widget styles"""
        self.setStyleSheet(f"""
            NetworkThroughputGraph {{
                background-color: {COLORS.bg_highlight};
                border: 1px solid {COLORS.terminal_black};
                border-radius: 8px;
            }}
        """)
    
    def _init_demo_data(self):
        """Initialize with demo data"""
        import random
        
        now = datetime.now()
        for i in range(30):
            value = random.uniform(20, 100)
            point = ThroughputDataPoint(
                timestamp=now,
                value=value,
                label=f"{value:.1f}"
            )
            self.graph.add_data_point(point)
        
        self._update_stats()
    
    def add_data_point(self, value: float, label: str = ""):
        """Add a throughput data point"""
        point = ThroughputDataPoint(
            timestamp=datetime.now(),
            value=value,
            label=label or f"{value:.1f}"
        )
        self.graph.add_data_point(point)
        self._current_value = value
        self._update_stats()
    
    def _update_stats(self):
        """Update statistics display"""
        data = self.graph.get_data()
        if not data:
            return
        
        values = [d.value for d in data]
        
        # Current
        self._current_value = values[-1]
        self.current_label.setText(f"{self._current_value:.1f} {self._unit}")
        
        # Peak
        self._peak_value = max(self._peak_value, max(values))
        self.peak_label.setText(f"{self._peak_value:.1f} {self._unit}")
        
        # Average
        self._average_value = sum(values) / len(values)
        self.avg_label.setText(f"{self._average_value:.1f} {self._unit}")
        
        # Total (simulated)
        total_mb = sum(values) * 0.5 / 1024  # Rough approximation
        self.total_label.setText(f"{total_mb:.2f} MB")
    
    def _simulate_data(self):
        """Simulate network throughput data"""
        import random
        
        # Simulate varying network activity
        base_value = 50.0
        variation = random.uniform(-20, 30)
        burst = random.uniform(0, 40) if random.random() < 0.2 else 0  # Occasional bursts
        
        value = max(5, base_value + variation + burst)
        
        self.add_data_point(value)
    
    def set_unit(self, unit: str):
        """Set the unit for display (e.g., KB/s, MB/s, req/s)"""
        self._unit = unit
        self._update_stats()
    
    def clear(self):
        """Clear all data"""
        self.graph.clear_data()
        self._current_value = 0.0
        self._peak_value = 0.0
        self._average_value = 0.0
        self._update_stats()
    
    def get_current_value(self) -> float:
        """Get current throughput value"""
        return self._current_value
    
    def get_peak_value(self) -> float:
        """Get peak throughput value"""
        return self._peak_value
    
    def get_average_value(self) -> float:
        """Get average throughput value"""
        return self._average_value
    
    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()
        super().mousePressEvent(event)
