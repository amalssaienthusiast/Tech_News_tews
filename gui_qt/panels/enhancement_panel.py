"""
Enhancement Panel - Storage mode, personalization, and cache controls.

Features:
- Storage mode selection (ephemeral/hybrid/persistent)
- Personalization score display
- Redis cache statistics
- Export functionality
"""

from typing import Callable, Dict, Optional

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QComboBox, QFrame, QHBoxLayout, QLabel, QProgressBar,
    QPushButton, QVBoxLayout, QWidget
)

from gui_qt.theme import COLORS


class StorageModeWidget(QFrame):
    """Storage mode selector with status indicator."""
    
    mode_changed = pyqtSignal(str)
    
    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._setup_ui()
    
    def _setup_ui(self) -> None:
        self.setStyleSheet(f"""
            StorageModeWidget {{
                background-color: {COLORS.bg_highlight};
                border-radius: 8px;
            }}
        """)
        
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 12, 16, 12)
        layout.setSpacing(8)
        
        # Header
        header = QHBoxLayout()
        label = QLabel("💾 Storage Mode")
        label.setStyleSheet(f"color: {COLORS.fg}; font-weight: bold;")
        header.addWidget(label)
        
        self.status_dot = QLabel("●")
        self.status_dot.setStyleSheet(f"color: {COLORS.green}; font-size: 8px;")
        header.addWidget(self.status_dot)
        header.addStretch()
        layout.addLayout(header)
        
        # Mode selector
        self.mode_combo = QComboBox()
        self.mode_combo.addItems([
            "⚡ Ephemeral (memory only)",
            "🔄 Hybrid (cache + memory)",
            "💿 Persistent (full database)"
        ])
        self.mode_combo.setCurrentIndex(1)
        self.mode_combo.currentIndexChanged.connect(self._on_change)
        layout.addWidget(self.mode_combo)
        
        # Description
        self.desc = QLabel("Live feed with AI summary cache")
        self.desc.setStyleSheet(f"color: {COLORS.comment}; font-size: 11px;")
        layout.addWidget(self.desc)
    
    def _on_change(self, index: int) -> None:
        modes = ["ephemeral", "hybrid", "persistent"]
        descriptions = [
            "Articles auto-expire (2hr TTL)",
            "Live feed with AI summary cache",
            "Full database storage"
        ]
        self.desc.setText(descriptions[index])
        self.mode_changed.emit(modes[index])


class CacheStatsWidget(QFrame):
    """Redis cache statistics display."""
    
    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._setup_ui()
    
    def _setup_ui(self) -> None:
        self.setStyleSheet(f"""
            CacheStatsWidget {{
                background-color: {COLORS.bg_highlight};
                border-radius: 8px;
            }}
        """)
        
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 12, 16, 12)
        layout.setSpacing(8)
        
        # Header
        header = QHBoxLayout()
        label = QLabel("📊 Cache Stats")
        label.setStyleSheet(f"color: {COLORS.fg}; font-weight: bold;")
        header.addWidget(label)
        
        self.status = QLabel("Connected")
        self.status.setStyleSheet(f"color: {COLORS.green}; font-size: 11px;")
        header.addWidget(self.status)
        header.addStretch()
        layout.addLayout(header)
        
        # Stats
        self.stats = {}
        for key, label in [("hits", "Cache Hits"), ("misses", "Cache Misses"), ("summaries", "AI Summaries")]:
            row = QHBoxLayout()
            lbl = QLabel(label)
            lbl.setStyleSheet(f"color: {COLORS.fg}; font-size: 12px;")
            row.addWidget(lbl)
            row.addStretch()
            val = QLabel("0")
            val.setStyleSheet(f"color: {COLORS.cyan}; font-weight: bold;")
            row.addWidget(val)
            self.stats[key] = val
            layout.addLayout(row)
        
        # Hit rate bar
        self.hit_rate = QProgressBar()
        self.hit_rate.setRange(0, 100)
        self.hit_rate.setValue(0)
        self.hit_rate.setTextVisible(False)
        self.hit_rate.setFixedHeight(4)
        layout.addWidget(self.hit_rate)
    
    def update_stats(self, hits: int = 0, misses: int = 0, summaries: int = 0) -> None:
        """Update cache statistics."""
        self.stats["hits"].setText(str(hits))
        self.stats["misses"].setText(str(misses))
        self.stats["summaries"].setText(str(summaries))
        
        total = hits + misses
        rate = int((hits / total) * 100) if total > 0 else 0
        self.hit_rate.setValue(rate)
    
    def set_connected(self, connected: bool) -> None:
        """Update connection status."""
        if connected:
            self.status.setText("Connected")
            self.status.setStyleSheet(f"color: {COLORS.green}; font-size: 11px;")
        else:
            self.status.setText("Disconnected")
            self.status.setStyleSheet(f"color: {COLORS.red}; font-size: 11px;")


class PersonalizationWidget(QFrame):
    """Personalization score and settings."""
    
    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._setup_ui()
    
    def _setup_ui(self) -> None:
        self.setStyleSheet(f"""
            PersonalizationWidget {{
                background-color: {COLORS.bg_highlight};
                border-radius: 8px;
            }}
        """)
        
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 12, 16, 12)
        layout.setSpacing(8)
        
        # Header
        header = QLabel("🎯 Personalization")
        header.setStyleSheet(f"color: {COLORS.fg}; font-weight: bold;")
        layout.addWidget(header)
        
        # Active topics
        self.topics_label = QLabel("Topics: AI, Security")
        self.topics_label.setStyleSheet(f"color: {COLORS.cyan}; font-size: 12px;")
        layout.addWidget(self.topics_label)
        
        # Watchlist
        self.watchlist_label = QLabel("Watchlist: 5 companies")
        self.watchlist_label.setStyleSheet(f"color: {COLORS.comment}; font-size: 11px;")
        layout.addWidget(self.watchlist_label)
        
        # Score indicator
        score_row = QHBoxLayout()
        score_lbl = QLabel("Avg Score Boost")
        score_lbl.setStyleSheet(f"color: {COLORS.fg}; font-size: 12px;")
        score_row.addWidget(score_lbl)
        score_row.addStretch()
        self.score_val = QLabel("+15%")
        self.score_val.setStyleSheet(f"color: {COLORS.green}; font-weight: bold;")
        score_row.addWidget(self.score_val)
        layout.addLayout(score_row)
    
    def update_settings(self, topics: list = None, watchlist_count: int = 0, boost: float = 0) -> None:
        """Update personalization display."""
        if topics:
            self.topics_label.setText(f"Topics: {', '.join(topics[:3])}")
        self.watchlist_label.setText(f"Watchlist: {watchlist_count} companies")
        self.score_val.setText(f"+{boost:.0f}%")


class EnhancementPanel(QFrame):
    """Full enhancement panel combining all widgets."""
    
    mode_changed = pyqtSignal(str)
    export_requested = pyqtSignal()
    
    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._setup_ui()
    
    def _setup_ui(self) -> None:
        self.setStyleSheet(f"""
            EnhancementPanel {{
                background-color: {COLORS.bg_dark};
                border-left: 1px solid {COLORS.border};
            }}
        """)
        self.setFixedWidth(280)
        
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(16)
        
        # Header
        header = QLabel("⚙️ Enhancements")
        header.setStyleSheet(f"color: {COLORS.fg}; font-size: 16px; font-weight: bold;")
        layout.addWidget(header)
        
        # Storage mode
        self.storage = StorageModeWidget()
        self.storage.mode_changed.connect(self.mode_changed.emit)
        layout.addWidget(self.storage)
        
        # Cache stats
        self.cache = CacheStatsWidget()
        layout.addWidget(self.cache)
        
        # Personalization
        self.personalization = PersonalizationWidget()
        layout.addWidget(self.personalization)
        
        layout.addStretch()
        
        # Export button
        export_btn = QPushButton("📤 Export Saved")
        export_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {COLORS.bg_highlight};
                color: {COLORS.fg};
                border: 1px solid {COLORS.border};
                border-radius: 6px;
                padding: 10px;
            }}
            QPushButton:hover {{
                border-color: {COLORS.cyan};
            }}
        """)
        export_btn.clicked.connect(self.export_requested.emit)
        layout.addWidget(export_btn)
