"""
Stats Panel Widget for Tech News Scraper
Displays live statistics matching tkinter sidebar
"""

from typing import Dict, Any, Optional

from PyQt6.QtWidgets import (
    QFrame, QVBoxLayout, QHBoxLayout, QLabel,
    QGridLayout, QWidget
)
from PyQt6.QtCore import pyqtSignal, Qt

from ..theme import COLORS, Fonts


class StatItem(QFrame):
    """Single statistic display item"""
    
    def __init__(
        self, 
        label: str, 
        value: str = "0",
        color: str = COLORS.cyan,
        parent=None
    ):
        super().__init__(parent)
        self._label = label
        self._value = value
        self._color = color
        
        self._setup_ui()
    
    def _setup_ui(self):
        """Build the stat item UI"""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 8, 12, 8)
        layout.setSpacing(4)
        
        # Label
        self.label = QLabel(self._label, self)
        self.label.setFont(Fonts.get_qfont('xs'))
        self.label.setStyleSheet(f"color: {COLORS.fg_dark};")
        layout.addWidget(self.label)
        
        # Value
        self.value_label = QLabel(self._value, self)
        self.value_label.setFont(Fonts.get_qfont('lg', 'bold'))
        self.value_label.setStyleSheet(f"color: {self._color};")
        layout.addWidget(self.value_label)
        
        # Card styling
        self.setStyleSheet(f"""
            QFrame {{
                background-color: {COLORS.bg_highlight};
                border-radius: 6px;
            }}
        """)
    
    def set_value(self, value: str):
        """Update the displayed value"""
        self._value = value
        self.value_label.setText(str(value))
    
    def set_color(self, color: str):
        """Update the value color"""
        self._color = color
        self.value_label.setStyleSheet(f"color: {color};")


class StatsPanel(QFrame):
    """Statistics panel displaying multiple stat items
    
    Matches the sidebar stats from tkinter gui/app.py
    """
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self._stats: Dict[str, StatItem] = {}
        
        self._setup_ui()
    
    def _setup_ui(self):
        """Build the stats panel UI"""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)
        
        # Header
        header = QLabel("📊 Statistics", self)
        header.setFont(Fonts.get_qfont('md', 'bold'))
        header.setStyleSheet(f"color: {COLORS.cyan};")
        layout.addWidget(header)
        
        # Stats grid
        self.stats_grid = QGridLayout()
        self.stats_grid.setSpacing(8)
        layout.addLayout(self.stats_grid)
        
        # Create default stats (matching tkinter)
        default_stats = [
            ("Articles", "0", COLORS.cyan, 0, 0),
            ("Sources", "0", COLORS.green, 0, 1),
            ("Queries", "0", COLORS.yellow, 1, 0),
            ("Rejected", "0", COLORS.red, 1, 1),
        ]
        
        for label, value, color, row, col in default_stats:
            stat_item = StatItem(label, value, color, self)
            self.stats_grid.addWidget(stat_item, row, col)
            self._stats[label.lower()] = stat_item
        
        # Intelligence section (v3.0)
        layout.addSpacing(8)
        
        intel_header = QLabel("🧠 Intelligence", self)
        intel_header.setFont(Fonts.get_qfont('md', 'bold'))
        intel_header.setStyleSheet(f"color: {COLORS.magenta};")
        layout.addWidget(intel_header)
        
        self.intel_grid = QGridLayout()
        self.intel_grid.setSpacing(8)
        layout.addLayout(self.intel_grid)
        
        intel_stats = [
            ("Analyzed", "0", COLORS.magenta, 0, 0),
            ("Disruptive", "0", COLORS.orange, 0, 1),
            ("High Priority", "0", COLORS.green, 1, 0),
            ("Avg Score", "0.0", COLORS.cyan, 1, 1),
        ]
        
        for label, value, color, row, col in intel_stats:
            stat_item = StatItem(label, value, color, self)
            self.intel_grid.addWidget(stat_item, row, col)
            self._stats[label.lower().replace(" ", "_")] = stat_item
        
        # Overall styling
        self.setStyleSheet(f"""
            QFrame {{
                background-color: transparent;
            }}
        """)
    
    def update_stat(self, key: str, value: Any):
        """Update a specific statistic
        
        Args:
            key: Stat key (lowercase, underscored)
            value: New value
        """
        key = key.lower().replace(" ", "_")
        if key in self._stats:
            if isinstance(value, float):
                self._stats[key].set_value(f"{value:.1f}")
            else:
                self._stats[key].set_value(str(value))
    
    def update_stats(self, stats: Dict[str, Any]):
        """Update multiple statistics at once
        
        Args:
            stats: Dictionary of stat key -> value
        """
        for key, value in stats.items():
            self.update_stat(key, value)
    
    def get_stat(self, key: str) -> Optional[str]:
        """Get current value of a stat"""
        key = key.lower().replace(" ", "_")
        if key in self._stats:
            return self._stats[key]._value
        return None


class LiveStatsPanel(StatsPanel):
    """Extended stats panel with live update support"""
    
    stats_updated = pyqtSignal(dict)
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.current_stats: Dict[str, Any] = {
            'articles': 0,
            'sources': 0,
            'queries': 0,
            'rejected': 0,
            'analyzed': 0,
            'disruptive': 0,
            'high_priority': 0,
            'avg_score': 0.0,
        }
    
    def update_stat(self, key: str, value: Any):
        """Update stat and track current value"""
        key = key.lower().replace(" ", "_")
        self.current_stats[key] = value
        super().update_stat(key, value)
        self.stats_updated.emit(self.current_stats.copy())
    
    def increment_stat(self, key: str, amount: int = 1):
        """Increment a stat by amount"""
        key = key.lower().replace(" ", "_")
        current = self.current_stats.get(key, 0)
        self.update_stat(key, current + amount)
    
    def reset(self):
        """Reset all stats to zero"""
        self.current_stats = {
            'articles': 0,
            'sources': 0,
            'queries': 0,
            'rejected': 0,
            'analyzed': 0,
            'disruptive': 0,
            'high_priority': 0,
            'avg_score': 0.0,
        }
        self.update_stats(self.current_stats)
