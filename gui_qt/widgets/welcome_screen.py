"""
Welcome Screen Widget
Initial screen shown on app startup matching tkinter gui/app.py
"""

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QFrame, QGridLayout, QSpacerItem, QSizePolicy
)
from PyQt6.QtCore import pyqtSignal, Qt
from PyQt6.QtGui import QFont

from ..theme import COLORS, Fonts


class FeatureCard(QFrame):
    """Feature highlight card for welcome screen"""
    
    def __init__(self, icon: str, title: str, description: str, parent=None):
        super().__init__(parent)
        self._setup_ui(icon, title, description)
    
    def _setup_ui(self, icon: str, title: str, description: str):
        """Build the card UI"""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 12, 16, 12)
        layout.setSpacing(8)
        
        # Icon
        icon_label = QLabel(icon, self)
        icon_label.setStyleSheet(f"font-size: 24px;")
        layout.addWidget(icon_label)
        
        # Title
        title_label = QLabel(title, self)
        title_label.setFont(Fonts.get_qfont('md', 'bold'))
        title_label.setStyleSheet(f"color: {COLORS.fg};")
        layout.addWidget(title_label)
        
        # Description
        desc_label = QLabel(description, self)
        desc_label.setFont(Fonts.get_qfont('sm'))
        desc_label.setStyleSheet(f"color: {COLORS.fg_dark};")
        desc_label.setWordWrap(True)
        layout.addWidget(desc_label)
        
        # Card styling
        self.setStyleSheet(f"""
            QFrame {{
                background-color: {COLORS.bg_highlight};
                border-radius: 8px;
            }}
        """)


class WelcomeScreen(QWidget):
    """Welcome screen shown on app startup
    
    Signals:
        start_live_feed_clicked(): Emitted when user clicks start
        view_history_clicked(): Emitted when user wants to view history
        view_monitor_clicked(): Emitted when user wants live monitor
    """
    
    start_live_feed_clicked = pyqtSignal()
    view_history_clicked = pyqtSignal()
    view_monitor_clicked = pyqtSignal()
    
    VERSION = "7.0"
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self._setup_ui()
    
    def _setup_ui(self):
        """Build the welcome screen UI"""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(40, 30, 40, 30)
        layout.setSpacing(24)
        layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        
        # Spacer at top
        layout.addSpacing(20)
        
        # Header section
        header = self._create_header()
        layout.addWidget(header, 0, Qt.AlignmentFlag.AlignCenter)
        
        # Instructions section
        instructions = self._create_instructions()
        layout.addWidget(instructions)
        
        # System status section
        status = self._create_status_section()
        layout.addWidget(status)
        
        # CTA buttons
        buttons = self._create_buttons()
        layout.addLayout(buttons)
        
        # Spacer at bottom
        layout.addStretch()
        
        # Background
        self.setStyleSheet(f"""
            QWidget {{
                background-color: {COLORS.bg};
            }}
        """)
    
    def _create_header(self) -> QWidget:
        """Create header section with icon and title"""
        container = QFrame(self)
        layout = QVBoxLayout(container)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.setSpacing(12)
        
        # App icon
        icon = QLabel("📰", container)
        icon.setStyleSheet("font-size: 48px;")
        icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(icon)
        
        # Title
        title = QLabel("Welcome to Tech News Scraper", container)
        title.setFont(Fonts.get_qfont('2xl', 'bold'))
        title.setStyleSheet(f"color: {COLORS.fg};")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(title)
        
        # Subtitle
        subtitle = QLabel("Your intelligent tech news discovery platform", container)
        subtitle.setFont(Fonts.get_qfont('md'))
        subtitle.setStyleSheet(f"color: {COLORS.fg_dark};")
        subtitle.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(subtitle)
        
        # Version badge
        badge_container = QHBoxLayout()
        badge_container.setAlignment(Qt.AlignmentFlag.AlignCenter)
        
        version_badge = QLabel(f"v{self.VERSION}", container)
        version_badge.setFont(Fonts.get_qfont('sm', 'bold'))
        version_badge.setStyleSheet(f"""
            QLabel {{
                background-color: {COLORS.green};
                color: {COLORS.black};
                padding: 4px 12px;
                border-radius: 4px;
            }}
        """)
        badge_container.addWidget(version_badge)
        
        # Quantum badge
        quantum_badge = QLabel("⚡ Quantum", container)
        quantum_badge.setFont(Fonts.get_qfont('sm', 'bold'))
        quantum_badge.setStyleSheet(f"""
            QLabel {{
                background-color: {COLORS.magenta};
                color: {COLORS.black};
                padding: 4px 12px;
                border-radius: 4px;
                margin-left: 8px;
            }}
        """)
        badge_container.addWidget(quantum_badge)
        
        layout.addLayout(badge_container)
        
        return container
    
    def _create_instructions(self) -> QFrame:
        """Create getting started instructions"""
        container = QFrame(self)
        container.setStyleSheet(f"""
            QFrame {{
                background-color: {COLORS.bg_highlight};
                border-radius: 8px;
                padding: 20px;
            }}
        """)
        
        layout = QVBoxLayout(container)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(12)
        
        # Header
        header = QLabel("🚀 Getting Started", container)
        header.setFont(Fonts.get_qfont('lg', 'bold'))
        header.setStyleSheet(f"color: {COLORS.cyan};")
        layout.addWidget(header)
        
        # Instructions list
        instructions = [
            ("⚡", "START LIVE FEED", "Click to begin fetching articles from all sources"),
            ("📊", "View Live Monitor", "Monitor system activity and source status in real-time"),
            ("🔍", "Search", "Use the search bar to find specific articles"),
            ("📜", "View History", "Access previously fetched articles"),
        ]
        
        for icon, title, desc in instructions:
            row = QHBoxLayout()
            row.setSpacing(12)
            
            icon_label = QLabel(icon, container)
            icon_label.setStyleSheet("font-size: 16px;")
            icon_label.setFixedWidth(24)
            row.addWidget(icon_label)
            
            title_label = QLabel(title, container)
            title_label.setFont(Fonts.get_qfont('md', 'bold'))
            title_label.setStyleSheet(f"color: {COLORS.fg};")
            row.addWidget(title_label)
            
            sep = QLabel(" — ", container)
            sep.setStyleSheet(f"color: {COLORS.comment};")
            row.addWidget(sep)
            
            desc_label = QLabel(desc, container)
            desc_label.setFont(Fonts.get_qfont('sm'))
            desc_label.setStyleSheet(f"color: {COLORS.fg_dark};")
            row.addWidget(desc_label, 1)
            
            layout.addLayout(row)
        
        return container
    
    def _create_status_section(self) -> QFrame:
        """Create system status section"""
        container = QFrame(self)
        container.setStyleSheet(f"""
            QFrame {{
                background-color: {COLORS.bg_visual};
                border-radius: 8px;
            }}
        """)
        
        layout = QVBoxLayout(container)
        layout.setContentsMargins(24, 16, 24, 16)
        layout.setSpacing(16)
        
        # Header
        header = QLabel("📊 System Status", container)
        header.setFont(Fonts.get_qfont('md', 'bold'))
        header.setStyleSheet(f"color: {COLORS.green};")
        layout.addWidget(header)
        
        # Stats grid
        grid = QGridLayout()
        grid.setSpacing(12)
        
        stats = [
            ("Sources Ready", "10+", COLORS.cyan),
            ("RSS Feeds", "30+", COLORS.orange),
            ("APIs", "Google, Bing", COLORS.green),
            ("Status", "Ready", COLORS.bright_green),
        ]
        
        for i, (label, value, color) in enumerate(stats):
            stat_box = QFrame(container)
            stat_box.setStyleSheet(f"""
                QFrame {{
                    background-color: {COLORS.bg_highlight};
                    border-radius: 6px;
                    padding: 8px;
                }}
            """)
            
            stat_layout = QVBoxLayout(stat_box)
            stat_layout.setContentsMargins(12, 8, 12, 8)
            stat_layout.setSpacing(4)
            
            label_widget = QLabel(label, stat_box)
            label_widget.setFont(Fonts.get_qfont('xs'))
            label_widget.setStyleSheet(f"color: {COLORS.fg_dark};")
            stat_layout.addWidget(label_widget)
            
            value_widget = QLabel(value, stat_box)
            value_widget.setFont(Fonts.get_qfont('md', 'bold'))
            value_widget.setStyleSheet(f"color: {color};")
            stat_layout.addWidget(value_widget)
            
            grid.addWidget(stat_box, i // 2, i % 2)
        
        layout.addLayout(grid)
        
        return container
    
    def _create_buttons(self) -> QHBoxLayout:
        """Create CTA buttons"""
        layout = QHBoxLayout()
        layout.setSpacing(12)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        
        # Start Live Feed button (primary)
        self.start_btn = QPushButton("⚡ START LIVE FEED", self)
        self.start_btn.setFont(Fonts.get_qfont('md', 'bold'))
        self.start_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.start_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {COLORS.green};
                color: {COLORS.black};
                border: none;
                border-radius: 8px;
                padding: 14px 28px;
                font-weight: bold;
            }}
            QPushButton:hover {{
                background-color: {COLORS.bright_green};
            }}
            QPushButton:pressed {{
                background-color: #8ab45a;
            }}
        """)
        self.start_btn.clicked.connect(self.start_live_feed_clicked.emit)
        layout.addWidget(self.start_btn)
        
        # View Monitor button
        self.monitor_btn = QPushButton("📊 View Live Monitor", self)
        self.monitor_btn.setFont(Fonts.get_qfont('md', 'bold'))
        self.monitor_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.monitor_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {COLORS.blue};
                color: {COLORS.fg};
                border: none;
                border-radius: 8px;
                padding: 14px 20px;
            }}
            QPushButton:hover {{
                background-color: {COLORS.bright_blue};
            }}
        """)
        self.monitor_btn.clicked.connect(self.view_monitor_clicked.emit)
        layout.addWidget(self.monitor_btn)
        
        # View History button
        self.history_btn = QPushButton("📜 View History", self)
        self.history_btn.setFont(Fonts.get_qfont('md'))
        self.history_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.history_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {COLORS.bg_highlight};
                color: {COLORS.fg};
                border: 1px solid {COLORS.terminal_black};
                border-radius: 8px;
                padding: 14px 20px;
            }}
            QPushButton:hover {{
                background-color: {COLORS.bg_visual};
                border: 1px solid {COLORS.comment};
            }}
        """)
        self.history_btn.clicked.connect(self.view_history_clicked.emit)
        layout.addWidget(self.history_btn)
        
        return layout
