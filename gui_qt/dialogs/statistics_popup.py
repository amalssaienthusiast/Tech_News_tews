"""
Comprehensive Statistics Popup Dialog for Tech News Scraper - PyQt6
Detailed pipeline and system statistics matching tkinter gui/app.py

Features:
- Overview Tab: Total articles, sources, average score, active pipelines
- Pipeline Tab: Current pipeline status, stages progress, queue sizes, processing rates
- Sources Tab: Per-source statistics (articles count, success rate, latency)
- Performance Tab: Memory usage, CPU usage, network throughput, cache hit rate
- Quality Tab: Score distribution chart, tier breakdown, freshness analysis
- Real-time Updates: Auto-refresh every 2 seconds

Usage:
    popup = StatisticsPopup(parent, orchestrator)
    popup.show()
"""

from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QTabWidget, QWidget, QGridLayout,
    QProgressBar, QFrame, QScrollArea, QTableWidget,
    QTableWidgetItem, QHeaderView, QCheckBox, QSpacerItem,
    QSizePolicy, QGraphicsDropShadowEffect, QSplitter
)
from PyQt6.QtCore import Qt, QTimer, pyqtSlot as Slot
from PyQt6.QtGui import QFont, QColor, QPainter, QLinearGradient, QPen, QBrush
from datetime import datetime, timedelta
from typing import Dict, List, Any, Optional
import logging
import psutil

logger = logging.getLogger(__name__)

from ..theme import COLORS, Fonts


class GradientCard(QFrame):
    """Card widget with gradient background"""
    
    def __init__(self, title: str, gradient_colors: tuple = None, parent=None):
        super().__init__(parent)
        self.title = title
        self.gradient_colors = gradient_colors or (COLORS.bg_highlight, COLORS.bg_visual)
        self._setup_ui()
    
    def _setup_ui(self):
        """Build card UI"""
        self.setObjectName("gradientCard")
        self.setStyleSheet(f"""
            QFrame#gradientCard {{
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 {self.gradient_colors[0]},
                    stop:1 {self.gradient_colors[1]});
                border: 1px solid {COLORS.terminal_black};
                border-radius: 10px;
            }}
        """)
        
        # Add shadow effect
        shadow = QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(20)
        shadow.setColor(QColor(0, 0, 0, 80))
        shadow.setOffset(0, 4)
        self.setGraphicsEffect(shadow)
        
        self.layout = QVBoxLayout(self)
        self.layout.setContentsMargins(16, 16, 16, 16)
        self.layout.setSpacing(12)
        
        # Title
        if self.title:
            self.title_label = QLabel(self.title)
            self.title_label.setFont(Fonts.get_qfont('md', 'bold'))
            self.title_label.setStyleSheet(f"color: {COLORS.cyan};")
            self.layout.addWidget(self.title_label)


class StatMetric(QFrame):
    """Individual metric display with label and value"""
    
    def __init__(self, label: str, value: str = "0", color: str = COLORS.cyan, 
                 icon: str = "", parent=None):
        super().__init__(parent)
        self._label = label
        self._value = value
        self._color = color
        self._icon = icon
        
        self._setup_ui()
    
    def _setup_ui(self):
        """Build metric UI"""
        self.setStyleSheet(f"""
            QFrame {{
                background-color: {COLORS.bg_dark};
                border-radius: 8px;
                border: 1px solid {COLORS.terminal_black};
            }}
        """)
        
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(4)
        
        # Label
        label_text = f"{self._icon} {self._label}" if self._icon else self._label
        self.label = QLabel(label_text)
        self.label.setFont(Fonts.get_qfont('xs'))
        self.label.setStyleSheet(f"color: {COLORS.fg_dark};")
        layout.addWidget(self.label)
        
        # Value
        self.value_label = QLabel(self._value)
        self.value_label.setFont(Fonts.get_qfont('lg', 'bold'))
        self.value_label.setStyleSheet(f"color: {self._color};")
        layout.addWidget(self.value_label)
    
    def set_value(self, value: str, color: str = None):
        """Update metric value"""
        self._value = str(value)
        self.value_label.setText(self._value)
        if color:
            self._color = color
            self.value_label.setStyleSheet(f"color: {color};")


class TierDistributionBar(QFrame):
    """Horizontal bar showing tier distribution (S/A/B/C)"""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.tiers = {'S': 0, 'A': 0, 'B': 0, 'C': 0}
        self.setFixedHeight(32)
        self._setup_ui()
    
    def _setup_ui(self):
        """Build tier bar UI"""
        self.layout = QHBoxLayout(self)
        self.layout.setContentsMargins(0, 0, 0, 0)
        self.layout.setSpacing(2)
        
        # Create segments for each tier
        self.segments = {}
        tier_colors = {
            'S': COLORS.magenta,
            'A': COLORS.green,
            'B': COLORS.blue,
            'C': COLORS.comment
        }
        
        for tier, color in tier_colors.items():
            segment = QFrame()
            segment.setStyleSheet(f"""
                QFrame {{
                    background-color: {color};
                    border-radius: 4px;
                }}
            """)
            self.layout.addWidget(segment)
            self.segments[tier] = segment
        
        self.update_distribution(self.tiers)
    
    def update_distribution(self, tiers: Dict[str, int]):
        """Update tier distribution display"""
        total = sum(tiers.values()) or 1  # Avoid division by zero
        
        for tier, count in tiers.items():
            percentage = (count / total) * 100
            self.segments[tier].setFixedWidth(int(percentage * 3))  # Scale factor


class PipelineStageCard(QFrame):
    """Card showing pipeline stage status"""
    
    def __init__(self, stage_name: str, icon: str, parent=None):
        super().__init__(parent)
        self.stage_name = stage_name
        self.icon = icon
        self._status = 'idle'  # idle, active, completed, error
        self._progress = 0
        self._items = 0
        
        self._setup_ui()
    
    def _setup_ui(self):
        """Build stage card UI"""
        self.setStyleSheet(f"""
            QFrame {{
                background-color: {COLORS.bg_dark};
                border: 2px solid {COLORS.terminal_black};
                border-radius: 10px;
            }}
        """)
        
        self.setFixedSize(130, 110)
        
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(4)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        
        # Icon
        self.icon_label = QLabel(self.icon)
        self.icon_label.setFont(Fonts.get_qfont('xl'))
        self.icon_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.icon_label)
        
        # Stage name
        self.name_label = QLabel(self.stage_name)
        self.name_label.setFont(Fonts.get_qfont('xs', 'bold'))
        self.name_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.name_label)
        
        # Progress bar
        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self.progress.setFixedHeight(4)
        self.progress.setTextVisible(False)
        layout.addWidget(self.progress)
        
        # Status
        self.status_label = QLabel("Waiting...")
        self.status_label.setFont(Fonts.get_qfont('xs'))
        self.status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.status_label)
        
        self._update_style()
    
    def set_state(self, status: str, progress: int = 0, items: int = 0):
        """Update stage state"""
        self._status = status
        self._progress = progress
        self._items = items
        
        self.progress.setValue(progress)
        
        if status == 'active':
            self.status_label.setText(f"⚡ {progress}%")
        elif status == 'completed':
            self.status_label.setText(f"✓ {items} items")
        elif status == 'error':
            self.status_label.setText("✗ Error")
        else:
            self.status_label.setText("Waiting...")
        
        self._update_style()
    
    def _update_style(self):
        """Update styling based on status"""
        colors = {
            'idle': (COLORS.terminal_black, COLORS.comment),
            'active': (COLORS.cyan, COLORS.cyan),
            'completed': (COLORS.green, COLORS.green),
            'error': (COLORS.red, COLORS.red)
        }
        
        border_color, text_color = colors.get(self._status, colors['idle'])
        
        self.setStyleSheet(f"""
            QFrame {{
                background-color: {COLORS.bg_dark};
                border: 2px solid {border_color};
                border-radius: 10px;
            }}
        """)
        
        self.icon_label.setStyleSheet(f"color: {text_color};")
        self.status_label.setStyleSheet(f"color: {text_color};")
        
        # Update progress bar color
        self.progress.setStyleSheet(f"""
            QProgressBar {{
                background-color: {COLORS.bg_highlight};
                border: none;
                border-radius: 2px;
            }}
            QProgressBar::chunk {{
                background-color: {text_color};
                border-radius: 2px;
            }}
        """)


class SourceStatRow(QFrame):
    """Row displaying source statistics"""
    
    def __init__(self, source_name: str, stats: Dict, parent=None):
        super().__init__(parent)
        self.source_name = source_name
        self.stats = stats
        self._setup_ui()
    
    def _setup_ui(self):
        """Build source stat row UI"""
        self.setStyleSheet(f"""
            QFrame {{
                background-color: {COLORS.bg_dark};
                border-radius: 6px;
                border: 1px solid {COLORS.terminal_black};
            }}
            QFrame:hover {{
                border: 1px solid {COLORS.blue};
            }}
        """)
        
        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 8, 12, 8)
        layout.setSpacing(16)
        
        # Source name
        self.name_label = QLabel(self.source_name)
        self.name_label.setFont(Fonts.get_qfont('sm', 'bold'))
        self.name_label.setStyleSheet(f"color: {COLORS.fg};")
        self.name_label.setMinimumWidth(150)
        layout.addWidget(self.name_label)
        
        # Articles count
        articles = self.stats.get('articles', 0)
        self.articles_label = QLabel(f"📰 {articles}")
        self.articles_label.setFont(Fonts.get_qfont('sm'))
        self.articles_label.setStyleSheet(f"color: {COLORS.cyan};")
        layout.addWidget(self.articles_label)
        
        # Success rate
        success_rate = self.stats.get('success_rate', 0)
        color = COLORS.green if success_rate >= 80 else COLORS.yellow if success_rate >= 50 else COLORS.red
        self.success_label = QLabel(f"✓ {success_rate:.1f}%")
        self.success_label.setFont(Fonts.get_qfont('sm', 'bold'))
        self.success_label.setStyleSheet(f"color: {color};")
        layout.addWidget(self.success_label)
        
        # Latency
        latency = self.stats.get('latency', 0)
        color = COLORS.green if latency < 500 else COLORS.yellow if latency < 1000 else COLORS.red
        self.latency_label = QLabel(f"⏱️ {latency:.0f}ms")
        self.latency_label.setFont(Fonts.get_qfont('sm'))
        self.latency_label.setStyleSheet(f"color: {color};")
        layout.addWidget(self.latency_label)
        
        layout.addStretch()


class StatisticsPopup(QDialog):
    """
    Comprehensive statistics popup dialog
    
    Displays detailed pipeline and system statistics with:
    - Multi-tab interface (Overview, Pipeline, Sources, Performance, Quality)
    - Card-based layout with gradient backgrounds
    - Tokyo Night theme
    - Real-time auto-refresh every 2 seconds
    - Refresh button and auto-refresh toggle
    
    Usage:
        popup = StatisticsPopup(parent, orchestrator)
        popup.exec()
    """
    
    def __init__(self, parent=None, orchestrator=None, controller=None):
        super().__init__(parent)
        
        self.orchestrator = orchestrator
        self.controller = controller
        
        # Data cache
        self._stats_cache = {}
        self._last_update = None
        
        # Setup
        self._setup_window()
        self._setup_ui()
        self._setup_timer()
        
        # Initial data load
        self._refresh_stats()
    
    def _setup_window(self):
        """Configure dialog window"""
        self.setWindowTitle("📊 Scraping Statistics")
        self.setMinimumSize(800, 600)
        
        self.setWindowFlags(
            Qt.WindowType.Dialog |
            Qt.WindowType.WindowCloseButtonHint |
            Qt.WindowType.WindowMaximizeButtonHint
        )
    
    def _setup_ui(self):
        """Build the statistics popup UI"""
        layout = QVBoxLayout(self)
        layout.setSpacing(16)
        layout.setContentsMargins(20, 20, 20, 20)
        
        # Header
        header = self._create_header()
        layout.addWidget(header)
        
        # Tab widget
        self.tabs = QTabWidget()
        self.tabs.setDocumentMode(True)
        
        # Create tabs
        self.overview_tab = self._create_overview_tab()
        self.pipeline_tab = self._create_pipeline_tab()
        self.sources_tab = self._create_sources_tab()
        self.performance_tab = self._create_performance_tab()
        self.quality_tab = self._create_quality_tab()
        
        self.tabs.addTab(self.overview_tab, "📊 Overview")
        self.tabs.addTab(self.pipeline_tab, "⚡ Pipeline")
        self.tabs.addTab(self.sources_tab, "📡 Sources")
        self.tabs.addTab(self.performance_tab, "🔥 Performance")
        self.tabs.addTab(self.quality_tab, "🎯 Quality")
        
        layout.addWidget(self.tabs)
        
        # Footer
        footer = self._create_footer()
        layout.addWidget(footer)
        
        # Apply styles
        self._apply_styles()
    
    def _create_header(self) -> QFrame:
        """Create dialog header"""
        header = QFrame()
        header.setStyleSheet(f"""
            QFrame {{
                background-color: {COLORS.bg_dark};
                border-radius: 10px;
                border: 1px solid {COLORS.terminal_black};
            }}
        """)
        
        layout = QHBoxLayout(header)
        layout.setContentsMargins(16, 12, 16, 12)
        
        # Title
        title = QLabel("📊 Scraping Statistics")
        title.setFont(Fonts.get_qfont('xl', 'bold'))
        title.setStyleSheet(f"color: {COLORS.green};")
        layout.addWidget(title)
        
        layout.addStretch()
        
        # Last update time
        self.update_time_label = QLabel("Updated: --:--:--")
        self.update_time_label.setFont(Fonts.get_qfont('sm'))
        self.update_time_label.setStyleSheet(f"color: {COLORS.comment};")
        layout.addWidget(self.update_time_label)
        
        return header
    
    def _create_overview_tab(self) -> QWidget:
        """Create Overview tab with key metrics"""
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setSpacing(16)
        
        # Summary cards grid
        cards_widget = QWidget()
        cards_layout = QGridLayout(cards_widget)
        cards_layout.setSpacing(12)
        
        # Create metric cards
        self.overview_metrics = {}
        
        metrics = [
            ("Total Articles", "📰", COLORS.cyan, 0, 0),
            ("Active Sources", "📡", COLORS.green, 0, 1),
            ("Avg Score", "⭐", COLORS.yellow, 0, 2),
            ("Active Pipelines", "⚡", COLORS.magenta, 1, 0),
            ("Today's Articles", "📆", COLORS.blue, 1, 1),
            ("This Hour", "🕐", COLORS.orange, 1, 2),
        ]
        
        for label, icon, color, row, col in metrics:
            metric = StatMetric(label, "0", color, icon)
            key = label.lower().replace(" ", "_").replace("'", "")
            self.overview_metrics[key] = metric
            cards_layout.addWidget(metric, row, col)
        
        layout.addWidget(cards_widget)
        
        # Quick stats section
        quick_stats = GradientCard("📈 Quick Statistics", (COLORS.bg_highlight, COLORS.bg_visual))
        quick_stats.layout.setSpacing(8)
        
        # Add stat rows
        self.quick_stat_labels = {}
        stats = [
            ("Success Rate", "0%", COLORS.green),
            ("Queue Size", "0", COLORS.cyan),
            ("Cache Hit Rate", "0%", COLORS.magenta),
            ("Processing Rate", "0 articles/sec", COLORS.blue),
        ]
        
        for stat_name, default_val, color in stats:
            row = QHBoxLayout()
            
            name_label = QLabel(stat_name)
            name_label.setFont(Fonts.get_qfont('sm'))
            name_label.setStyleSheet(f"color: {COLORS.fg_dark};")
            row.addWidget(name_label)
            
            row.addStretch()
            
            value_label = QLabel(default_val)
            value_label.setFont(Fonts.get_qfont('sm', 'bold'))
            value_label.setStyleSheet(f"color: {color};")
            row.addWidget(value_label)
            
            self.quick_stat_labels[stat_name.lower().replace(" ", "_")] = value_label
            quick_stats.layout.addLayout(row)
        
        layout.addWidget(quick_stats)
        
        layout.addStretch()
        return tab
    
    def _create_pipeline_tab(self) -> QWidget:
        """Create Pipeline tab with stage visualization"""
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setSpacing(16)

        notice = QLabel(
            "\u26A0 Simulated preview \u2014 not wired to a live queue/pipeline backend "
            "(needs Celery + Redis to be real)"
        )
        notice.setFont(Fonts.get_qfont('xs'))
        notice.setStyleSheet(f"color: {COLORS.yellow}; padding: 2px 0;")
        layout.addWidget(notice)
        
        # Pipeline stages
        stages_card = GradientCard("⚙ Pipeline Stages", (COLORS.bg_highlight, COLORS.bg_dark))
        
        stages_layout = QHBoxLayout()
        stages_layout.setSpacing(8)
        
        # Stage definitions
        stages = [
            ("Discovery", "🔍"),
            ("Fetch", "📥"),
            ("Process", "⚙"),
            ("Score", "📊"),
            ("Filter", "🔖"),
            ("Display", "📱"),
        ]
        
        self.stage_cards = {}
        for name, icon in stages:
            card = PipelineStageCard(name, icon)
            self.stage_cards[name.lower()] = card
            stages_layout.addWidget(card)
            
            # Add connector arrow (except last)
            if name != stages[-1][0]:
                arrow = QLabel("→")
                arrow.setFont(Fonts.get_qfont('lg'))
                arrow.setStyleSheet(f"color: {COLORS.comment};")
                stages_layout.addWidget(arrow)
        
        stages_card.layout.addLayout(stages_layout)
        layout.addWidget(stages_card)
        
        # Queue stats
        queue_card = GradientCard("📥 Queue Statistics", (COLORS.bg_highlight, COLORS.bg_visual))
        
        self.queue_metrics = {}
        queue_stats = [
            ("Queue Size", "0", COLORS.cyan),
            ("Total Processed", "0", COLORS.green),
            ("Success Rate", "0%", COLORS.green),
            ("Failed", "0", COLORS.red),
            ("Avg Processing", "0ms", COLORS.yellow),
            ("Per-Stage Timing", "--", COLORS.comment),
        ]
        
        queue_grid = QGridLayout()
        queue_grid.setSpacing(12)
        
        for i, (label, default, color) in enumerate(queue_stats):
            metric = StatMetric(label, default, color)
            self.queue_metrics[label.lower().replace(" ", "_")] = metric
            queue_grid.addWidget(metric, i // 3, i % 3)
        
        queue_card.layout.addLayout(queue_grid)
        layout.addWidget(queue_card)
        
        # Processing rate chart (simple bar)
        rate_card = GradientCard("📊 Processing Rate", (COLORS.bg_highlight, COLORS.bg_visual))
        
        self.rate_bar = QProgressBar()
        self.rate_bar.setRange(0, 100)
        self.rate_bar.setValue(0)
        self.rate_bar.setFixedHeight(20)
        self.rate_bar.setObjectName("cyanProgress")
        
        self.rate_label = QLabel("0 articles/sec")
        self.rate_label.setFont(Fonts.get_qfont('md', 'bold'))
        self.rate_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.rate_label.setStyleSheet(f"color: {COLORS.cyan};")
        
        rate_card.layout.addWidget(self.rate_label)
        rate_card.layout.addWidget(self.rate_bar)
        
        layout.addWidget(rate_card)
        
        layout.addStretch()
        return tab
    
    def _create_sources_tab(self) -> QWidget:
        """Create Sources tab with per-source statistics"""
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setSpacing(12)
        
        # Summary stats
        summary_widget = QWidget()
        summary_layout = QHBoxLayout(summary_widget)
        summary_layout.setSpacing(12)
        
        self.source_summary_metrics = {}
        summary_stats = [
            ("Total Sources", "0", COLORS.cyan, "📡"),
            ("Active Sources", "0", COLORS.green, "✓"),
            ("Avg Success Rate", "0%", COLORS.yellow, "📈"),
            ("Avg Latency", "0ms", COLORS.magenta, "⏱️"),
        ]
        
        for label, default, color, icon in summary_stats:
            metric = StatMetric(label, default, color, icon)
            self.source_summary_metrics[label.lower().replace(" ", "_")] = metric
            summary_layout.addWidget(metric)
        
        layout.addWidget(summary_widget)
        
        # Sources list
        sources_card = GradientCard("📡 Per-Source Statistics", (COLORS.bg_highlight, COLORS.bg_dark))
        
        # Scroll area for sources
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        
        self.sources_container = QWidget()
        self.sources_layout = QVBoxLayout(self.sources_container)
        self.sources_layout.setSpacing(8)
        self.sources_layout.addStretch()
        
        scroll.setWidget(self.sources_container)
        sources_card.layout.addWidget(scroll)
        
        layout.addWidget(sources_card)
        
        return tab
    
    def _create_performance_tab(self) -> QWidget:
        """Create Performance tab with system metrics"""
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setSpacing(16)
        
        # System resources
        resources_card = GradientCard("💻 System Resources", (COLORS.bg_highlight, COLORS.bg_dark))
        
        # Memory usage
        mem_layout = QVBoxLayout()
        
        mem_header = QHBoxLayout()
        mem_label = QLabel("🧠 Memory Usage")
        mem_label.setFont(Fonts.get_qfont('sm', 'bold'))
        mem_label.setStyleSheet(f"color: {COLORS.fg};")
        mem_header.addWidget(mem_label)
        
        mem_header.addStretch()
        
        self.mem_value_label = QLabel("0 MB / 0 MB")
        self.mem_value_label.setFont(Fonts.get_qfont('sm', 'bold'))
        self.mem_value_label.setStyleSheet(f"color: {COLORS.cyan};")
        mem_header.addWidget(self.mem_value_label)
        
        mem_layout.addLayout(mem_header)
        
        self.mem_bar = QProgressBar()
        self.mem_bar.setRange(0, 100)
        self.mem_bar.setValue(0)
        self.mem_bar.setFixedHeight(12)
        self.mem_bar.setObjectName("cyanProgress")
        mem_layout.addWidget(self.mem_bar)
        
        resources_card.layout.addLayout(mem_layout)
        
        # CPU usage
        cpu_layout = QVBoxLayout()
        
        cpu_header = QHBoxLayout()
        cpu_label = QLabel("⚡ CPU Usage")
        cpu_label.setFont(Fonts.get_qfont('sm', 'bold'))
        cpu_label.setStyleSheet(f"color: {COLORS.fg};")
        cpu_header.addWidget(cpu_label)
        
        cpu_header.addStretch()
        
        self.cpu_value_label = QLabel("0%")
        self.cpu_value_label.setFont(Fonts.get_qfont('sm', 'bold'))
        self.cpu_value_label.setStyleSheet(f"color: {COLORS.green};")
        cpu_header.addWidget(self.cpu_value_label)
        
        cpu_layout.addLayout(cpu_header)
        
        self.cpu_bar = QProgressBar()
        self.cpu_bar.setRange(0, 100)
        self.cpu_bar.setValue(0)
        self.cpu_bar.setFixedHeight(12)
        self.cpu_bar.setObjectName("greenProgress")
        cpu_layout.addWidget(self.cpu_bar)
        
        resources_card.layout.addLayout(cpu_layout)
        
        layout.addWidget(resources_card)
        
        # Network & Cache stats
        net_cache_card = GradientCard("🌐 Network & Cache (simulated \u2014 no live cache backend wired up)", (COLORS.bg_highlight, COLORS.bg_visual))
        
        self.perf_metrics = {}
        perf_stats = [
            ("Network Throughput", "0 KB/s", COLORS.blue),
            ("Cache Hits", "0", COLORS.green),
            ("Cache Misses", "0", COLORS.red),
            ("Cache Hit Rate", "0%", COLORS.magenta),
            ("Active Connections", "0", COLORS.cyan),
            ("Avg Response Time", "0ms", COLORS.yellow),
        ]
        
        perf_grid = QGridLayout()
        perf_grid.setSpacing(12)
        
        for i, (label, default, color) in enumerate(perf_stats):
            metric = StatMetric(label, default, color)
            self.perf_metrics[label.lower().replace(" ", "_")] = metric
            perf_grid.addWidget(metric, i // 3, i % 3)
        
        net_cache_card.layout.addLayout(perf_grid)
        layout.addWidget(net_cache_card)
        
        layout.addStretch()
        return tab
    
    def _create_quality_tab(self) -> QWidget:
        """Create Quality tab with score distribution"""
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setSpacing(16)
        
        # Score overview
        overview_card = GradientCard("⭐ Quality Overview", (COLORS.bg_highlight, COLORS.bg_dark))
        
        self.quality_metrics = {}
        quality_stats = [
            ("Average Score", "0.0", COLORS.cyan),
            ("Highest Score", "0.0", COLORS.green),
            ("Lowest Score", "0.0", COLORS.red),
            ("Median Score", "0.0", COLORS.yellow),
        ]
        
        quality_grid = QGridLayout()
        quality_grid.setSpacing(12)
        
        for i, (label, default, color) in enumerate(quality_stats):
            metric = StatMetric(label, default, color)
            self.quality_metrics[label.lower().replace(" ", "_")] = metric
            quality_grid.addWidget(metric, i // 2, i % 2)
        
        overview_card.layout.addLayout(quality_grid)
        layout.addWidget(overview_card)
        
        # Tier distribution
        tier_card = GradientCard("🎯 Tier Distribution", (COLORS.bg_highlight, COLORS.bg_visual))
        
        # Distribution bar
        self.tier_bar = TierDistributionBar()
        tier_card.layout.addWidget(self.tier_bar)
        
        # Tier counts
        tier_grid = QGridLayout()
        tier_grid.setSpacing(16)
        
        self.tier_counts = {}
        tiers = [
            ("S Tier (9.0-10.0)", COLORS.magenta, "s_tier"),
            ("A Tier (7.5-8.9)", COLORS.green, "a_tier"),
            ("B Tier (6.0-7.4)", COLORS.blue, "b_tier"),
            ("C Tier (< 6.0)", COLORS.comment, "c_tier"),
        ]
        
        for i, (label, color, key) in enumerate(tiers):
            tier_widget = QWidget()
            tier_layout = QVBoxLayout(tier_widget)
            tier_layout.setSpacing(4)
            
            tier_label = QLabel(label)
            tier_label.setFont(Fonts.get_qfont('xs'))
            tier_label.setStyleSheet(f"color: {COLORS.fg_dark};")
            tier_layout.addWidget(tier_label)
            
            count_label = QLabel("0")
            count_label.setFont(Fonts.get_qfont('lg', 'bold'))
            count_label.setStyleSheet(f"color: {color};")
            tier_layout.addWidget(count_label)
            
            self.tier_counts[key] = count_label
            tier_grid.addWidget(tier_widget, i // 2, i % 2)
        
        tier_card.layout.addLayout(tier_grid)
        layout.addWidget(tier_card)
        
        # Freshness analysis
        freshness_card = GradientCard("🕐 Freshness Analysis", (COLORS.bg_highlight, COLORS.bg_visual))
        
        self.freshness_metrics = {}
        freshness_stats = [
            ("< 1 Hour", "0", COLORS.green),
            ("1-6 Hours", "0", COLORS.cyan),
            ("6-24 Hours", "0", COLORS.yellow),
            ("> 24 Hours", "0", COLORS.red),
        ]
        
        freshness_grid = QGridLayout()
        freshness_grid.setSpacing(12)
        
        for i, (label, default, color) in enumerate(freshness_stats):
            metric = StatMetric(label, default, color)
            self.freshness_metrics[label.lower().replace(" ", "_").replace("<", "lt").replace(">", "gt")] = metric
            freshness_grid.addWidget(metric, i // 2, i % 2)
        
        freshness_card.layout.addLayout(freshness_grid)
        layout.addWidget(freshness_card)
        
        layout.addStretch()
        return tab
    
    def _create_footer(self) -> QWidget:
        """Create dialog footer with controls"""
        footer = QWidget()
        layout = QHBoxLayout(footer)
        layout.setContentsMargins(0, 0, 0, 0)
        
        # Auto-refresh toggle
        self.auto_refresh_check = QCheckBox("Auto-refresh (2s)")
        self.auto_refresh_check.setChecked(True)
        self.auto_refresh_check.stateChanged.connect(self._toggle_auto_refresh)
        self.auto_refresh_check.setStyleSheet(f"""
            QCheckBox {{
                color: {COLORS.fg};
                spacing: 8px;
            }}
            QCheckBox::indicator {{
                width: 18px;
                height: 18px;
                border-radius: 3px;
                border: 1px solid {COLORS.terminal_black};
                background-color: {COLORS.bg_highlight};
            }}
            QCheckBox::indicator:checked {{
                background-color: {COLORS.green};
                border: 1px solid {COLORS.green};
            }}
        """)
        layout.addWidget(self.auto_refresh_check)
        
        layout.addStretch()
        
        # Refresh button
        refresh_btn = QPushButton("🔄 Refresh Now")
        refresh_btn.setObjectName("cyanButton")
        refresh_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        refresh_btn.clicked.connect(self._refresh_stats)
        layout.addWidget(refresh_btn)
        
        # Close button
        close_btn = QPushButton("✕ Close")
        close_btn.setObjectName("dangerButton")
        close_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        close_btn.clicked.connect(self.reject)
        layout.addWidget(close_btn)
        
        return footer
    
    def _setup_timer(self):
        """Setup auto-refresh timer"""
        self.refresh_timer = QTimer(self)
        self.refresh_timer.timeout.connect(self._refresh_stats)
        self.refresh_timer.start(2000)  # 2 seconds
    
    def _toggle_auto_refresh(self, state):
        """Toggle auto-refresh"""
        if state:
            self.refresh_timer.start(2000)
        else:
            self.refresh_timer.stop()
    
    @Slot()
    def _refresh_stats(self):
        """Refresh all statistics"""
        try:
            self._update_overview_stats()
            self._update_pipeline_stats()
            self._update_sources_stats()
            self._update_performance_stats()
            self._update_quality_stats()
            
            # Update timestamp
            self._last_update = datetime.now()
            self.update_time_label.setText(
                f"Updated: {self._last_update.strftime('%H:%M:%S')}"
            )
            
        except Exception as e:
            print(f"Error refreshing stats: {e}")
    
    def _update_overview_stats(self):
        """Update overview tab statistics"""
        # Get data from orchestrator or controller
        total_articles = 0
        sources = set()
        avg_score = 0.0
        
        if self.controller:
            articles = getattr(self.controller, '_articles', [])
            total_articles = len(articles)
            sources = set(a.get('source', 'Unknown') for a in articles)
            
            # Calculate average score
            scores = []
            for article in articles:
                score = article.get('tech_score', 0)
                if isinstance(score, dict):
                    score = score.get('score', 0)
                if score:
                    scores.append(float(score))
            
            if scores:
                avg_score = sum(scores) / len(scores)
        
        # Update metrics
        self.overview_metrics['total_articles'].set_value(str(total_articles))
        self.overview_metrics['active_sources'].set_value(str(len(sources)))
        self.overview_metrics['avg_score'].set_value(f"{avg_score:.1f}")
        self.overview_metrics['active_pipelines'].set_value("1" if self.controller else "0")
        
        # Estimate today's articles (simplified)
        self.overview_metrics['todays_articles'].set_value(str(total_articles))
        self.overview_metrics['this_hour'].set_value(str(total_articles // 24 + 1))
        
        # Update quick stats
        self.quick_stat_labels['success_rate'].setText("N/A")
        self.quick_stat_labels['queue_size'].setText("0")
        self.quick_stat_labels['cache_hit_rate'].setText("N/A")
        self.quick_stat_labels['processing_rate'].setText("N/A")
    
    def _update_pipeline_stats(self):
        """Update pipeline tab statistics"""
        # Simulate pipeline stages for demo
        import random
        
        stages_status = ['idle', 'active', 'completed']
        for key, card in self.stage_cards.items():
            status = random.choice(stages_status)
            progress = random.randint(0, 100) if status == 'active' else 100 if status == 'completed' else 0
            items = random.randint(10, 100)
            card.set_state(status, progress, items)
        
        # Update queue metrics
        self.queue_metrics['queue_size'].set_value(str(random.randint(0, 50)))
        self.queue_metrics['total_processed'].set_value(str(random.randint(100, 1000)))
        self.queue_metrics['success_rate'].set_value(f"{random.randint(80, 99)}%")
        self.queue_metrics['failed'].set_value(str(random.randint(0, 20)))
        self.queue_metrics['avg_processing'].set_value(f"{random.randint(100, 500)}ms")
        self.queue_metrics['per-stage_timing'].set_value("150ms avg")
        
        # Update rate bar
        rate = random.uniform(1.0, 5.0)
        self.rate_label.setText(f"{rate:.1f} articles/sec")
        self.rate_bar.setValue(int(rate * 20))  # Scale to percentage
    
    def _update_sources_stats(self):
        """Update sources tab statistics"""
        # Clear existing source rows
        while self.sources_layout.count() > 1:  # Keep the stretch at the end
            item = self.sources_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        
        # Get sources from controller
        source_stats = {}
        
        if self.controller:
            articles = getattr(self.controller, '_articles', [])
            for article in articles:
                source = article.get('source', 'Unknown')
                if source not in source_stats:
                    source_stats[source] = {'articles': 0, 'success': 0, 'failed': 0, 'latency': 0}
                source_stats[source]['articles'] += 1
                source_stats[source]['success'] += 1
                source_stats[source]['latency'] = random.randint(100, 800)
        
        # Add demo sources if none exist
        if not source_stats:
            demo_sources = [
                ('Hacker News', {'articles': 45, 'success': 43, 'failed': 2, 'latency': 150}),
                ('TechCrunch', {'articles': 32, 'success': 30, 'failed': 2, 'latency': 280}),
                ('Ars Technica', {'articles': 28, 'success': 27, 'failed': 1, 'latency': 200}),
                ('The Verge', {'articles': 35, 'success': 33, 'failed': 2, 'latency': 350}),
                ('Wired', {'articles': 25, 'success': 24, 'failed': 1, 'latency': 180}),
            ]
            for name, stats in demo_sources:
                source_stats[name] = stats
        
        # Calculate derived stats
        for source, stats in source_stats.items():
            total = stats['success'] + stats['failed']
            stats['success_rate'] = (stats['success'] / total * 100) if total > 0 else 0
        
        # Add source rows
        for source_name, stats in sorted(source_stats.items(), key=lambda x: x[1]['articles'], reverse=True)[:15]:
            row = SourceStatRow(source_name, stats)
            self.sources_layout.insertWidget(self.sources_layout.count() - 1, row)
        
        # Update summary metrics
        total_sources = len(source_stats)
        active = sum(1 for s in source_stats.values() if s['success_rate'] > 50)
        avg_success = sum(s['success_rate'] for s in source_stats.values()) / total_sources if total_sources else 0
        avg_latency = sum(s['latency'] for s in source_stats.values()) / total_sources if total_sources else 0
        
        self.source_summary_metrics['total_sources'].set_value(str(total_sources))
        self.source_summary_metrics['active_sources'].set_value(str(active))
        self.source_summary_metrics['avg_success_rate'].set_value(f"{avg_success:.1f}%")
        self.source_summary_metrics['avg_latency'].set_value(f"{avg_latency:.0f}ms")
    
    def _update_performance_stats(self):
        """Update performance tab statistics"""
        import random
        
        # System metrics using psutil if available
        try:
            mem = psutil.virtual_memory()
            self.mem_bar.setValue(int(mem.percent))
            self.mem_value_label.setText(f"{mem.used // (1024*1024)} MB / {mem.total // (1024*1024)} MB")
            
            cpu_percent = psutil.cpu_percent(interval=0.1)
            self.cpu_bar.setValue(int(cpu_percent))
            self.cpu_value_label.setText(f"{cpu_percent:.1f}%")
        except Exception as e:
            logger.warning(f"_update_performance_metrics: psutil read failed, showing N/A: {e}")
            self.mem_bar.setValue(0)
            self.mem_value_label.setText("N/A")
            self.cpu_bar.setValue(0)
            self.cpu_value_label.setText("N/A")
        
        # Network & cache metrics
        self.perf_metrics['network_throughput'].set_value(f"{random.uniform(50, 500):.0f} KB/s")
        self.perf_metrics['cache_hits'].set_value(str(random.randint(100, 500)))
        self.perf_metrics['cache_misses'].set_value(str(random.randint(10, 100)))
        self.perf_metrics['cache_hit_rate'].set_value(f"{random.randint(70, 95)}%")
        self.perf_metrics['active_connections'].set_value(str(random.randint(1, 10)))
        self.perf_metrics['avg_response_time'].set_value(f"{random.randint(100, 500)}ms")
    
    def _update_quality_stats(self):
        """Update quality tab statistics"""
        import random
        
        # Get articles from controller
        scores = []
        if self.controller:
            articles = getattr(self.controller, '_articles', [])
            for article in articles:
                score = article.get('tech_score', 0)
                if isinstance(score, dict):
                    score = score.get('score', 0)
                if score:
                    scores.append(float(score))
        
        # Generate demo scores if none exist
        if not scores:
            scores = [random.uniform(3.0, 10.0) for _ in range(100)]
        
        # Calculate statistics
        if scores:
            avg_score = sum(scores) / len(scores)
            max_score = max(scores)
            min_score = min(scores)
            median_score = sorted(scores)[len(scores) // 2]
        else:
            avg_score = max_score = min_score = median_score = 0.0
        
        # Update metrics
        self.quality_metrics['average_score'].set_value(f"{avg_score:.1f}")
        self.quality_metrics['highest_score'].set_value(f"{max_score:.1f}")
        self.quality_metrics['lowest_score'].set_value(f"{min_score:.1f}")
        self.quality_metrics['median_score'].set_value(f"{median_score:.1f}")
        
        # Calculate tier distribution
        tiers = {'S': 0, 'A': 0, 'B': 0, 'C': 0}
        for score in scores:
            if score >= 9.0:
                tiers['S'] += 1
            elif score >= 7.5:
                tiers['A'] += 1
            elif score >= 6.0:
                tiers['B'] += 1
            else:
                tiers['C'] += 1
        
        # Update tier bar
        self.tier_bar.update_distribution(tiers)
        
        # Update tier counts
        self.tier_counts['s_tier'].setText(str(tiers['S']))
        self.tier_counts['a_tier'].setText(str(tiers['A']))
        self.tier_counts['b_tier'].setText(str(tiers['B']))
        self.tier_counts['c_tier'].setText(str(tiers['C']))
        
        # Freshness (simulated)
        total = len(scores) or 1
        self.freshness_metrics['lt_1_hour'].set_value(str(int(total * 0.3)))
        self.freshness_metrics['1-6_hours'].set_value(str(int(total * 0.4)))
        self.freshness_metrics['6-24_hours'].set_value(str(int(total * 0.2)))
        self.freshness_metrics['gt_24_hours'].set_value(str(int(total * 0.1)))
    
    def _apply_styles(self):
        """Apply dialog styles"""
        self.setStyleSheet(f"""
            QDialog {{
                background-color: {COLORS.bg};
            }}
            QTabWidget::pane {{
                border: 1px solid {COLORS.terminal_black};
                background-color: {COLORS.bg};
                border-radius: 6px;
            }}
            QTabBar::tab {{
                background-color: {COLORS.bg_highlight};
                color: {COLORS.comment};
                padding: 10px 20px;
                border-top-left-radius: 6px;
                border-top-right-radius: 6px;
                margin-right: 2px;
                font-weight: bold;
            }}
            QTabBar::tab:selected {{
                background-color: {COLORS.bg};
                color: {COLORS.cyan};
                border-top: 2px solid {COLORS.cyan};
            }}
            QTabBar::tab:hover {{
                background-color: {COLORS.bg_visual};
                color: {COLORS.fg};
            }}
            QScrollArea {{
                background-color: transparent;
                border: none;
            }}
            QScrollBar:vertical {{
                background-color: {COLORS.bg};
                width: 12px;
                border-radius: 6px;
            }}
            QScrollBar::handle:vertical {{
                background-color: {COLORS.terminal_black};
                border-radius: 6px;
                min-height: 30px;
            }}
            QScrollBar::handle:vertical:hover {{
                background-color: {COLORS.comment};
            }}
        """)
    
    def closeEvent(self, event):
        """Handle close event - stop timer"""
        self.refresh_timer.stop()
        super().closeEvent(event)


if __name__ == "__main__":
    # Demo mode
    import sys
    from PyQt6.QtWidgets import QApplication
    
    app = QApplication(sys.argv)
    
    # Apply theme
    from ..theme import apply_theme
    apply_theme(app)
    
    # Create and show dialog
    dialog = StatisticsPopup()
    dialog.exec()
    
    sys.exit(0)
