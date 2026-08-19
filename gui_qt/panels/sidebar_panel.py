"""
Modernized Sidebar Panel.
Handles the dual-timer system (2-min Global, 20-min Full Scrape), Mode Selection, and UI controls.
"""

from PyQt6.QtWidgets import (
    QFrame, QVBoxLayout, QHBoxLayout, QLabel, 
    QPushButton, QScrollArea, QWidget, QComboBox
)
from PyQt6.QtCore import pyqtSignal, Qt, QTimer
from datetime import datetime
from gui_qt.theme import COLORS

class SidebarPanel(QFrame):
    """
    Modernized standalone sidebar widget.
    Controls the 2-minute (Global) and 20-minute (Deep Scrape) dual cycles.
    """
    
    # Signals
    start_feed_clicked = pyqtSignal()
    global_rotation_triggered = pyqtSignal()
    deep_scrape_triggered = pyqtSignal()
    mode_changed = pyqtSignal(str)
    view_live_monitor_clicked = pyqtSignal()
    view_custom_sources_clicked = pyqtSignal()
    history_clicked = pyqtSignal()


    def __init__(self, parent=None):
        super().__init__(parent)
        self.EXPANDED_WIDTH = 290
        self.setMinimumWidth(0)
        self.setMaximumWidth(self.EXPANDED_WIDTH)
        self.setStyleSheet(
            f"background-color: {COLORS.bg_dark}; border-right: 1px solid {COLORS.border};"
        )
        
        # Dual-Timers State
        self._global_secs = 300    # 5 minutes (matches backend refresh interval)
        self._deep_secs = 1200     # 20 minutes
        self._cycles_completed = 0
        self._is_live = False
        
        # UI Setup
        self._setup_ui()
        
        # Timers Initialization
        self._global_timer = QTimer(self)
        self._global_timer.timeout.connect(self._tick_global)
        
        self._deep_timer = QTimer(self)
        self._deep_timer.timeout.connect(self._tick_deep)
        
        self._pulse_state = True
        self._pulse_timer = QTimer(self)
        self._pulse_timer.timeout.connect(self._tick_pulse)

    def _setup_ui(self):
        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet("QScrollArea { border: none; background: transparent; }")
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        container = QWidget()
        container.setStyleSheet("background: transparent;")
        layout = QVBoxLayout(container)
        layout.setContentsMargins(16, 20, 16, 20)
        layout.setSpacing(16)

        # 1. Master Start/Stop Button
        self.start_btn = QPushButton("▶ Start Dual Engine")
        self.start_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.start_btn.setFixedHeight(50)
        self.start_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {COLORS.cyan};
                color: {COLORS.bg_dark};
                border-radius: 8px;
                font-size: 15px;
                font-weight: bold;
            }}
            QPushButton:hover {{ background-color: {COLORS.bright_cyan}; }}
        """)
        self.start_btn.clicked.connect(self._toggle_engine)
        layout.addWidget(self.start_btn)

        # 2. Live Monitor Button
        self.monitor_btn = QPushButton("🖥️ Lifecycle Monitor")
        self.monitor_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.monitor_btn.setFixedHeight(36)
        self.monitor_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {COLORS.bg_visual}; color: {COLORS.blue};
                border: 1px solid {COLORS.blue}; border-radius: 6px;
                font-size: 12px; font-weight: bold;
            }}
            QPushButton:hover {{ background-color: {COLORS.blue}; color: {COLORS.fg}; }}
        """)
        self.monitor_btn.clicked.connect(self.view_live_monitor_clicked.emit)
        layout.addWidget(self.monitor_btn)
        
        # 3. Custom Sources Manager Button
        self.custom_btn = QPushButton("⚙️ Custom Sources Manager")
        self.custom_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.custom_btn.setFixedHeight(36)
        self.custom_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {COLORS.bg_visual}; color: {COLORS.purple};
                border: 1px solid {COLORS.purple}; border-radius: 6px;
                font-size: 12px; font-weight: bold;
            }}
            QPushButton:hover {{ background-color: {COLORS.purple}; color: {COLORS.fg}; }}
        """)
        self.custom_btn.clicked.connect(self.view_custom_sources_clicked.emit)
        layout.addWidget(self.custom_btn)

        # 4. History Button
        self.history_btn = QPushButton("📜 Article History")
        self.history_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.history_btn.setFixedHeight(36)
        self.history_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {COLORS.bg_visual}; color: {COLORS.yellow};
                border: 1px solid {COLORS.yellow}; border-radius: 6px;
                font-size: 12px; font-weight: bold;
            }}
            QPushButton:hover {{ background-color: {COLORS.yellow}; color: {COLORS.bg_dark}; }}
        """)
        self.history_btn.clicked.connect(self.history_clicked.emit)
        layout.addWidget(self.history_btn)

        self._add_separator(layout)


        # 4. Timers Display
        timer_header = QLabel("⏱ ENGINE CYCLES")
        timer_header.setStyleSheet(f"color: {COLORS.comment}; font-weight: bold; font-size: 11px;")
        layout.addWidget(timer_header)

        # Global Timer (2m)
        g_layout = QHBoxLayout()
        g_lbl = QLabel("🌍 Global Rotation:")
        g_lbl.setStyleSheet(f"color: {COLORS.fg}; font-size: 12px;")
        self.global_countdown_lbl = QLabel("300s")
        self.global_countdown_lbl.setStyleSheet(f"color: {COLORS.green}; font-weight: bold;")
        g_layout.addWidget(g_lbl)
        g_layout.addStretch()
        g_layout.addWidget(self.global_countdown_lbl)
        layout.addLayout(g_layout)

        # Deep Scrape Timer (20m)
        d_layout = QHBoxLayout()
        d_lbl = QLabel("🛸 Deep Scrape:")
        d_lbl.setStyleSheet(f"color: {COLORS.fg}; font-size: 12px;")
        self.deep_countdown_lbl = QLabel("1200s")
        self.deep_countdown_lbl.setStyleSheet(f"color: {COLORS.orange}; font-weight: bold;")
        d_layout.addWidget(d_lbl)
        d_layout.addStretch()
        d_layout.addWidget(self.deep_countdown_lbl)
        layout.addLayout(d_layout)

        # Cycle Counter
        c_layout = QHBoxLayout()
        c_lbl = QLabel("🔄 Cycles Completed:")
        c_lbl.setStyleSheet(f"color: {COLORS.fg}; font-size: 12px;")
        self.cycles_lbl = QLabel("0")
        self.cycles_lbl.setStyleSheet(f"color: {COLORS.magenta}; font-weight: bold;")
        c_layout.addWidget(c_lbl)
        c_layout.addStretch()
        c_layout.addWidget(self.cycles_lbl)
        layout.addLayout(c_layout)

        self._add_separator(layout)

        # 5. Status Indicators
        self.live_indicator = QLabel("○ OFFLINE")
        self.live_indicator.setStyleSheet(f"color: {COLORS.comment}; font-weight: bold;")
        layout.addWidget(self.live_indicator)
        
        self.region_indicator = QLabel("🌍 Region: None")
        self.region_indicator.setStyleSheet(f"color: {COLORS.fg_dark};")
        layout.addWidget(self.region_indicator)

        layout.addStretch()
        
        # Stats
        self.stats_articles = QLabel("📰 Articles: 0")
        self.stats_sources = QLabel("🔗 Sources: 0")
        self.stats_articles.setStyleSheet(f"color: {COLORS.fg_dark};")
        self.stats_sources.setStyleSheet(f"color: {COLORS.fg_dark};")
        layout.addWidget(self.stats_articles)
        layout.addWidget(self.stats_sources)
        
        self._add_separator(layout)
        
        # 6. Mode & Intelligence (Legacy Support)
        self.mode_combo = QComboBox()
        self.mode_combo.addItems(["🚀 Ephemeral", "⚡ Hybrid", "💾 Persistent"])
        self.mode_combo.currentIndexChanged.connect(lambda i: self.mode_changed.emit(["ephemeral", "hybrid", "persistent"][i]))
        layout.addWidget(self.mode_combo)
        
        self._intel_labels = {}
        for key in ["Analyzed", "Disruptive", "High Priority"]:
            row = QHBoxLayout()
            lbl = QLabel(f"{key}:")
            val = QLabel("0")
            row.addWidget(lbl)
            row.addWidget(val)
            self._intel_labels[key] = val
            layout.addLayout(row)

        scroll.setWidget(container)
        main_l = QVBoxLayout(self)
        main_l.setContentsMargins(0, 0, 0, 0)
        main_l.addWidget(scroll)

    def _add_separator(self, layout: QVBoxLayout):
        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet(f"background-color: {COLORS.border};")
        sep.setFixedHeight(1)
        layout.addWidget(sep)

    def _toggle_engine(self):
        if not self._is_live:
            # Start
            self._is_live = True
            self.start_btn.setText("⏸ Stop Engine")
            self.start_btn.setStyleSheet(f"background-color: {COLORS.red}; color: {COLORS.bg_dark}; font-weight: bold; border-radius: 8px;")
            self._global_timer.start(1000)
            self._deep_timer.start(1000)
            self._pulse_timer.start(800)
            
            # Only trigger the initial feed fetch — deep scrape and global rotation
            # will fire on their first timer ticks to avoid 3× startup load
            self.start_feed_clicked.emit()
        else:
            # Stop
            self._is_live = False
            self.start_btn.setText("▶ Start Dual Engine")
            self.start_btn.setStyleSheet(f"background-color: {COLORS.cyan}; color: {COLORS.bg_dark}; font-weight: bold; border-radius: 8px;")
            self._global_timer.stop()
            self._deep_timer.stop()
            self._pulse_timer.stop()
            self.live_indicator.setText("○ OFFLINE")
            self.live_indicator.setStyleSheet(f"color: {COLORS.comment}; font-weight: bold;")

    def _tick_global(self):
        self._global_secs -= 1
        if self._global_secs <= 0:
            self._global_secs = 300
            self.global_countdown_lbl.setText("🔄")
            self.global_rotation_triggered.emit()
        else:
            self.global_countdown_lbl.setText(f"{self._global_secs}s")

    def _tick_deep(self):
        self._deep_secs -= 1
        if self._deep_secs <= 0:
            self._deep_secs = 1200
            self._cycles_completed += 1
            self.cycles_lbl.setText(str(self._cycles_completed))
            self.deep_countdown_lbl.setText("🔄")
            self.deep_scrape_triggered.emit()
        else:
            self.deep_countdown_lbl.setText(f"{self._deep_secs}s")

    def _tick_pulse(self):
        if not self._is_live: return
        self._pulse_state = not self._pulse_state
        color = COLORS.green if self._pulse_state else COLORS.fg_dark
        self.live_indicator.setText("● LIVE")
        self.live_indicator.setStyleSheet(f"color: {color}; font-weight: bold;")

    def update_stats(self, articles=0, sources=0, saved=0):
        self.stats_articles.setText(f"📰 Articles: {articles}")
        self.stats_sources.setText(f"🔗 Sources: {sources}")

    def set_live_status(self, is_live: bool, region: str = "", source_count: int = 0):
        self.region_indicator.setText(f"🌍 Region: {region} ({source_count} sources)")
        
    def update_intelligence_stats(self, analyzed=0, disruptive=0, high_priority=0):
        if "Analyzed" in self._intel_labels:
            self._intel_labels["Analyzed"].setText(str(analyzed))
            self._intel_labels["Disruptive"].setText(str(disruptive))
            self._intel_labels["High Priority"].setText(str(high_priority))
            
    def set_fetching(self, is_fetching: bool):
        pass # Stub since old sidebar had it

    def reset_countdown(self):
        self._global_secs = 300
        self.global_countdown_lbl.setText("300s")
