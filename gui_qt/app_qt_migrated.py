"""
Tech News Scraper v8.0 - PyQt6 Enterprise Edition

Refactored migration target for gui/app.py parity:
- Full PyQt6 runtime with thread-safe async bridges
- Live feed, URL analysis, history/restore, export, statistics
- Global discovery + reddit stream + smart proxy + quantum hooks
- Developer/user mode with passcode protection
- Alerts, newsletter, crawler, and sentiment dialog integrations
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import sys
from pathlib import Path

# Add project root to sys.path so it can be run directly from anywhere
root_dir = str(Path(__file__).resolve().parent.parent)
if root_dir not in sys.path:
    sys.path.insert(0, root_dir)

from dataclasses import asdict, is_dataclass
from datetime import UTC, datetime
from typing import Any, Dict, List, Optional

from src.engine.realtime_feeder import RobustDateParser

from PyQt6.QtCore import Qt, QTimer, pyqtSignal, QPropertyAnimation, QEasingCurve
from PyQt6.QtGui import QAction, QKeySequence, QShortcut
from PyQt6.QtWidgets import (
    QApplication,
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QPushButton,
    QScrollArea,
    QStackedWidget,
    QStatusBar,
    QVBoxLayout,
    QWidget,
    QSplitter,
)

# Fix for macOS Apple Silicon multi-threading import crash
import numpy

try:
    import datasketch
    import src.engine.orchestrator
    import src.intelligence.sentiment_analyzer
    import src.data_structures.trie
except ImportError:
    pass

# Add project root to path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from gui_qt.dialogs.developer_dashboard import DeveloperDashboard as _DevDashboard


def show_developer_dashboard(parent=None, orchestrator=None):
    """Show the canonical 6-tab developer dashboard."""
    dialog = _DevDashboard(parent, orchestrator)
    dialog.exec()


from gui_qt.dialogs.alert_dialog import show_alert_config
from gui_qt.dialogs.article_viewer import show_article_viewer
from gui_qt.dialogs.crawler_dialog import CrawlerDialog
from gui_qt.dialogs.custom_sources_dialog import show_custom_sources_dialog
from gui_qt.dialogs.newsletter_dialog import show_newsletter_dialog
from gui_qt.dialogs.sentiment_dialog import SentimentDashboard
from gui_qt.dialogs.statistics_popup import StatisticsPopup
from gui_qt.event_manager import get_event_manager, EventType as GUIEventType
from gui_qt.config_manager import get_config
from gui_qt.mode_manager import get_mode_manager
from gui_qt.panels.admin_panel import show_admin_panel
from gui_qt.panels.dashboard_panel import LiveDashboardPanel
from gui_qt.panels.sidebar_panel import SidebarPanel
from gui_qt.widgets.custom_sources_manager import CustomSourcesManager
from gui_qt.widgets.live_activity_log import LiveActivityLog
from gui_qt.panels.feed_panel import FeedPanel
from gui_qt.security import get_security_manager
from gui_qt.theme import COLORS, apply_theme
from gui_qt.utils.async_bridge import cleanup, run_async, get_async_bridge
from gui_qt.widgets.dialogs.history import ExportDialog, HistoryViewer
from gui_qt.widgets.dialogs.preferences import PreferencesDialog
from gui_qt.widgets.global_discovery_page import GlobalDiscoveryPage

import time

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s.%(msecs)03d [%(levelname)s] [%(name)s:%(lineno)d] %(message)s",
    datefmt="%H:%M:%S",
    force=True,
)
logger = logging.getLogger("TechNewsApp")


class HeaderBar(QFrame):
    """Application header with branding, global discovery button, and mode indicator."""
    menu_clicked = pyqtSignal()
    global_clicked = pyqtSignal()  # Navigate to Global Discovery page

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setStyleSheet(
            f"""
            HeaderBar {{
                background-color: {COLORS.bg_dark};
                border-bottom: 3px solid {COLORS.cyan};
            }}
            """
        )
        self.setFixedHeight(80)
        self._setup_ui()

    def _setup_ui(self) -> None:
        layout = QHBoxLayout(self)
        layout.setContentsMargins(24, 0, 24, 0)
        layout.setSpacing(20)

        # Hamburger menu -- toggles the sidebar, which starts collapsed
        self.menu_btn = QPushButton("\u2630")
        self.menu_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.menu_btn.setFixedSize(40, 40)
        self.menu_btn.setStyleSheet(
            f"""
            QPushButton {{
                background-color: {COLORS.bg_visual};
                color: {COLORS.fg};
                border: 1px solid {COLORS.border};
                border-radius: 6px;
                font-size: 18px;
            }}
            QPushButton:hover {{
                border: 1px solid {COLORS.cyan};
                color: {COLORS.cyan};
            }}
            """
        )
        self.menu_btn.clicked.connect(self.menu_clicked.emit)
        layout.addWidget(self.menu_btn)

        # Branding
        branding = QWidget()
        branding_layout = QHBoxLayout(branding)
        branding_layout.setContentsMargins(0, 0, 0, 0)
        branding_layout.setSpacing(10)

        logo = QLabel("⚡")
        logo.setStyleSheet(f"color: {COLORS.cyan}; font-size: 32px;")
        branding_layout.addWidget(logo)

        title = QLabel("TECH NEWS SCRAPER")
        title.setStyleSheet(
            f"color: {COLORS.fg}; font-size: 20px; font-weight: bold; letter-spacing: 1px;"
        )
        branding_layout.addWidget(title)

        version = QLabel("v8.0")
        version.setStyleSheet(
            f"color: {COLORS.comment}; font-size: 12px; margin-top: 8px;"
        )
        branding_layout.addWidget(version)

        layout.addWidget(branding)
        layout.addStretch()
        logger.info("HeaderBar initialized with branding")

        # Global Discovery Button
        self.global_btn = QPushButton("🌍 Global")
        self.global_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.global_btn.setFixedHeight(36)
        self.global_btn.setStyleSheet(
            f"""
            QPushButton {{
                background-color: {COLORS.cyan}22;
                color: {COLORS.cyan};
                border: 1px solid {COLORS.cyan};
                border-radius: 6px;
                padding: 6px 16px;
                font-weight: bold;
                font-size: 12px;
            }}
            QPushButton:hover {{
                background-color: {COLORS.cyan}44;
            }}
            """
        )
        self.global_btn.clicked.connect(self.global_clicked.emit)
        layout.addWidget(self.global_btn)

        # Mode Indicator
        self.mode_badge = QLabel("👤 USER")
        self.mode_badge.setStyleSheet(
            f"""
            background-color: {COLORS.blue};
            color: {COLORS.fg};
            border-radius: 4px;
            padding: 6px 12px;
            font-weight: bold;
            font-size: 11px;
            """
        )
        layout.addWidget(self.mode_badge)

        # Time Label
        self.time_label = QLabel()
        self.time_label.setStyleSheet(f"color: {COLORS.fg_dark}; font-size: 13px;")
        layout.addWidget(self.time_label)

        self.timer = QTimer(self)
        self.timer.timeout.connect(self._update_time)
        self.timer.start(1000)
        self._update_time()

        # Exit Button
        exit_btn = QPushButton("⏻ Exit")
        exit_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        exit_btn.setStyleSheet(
            f"""
            QPushButton {{
                background-color: {COLORS.red};
                color: {COLORS.fg};
                border: none;
                border-radius: 6px;
                padding: 8px 16px;
                font-weight: bold;
            }}
            QPushButton:hover {{
                background-color: {COLORS.bright_red};
            }}
            """
        )
        exit_btn.clicked.connect(QApplication.instance().quit)
        layout.addWidget(exit_btn)

    def _update_time(self) -> None:
        self.time_label.setText(datetime.now().strftime("%H:%M:%S"))

    def set_mode_indicator(self, mode: str) -> None:
        if mode == "developer":
            self.mode_badge.setText("⚡ DEV")
            self.mode_badge.setStyleSheet(
                f"""
                background-color: {COLORS.magenta};
                color: {COLORS.fg};
                border-radius: 4px;
                padding: 6px 12px;
                font-weight: bold;
                font-size: 11px;
                """
            )
        else:
            self.mode_badge.setText("👤 USER")
            self.mode_badge.setStyleSheet(
                f"""
                background-color: {COLORS.blue};
                color: {COLORS.fg};
                border-radius: 4px;
                padding: 6px 12px;
                font-weight: bold;
                font-size: 11px;
                """
            )

class TechNewsApp(QMainWindow):
    """Main application window with Tk parity-focused PyQt6 migration."""

    VERSION = "8.0"

    stream_article_received = pyqtSignal(dict)
    pipeline_status_received = pyqtSignal(str, str)
    region_status_received = pyqtSignal(str, int)

    def __init__(self) -> None:
        super().__init__()

        self.setWindowTitle(f"Tech News Scraper v{self.VERSION}")
        self.setMinimumSize(1400, 900)
        self.resize(1600, 1000)

        # Runtime state
        self.articles: List[Dict[str, Any]] = []
        self.archived_history: List[Dict[str, Any]] = []
        self.archived_urls: set[str] = set()
        self.saved_articles: set[str] = set()
        self._displayed_urls: set[str] = set()
        self._displayed_titles: set[str] = set()
        self._history_batches: List[Dict[str, Any]] = []
        self._history_limit = 30
        self._active_query = ""
        self._fetching = False
        self._current_region = "US"


        # In-memory intelligence counters (updated after each fetch)
        self._intel_analyzed: int = 0
        self._intel_disruptive: int = 0
        self._intel_high_priority: int = 0

        # Core components
        self._orchestrator = None
        self._pipeline = None
        self._global_discovery = None
        self._reddit_stream = None
        self._proxy_router = None
        self._crawler_dialog: Optional[CrawlerDialog] = None

        # Mode manager
        self._mode_manager = get_mode_manager(self)

        # Event manager & config manager (ported from gui/)
        self._event_manager = get_event_manager(parent=self)
        self._config = get_config()
        self._security = get_security_manager()

        self._setup_ui()
        self._setup_menu_bar()
        self._connect_signals()
        self._setup_shortcuts()
        self._init_all_systems()

        # Start event manager after systems are initialised
        self._event_manager.start()

        logger.info("Tech News Scraper v%s (PyQt6) started", self.VERSION)

    def _setup_ui(self) -> None:
        central = QWidget()
        central.setStyleSheet(f"background-color: {COLORS.bg};")
        self.setCentralWidget(central)

        main_layout = QVBoxLayout(central)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        self.header = HeaderBar()
        main_layout.addWidget(self.header)

        content_layout = QHBoxLayout()
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(0)

        self.sidebar = SidebarPanel()
        # Hidden initially; the hamburger menu button slides it open.
        self.sidebar.setMaximumWidth(0)
        self._sidebar_expanded = False
        self._sidebar_animation = QPropertyAnimation(self.sidebar, b"maximumWidth", self)
        self._sidebar_animation.setDuration(220)
        self._sidebar_animation.setEasingCurve(QEasingCurve.Type.InOutCubic)
        content_layout.addWidget(self.sidebar)

        self.feed_panel = FeedPanel(on_save=self._on_article_saved)
        content_layout.addWidget(self.feed_panel, 1)

        # LiveDashboardPanel kept as a non-visible widget so internal
        # update calls (set_progress, update_source, add_article, etc.)
        # continue to work without errors.  It is NOT added to the layout.
        self.dashboard = LiveDashboardPanel()

        content_widget = QWidget()
        content_widget.setLayout(content_layout)

        # Splitter to separate content (feed) and live log
        splitter = QSplitter(Qt.Orientation.Vertical)
        splitter.addWidget(content_widget)

        self.activity_log = LiveActivityLog()
        splitter.addWidget(self.activity_log)
        splitter.setSizes([700, 200])

        # ─── Page Navigation (QStackedWidget) ───
        # Page 0: Feed view (splitter with feed + log)
        # Page 1: Global Discovery page
        self._page_stack = QStackedWidget()
        self._page_stack.addWidget(splitter)            # Index 0: Feed

        self.global_discovery_page = GlobalDiscoveryPage()
        self.global_discovery_page.back_requested.connect(self._navigate_to_feed)
        self.global_discovery_page.region_scan_requested.connect(self._on_manual_region_scan)
        self._page_stack.addWidget(self.global_discovery_page)  # Index 1: Global Discovery

        main_layout.addWidget(self._page_stack, 1)

        # Wire header navigation
        self.header.global_clicked.connect(self._navigate_to_global_discovery)

        self.status_bar = QStatusBar()
        self.status_bar.setStyleSheet(
            f"background-color: {COLORS.bg_dark}; color: {COLORS.fg}; border-top: 1px solid {COLORS.border};"
        )
        self.setStatusBar(self.status_bar)
        self._set_status(
            "Ready - Press F12 for Developer Mode or click 'Start Live Feed'"
        )

    def _setup_menu_bar(self) -> None:
        menu_bar = self.menuBar()

        # File
        file_menu = menu_bar.addMenu("File")

        prefs_action = QAction("⚙️ Preferences", self)
        prefs_action.setShortcut("Ctrl+,")
        prefs_action.triggered.connect(self._show_preferences)
        file_menu.addAction(prefs_action)

        export_action = QAction("📤 Export Articles", self)
        export_action.setShortcut("Ctrl+E")
        export_action.triggered.connect(self._on_export)
        file_menu.addAction(export_action)

        file_menu.addSeparator()

        quit_action = QAction("Quit", self)
        quit_action.setShortcut("Ctrl+Q")
        quit_action.triggered.connect(self.close)
        file_menu.addAction(quit_action)

        # View
        view_menu = menu_bar.addMenu("View")

        stats_action = QAction("📊 Statistics", self)
        stats_action.setShortcut("Ctrl+I")
        stats_action.triggered.connect(self._show_statistics)
        view_menu.addAction(stats_action)

        history_action = QAction("📜 History", self)
        history_action.setShortcut("Ctrl+H")
        history_action.triggered.connect(self._show_history)
        view_menu.addAction(history_action)

        toggle_dash_action = QAction("🖥️ Toggle Dashboard", self)
        toggle_dash_action.setShortcut("Ctrl+D")
        toggle_dash_action.triggered.connect(self._toggle_dashboard)
        view_menu.addAction(toggle_dash_action)

        global_action = QAction("🌍 Global Discovery", self)
        global_action.setShortcut("Ctrl+G")
        global_action.triggered.connect(self._navigate_to_global_discovery)
        view_menu.addAction(global_action)

        # Tools (Tk parity features)
        tools_menu = menu_bar.addMenu("Tools")

        crawler_action = QAction("🕷️ Web Crawler", self)
        crawler_action.triggered.connect(self._show_crawler_dialog)
        tools_menu.addAction(crawler_action)

        sentiment_action = QAction("📊 Sentiment Dashboard", self)
        sentiment_action.triggered.connect(self._show_sentiment_dashboard)
        tools_menu.addAction(sentiment_action)

        alerts_action = QAction("🔔 Configure Alerts", self)
        alerts_action.triggered.connect(self._show_alert_config)
        tools_menu.addAction(alerts_action)

        newsletter_action = QAction("📰 Newsletter", self)
        newsletter_action.triggered.connect(self._show_newsletter_dialog)
        tools_menu.addAction(newsletter_action)

        custom_sources_action = QAction("⚙️ Custom Sources", self)
        custom_sources_action.triggered.connect(self._show_custom_sources)
        tools_menu.addAction(custom_sources_action)

        # Developer
        self.dev_menu = menu_bar.addMenu("Developer")

        dev_dashboard_action = QAction("🛠️ Dashboard", self)
        dev_dashboard_action.setShortcut("Ctrl+Shift+D")
        dev_dashboard_action.triggered.connect(self._show_developer_dashboard)
        self.dev_menu.addAction(dev_dashboard_action)

        admin_panel_action = QAction("🖧 Admin Control Panel", self)
        admin_panel_action.setShortcut("Ctrl+Shift+A")
        admin_panel_action.triggered.connect(self._show_admin_panel)
        self.dev_menu.addAction(admin_panel_action)

        change_passcode_action = QAction("🔐 Change Passcode", self)
        change_passcode_action.triggered.connect(self._change_dev_passcode)
        self.dev_menu.addAction(change_passcode_action)

        self.dev_menu.menuAction().setVisible(False)

    def _setup_shortcuts(self) -> None:
        user_shortcut = QShortcut(QKeySequence("F11"), self)
        user_shortcut.activated.connect(lambda: self._request_mode_switch("user"))

        dev_shortcut = QShortcut(QKeySequence("F12"), self)
        dev_shortcut.activated.connect(lambda: self._request_mode_switch("developer"))

        mode_shortcut = QShortcut(QKeySequence("Ctrl+M"), self)
        mode_shortcut.activated.connect(self._toggle_mode)

        refresh_shortcut = QShortcut(QKeySequence("Ctrl+R"), self)
        refresh_shortcut.activated.connect(self._start_live_feed)

        logger.info(
            "Keyboard shortcuts registered: F11 (User), F12 (Developer), Ctrl+M (Toggle), Ctrl+R (Refresh)"
        )

    def _connect_signals(self) -> None:

        self.sidebar.start_feed_clicked.connect(self._start_live_feed)
        self.header.menu_clicked.connect(self._toggle_sidebar)
        self.sidebar.mode_changed.connect(self._on_mode_change)
        self.sidebar.view_live_monitor_clicked.connect(self._show_live_monitor)
        
        self.sidebar.global_rotation_triggered.connect(self._on_global_rotation)
        self.sidebar.deep_scrape_triggered.connect(self._on_deep_scrape)
        self.sidebar.view_custom_sources_clicked.connect(self._show_custom_sources_manager)
        self.sidebar.history_clicked.connect(self._show_history)

        self.feed_panel.article_clicked.connect(self._on_article_click)
        self.feed_panel.article_saved.connect(self._on_article_saved)
        self.feed_panel.search_requested.connect(self._on_search)
        self.feed_panel.url_analysis_requested.connect(self._on_url_analysis)
        self.feed_panel.refresh_requested.connect(self._start_live_feed)
        self.feed_panel.history_requested.connect(self._show_history)
        self.feed_panel.article_archived.connect(self._on_article_archived)
        self.feed_panel.advanced_feeds_toggled.connect(self._on_advanced_feeds_toggled)


        self._mode_manager.mode_changed.connect(self._on_mode_changed)

        self.stream_article_received.connect(self._on_pipeline_stream_article)
        self.pipeline_status_received.connect(self._on_pipeline_status_received)
        self.region_status_received.connect(self._on_region_status)

    def _init_all_systems(self) -> None:
        """Kick off system initialization from the main thread."""
        self._startup_steps = [
            "Initializing orchestrator...",
            "Starting pipeline...",
            "Connecting global discovery...",
            "Starting Reddit stream...",
        ]
        self._startup_step_idx = 0
        self._startup_timer = QTimer(self)
        self._startup_timer.timeout.connect(self._advance_startup_step)
        self._startup_timer.start(900)

        bridge = get_async_bridge()
        bridge.run_coro(
            self._bootstrap_systems(),
            callback=self._on_bootstrap_complete,
            error_callback=lambda exc: logger.error("Bootstrap error: %s", exc),
        )

    def _advance_startup_step(self) -> None:
        """Advance the animated startup progress shown in the status bar."""
        if self._startup_step_idx < len(self._startup_steps):
            msg = self._startup_steps[self._startup_step_idx]
            progress = int(
                (self._startup_step_idx + 1) / len(self._startup_steps) * 100
            )
            self._set_status(f"[{progress}%] {msg}")
            self.dashboard.set_progress(progress)
            self._startup_step_idx += 1
        else:
            self._startup_timer.stop()

    async def _bootstrap_systems(self) -> None:
        for init_fn in (
            self._init_orchestrator,
            self._init_pipeline,
            self._init_global_discovery,
            self._init_reddit_stream,
            self._init_smart_proxy,
        ):
            try:
                await init_fn()
            except Exception as exc:
                logger.error("Init step %s failed: %s", init_fn.__name__, exc)

    def _on_bootstrap_complete(self, result: Any = None) -> None:
        """Executed on the Qt main thread when async bootstrap finishes."""
        self._set_status("All systems ready — Dual Engine live", "success")
        logger.info("⚡ Bootstrap complete — auto-starting Dual Engine")
        if not self.sidebar._is_live:
            self.sidebar.start_btn.click()
        else:
            self._start_live_feed()


    async def _init_orchestrator(self) -> None:
        try:
            from src.engine import TechNewsOrchestrator

            self._orchestrator = TechNewsOrchestrator()
            await self._load_existing_articles()
            logger.info("✓ TechNewsOrchestrator initialized")
        except Exception as exc:
            logger.error("Failed to initialize orchestrator: %s", exc)
            self._set_status(f"Orchestrator init warning: {exc}", "warning")

    async def _load_existing_articles(self) -> None:
        try:
            self.articles = []
            self.feed_panel.set_articles([])
            logger.info("🧹 Session reset on launch: 0 stale articles")
        except Exception as exc:
            logger.warning("Could not reset session articles on launch: %s", exc)

    def _apply_loaded_articles(self, articles: List[Dict[str, Any]]) -> None:
        self.articles = list(articles)
        self.feed_panel.set_articles(articles)
        self._update_caches_from_articles(articles)
        self._update_live_metrics(progress=100)
        self._set_status(f"📚 Loaded {len(articles)} existing articles from database")

    async def _init_pipeline(self) -> None:
        try:
            from src.engine.enhanced_feeder import EnhancedNewsPipeline

            self._pipeline = EnhancedNewsPipeline(
                enable_discovery=True,
                max_articles=500,
                max_age_hours=72,
            )
            self._pipeline.add_status_callback(self._pipeline_status_callback)
            self._pipeline.add_article_callback(self._pipeline_article_callback)
            await self._pipeline.start()

            logger.info("✓ Enhanced pipeline initialized")
        except Exception as exc:
            logger.error("Pipeline init failed: %s", exc)
            self._set_status(f"Pipeline init warning: {exc}", "warning")

    async def _init_global_discovery(self) -> None:
        try:
            from src.discovery.global_discovery import get_global_discovery_manager

            self._global_discovery = get_global_discovery_manager()
            if self._global_discovery:
                self._global_discovery.on_new_region = self._on_region_change
                await self._global_discovery.start()
                
                # Wire to the Global Discovery Page widget on the main GUI thread
                mgr = self._global_discovery
                QTimer.singleShot(0, lambda: self.global_discovery_page.set_discovery_manager(mgr))
                
                logger.info("✓ Global discovery started and wired to GUI")
        except Exception as exc:
            logger.warning("Global discovery unavailable: %s", exc)

    async def _init_reddit_stream(self) -> None:
        try:
            from src.sources.reddit_stream import get_reddit_stream_client

            self._reddit_stream = get_reddit_stream_client()
            if self._reddit_stream:
                self._reddit_stream.on_new_post = self._on_reddit_post
                await self._reddit_stream.start()
                logger.info("✓ Reddit stream started")
        except Exception as exc:
            logger.warning("Reddit stream unavailable: %s", exc)

    async def _init_smart_proxy(self) -> None:
        try:
            from src.bypass.smart_proxy_router import get_smart_proxy_router

            self._proxy_router = get_smart_proxy_router()
            if self._proxy_router:
                logger.info("✓ Smart proxy router initialized")
        except Exception as exc:
            logger.warning("Smart proxy unavailable: %s", exc)


    def _pipeline_status_callback(self, component: str, status: str) -> None:
        self.pipeline_status_received.emit(component, status)

    def _pipeline_article_callback(self, article: Any) -> None:
        try:
            converted = self._convert_article_to_dict(article)
            self.stream_article_received.emit(converted)
        except Exception as exc:
            logger.debug("Pipeline article callback error: %s", exc)

    def _on_pipeline_status_received(self, component: str, status: str) -> None:
        text = f"[{component}] {status}"
        self._set_status(text)
        
        # Stream to LiveActivityLog
        if "error" in status.lower() or "failed" in status.lower():
            self.activity_log.error(status, source=component)
        elif "✓" in status or "success" in status.lower() or "found" in status.lower():
            self.activity_log.success(status, source=component)
        else:
            self.activity_log.info(status, source=component)

        # Heuristic progress updates based on pipeline status text.
        lowered = status.lower()
        if "starting" in lowered:
            self.dashboard.set_progress(5)
        elif "fetch" in lowered or "running" in lowered:
            self.dashboard.set_progress(35)
        elif "dedup" in lowered:
            self.dashboard.set_progress(70)
        elif "ready" in lowered or "stopped" in lowered:
            self.dashboard.set_progress(0)
        elif "✓" in status:
            self.dashboard.set_progress(100)

        source_name = component.replace("_", " ").title()
        if source_name in self.dashboard.source_grid.sources:
            active = "error" not in lowered
            self.dashboard.update_source(
                source_name, "active" if active else "error", 0
            )

    def _on_pipeline_stream_article(self, article: Any) -> None:
        try:
            converted = self._convert_article_to_dict(article) if not isinstance(article, dict) else article
            if self._is_duplicate_article(converted):
                return

            self.articles.insert(0, converted)
            self._displayed_urls.add(converted.get("url", ""))
            if converted.get("title"):
                self._displayed_titles.add(converted.get("title", "").strip().lower())

            if len(self.articles) > 1000:
                self.articles = self.articles[:1000]

            self.feed_panel.add_article(converted, prepend=True)
            self.dashboard.add_article(converted)
            self._update_live_metrics(progress=100)
        except Exception as exc:
            logger.error("Error in stream article processing: %s", exc)

    def _request_mode_switch(self, mode: str) -> None:
        if self._mode_manager.request_mode_switch(mode):
            self._set_status(f"Switched to {mode.upper()} mode")

    def _toggle_mode(self) -> None:
        target = (
            "developer" if self._mode_manager.get_current_mode() == "user" else "user"
        )
        self._request_mode_switch(target)

    def _on_mode_changed(self, old_mode: str, new_mode: str) -> None:
        self.header.set_mode_indicator(new_mode)
        self.dev_menu.menuAction().setVisible(new_mode == "developer")

        if new_mode == "developer":
            self._set_status("🛠️ Developer Mode - Full system access granted", "success")
        else:
            self._set_status("👤 User Mode - Standard features only")

    def _show_developer_dashboard(self) -> None:
        show_developer_dashboard(self, self._orchestrator)



    def _show_custom_sources_manager(self) -> None:
        if not hasattr(self, "_custom_sources_dialog"):
            self._custom_sources_dialog = CustomSourcesManager()
        self._custom_sources_dialog.show()
        self._custom_sources_dialog.raise_()
        
    def _on_global_rotation(self) -> None:
        logger.info("Global rotation triggered (2m). Archiving older news.")
        self._set_status("🔄 Running Global Rotation (2m)...")
        self._start_live_feed()

    def _on_deep_scrape(self) -> None:
        logger.info("Deep scrape triggered (20m). Fetching all sources.")
        self._set_status("🛸 Running Deep Scrape (20m)...")
        self._start_live_feed()

    def _show_disruptive_news(self) -> None:
        show_custom_sources_dialog(self)

    def _change_dev_passcode(self) -> None:
        self._mode_manager.change_passcode()

    def _show_admin_panel(self) -> None:
        show_admin_panel(self)

    def _show_custom_sources(self) -> None:
        show_custom_sources_dialog(self)

    def _on_region_change(self, hub: Any) -> None:
        """Sync callback — emits status update and triggers regional news discovery."""
        code = getattr(hub, "code", "--")
        name = getattr(hub, "name", code)
        self._current_region = code
        self.region_status_received.emit(code, 19)

        # Update Global Discovery page with active hub
        try:
            clean_name = name.split("(")[0].strip() if "(" in name else name
            self.global_discovery_page.update_active_hub(code, clean_name)
        except Exception:
            pass

        # Launch background task to fetch news for the new region
        bridge = get_async_bridge()
        bridge.run_coro(
            self._run_region_discovery(hub),
            callback=self._on_region_discovery_complete,
            error_callback=lambda exc: logger.warning("Region discovery warning for %s: %s", code, exc),
        )

    async def _run_region_discovery(self, hub: Any) -> List[Dict[str, Any]]:
        """Fetch live news for a rotated global technology hub using Google News RSS."""
        code = getattr(hub, "code", "US")
        name = getattr(hub, "name", code)
        clean_name = name.split("(")[0].strip() if "(" in name else name
        topics = getattr(hub, "topics", []) or ["technology", "AI"]
        
        logger.info("🌍 Running active region discovery for %s (%s)...", clean_name, code)
        
        search_articles: List[Dict[str, Any]] = []
        
        # Use Google News RSS with geo-targeting for the hub's region
        try:
            import aiohttp
            from src.sources.google_news import GoogleNewsClient
            from src.engine.quality_filter import SourceQualityFilter
            from src.core.types import Article, SourceTier
            
            qf = SourceQualityFilter(strict_mode=True)
            gn = GoogleNewsClient(region=code.lower())
            async with aiohttp.ClientSession() as session:
                # Fetch topic-specific feeds for the region (NO headlines feed)
                gn_results = await gn.fetch_rss_feeds(
                    session=session,
                    topics=["technology", "science"],
                    include_headlines=False,
                )
                
                # Also search for region-specific tech topics
                primary_topic = topics[0] if topics else "technology"
                query_str = f"{clean_name} {primary_topic} technology news"
                search_results = await gn.search(session=session, query=query_str)
                gn_results.extend(search_results)
                
                # Apply Unified Feed Chain dedup & quality filters to region discovery
                from src.engine.unified_chain import unified_engine

                for art in gn_results:
                    art_obj = Article(
                        id=getattr(art, "id", "") or getattr(art, "url", ""),
                        url=getattr(art, "url", ""),
                        title=getattr(art, "title", ""),
                        content=getattr(art, "snippet", "") or getattr(art, "title", ""),
                        summary=getattr(art, "snippet", "") or "",
                        source=f"{getattr(art, 'source', 'Google News')} ({code})",
                        source_tier=SourceTier.TIER_2,
                        published_at=getattr(art, "published_at", None),
                    )
                    if not unified_engine.dedup.check_and_add(art_obj):
                        if unified_engine.quality.check(art_obj):
                            await unified_engine.feed.push(art_obj)
                            d = self._convert_article_to_dict(art_obj)
                            search_articles.append(d)
                            if len(search_articles) >= 20:
                                break
                    
        except Exception as exc:
            logger.debug("Google RSS region fetch warning for %s: %s", code, exc)
            
        return search_articles


    def _on_region_discovery_complete(self, raw_articles: List[Any]) -> None:
        if not raw_articles:
            return
        new_articles = [a for a in raw_articles if not self._is_duplicate_article(a)]
        if not new_articles:
            return
            
        for art in reversed(new_articles):
            self.articles.insert(0, art)
            self.feed_panel.add_article(art, prepend=True)
            if art.get("url"):
                self._displayed_urls.add(art.get("url", ""))
            if art.get("title"):
                self._displayed_titles.add(art.get("title", "").strip().lower())

        if len(self.articles) > 1000:
            self.articles = self.articles[:1000]
            
        self.sidebar.update_stats(
            articles=len(self.articles),
            sources=len({a.get("source", "") for a in self.articles if a.get("source")}),
            saved=len(self.saved_articles),
        )
        
        # Update Global Discovery page with article count for the region
        try:
            self.global_discovery_page.update_hub_stats(
                self._current_region, len(new_articles)
            )
        except Exception:
            pass
        
        self._set_status(f"🌍 Discovered {len(new_articles)} new articles from {self._current_region}", "success")

    # ─── Page Navigation ───
    
    def _navigate_to_feed(self) -> None:
        """Switch to the Feed view (page 0)."""
        self._page_stack.setCurrentIndex(0)
        self.header.global_btn.setStyleSheet(
            f"""
            QPushButton {{
                background-color: {COLORS.cyan}22;
                color: {COLORS.cyan};
                border: 1px solid {COLORS.cyan};
                border-radius: 6px;
                padding: 6px 16px;
                font-weight: bold;
                font-size: 12px;
            }}
            QPushButton:hover {{
                background-color: {COLORS.cyan}44;
            }}
            """
        )
        self._set_status("📰 Feed view")

    def _navigate_to_global_discovery(self) -> None:
        """Switch to the Global Discovery view (page 1)."""
        self._page_stack.setCurrentIndex(1)
        self.header.global_btn.setStyleSheet(
            f"""
            QPushButton {{
                background-color: {COLORS.cyan};
                color: #1e1e2e;
                border: 1px solid {COLORS.cyan};
                border-radius: 6px;
                padding: 6px 16px;
                font-weight: bold;
                font-size: 12px;
            }}
            QPushButton:hover {{
                background-color: #9decf5;
            }}
            """
        )
        self._set_status("🌍 Global Discovery Manager")

    def _on_manual_region_scan(self, hub: Any) -> None:
        """Handle manual region scan from Global Discovery page."""
        code = getattr(hub, "code", "US")
        name = getattr(hub, "name", code)
        logger.info("🌍 Manual scan requested for %s (%s)", name, code)
        self._current_region = code
        
        bridge = get_async_bridge()
        bridge.run_coro(
            self._run_region_discovery(hub),
            callback=self._on_region_discovery_complete,
            error_callback=lambda exc: logger.warning(
                "Manual region scan warning for %s: %s", code, exc
            ),
        )

    def _on_region_status(self, region: str, source_count: int) -> None:
        self.sidebar.set_live_status(True, region, source_count)
        self._set_status(f"🌍 Scanning region {region}...")
        self._start_live_feed()

    def _on_reddit_post(self, post: Dict[str, Any]) -> None:
        """Sync callback — converts Reddit post to Article and emits Qt signal."""
        try:
            from src.core.types import Article, SourceTier, TechScore

            raw_score = post.get("score", 0)
            normalized = min(raw_score / 1000.0, 1.0)

            article = Article(
                id=f"reddit_{post.get('id', '')}",
                title=post.get("title", "Untitled"),
                url=post.get("external_url") or post.get("url", ""),
                content="",
                summary="",
                source=f"reddit/r/{post.get('subreddit', 'technology')}",
                source_tier=SourceTier.TIER_3,
                published_at=post.get("created_utc"),
                scraped_at=datetime.now(),
                tech_score=TechScore(score=normalized, confidence=0.7),
            )
            self.stream_article_received.emit(self._convert_article_to_dict(article))
        except Exception as exc:
            logger.error("Reddit post handling error: %s", exc)

    def _normalize_score(self, score: Any) -> float:
        try:
            if isinstance(score, dict):
                score = score.get("score", 0)
            score = float(score)
        except Exception:
            return 0.0

        # Normalize commonly-seen ranges: 0-1, 0-10, 0-100.
        if score <= 1.0:
            score *= 100.0
        elif score <= 10.0:
            score *= 10.0

        return max(0.0, min(100.0, score))

    def _extract_pub_timestamp(self, article: Dict[str, Any]) -> float:
        if "_timestamp" in article and isinstance(article["_timestamp"], (int, float)) and article["_timestamp"] > 0:
            return float(article["_timestamp"])

        raw_date = article.get("published_at") or article.get("published") or article.get("scraped_at")
        if isinstance(raw_date, (int, float)) and raw_date > 0:
            return float(raw_date)
        if isinstance(raw_date, datetime):
            dt = raw_date
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=UTC)
            return dt.timestamp()
        
        if isinstance(raw_date, str) and raw_date.strip():
            dt = RobustDateParser.parse(raw_date, url=article.get("url"))
            if dt:
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=UTC)
                return dt.timestamp()

        return 0.0

    def _format_relative_time(self, pub_timestamp: float) -> str:
        if not pub_timestamp or pub_timestamp <= 0:
            return "Recent"
        now_ts = datetime.now(UTC).timestamp()
        diff_sec = max(0, now_ts - pub_timestamp)
        if diff_sec < 60:
            return "Just now"
        elif diff_sec < 3600:
            mins = int(diff_sec // 60)
            return f"{mins}m ago"
        elif diff_sec < 86400:
            hours = int(diff_sec // 3600)
            return f"{hours}h ago"
        elif diff_sec < 172800:
            return "Yesterday"
        else:
            days = int(diff_sec // 86400)
            if days <= 7:
                return f"{days}d ago"
            dt = datetime.fromtimestamp(pub_timestamp, tz=UTC)
            return dt.strftime("%b %d")

    def _convert_article_to_dict(self, article: Any) -> Dict[str, Any]:
        if isinstance(article, dict):
            result = dict(article)
        elif is_dataclass(article):
            result = asdict(article)
        else:
            result = {
                "id": getattr(article, "id", ""),
                "url": getattr(article, "url", ""),
                "title": getattr(article, "title", "") or "Untitled",
                "content": getattr(article, "content", ""),
                "summary": getattr(article, "summary", ""),
                "ai_summary": getattr(
                    article, "ai_summary", getattr(article, "summary", "")
                ),
                "full_content": getattr(
                    article, "full_content", getattr(article, "content", "")
                ),
                "source": getattr(article, "source", "Unknown") or "Unknown",
                "source_tier": getattr(article, "source_tier", "standard"),
                "tier": getattr(
                    article, "tier", getattr(article, "source_tier", "standard")
                ),
                "published_at": getattr(article, "published_at", None),
                "published": getattr(article, "published", None),
                "scraped_at": getattr(article, "scraped_at", None),
                "tech_score": getattr(article, "tech_score", 0.0),
                "relevance_score": getattr(article, "relevance_score", 0.0),
                "topics": getattr(article, "topics", []),
                "keywords": getattr(article, "keywords", []),
                "entities": getattr(article, "entities", []),
            }

        url = result.get("url", "") or ""
        title = result.get("title", "") or "Untitled"

        # Clean HTML out of summary/description strings
        raw_desc = result.get("description", "") or result.get("summary", "") or ""
        if raw_desc and "<" in raw_desc and ">" in raw_desc:
            from bs4 import BeautifulSoup
            clean_desc = BeautifulSoup(raw_desc, "html.parser").get_text(separator=" ", strip=True)
            result["description"] = clean_desc
            result["summary"] = clean_desc

        result["url"] = url
        result["title"] = title

        result.setdefault("source", "Unknown")
        result.setdefault("ai_summary", result.get("summary", "") or "")
        result.setdefault("full_content", result.get("content", "") or "")
        result.setdefault("topics", [])
        result.setdefault("keywords", [])
        result.setdefault("entities", [])
        result.setdefault("source_tier", result.get("tier", "standard"))
        result.setdefault("tier", result.get("source_tier", "standard"))


        # Extract normalized timestamp and relative liveness string
        ts = self._extract_pub_timestamp(result)
        result["_timestamp"] = ts
        result["relative_time"] = self._format_relative_time(ts)

        # Normalize published keys for ArticleCard compatibility.
        published = result.get("published") or result.get("published_at") or datetime.fromtimestamp(ts, tz=UTC).strftime("%Y-%m-%d %H:%M")
        result["published"] = published
        result["published_at"] = published

        result["tech_score"] = self._normalize_score(result.get("tech_score", 0.0))

        article_id = result.get("id")
        if not article_id:
            basis = f"{url}|{title}"
            article_id = hashlib.md5(basis.encode("utf-8", errors="ignore")).hexdigest()
            result["id"] = article_id

        return result

    def _canonicalize_articles(self, raw_articles: List[Any]) -> List[Dict[str, Any]]:
        converted = [self._convert_article_to_dict(article) for article in raw_articles]

        unique: List[Dict[str, Any]] = []
        seen_urls: set[str] = set()
        for article in converted:
            url = article.get("url", "")
            if url and url in seen_urls:
                continue
            if url:
                seen_urls.add(url)
            unique.append(article)

        # Sort descending by publication timestamp (newest first)
        unique.sort(key=lambda a: a.get("_timestamp", 0.0), reverse=True)
        return unique


    def _is_duplicate_article(self, article: Any) -> bool:
        if isinstance(article, dict):
            url = article.get("url", "")
            article_id = article.get("id", "")
            title = article.get("title", "")
        else:
            url = getattr(article, "url", "")
            article_id = getattr(article, "id", "")
            title = getattr(article, "title", "")

        if url and url in self._displayed_urls:
            return True

        title_clean = title.strip().lower() if title else ""
        if title_clean and hasattr(self, "_displayed_titles") and title_clean in self._displayed_titles:
            return True

        # O(1) set lookup instead of O(300) linear scan
        if article_id and hasattr(self, "_displayed_ids") and article_id in self._displayed_ids:
            return True

        return False

    def _update_caches_from_articles(self, articles: List[Dict[str, Any]]) -> None:
        self._displayed_urls = {a.get("url", "") for a in articles if a.get("url")}
        self._displayed_titles = {
            a.get("title", "").strip().lower() for a in articles if a.get("title")
        }
        self._displayed_ids = {a.get("id", "") for a in articles if a.get("id")}


    def _update_live_metrics(self, progress: Optional[int] = None) -> None:
        sources = {a.get("source", "") for a in self.articles if a.get("source")}

        self.sidebar.update_stats(
            articles=len(self.articles),
            sources=len(sources),
            saved=len(self.saved_articles),
        )

        self.sidebar.set_live_status(
            is_live=len(self.articles) > 0 or self._fetching,
            region=self._current_region,
            source_count=len(sources),
        )

        self.dashboard.update_stats(
            total=len(self.articles),
            rss=self._pipeline.get_stats().get("rss_articles", 0)
            if self._pipeline
            else 0,
            api=self._pipeline.get_stats().get("api_articles", 0)
            if self._pipeline
            else 0,
            dedup_rate=self._pipeline.get_stats().get("duplicates_filtered", 0)
            if self._pipeline
            else 0,
        )

        if progress is not None:
            self.dashboard.set_progress(progress)

    def _record_history_snapshot(self, reason: str) -> None:
        if not self.articles:
            return

        # Store only lightweight metadata — not full content/summary strings
        snapshot = {
            "timestamp": datetime.now().isoformat(timespec="seconds"),
            "reason": reason,
            "count": len(self.articles),
            "articles": [
                {
                    "title": a.get("title", ""),
                    "url": a.get("url", ""),
                    "source": a.get("source", ""),
                    "published_at": a.get("published_at", ""),
                }
                for a in self.articles
            ],
        }

        self._history_batches.insert(0, snapshot)
        if len(self._history_batches) > self._history_limit:
            self._history_batches = self._history_batches[: self._history_limit]


    def _start_live_feed(self) -> None:
        if self._fetching:
            return

        self._fetching = True
        self.sidebar.set_fetching(True)
        self.sidebar.set_live_status(True, self._current_region, 0)
        self.dashboard.set_progress(10)
        self._set_status("Fetching articles from all sources...")

        async def fetch() -> List[Any]:
            if not self._pipeline:
                return []
            return await self._pipeline.fetch_unified_live_feed(count=1000)


        def on_complete(articles: List[Any]) -> None:
            self._on_fetch_complete(articles)

        def on_error(error: Exception) -> None:
            self._fetching = False
            self.sidebar.set_fetching(False)
            self.sidebar.set_live_status(False, self._current_region, 0)
            self.dashboard.set_progress(0)
            self._set_status(f"Fetch error: {error}", "error")

        # Use the persistent AsyncBridge loop so the pipeline's aiohttp
        # ClientSession (created during bootstrap on that same loop) is
        # never handed to a different, throwaway loop.
        get_async_bridge().run_coro(
            fetch(), callback=on_complete, error_callback=on_error
        )

    # ------------------------------------------------------------------
    # In-memory article scoring (FIX 5)
    # ------------------------------------------------------------------

    _DISRUPTIVE_KW = [
        "breach",
        "hack",
        "attack",
        "ban",
        "crisis",
        "collapse",
        "emergency",
        "shutdown",
        "recall",
        "lawsuit",
        "explosion",
        "war",
        "sanction",
        "fine",
        "regulation",
        "outage",
        "leaked",
        "arrested",
        "fraud",
        "bankruptcy",
    ]

    def _score_articles_in_memory(self, articles: List[Dict[str, Any]]) -> None:
        """Score articles using actual backend pipelines (TechKeywordMatcher & SentimentAnalyzer).

        Sets:
          article['_disruptive']   = True/False
          article['_criticality']  = float 0.0–1.0
        Also refreshes the three intel counters and sorts articles efficiently.
        """
        analyzed = 0
        disruptive = 0
        high_priority = 0

        try:
            if not hasattr(self, "_matcher") or self._matcher is None:
                from src.data_structures.trie import TechKeywordMatcher
                self._matcher = TechKeywordMatcher()

            if not hasattr(self, "_sentiment_analyzer") or self._sentiment_analyzer is None:
                from src.intelligence.sentiment_analyzer import SentimentAnalyzer
                self._sentiment_analyzer = SentimentAnalyzer()

            matcher = self._matcher
            sentiment_analyzer = self._sentiment_analyzer

            from datetime import datetime, timezone, timedelta
            import dateutil.parser

            now = datetime.now(timezone.utc)
            tzinfos = {
                "EDT": -14400, "EST": -18000, "CDT": -18000, "CST": -21600,
                "MDT": -21600, "MST": -25200, "PDT": -25200, "PST": -28800,
                "UTC": 0, "GMT": 0, "BST": 3600, "CET": 3600, "CEST": 7200,
            }

            for article in articles:
                # Pre-parse date once per article (avoids 4500+ parses during sorting)
                if "_parsed_dt" not in article:
                    pub_date_str = article.get("published_at")
                    parsed_dt = now
                    if pub_date_str:
                        try:
                            parsed_dt = dateutil.parser.parse(pub_date_str, tzinfos=tzinfos)
                            if parsed_dt.tzinfo is None:
                                parsed_dt = parsed_dt.replace(tzinfo=timezone.utc)
                        except Exception:
                            parsed_dt = now
                    article["_parsed_dt"] = parsed_dt

                text = " ".join(
                    filter(
                        None,
                        [
                            article.get("title", ""),
                            article.get("summary", ""),
                            article.get("content", ""),
                            article.get("ai_summary", ""),
                        ],
                    )
                ).lower()

                # Use backend Keyword Matcher
                matches = [kw for kw, _pos, _weight in matcher.find_matches(text)]

                # Calculate real Tech Score based on match weights
                tech_score = (
                    sum(matcher.TECH_KEYWORDS.get(kw.lower(), 1.0) for kw in matches)
                    / 10.0
                )

                # Use backend VADER Sentiment Analyzer
                sentiment = sentiment_analyzer.analyze(text, persist=False)

                # Highly negative or highly positive sentiment combined with tech score = disruptive
                is_disruptive = tech_score > 0.4 and abs(sentiment.score) > 0.3
                criticality = min(tech_score * 2.0 + abs(sentiment.score), 1.0)

                article["_disruptive"] = is_disruptive
                article["_criticality"] = round(criticality, 3)
                article["sentiment_label"] = sentiment.label.value
                article["sentiment_score"] = sentiment.score

                analyzed += 1
                if is_disruptive:
                    disruptive += 1
                if criticality >= 0.4 or tech_score >= 0.8:
                    high_priority += 1

        except Exception as e:
            logger.error(f"Intelligence backend scoring failed: {e}")
            # Fallback
            for article in articles:
                article["_disruptive"] = False
                article["_criticality"] = 0.0
                analyzed += 1

        self._intel_analyzed = analyzed
        self._intel_disruptive = disruptive
        self._intel_high_priority = high_priority

        # Fast O(N log N) sort using pre-parsed datetime objects
        from datetime import datetime, timezone, timedelta
        now = datetime.now(timezone.utc)

        def sort_key(article):
            pub_date = article.get("_parsed_dt", now)
            is_recent = (now - pub_date) <= timedelta(hours=72)
            is_disruptive = article.get("_disruptive", False)
            criticality = article.get("_criticality", 0.0)
            return (
                is_recent,
                is_disruptive,
                criticality,
                pub_date.timestamp()
            )

        articles.sort(key=sort_key, reverse=True)


    def _on_fetch_complete(self, raw_articles: List[Any]) -> None:
        t_complete_start = time.perf_counter()
        self._fetching = False
        self.sidebar.set_fetching(False)
        self.sidebar.reset_countdown()

        new_incoming = self._canonicalize_articles(raw_articles or [])

        if not new_incoming:
            self.sidebar.set_live_status(False, self._current_region, 0)
            self.dashboard.set_progress(0)
            self._set_status("No articles found", "warning")
            return

        # Live Cycle Archiving: Move older cycle articles to archived history
        new_urls = {a.get("url", "") for a in new_incoming if a.get("url")}
        archived_count = 0
        for old_art in self.articles:
            url = old_art.get("url", "")
            if url and url not in new_urls and url not in self.archived_urls:
                self.archived_urls.add(url)
                self.archived_history.append(old_art)
                archived_count += 1

        self._record_history_snapshot("manual_fetch")

        self.articles = list(new_incoming)
        self._score_articles_in_memory(self.articles)  # keyword scoring + 72h priority sort
        self.feed_panel.set_articles(self.articles)  # Display fresh live news cycle in feeder
        self._update_caches_from_articles(self.articles)
        self._update_live_metrics(progress=100)
        self._update_intelligence_stats()


        sources = {a.get("source", "") for a in self.articles if a.get("source")}
        t_gui_ms = (time.perf_counter() - t_complete_start) * 1000
        logger.info(
            f"⏱️ [{t_gui_ms:.1f}ms] 🖥️ GUI render complete: {len(self.articles)} cards updated across {len(sources)} sources"
        )
        self._set_status(
            f"Loaded {len(self.articles)} articles from {len(sources)} sources", "success"
        )


    def _on_article_saved(self, article_id: str, is_saved: bool) -> None:
        if is_saved:
            self.saved_articles.add(article_id)
        else:
            self.saved_articles.discard(article_id)

        self.sidebar.update_stats(
            articles=len(self.articles),
            sources=len(
                {a.get("source", "") for a in self.articles if a.get("source")}
            ),
            saved=len(self.saved_articles),
        )

    def _toggle_sidebar(self) -> None:
        """Slide the sidebar open/closed. It's an animation on maximumWidth
        rather than a simple show/hide so it actually slides instead of
        popping instantly -- the sidebar widget itself stays alive and its
        internal timers/stat updates keep running either way, so nothing
        goes stale while it's collapsed."""
        self._sidebar_animation.stop()
        start = self.sidebar.maximumWidth()
        end = self.sidebar.EXPANDED_WIDTH if not self._sidebar_expanded else 0
        self._sidebar_animation.setStartValue(start)
        self._sidebar_animation.setEndValue(end)
        self._sidebar_animation.start()
        self._sidebar_expanded = not self._sidebar_expanded

    def _on_article_click(self, article: Dict[str, Any]) -> None:
        try:
            # Pass the orchestrator so the viewer can fetch full article
            # content via DeepScraper when the article's `content` field
            # is empty (which is the case for RSS articles — they only
            # have a summary/description, not the full body).
            show_article_viewer(self, article, orchestrator=self._orchestrator)
        except Exception as exc:
            logger.warning("Article viewer failed: %s", exc)
            self._set_status(f"Could not open article viewer: {exc}", "error")

    def _apply_search_and_filters(self) -> None:
        filtered = self.articles
        
        # 1. Advanced Feeds Filter
        if getattr(self, '_advanced_feeds_mode', False):
            filtered = [
                a for a in filtered 
                if a.get('is_advanced', False) or 
                   'duckduckgo' in str(a.get('source_api', '')).lower() or 
                   'duckduckgo' in str(a.get('source', '')).lower()
            ]

        # 2. Search Query Filter
        if self._active_query:
            query_terms = [t for t in self._active_query.lower().split() if t]

            def score_article(article: Dict[str, Any]) -> float:
                title = str(article.get("title", "")).lower()
                body_fields = [
                    article.get("source", ""),
                    article.get("ai_summary", ""),
                    article.get("summary", ""),
                    article.get("full_content", ""),
                    " ".join(article.get("topics", []) or []),
                    " ".join(article.get("keywords", []) or []),
                    " ".join(article.get("entities", []) or []),
                ]
                body = " ".join(str(v) for v in body_fields if v).lower()

                score = 0.0
                for term in query_terms:
                    title_hits = title.count(term)
                    body_hits = body.count(term)
                    if title_hits == 0 and body_hits == 0:
                        return 0.0  # AND semantics
                    score += title_hits * 3.0 + body_hits * 1.0
                return score

            scored = [(score_article(a), a) for a in filtered]
            filtered = [a for s, a in sorted(scored, key=lambda pair: pair[0], reverse=True) if s > 0]
            
            if not filtered:
                self.feed_panel.set_articles([])
                self._set_status(f"No articles found matching '{self._active_query}'")
                return
                
            self._set_status(f"Found {len(filtered)} articles matching '{self._active_query}'")
        else:
            if getattr(self, '_advanced_feeds_mode', False):
                self._set_status(f"Showing {len(filtered)} Advanced/Bypassed articles")
            else:
                self._set_status("Search cleared")

        self.feed_panel.set_articles(filtered)

    def _on_search(self, query: str) -> None:
        self._active_query = query.strip()
        self._apply_search_and_filters()
        
        # If no local match and we have a query, try remote search (DuckDuckGo fallback)
        if self._active_query and self.feed_panel.container_layout.count() <= 1:
            self._set_status(
                f"No local match for '{self._active_query}', trying remote search..."
            )
            get_async_bridge().run_coro(
                self._run_remote_search(self._active_query),
                callback=self._on_fetch_complete,
            )

    def _on_advanced_feeds_toggled(self, checked: bool) -> None:
        self._advanced_feeds_mode = checked
        self._apply_search_and_filters()

    async def _run_remote_search(self, query: str) -> List[Any]:
        if not self._orchestrator:
            return []

        try:
            result = await self._orchestrator.search(
                query, max_articles=50, max_sources=5
            )
            return list(getattr(result, "articles", []) or [])
        except Exception as exc:
            logger.warning("Remote search failed for '%s': %s", query, exc)
            return []

    def _on_mode_change(self, mode: str) -> None:
        self._set_status(f"Storage mode: {mode.upper()}")

    def _on_url_analysis(self, url: str) -> None:
        url = url.strip()

        if not url:
            self._set_status("Paste a URL first", "warning")
            return

        if not url.startswith(("http://", "https://")):
            self._set_status("URL must start with http:// or https://", "warning")
            return

        self._set_status(f"🔬 Analyzing {url[:80]}...")

        async def analyze() -> Any:
            if self._orchestrator:
                return await self._orchestrator.analyze_url(url)
            return None

        def on_complete(result: Any) -> None:
            if result and getattr(result, "article", None):
                article = self._convert_article_to_dict(result.article)
                # Treat manual URL analysis as an advanced view
                article['is_advanced'] = True
                
                self._update_live_metrics(progress=100)
                self._set_status("✓ URL analysis complete", "success")
                
                # Open directly in the separate popup widget without polluting the main stream
                self._on_article_click(article)
            else:
                self._set_status("URL analysis returned no article", "warning")

        def on_error(error: Exception) -> None:
            self._set_status(f"URL analysis error: {error}", "error")

        get_async_bridge().run_coro(
            analyze(), callback=on_complete, error_callback=on_error
        )

    def _show_preferences(self) -> None:
        dialog = PreferencesDialog(self)
        dialog.preferences_changed.connect(self._apply_preferences)
        dialog.exec()

    def _show_statistics(self) -> None:
        try:
            dialog = StatisticsPopup(
                self,
                orchestrator=self._orchestrator,
                controller=_StatsControllerAdapter(self),
            )
            dialog.exec()
        except Exception as exc:
            logger.warning("Statistics popup fallback due to: %s", exc)
            self._set_status(f"Statistics popup error: {exc}", "error")

    def _toggle_dashboard(self) -> None:
        self.dashboard.setVisible(not self.dashboard.isVisible())

    def _apply_preferences(self, prefs: Dict[str, Any]) -> None:
        mode = prefs.get("storage", {}).get("mode", "hybrid")
        mode_lookup = {"ephemeral": 0, "hybrid": 1, "persistent": 2}
        self.sidebar.mode_combo.setCurrentIndex(mode_lookup.get(mode, 1))
        self._set_status("Preferences saved", "success")

    def _show_history(self) -> None:
        """Show session History popup displaying all archived cycle articles."""
        all_session_history = list(self.archived_history)
        
        # Include current active articles if they are not already in archived list
        seen = {a.get("url", "") for a in all_session_history if a.get("url")}
        for art in self.articles:
            url = art.get("url", "")
            if url and url not in seen:
                all_session_history.append(art)

        try:
            from gui_qt.dialogs.history_popup import HistoryPopup
            popup = HistoryPopup(parent=self, articles=all_session_history)
            popup.exec()
        except Exception as exc:
            logger.error("Error opening History popup: %s", exc)
            self._set_status(f"Error displaying history: {exc}", "error")


    def _on_batch_restored(self, articles: List[Dict[str, Any]]) -> None:
        canonical = self._canonicalize_articles(articles)
        self.articles = canonical
        self.feed_panel.set_articles(canonical)
        self._update_caches_from_articles(canonical)
        self._update_live_metrics(progress=100)
        self._set_status(f"Restored {len(canonical)} articles from history", "success")

    def _on_article_archived(self, article_payload: Any) -> None:
        """Archive an article into history so it moves out of the live feeder."""
        try:
            if isinstance(article_payload, dict):
                art_id = article_payload.get("id", "")
                url = article_payload.get("url", "")
                art_dict = article_payload
            else:
                art_id = str(article_payload)
                art_dict = next((a for a in self.articles if a.get("id") == art_id), {})
                url = art_dict.get("url", "")

            if url and url not in self.archived_urls:
                self.archived_urls.add(url)
                if art_dict:
                    self.archived_history.append(art_dict)

            self.articles = [a for a in self.articles if a.get("id") != art_id and (not url or a.get("url") != url)]
            self.feed_panel.set_articles(self.articles)
            self._update_caches_from_articles(self.articles)
            self._update_live_metrics()
            self._set_status("Article moved to history", "info")
        except Exception as e:
            logger.error(f"Error archiving article: {e}")
            self._set_status("Error archiving article", "error")


    def _on_export(self) -> None:
        if not self.articles:
            self._set_status("No articles to export", "warning")
            return

        dialog = ExportDialog(self.articles, self)
        dialog.exec()

    def _show_sentiment_dashboard(self) -> None:
        if not self.articles:
            self._set_status("No articles available for sentiment analysis", "warning")
            return

        dialog = SentimentDashboard(self.articles, self)
        dialog.exec()

    def _show_alert_config(self) -> None:
        show_alert_config(self)

    def _show_newsletter_dialog(self) -> None:
        show_newsletter_dialog(self, articles=self.articles)

    def _show_crawler_dialog(self) -> None:
        if self._crawler_dialog and self._crawler_dialog.isVisible():
            self._crawler_dialog.raise_()
            self._crawler_dialog.activateWindow()
            return

        self._crawler_dialog = CrawlerDialog(self, orchestrator=self._orchestrator)
        self._crawler_dialog.crawl_completed.connect(self._on_crawler_completed)
        self._crawler_dialog.show()

    def _on_crawler_completed(self, crawled_articles: List[Any]) -> None:
        if not crawled_articles:
            self._set_status("Crawler completed with no new articles", "warning")
            return

        converted = self._canonicalize_articles(crawled_articles)
        converted_urls = {c.get("url") for c in converted if c.get("url")}
        merged = converted + [
            a for a in self.articles if a.get("url") not in converted_urls
        ]
        self._record_history_snapshot("crawler_merge")
        self.articles = merged[:1000]
        self.feed_panel.set_articles(self.articles)
        self._update_caches_from_articles(self.articles)
        self._update_live_metrics(progress=100)
        self._set_status(f"Crawler merged {len(converted)} articles", "success")

    def _update_intelligence_stats(self) -> None:
        """Push in-memory intelligence counters to the sidebar panel.

        Counters are updated by _score_articles_in_memory() after each fetch.
        Falls back to a DB query only when no articles have been scored yet.
        """
        analyzed = self._intel_analyzed
        disruptive = self._intel_disruptive
        high_priority = self._intel_high_priority

        if analyzed == 0 and self.articles:
            pass

        QTimer.singleShot(
            0,
            lambda a=analyzed, d=disruptive, h=high_priority: (
                self.sidebar.update_intelligence_stats(
                    analyzed=a,
                    disruptive=d,
                    high_priority=h,
                )
            ),
        )

    def _show_live_monitor(self) -> None:
        """Open the full-screen Live Monitor overlay with real pipeline data."""
        try:
            from gui_qt.widgets.live_monitor_overlay import LiveMonitorOverlay

            # Score articles if not yet done
            if self._intel_analyzed == 0 and self.articles:
                self._score_articles_in_memory(self.articles)

            sources_active = len(
                {a.get("source", "") for a in self.articles if a.get("source")}
            )
            overlay = LiveMonitorOverlay(
                self,
                articles=self.articles,
                intel_analyzed=self._intel_analyzed,
                intel_disruptive=self._intel_disruptive,
                intel_high_prio=self._intel_high_priority,
                sources_active=sources_active,
            )

            # Pass the orchestrator to the overlay for deeper metrics if possible
            if hasattr(overlay, "set_orchestrator"):
                overlay.set_orchestrator(self._orchestrator)

            overlay.exec()
        except Exception as exc:
            logger.warning("Live Monitor overlay not available: %s", exc)
            self._set_status("Live Monitor not available yet", "warning")

    def _show_disruptive_news(self) -> None:
        """Open the Disruptive News dialog, seeded with in-memory scored articles."""
        try:
            from gui_qt.dialogs.disruptive_news_dialog import DisruptiveNewsDialog

            # If we haven't scored yet, run scoring now so the dialog has data.
            if self._intel_analyzed == 0 and self.articles:
                self._score_articles_in_memory(self.articles)

            dialog = DisruptiveNewsDialog(self, in_memory_articles=self.articles)
            dialog.exec()
        except Exception as exc:
            logger.warning("Disruptive News dialog not available: %s", exc)
            self._set_status("Disruptive News dialog not available yet", "warning")

    def _set_status(self, message: str, level: str = "info") -> None:
        """Thread-safe status bar update — always dispatches to the main thread."""

        def _do_update():
            try:
                colors = {
                    "info": COLORS.fg,
                    "success": COLORS.green,
                    "warning": COLORS.orange,
                    "error": COLORS.red,
                }
                self.status_bar.setStyleSheet(
                    f"background-color: {COLORS.bg_dark}; color: {colors.get(level, COLORS.fg)}; border-top: 1px solid {COLORS.border};"
                )
                self.status_bar.showMessage(message)
            except RuntimeError:
                pass  # Widget already deleted during shutdown

        QTimer.singleShot(0, _do_update)

    def closeEvent(self, event) -> None:
        if getattr(self, "_shutdown_completed", False):
            event.accept()
            return

        event.ignore()

        if getattr(self, "_shutdown_in_progress", False):
            return

        self._shutdown_in_progress = True
        self._event_manager.stop()

        async def shutdown() -> None:
            if self._global_discovery:
                await self._global_discovery.stop()
            if self._reddit_stream:
                await self._reddit_stream.stop()
            if self._pipeline:
                await self._pipeline.stop()
            if self._orchestrator and hasattr(self._orchestrator, "shutdown"):
                await self._orchestrator.shutdown()

        def on_shutdown_done(fut):
            try:
                fut.result()
            except Exception as exc:
                logger.debug("Shutdown exception: %s", exc)
            self._shutdown_completed = True
            cleanup()
            logger.info("Application closed cleanly")
            QTimer.singleShot(0, self.close)

        try:
            bridge = get_async_bridge()
            future = bridge.run_coro(shutdown())
            future.add_done_callback(on_shutdown_done)
        except Exception as exc:
            logger.debug("Shutdown trigger error: %s", exc)
            self._shutdown_completed = True
            cleanup()
            QTimer.singleShot(0, self.close)


def main() -> None:
    app = QApplication(sys.argv)
    app.setApplicationName("Tech News Scraper")
    app.setApplicationVersion(TechNewsApp.VERSION)

    apply_theme(app)

    window = TechNewsApp()
    window.show()

    # macOS: bring app to front once at startup.
    import platform

    if platform.system() == "Darwin":
        window.raise_()
        window.activateWindow()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
