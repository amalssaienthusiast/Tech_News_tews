"""
Source Activity Matrix Widget
Grid showing all sources with activity indicators

Features:
- Grid showing all sources
- Progress bars for each source's fetch status
- Activity indicators (pulsing dots)
- Success/failure counters
"""

from typing import Dict, List, Optional
from dataclasses import dataclass, field
from datetime import datetime

from PyQt6.QtWidgets import (
    QFrame, QVBoxLayout, QHBoxLayout, QLabel, 
    QProgressBar, QGridLayout, QWidget, QSizePolicy,
    QScrollArea, QGraphicsOpacityEffect
)
from PyQt6.QtCore import Qt, QTimer, pyqtSignal, QPropertyAnimation, QEasingCurve
from PyQt6.QtGui import QColor, QFont

from ..theme import COLORS, Fonts


@dataclass
class SourceActivity:
    """Activity data for a single source"""
    name: str
    is_active: bool = False
    progress: int = 0  # 0-100
    success_count: int = 0
    failure_count: int = 0
    last_fetch: Optional[datetime] = None
    current_task: str = ""


class PulsingDot(QFrame):
    """Animated pulsing dot indicator"""
    
    def __init__(self, color: str = COLORS.cyan, parent=None):
        super().__init__(parent)
        self._color = color
        self._opacity_effect = QGraphicsOpacityEffect(self)
        self._opacity_effect.setOpacity(1.0)
        self.setGraphicsEffect(self._opacity_effect)
        
        self.setFixedSize(8, 8)
        self._apply_style()
        
        # Pulse animation
        self._animation = QPropertyAnimation(self._opacity_effect, b"opacity")
        self._animation.setDuration(1000)
        self._animation.setStartValue(1.0)
        self._animation.setEndValue(0.3)
        self._animation.setEasingCurve(QEasingCurve.Type.InOutSine)
        self._animation.setLoopCount(-1)  # Infinite
        self._animation.start()
    
    def _apply_style(self):
        self.setStyleSheet(f"""
            background-color: {self._color};
            border-radius: 4px;
        """)
    
    def set_color(self, color: str):
        self._color = color
        self._apply_style()
    
    def stop(self):
        self._animation.stop()
        self._opacity_effect.setOpacity(1.0)
    
    def start(self):
        self._animation.start()


class SourceActivityItem(QFrame):
    """Single source activity item in the matrix"""
    
    clicked = pyqtSignal(str)  # Emits source name
    
    def __init__(self, activity: SourceActivity, parent=None):
        super().__init__(parent)
        self._activity = activity
        self.setFixedSize(160, 90)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._setup_ui()
        self._apply_styles()
    
    def _setup_ui(self):
        """Build the activity item UI"""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.setSpacing(6)
        
        # Top row: Name and activity indicator
        top_layout = QHBoxLayout()
        top_layout.setSpacing(6)
        
        # Activity pulsing dot
        self.pulse_dot = PulsingDot(COLORS.cyan if self._activity.is_active else COLORS.comment, self)
        if not self._activity.is_active:
            self.pulse_dot.stop()
        top_layout.addWidget(self.pulse_dot)
        
        # Source name
        self.name_label = QLabel(self._activity.name[:15])
        self.name_label.setFont(Fonts.get_qfont('xs', 'bold'))
        self.name_label.setWordWrap(True)
        top_layout.addWidget(self.name_label, 1)
        
        layout.addLayout(top_layout)
        
        # Progress bar
        self.progress_bar = QProgressBar()
        self.progress_bar.setFixedHeight(6)
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(self._activity.progress)
        self.progress_bar.setTextVisible(False)
        layout.addWidget(self.progress_bar)
        
        # Status text
        self.status_label = QLabel(self._activity.current_task or "Idle")
        self.status_label.setFont(Fonts.get_qfont('xs'))
        self.status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.status_label)
        
        # Counters row
        counters_layout = QHBoxLayout()
        counters_layout.setSpacing(8)
        
        # Success count
        self.success_label = QLabel(f"✓ {self._activity.success_count}")
        self.success_label.setFont(Fonts.get_qfont('xs'))
        self.success_label.setStyleSheet(f"color: {COLORS.green};")
        counters_layout.addWidget(self.success_label)
        
        counters_layout.addStretch()
        
        # Failure count
        self.failure_label = QLabel(f"✗ {self._activity.failure_count}")
        self.failure_label.setFont(Fonts.get_qfont('xs'))
        failure_color = COLORS.red if self._activity.failure_count > 0 else COLORS.comment
        self.failure_label.setStyleSheet(f"color: {failure_color};")
        counters_layout.addWidget(self.failure_label)
        
        layout.addLayout(counters_layout)
    
    def _apply_styles(self):
        """Apply styles based on activity state"""
        if self._activity.is_active:
            border_color = COLORS.cyan
            bg_color = COLORS.bg_highlight
        elif self._activity.failure_count > self._activity.success_count:
            border_color = COLORS.red
            bg_color = COLORS.bg_visual
        else:
            border_color = COLORS.terminal_black
            bg_color = COLORS.bg_dark
        
        self.setStyleSheet(f"""
            SourceActivityItem {{
                background-color: {bg_color};
                border: 1px solid {border_color};
                border-radius: 6px;
            }}
            SourceActivityItem:hover {{
                border: 1px solid {COLORS.blue};
                background-color: {COLORS.bg_visual};
            }}
        """)
        
        # Progress bar color based on status
        if self._activity.is_active:
            progress_color = COLORS.cyan
        elif self._activity.failure_count > self._activity.success_count:
            progress_color = COLORS.red
        else:
            progress_color = COLORS.green
        
        self.progress_bar.setStyleSheet(f"""
            QProgressBar {{
                background-color: {COLORS.bg_dark};
                border: none;
                border-radius: 3px;
            }}
            QProgressBar::chunk {{
                background-color: {progress_color};
                border-radius: 3px;
            }}
        """)
        
        self.name_label.setStyleSheet(f"color: {COLORS.fg};")
        self.status_label.setStyleSheet(f"color: {COLORS.fg_dark};")
    
    def update_activity(self, activity: SourceActivity):
        """Update the activity display"""
        self._activity = activity
        
        # Update progress
        self.progress_bar.setValue(activity.progress)
        
        # Update status
        self.status_label.setText(activity.current_task or "Idle")
        
        # Update counters
        self.success_label.setText(f"✓ {activity.success_count}")
        self.failure_label.setText(f"✗ {activity.failure_count}")
        
        # Update pulsing dot
        if activity.is_active:
            self.pulse_dot.set_color(COLORS.cyan)
            self.pulse_dot.start()
        else:
            self.pulse_dot.set_color(COLORS.comment)
            self.pulse_dot.stop()
        
        self._apply_styles()
    
    def get_activity(self) -> SourceActivity:
        return self._activity
    
    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit(self._activity.name)
        super().mousePressEvent(event)


class SourceActivityMatrix(QFrame):
    """
    Source activity matrix widget
    
    Signals:
        source_clicked(str): Emitted when a source is clicked
    """
    
    source_clicked = pyqtSignal(str)
    
    def __init__(self, columns: int = 4, show_demo_data: bool = False, parent=None):
        super().__init__(parent)
        self._columns = columns
        self._sources: Dict[str, SourceActivityItem] = {}
        
        self.setObjectName("cardFrame")
        self.setFrameStyle(QFrame.Shape.StyledPanel | QFrame.Shadow.Plain)
        self._setup_ui()
        self._apply_styles()
        
        # Demo data is opt-in only (isolated widget preview/testing); the real
        # app starts this empty and calls add_source()/update_source() with
        # genuine per-source status.
        if show_demo_data:
            self._init_demo_sources()
        
        # Preview-only randomized stream; never started automatically.
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._simulate_activity)
    
    def _setup_ui(self):
        """Build the matrix UI"""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)
        
        # Header
        header_layout = QHBoxLayout()
        
        title = QLabel("📊 Source Activity Matrix")
        title.setObjectName("headerLabel")
        title.setFont(Fonts.get_qfont('md', 'bold'))
        header_layout.addWidget(title)
        
        header_layout.addStretch()
        
        # Active count
        self.active_label = QLabel("⚡ 0 Active")
        self.active_label.setFont(Fonts.get_qfont('sm'))
        self.active_label.setStyleSheet(f"color: {COLORS.cyan};")
        header_layout.addWidget(self.active_label)
        
        # Stats
        self.stats_label = QLabel("✓ 0 ✗ 0")
        self.stats_label.setFont(Fonts.get_qfont('sm'))
        self.stats_label.setStyleSheet(f"color: {COLORS.comment};")
        header_layout.addWidget(self.stats_label)
        
        layout.addLayout(header_layout)
        
        # Scroll area for matrix
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll_area.setStyleSheet(f"""
            QScrollArea {{
                background-color: {COLORS.bg};
                border: 1px solid {COLORS.terminal_black};
                border-radius: 6px;
            }}
        """)
        
        # Container for grid
        self.grid_container = QWidget()
        self.grid_layout = QGridLayout(self.grid_container)
        self.grid_layout.setContentsMargins(12, 12, 12, 12)
        self.grid_layout.setSpacing(10)
        
        scroll_area.setWidget(self.grid_container)
        layout.addWidget(scroll_area)
        
        # Footer
        footer_layout = QHBoxLayout()
        footer_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        
        legend_items = [
            (COLORS.cyan, "⚡ Active"),
            (COLORS.green, "✓ Success"),
            (COLORS.red, "✗ Failed"),
            (COLORS.comment, "⏸ Idle"),
        ]
        
        for color, text in legend_items:
            item = QLabel(text)
            item.setFont(Fonts.get_qfont('xs'))
            item.setStyleSheet(f"color: {color};")
            footer_layout.addWidget(item)
        
        layout.addLayout(footer_layout)
    
    def _apply_styles(self):
        """Apply widget styles"""
        self.setStyleSheet(f"""
            SourceActivityMatrix {{
                background-color: {COLORS.bg_highlight};
                border: 1px solid {COLORS.terminal_black};
                border-radius: 8px;
            }}
        """)
    
    def _init_demo_sources(self):
        """Initialize with demo sources"""
        demo_sources = [
            SourceActivity("Hacker News", True, 45, 120, 2, datetime.now(), "Fetching..."),
            SourceActivity("GitHub Trending", False, 0, 85, 0, datetime.now()),
            SourceActivity("Reddit r/programming", True, 72, 200, 5, datetime.now(), "Processing..."),
            SourceActivity("Dev.to", False, 0, 60, 1, datetime.now()),
            SourceActivity("Medium", True, 30, 45, 3, datetime.now(), "Scoring..."),
            SourceActivity("TechCrunch", False, 0, 30, 0, datetime.now()),
            SourceActivity("The Verge", False, 0, 25, 1, datetime.now()),
            SourceActivity("Ars Technica", True, 90, 40, 8, datetime.now(), "Filtering..."),
            SourceActivity("Wired", False, 0, 35, 0, datetime.now()),
            SourceActivity("Stack Overflow", False, 0, 150, 2, datetime.now()),
            SourceActivity("Product Hunt", True, 60, 55, 1, datetime.now(), "Discovering..."),
            SourceActivity("Smashing Magazine", False, 0, 20, 0, datetime.now()),
        ]
        
        for source in demo_sources:
            self.add_source(source)
        
        self._update_summary()
    
    def add_source(self, activity: SourceActivity):
        """Add a source to the matrix"""
        item = SourceActivityItem(activity, self)
        item.clicked.connect(self.source_clicked.emit)
        
        # Calculate grid position
        idx = len(self._sources)
        row = idx // self._columns
        col = idx % self._columns
        
        self.grid_layout.addWidget(item, row, col)
        self._sources[activity.name] = item
    
    def remove_source(self, name: str):
        """Remove a source from the matrix"""
        if name in self._sources:
            item = self._sources.pop(name)
            item.deleteLater()
            self._rebuild_grid()
    
    def _rebuild_grid(self):
        """Rebuild grid after removal"""
        # Clear layout
        while self.grid_layout.count():
            item = self.grid_layout.takeAt(0)
            if item.widget():
                item.widget().setParent(None)
        
        # Re-add items
        for idx, (name, item) in enumerate(self._sources.items()):
            row = idx // self._columns
            col = idx % self._columns
            self.grid_layout.addWidget(item, row, col)
    
    def update_source(self, name: str, activity: SourceActivity):
        """Update a source's activity"""
        if name in self._sources:
            self._sources[name].update_activity(activity)
            self._update_summary()
    
    def _update_summary(self):
        """Update summary statistics"""
        active = sum(1 for s in self._sources.values() if s.get_activity().is_active)
        total_success = sum(s.get_activity().success_count for s in self._sources.values())
        total_failures = sum(s.get_activity().failure_count for s in self._sources.values())
        
        self.active_label.setText(f"⚡ {active} Active")
        self.stats_label.setText(f"✓ {total_success} ✗ {total_failures}")
    
    def _simulate_activity(self):
        """Simulate source activity"""
        import random
        
        for name, item in self._sources.items():
            activity = item.get_activity()
            
            # Randomly toggle activity
            if random.random() < 0.1:  # 10% chance to toggle
                is_active = not activity.is_active
            else:
                is_active = activity.is_active
            
            # Update progress if active
            if is_active:
                progress = min(100, activity.progress + random.randint(5, 20))
                tasks = ["Fetching...", "Parsing...", "Scoring...", "Filtering...", "Storing..."]
                current_task = random.choice(tasks)
            else:
                progress = 0
                current_task = ""
            
            # Occasionally update counts
            success_count = activity.success_count
            failure_count = activity.failure_count
            
            if not is_active and activity.progress >= 100:
                if random.random() < 0.3:
                    if random.random() < 0.9:  # 90% success rate
                        success_count += random.randint(1, 5)
                    else:
                        failure_count += 1
            
            new_activity = SourceActivity(
                name=name,
                is_active=is_active,
                progress=progress if is_active else 0,
                success_count=success_count,
                failure_count=failure_count,
                last_fetch=datetime.now(),
                current_task=current_task
            )
            
            item.update_activity(new_activity)
        
        self._update_summary()
    
    def get_source_activity(self, name: str) -> Optional[SourceActivity]:
        """Get activity for a specific source"""
        if name in self._sources:
            return self._sources[name].get_activity()
        return None
    
    def get_all_activities(self) -> Dict[str, SourceActivity]:
        """Get all source activities"""
        return {name: item.get_activity() for name, item in self._sources.items()}
    
    def clear(self):
        """Clear all sources"""
        for item in self._sources.values():
            item.deleteLater()
        self._sources.clear()
        
        # Clear grid
        while self.grid_layout.count():
            item = self.grid_layout.takeAt(0)
            if item.widget():
                item.widget().setParent(None)
