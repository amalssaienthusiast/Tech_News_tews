"""
Global Discovery Page Widget.

A dedicated page for the Global Discovery Manager that shows:
- An interactive map of tech hubs worldwide
- Live rotation status with current region info
- Regional article feed with geo-tagged results
- Manual region selection for on-demand scanning

Navigation: Accessible via the "🌍 Global" button in the header bar.
"""

import asyncio
import logging
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional

from PyQt6.QtCore import Qt, QTimer, pyqtSignal, QPropertyAnimation, QEasingCurve
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QFrame, QScrollArea, QGridLayout, QSizePolicy,
    QProgressBar,
)
from PyQt6.QtGui import QFont

logger = logging.getLogger(__name__)

# Import colors from the main app module
try:
    from gui_qt.app_qt_migrated import COLORS
except ImportError:
    # Fallback colors
    class COLORS:
        bg = "#1e1e2e"
        bg_dark = "#181825"
        bg_visual = "#45475a"
        fg = "#cdd6f4"
        fg_dark = "#a6adc8"
        comment = "#6c7086"
        border = "#313244"
        cyan = "#89dceb"
        green = "#a6e3a1"
        yellow = "#f9e2af"
        orange = "#fab387"
        red = "#f38ba8"
        magenta = "#cba6f7"
        blue = "#89b4fa"
        bright_red = "#eba0ac"


# Tier colors for visual differentiation
TIER_COLORS = {
    10: "#a6e3a1",  # Tier 1 - Green (highest priority)
    9: "#94e2d5",
    8: "#89dceb",   # Tier 2 - Cyan
    7: "#74c7ec",
    6: "#89b4fa",   # Tier 3 - Blue
    5: "#b4befe",
    4: "#cba6f7",   # Tier 4 - Purple (lowest)
}


class HubCard(QFrame):
    """A card widget representing a single tech hub region."""
    
    clicked = pyqtSignal(object)  # Emits the hub object when clicked
    
    def __init__(self, hub: Any, is_active: bool = False, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self._hub = hub
        self._is_active = is_active
        self._article_count = 0
        self._setup_ui()
        self._apply_style()
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        
    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(4)
        
        # Header: Flag + Name
        header = QHBoxLayout()
        
        # Country flag emoji (using regional indicator symbols)
        flag = self._get_flag_emoji(self._hub.code)
        flag_label = QLabel(flag)
        flag_label.setStyleSheet(f"font-size: 24px;")
        header.addWidget(flag_label)
        
        name_label = QLabel(self._hub.name.split("(")[0].strip())
        name_label.setStyleSheet(f"color: {COLORS.fg}; font-size: 13px; font-weight: bold;")
        name_label.setWordWrap(True)
        header.addWidget(name_label, 1)
        
        # Priority badge
        priority = self._hub.priority
        color = TIER_COLORS.get(priority, COLORS.comment)
        priority_label = QLabel(f"P{priority}")
        priority_label.setStyleSheet(
            f"background-color: {color}; color: #1e1e2e; border-radius: 3px; "
            f"padding: 2px 6px; font-size: 10px; font-weight: bold;"
        )
        priority_label.setFixedHeight(18)
        header.addWidget(priority_label)
        
        layout.addLayout(header)
        
        # Topics
        topics_text = ", ".join(self._hub.topics[:3]) if self._hub.topics else "General"
        topics_label = QLabel(f"📋 {topics_text}")
        topics_label.setStyleSheet(f"color: {COLORS.comment}; font-size: 11px;")
        topics_label.setWordWrap(True)
        layout.addWidget(topics_label)
        
        # Stats line
        self._stats_label = QLabel("📰 0 articles")
        self._stats_label.setStyleSheet(f"color: {COLORS.fg_dark}; font-size: 11px;")
        layout.addWidget(self._stats_label)
        
        self.setFixedHeight(100)
        self.setMinimumWidth(200)
        
    def _apply_style(self):
        if self._is_active:
            border_color = COLORS.cyan
            bg = "#2a2a3a"
            shadow = f"border: 2px solid {COLORS.cyan};"
        else:
            border_color = COLORS.border
            bg = COLORS.bg_dark
            shadow = f"border: 1px solid {COLORS.border};"
            
        self.setStyleSheet(
            f"""
            HubCard {{
                background-color: {bg};
                {shadow}
                border-radius: 8px;
            }}
            HubCard:hover {{
                border: 1px solid {COLORS.cyan};
                background-color: #2a2a3a;
            }}
            """
        )
    
    def set_active(self, active: bool):
        self._is_active = active
        self._apply_style()
        
    def set_article_count(self, count: int):
        self._article_count = count
        self._stats_label.setText(f"📰 {count} articles")
        
    def mousePressEvent(self, event):
        self.clicked.emit(self._hub)
        super().mousePressEvent(event)
    
    @staticmethod
    def _get_flag_emoji(country_code: str) -> str:
        """Convert 2-letter country code to flag emoji."""
        try:
            return "".join(chr(0x1F1E6 + ord(c) - ord('A')) for c in country_code.upper())
        except Exception:
            return "🌍"


class GlobalDiscoveryPage(QWidget):
    """
    Full-page widget for the Global Discovery Manager.
    
    Shows all tech hubs on a grid, highlights the active one,
    and provides manual region selection for on-demand scanning.
    
    Signals:
        back_requested: Emitted when user wants to go back to feed view
        region_scan_requested: Emitted with hub object when user requests a scan
    """
    
    back_requested = pyqtSignal()
    region_scan_requested = pyqtSignal(object)
    
    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self._hub_cards: Dict[str, HubCard] = {}
        self._current_hub_code: str = "US"
        self._discovery_manager = None
        self._total_articles_by_hub: Dict[str, int] = {}
        self._setup_ui()
        
        # Auto-refresh timer for rotation status
        self._refresh_timer = QTimer(self)
        self._refresh_timer.timeout.connect(self._refresh_status)
        self._refresh_timer.start(5000)  # Every 5 seconds
    
    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        
        # ─── Top Bar ───
        top_bar = QFrame()
        top_bar.setStyleSheet(
            f"background-color: {COLORS.bg_dark}; border-bottom: 2px solid {COLORS.cyan};"
        )
        top_bar.setFixedHeight(60)
        top_layout = QHBoxLayout(top_bar)
        top_layout.setContentsMargins(16, 0, 16, 0)
        
        # Back button
        back_btn = QPushButton("← Back to Feed")
        back_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        back_btn.setStyleSheet(
            f"""
            QPushButton {{
                background-color: {COLORS.bg_visual};
                color: {COLORS.fg};
                border: 1px solid {COLORS.border};
                border-radius: 6px;
                padding: 8px 16px;
                font-weight: bold;
                font-size: 12px;
            }}
            QPushButton:hover {{
                border-color: {COLORS.cyan};
                color: {COLORS.cyan};
            }}
            """
        )
        back_btn.clicked.connect(self.back_requested.emit)
        top_layout.addWidget(back_btn)
        
        # Title
        title = QLabel("🌍 Global Discovery Manager")
        title.setStyleSheet(
            f"color: {COLORS.fg}; font-size: 18px; font-weight: bold; letter-spacing: 1px;"
        )
        top_layout.addWidget(title)
        top_layout.addStretch()
        
        # Active region indicator
        self._active_region_label = QLabel("🔄 Active: US — Silicon Valley")
        self._active_region_label.setStyleSheet(
            f"""
            background-color: {COLORS.cyan}22;
            color: {COLORS.cyan};
            border: 1px solid {COLORS.cyan};
            border-radius: 6px;
            padding: 6px 14px;
            font-weight: bold;
            font-size: 12px;
            """
        )
        top_layout.addWidget(self._active_region_label)
        
        # Rotation status
        self._rotation_label = QLabel("⏱️ Next rotation: --s")
        self._rotation_label.setStyleSheet(
            f"color: {COLORS.comment}; font-size: 11px; padding: 6px;"
        )
        top_layout.addWidget(self._rotation_label)
        
        layout.addWidget(top_bar)
        
        # ─── Stats Bar ───
        stats_bar = QFrame()
        stats_bar.setStyleSheet(
            f"background-color: {COLORS.bg}; border-bottom: 1px solid {COLORS.border};"
        )
        stats_bar.setFixedHeight(45)
        stats_layout = QHBoxLayout(stats_bar)
        stats_layout.setContentsMargins(16, 0, 16, 0)
        stats_layout.setSpacing(24)
        
        self._total_hubs_label = QLabel("📡 18 Tech Hubs")
        self._total_hubs_label.setStyleSheet(f"color: {COLORS.fg_dark}; font-size: 12px;")
        stats_layout.addWidget(self._total_hubs_label)
        
        self._total_articles_label = QLabel("📰 0 Total Articles")
        self._total_articles_label.setStyleSheet(f"color: {COLORS.green}; font-size: 12px;")
        stats_layout.addWidget(self._total_articles_label)
        
        self._coverage_label = QLabel("🌐 0/18 Regions Covered")
        self._coverage_label.setStyleSheet(f"color: {COLORS.yellow}; font-size: 12px;")
        stats_layout.addWidget(self._coverage_label)
        
        stats_layout.addStretch()
        
        # Scan All button
        scan_all_btn = QPushButton("🔄 Scan All Regions")
        scan_all_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        scan_all_btn.setStyleSheet(
            f"""
            QPushButton {{
                background-color: {COLORS.green};
                color: #1e1e2e;
                border: none;
                border-radius: 6px;
                padding: 6px 16px;
                font-weight: bold;
                font-size: 11px;
            }}
            QPushButton:hover {{
                background-color: #b6f3b1;
            }}
            """
        )
        scan_all_btn.clicked.connect(self._scan_all_regions)
        stats_layout.addWidget(scan_all_btn)
        
        layout.addWidget(stats_bar)
        
        # ─── Hub Grid (Scrollable) ───
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet(
            f"""
            QScrollArea {{
                background-color: {COLORS.bg};
                border: none;
            }}
            QScrollBar:vertical {{
                background-color: {COLORS.bg_dark};
                width: 10px;
                border-radius: 5px;
            }}
            QScrollBar::handle:vertical {{
                background-color: {COLORS.bg_visual};
                border-radius: 5px;
                min-height: 30px;
            }}
            """
        )
        
        grid_container = QWidget()
        grid_container.setStyleSheet(f"background-color: {COLORS.bg};")
        self._grid_layout = QGridLayout(grid_container)
        self._grid_layout.setContentsMargins(16, 16, 16, 16)
        self._grid_layout.setSpacing(12)
        
        # Section headers
        self._add_tier_section("🏆 Tier 1 — Major Tech Centers", 0)
        self._add_tier_section("🌟 Tier 2 — Major Markets", 2)
        self._add_tier_section("🚀 Tier 3 — Emerging Hubs", 4)
        self._add_tier_section("🔬 Tier 4 — Specialized Regions", 6)
        
        scroll.setWidget(grid_container)
        layout.addWidget(scroll, 1)
        
        # ─── Bottom Status ───
        bottom = QFrame()
        bottom.setStyleSheet(
            f"background-color: {COLORS.bg_dark}; border-top: 1px solid {COLORS.border};"
        )
        bottom.setFixedHeight(35)
        bottom_layout = QHBoxLayout(bottom)
        bottom_layout.setContentsMargins(16, 0, 16, 0)
        
        self._status_label = QLabel("🌍 Global Discovery Manager ready")
        self._status_label.setStyleSheet(f"color: {COLORS.comment}; font-size: 11px;")
        bottom_layout.addWidget(self._status_label)
        bottom_layout.addStretch()
        
        self._last_scan_label = QLabel("")
        self._last_scan_label.setStyleSheet(f"color: {COLORS.comment}; font-size: 11px;")
        bottom_layout.addWidget(self._last_scan_label)
        
        layout.addWidget(bottom)
    
    def _add_tier_section(self, title: str, row: int):
        """Add a tier section header to the grid."""
        label = QLabel(title)
        label.setStyleSheet(
            f"color: {COLORS.fg}; font-size: 14px; font-weight: bold; "
            f"padding: 8px 0 4px 0;"
        )
        self._grid_layout.addWidget(label, row, 0, 1, 4)
    
    def populate_hubs(self, hubs: list):
        """Populate the grid with hub cards from the GlobalDiscoveryManager."""
        # Clear existing cards
        self._hub_cards.clear()
        
        # Group by tier
        tiers = {
            "tier1": [h for h in hubs if h.priority >= 9],
            "tier2": [h for h in hubs if 7 <= h.priority < 9],
            "tier3": [h for h in hubs if 5 <= h.priority < 7],
            "tier4": [h for h in hubs if h.priority < 5],
        }
        
        tier_rows = {"tier1": 1, "tier2": 3, "tier3": 5, "tier4": 7}
        
        for tier_name, tier_hubs in tiers.items():
            row = tier_rows[tier_name]
            for col, hub in enumerate(tier_hubs):
                is_active = hub.code == self._current_hub_code
                card = HubCard(hub, is_active=is_active)
                card.clicked.connect(self._on_hub_clicked)
                
                # Update article count if we have stats
                count = self._total_articles_by_hub.get(hub.code, 0)
                card.set_article_count(count)
                
                self._hub_cards[hub.code] = card
                self._grid_layout.addWidget(card, row, col % 4)
                
                # If more than 4 per tier, add extra rows
                if col >= 4:
                    self._grid_layout.addWidget(card, row + 1, col % 4)
        
        self._total_hubs_label.setText(f"📡 {len(hubs)} Tech Hubs")
    
    def set_discovery_manager(self, manager):
        """Set the GlobalDiscoveryManager instance."""
        self._discovery_manager = manager
        if manager:
            self.populate_hubs(manager.hubs)
            self._refresh_status()
    
    def update_active_hub(self, hub_code: str, hub_name: str = ""):
        """Update which hub is currently active."""
        # Deactivate old
        if self._current_hub_code in self._hub_cards:
            self._hub_cards[self._current_hub_code].set_active(False)
        
        # Activate new
        self._current_hub_code = hub_code
        if hub_code in self._hub_cards:
            self._hub_cards[hub_code].set_active(True)
        
        display_name = hub_name or hub_code
        self._active_region_label.setText(f"🔄 Active: {hub_code} — {display_name}")
    
    def update_hub_stats(self, hub_code: str, article_count: int):
        """Update article count for a specific hub."""
        self._total_articles_by_hub[hub_code] = (
            self._total_articles_by_hub.get(hub_code, 0) + article_count
        )
        if hub_code in self._hub_cards:
            self._hub_cards[hub_code].set_article_count(
                self._total_articles_by_hub[hub_code]
            )
        
        # Update totals
        total = sum(self._total_articles_by_hub.values())
        covered = len([c for c in self._total_articles_by_hub.values() if c > 0])
        total_hubs = len(self._hub_cards) or 18
        
        self._total_articles_label.setText(f"📰 {total} Total Articles")
        self._coverage_label.setText(f"🌐 {covered}/{total_hubs} Regions Covered")
    
    def _refresh_status(self):
        """Refresh rotation status from the discovery manager."""
        if not self._discovery_manager:
            return
            
        try:
            hub = self._discovery_manager.get_current_hub()
            self.update_active_hub(hub.code, hub.name.split("(")[0].strip())
            
            # Calculate time until next rotation
            last_rot = self._discovery_manager.last_rotation
            interval = self._discovery_manager.rotation_interval
            elapsed = (datetime.now() - last_rot).total_seconds()
            remaining = max(0, interval - elapsed)
            self._rotation_label.setText(f"⏱️ Next rotation: {int(remaining)}s")
            
            # Update stats from manager
            stats = self._discovery_manager.get_stats()
            for code, count in stats.get("articles_by_region", {}).items():
                if code in self._hub_cards:
                    self._hub_cards[code].set_article_count(count)
                    
        except Exception as e:
            logger.debug(f"Status refresh error: {e}")
    
    def _on_hub_clicked(self, hub):
        """Handle manual hub selection — trigger on-demand scan."""
        self._status_label.setText(f"🔍 Scanning {hub.name}...")
        self.region_scan_requested.emit(hub)
        self._last_scan_label.setText(
            f"Last scan: {hub.code} at {datetime.now().strftime('%H:%M:%S')}"
        )
    
    def _scan_all_regions(self):
        """Trigger scan for all regions (sequentially via signals)."""
        if not self._discovery_manager:
            return
        
        self._status_label.setText("🔄 Scanning all regions...")
        for hub in self._discovery_manager.hubs:
            self.region_scan_requested.emit(hub)
