"""
Live Monitor Overlay — Tech News Scraper v8.0

Full-screen overlay compositing 7 live sub-widgets:
  1. LiveSourceHeartbeatMonitor
  2. LiveArticleStreamPreview
  3. LiveActivityLog
  4. LiveStatisticsPanel (8 metrics + trend arrows)
  5. PipelineVisualizer
  6. SourceActivityMatrix
  7. NetworkThroughputGraph

Opened as a QDialog (exec()) from the sidebar "View Live Monitor" button.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtWidgets import (
    QDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from ..theme import COLORS, Fonts
from ..event_manager import get_event_manager, EventType, GUIEvent

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _try_import_widget(module_path: str, class_name: str) -> Optional[type]:
    """Import a widget class by dotted module path, returning None on failure."""
    try:
        import importlib

        mod = importlib.import_module(module_path)
        return getattr(mod, class_name)
    except Exception as exc:
        logger.debug("Could not import %s.%s: %s", module_path, class_name, exc)
        return None


class _FallbackWidget(QFrame):
    """Placeholder shown when a sub-widget cannot be imported."""

    def __init__(self, title: str, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setStyleSheet(
            f"""
            QFrame {{
                background-color: {COLORS.bg_highlight};
                border: 1px dashed {COLORS.border};
                border-radius: 6px;
            }}
            """
        )
        layout = QVBoxLayout(self)
        icon = QLabel("📡")
        icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        icon.setStyleSheet("font-size: 28px; background: transparent;")
        layout.addWidget(icon)

        lbl = QLabel(title)
        lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lbl.setStyleSheet(
            f"color: {COLORS.comment}; font-size: 12px; background: transparent;"
        )
        layout.addWidget(lbl)


def _make_widget(module_path: str, class_name: str, title: str) -> QWidget:
    """Import and instantiate a widget, falling back to a placeholder."""
    cls = _try_import_widget(module_path, class_name)
    if cls is not None:
        try:
            return cls()
        except Exception as exc:
            logger.debug("Could not instantiate %s: %s", class_name, exc)
    return _FallbackWidget(title)


# ---------------------------------------------------------------------------
# LiveStatisticsPanel — 8 metrics with trend arrows
# ---------------------------------------------------------------------------


class LiveStatisticsPanel(QFrame):
    """
    8-metric statistics panel with trend arrows.

    Metrics:
      Total Articles, Sources Active, Articles/min, Dedup Rate,
      High Priority, Disruptive, Avg Score, API Latency
    """

    _METRICS = [
        ("📰", "Total Articles", COLORS.cyan),
        ("🌐", "Sources Active", COLORS.green),
        ("⚡", "Articles / min", COLORS.yellow),
        ("🔄", "Dedup Rate", COLORS.orange),
        ("🔴", "High Priority", COLORS.red),
        ("💥", "Disruptive", COLORS.magenta),
        ("📊", "Avg Score", COLORS.blue),
        ("🕒", "API Latency", COLORS.comment),
    ]

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._values: dict[str, tuple[float, float]] = {}  # name -> (current, prev)
        self._value_labels: dict[str, QLabel] = {}
        self._trend_labels: dict[str, QLabel] = {}
        self._setup_ui()

        self._demo_timer = QTimer(self)
        self._demo_timer.timeout.connect(self._tick_demo)
        # self._demo_timer.start(3000)  # DEMO TIMER DISABLED BY OPENCODE
        self._tick_demo()

    def _setup_ui(self) -> None:
        self.setStyleSheet(
            f"""
            LiveStatisticsPanel {{
                background-color: {COLORS.bg_highlight};
                border: 1px solid {COLORS.border};
                border-radius: 8px;
            }}
            """
        )
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(8)

        title_row = QHBoxLayout()
        title = QLabel("📈 Live Statistics")
        title.setFont(Fonts.get_qfont("md", "bold"))
        title.setStyleSheet(f"color: {COLORS.cyan}; background: transparent;")
        title_row.addWidget(title)
        title_row.addStretch()
        layout.addLayout(title_row)

        grid = QGridLayout()
        grid.setSpacing(8)

        for i, (icon, name, color) in enumerate(self._METRICS):
            row, col = divmod(i, 2)
            cell = QFrame()
            cell.setStyleSheet(
                f"""
                QFrame {{
                    background-color: {COLORS.bg_visual};
                    border-radius: 6px;
                }}
                """
            )
            cell_layout = QVBoxLayout(cell)
            cell_layout.setContentsMargins(10, 6, 10, 6)
            cell_layout.setSpacing(2)

            # Icon + name
            header_lbl = QLabel(f"{icon} {name}")
            header_lbl.setStyleSheet(
                f"color: {COLORS.comment}; font-size: 10px; background: transparent;"
            )
            cell_layout.addWidget(header_lbl)

            # Value + trend
            bottom_row = QHBoxLayout()
            val_lbl = QLabel("—")
            val_lbl.setStyleSheet(
                f"color: {color}; font-weight: bold; font-size: 16px; background: transparent;"
            )
            bottom_row.addWidget(val_lbl)
            bottom_row.addStretch()
            trend_lbl = QLabel("")
            trend_lbl.setStyleSheet("font-size: 14px; background: transparent;")
            bottom_row.addWidget(trend_lbl)
            cell_layout.addLayout(bottom_row)

            self._value_labels[name] = val_lbl
            self._trend_labels[name] = trend_lbl
            grid.addWidget(cell, row, col)

        layout.addLayout(grid)

    def update_metric(self, name: str, value: float, unit: str = "") -> None:
        """Update a single metric value and compute its trend arrow."""
        if name not in self._value_labels:
            return
        prev = self._values.get(name, (0.0, 0.0))[0]
        self._values[name] = (value, prev)

        fmt = f"{value:.0f}{unit}" if unit else f"{value:,.0f}"
        self._value_labels[name].setText(fmt)

        if value > prev:
            self._trend_labels[name].setText("▲")
            self._trend_labels[name].setStyleSheet(
                f"color: {COLORS.green}; font-size: 14px; background: transparent;"
            )
        elif value < prev:
            self._trend_labels[name].setText("▼")
            self._trend_labels[name].setStyleSheet(
                f"color: {COLORS.red}; font-size: 14px; background: transparent;"
            )
        else:
            self._trend_labels[name].setText("—")
            self._trend_labels[name].setStyleSheet(
                f"color: {COLORS.comment}; font-size: 14px; background: transparent;"
            )

    def push_real_stats(
        self,
        total_articles: int = 0,
        sources_active: int = 0,
        high_priority: int = 0,
        disruptive: int = 0,
        avg_score: float = 0.0,
        api_latency_ms: int = 0,
    ) -> None:
        """Push real metric values, stopping demo timer."""
        self._demo_timer.stop()
        self.update_metric("Total Articles", float(total_articles))
        self.update_metric("Sources Active", float(sources_active))
        self.update_metric("High Priority", float(high_priority))
        self.update_metric("Disruptive", float(disruptive))
        self.update_metric("Avg Score", avg_score)
        if api_latency_ms:
            self.update_metric("API Latency", float(api_latency_ms), "ms")

    def _tick_demo(self) -> None:
        """Simulate fluctuating metrics for demo/initial display."""
        import random

        prev = {n: self._values.get(n, (0.0, 0.0))[0] for _, n, _ in self._METRICS}
        self.update_metric(
            "Total Articles",
            max(0, prev.get("Total Articles", 0) + random.randint(0, 5)),
        )
        self.update_metric("Sources Active", random.randint(8, 12))
        self.update_metric("Articles / min", round(random.uniform(0.5, 4.0), 1))
        self.update_metric("Dedup Rate", round(random.uniform(10, 30), 1), "%")
        self.update_metric("High Priority", random.randint(0, 8))
        self.update_metric("Disruptive", random.randint(0, 3))
        self.update_metric("Avg Score", round(random.uniform(6.0, 9.0), 1))
        self.update_metric("API Latency", random.randint(80, 400), "ms")


# ---------------------------------------------------------------------------
# LiveMonitorOverlay
# ---------------------------------------------------------------------------


class LiveMonitorOverlay(QDialog):
    """
    Full-screen live monitoring overlay compositing 7 sub-widgets.

    Layout:
      ┌─────────────────────────────────────────────────────────┐
      │  Header bar: title + close button                        │
      ├─────────────────────────────────────────────────────────┤
      │  LEFT COLUMN             │  RIGHT COLUMN                 │
      │  ─────────────────────── │  ──────────────────────────── │
      │  LiveSourceHeartbeat (1) │  LiveStatisticsPanel (4)      │
      │  PipelineVisualizer  (5) │  LiveActivityLog (3)          │
      │  SourceActivityMatrix(6) │  NetworkThroughputGraph (7)   │
      │                          │  LiveArticleStream (2)        │
      └─────────────────────────────────────────────────────────┘

    Pass real data via the keyword args to seed the sub-widgets:
      articles          — list of canonicalized article dicts
      intel_analyzed    — int: number of articles scored
      intel_disruptive  — int: disruptive article count
      intel_high_prio   — int: high-priority article count
      sources_active    — int: number of active sources
    """

    def __init__(
        self,
        parent: Optional[QWidget] = None,
        articles: Optional[List[Dict[str, Any]]] = None,
        intel_analyzed: int = 0,
        intel_disruptive: int = 0,
        intel_high_prio: int = 0,
        sources_active: int = 0,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("🖥️ Live Monitor")
        self.setWindowFlag(Qt.WindowType.Window)
        self.resize(1400, 900)

        self._articles = articles or []
        self._intel_analyzed = intel_analyzed
        self._intel_disruptive = intel_disruptive
        self._intel_high_prio = intel_high_prio
        self._sources_active = sources_active
        self._orchestrator = None

        # Sub-widget references (set in _setup_ui)
        self._stats_panel: Optional[LiveStatisticsPanel] = None
        self._heartbeat_widget: Optional[QWidget] = None
        self._activity_log_widget: Optional[QWidget] = None
        self._article_stream_widget: Optional[QWidget] = None
        self._pipeline_widget: Optional[QWidget] = None
        self._matrix_widget: Optional[QWidget] = None

        self._setup_ui()
        self._apply_styles()

        # Push real data after UI is built
        QTimer.singleShot(100, self._push_real_data)

        # Subscribe to real-time events
        self._event_manager = get_event_manager()
        self._event_manager.subscribe(EventType.NEWS_UPDATE, self._on_news_update)
        self._event_manager.subscribe(EventType.METRICS_UPDATE, self._on_metrics_update)

    def set_orchestrator(self, orchestrator) -> None:
        self._orchestrator = orchestrator
        # Trigger an immediate pipeline refresh
        self._poll_orchestrator_state()

        # Start a real poll timer for pipeline updates instead of random demo
        self._orch_poll_timer = QTimer(self)
        self._orch_poll_timer.timeout.connect(self._poll_orchestrator_state)
        self._orch_poll_timer.start(2000)

    def _poll_orchestrator_state(self) -> None:
        if not self._orchestrator:
            return

        try:
            # Sync matrix
            if self._matrix_widget and hasattr(self._matrix_widget, "update_activity"):
                from gui_qt.widgets.source_activity_matrix import SourceActivity

                sources_dict = getattr(self._orchestrator, "_sources", {})
                for src_name, status in sources_dict.items():
                    act = SourceActivity(
                        name=src_name,
                        status="active"
                        if getattr(status, "status", "") == "online"
                        else "idle",
                        progress=100,
                        items_count=getattr(status, "article_count", 0),
                        current_task=f"Latency {getattr(status, 'latency', 0)}ms",
                        success_count=getattr(status, "article_count", 0),
                        error_count=getattr(status, "error_count", 0),
                    )
                    self._matrix_widget.update_activity(act)

            # Sync pipeline (simple heuristic mapped to article count for now,
            # since true orchestrator stages aren't perfectly mapped)
            if self._pipeline_widget and hasattr(
                self._pipeline_widget, "set_stage_state"
            ):
                from gui_qt.widgets.pipeline_visualizer import PipelineStage, StageState

                # Discovery is always complete if we have articles
                count = len(self._articles)
                d_state = StageState(
                    PipelineStage.DISCOVERY, "completed", 100, count, "Fetched"
                )
                self._pipeline_widget.set_stage_state(PipelineStage.DISCOVERY, d_state)

                e_state = StageState(
                    PipelineStage.EXTRACTION,
                    "active" if count % 5 != 0 else "completed",
                    min(100, (count * 2) % 100),
                    count,
                    "Extracting text",
                )
                self._pipeline_widget.set_stage_state(PipelineStage.EXTRACTION, e_state)

                i_state = StageState(
                    PipelineStage.INTELLIGENCE,
                    "completed",
                    100,
                    self._intel_analyzed,
                    "Scoring",
                )
                self._pipeline_widget.set_stage_state(
                    PipelineStage.INTELLIGENCE, i_state
                )

        except Exception as e:
            logger.debug(f"Failed to poll orchestrator: {e}")

    def closeEvent(self, event):
        """Unsubscribe when closed."""
        self._event_manager.unsubscribe(EventType.NEWS_UPDATE, self._on_news_update)
        self._event_manager.unsubscribe(
            EventType.METRICS_UPDATE, self._on_metrics_update
        )
        super().closeEvent(event)

    def _on_news_update(self, event: GUIEvent):
        """Handle incoming live articles."""
        article = event.data
        if not article:
            return

        self._articles.insert(0, article)
        if len(self._articles) > 500:
            self._articles.pop()

        # Re-tally metrics
        self._intel_disruptive = sum(1 for a in self._articles if a.get("_disruptive"))
        self._intel_high_prio = sum(
            1
            for a in self._articles
            if (a.get("_criticality", 0) > 0.7 or a.get("_disruptive"))
        )
        self._sources_active = len(
            {a.get("source", "") for a in self._articles if a.get("source")}
        )

        # Add to stream immediately
        stream_widget = self._article_stream_widget
        if stream_widget is not None and hasattr(stream_widget, "add_article"):
            from gui_qt.widgets.live_article_stream import StreamArticle

            ts_raw = (
                article.get("published_at")
                or article.get("fetched_at")
                or datetime.now()
            )
            if isinstance(ts_raw, str):
                try:
                    ts_raw = datetime.fromisoformat(ts_raw[:19])
                except ValueError:
                    ts_raw = datetime.now()
            elif not isinstance(ts_raw, datetime):
                ts_raw = datetime.now()

            tech_score = article.get("tech_score", 0)
            if isinstance(tech_score, dict):
                tech_score = float(tech_score.get("score", 0) or 0)
            else:
                tech_score = float(tech_score or 0)

            stream_art = StreamArticle(
                title=article.get("title", "Untitled")[:80],
                source=article.get("source", "Unknown"),
                timestamp=ts_raw,
                score=tech_score,
                url=article.get("url", ""),
                id=str(article.get("id", "")),
            )
            stream_widget.add_article(stream_art)

        # Update log
        log_widget = self._activity_log_widget
        if log_widget is not None and hasattr(log_widget, "info"):
            title = article.get("title", "")[:60]
            source = article.get("source", "unknown")
            log_widget.info(f"[{source}] {title}", source="Feed")

        self._push_real_data()

    def _on_metrics_update(self, event: GUIEvent):
        pass  # Optional to handle other metrics

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # ── Header bar ─────────────────────────────────────────────────────
        header = QFrame()
        header.setFixedHeight(56)
        header.setStyleSheet(
            f"background-color: {COLORS.bg_dark}; border-bottom: 2px solid {COLORS.cyan};"
        )
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(20, 0, 20, 0)
        header_layout.setSpacing(14)

        pulse_lbl = QLabel("● LIVE")
        pulse_lbl.setStyleSheet(
            f"color: {COLORS.green}; font-weight: bold; font-size: 14px;"
        )
        self._pulse_lbl = pulse_lbl
        self._pulse_state = True
        self._pulse_timer = QTimer(self)
        self._pulse_timer.timeout.connect(self._tick_pulse)
        # self._pulse_timer.start(800)  # DEMO TIMER DISABLED BY OPENCODE
        header_layout.addWidget(pulse_lbl)

        title = QLabel("Live Monitor — Tech News Scraper v8.0")
        title.setStyleSheet(f"color: {COLORS.fg}; font-size: 16px; font-weight: bold;")
        header_layout.addWidget(title)
        header_layout.addStretch()

        # Stats summary in header
        self._header_stats = QLabel("")
        self._header_stats.setStyleSheet(f"color: {COLORS.comment}; font-size: 12px;")
        header_layout.addWidget(self._header_stats)
        
        clear_cache_btn = QPushButton("🗑️ Clear Cache & Fresh Start")
        clear_cache_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        clear_cache_btn.setStyleSheet(
            f"""
            QPushButton {{
                background-color: {COLORS.orange};
                color: {COLORS.bg};
                border: none;
                border-radius: 6px;
                padding: 6px 16px;
                font-weight: bold;
            }}
            QPushButton:hover {{
                background-color: {COLORS.yellow};
            }}
            """
        )
        clear_cache_btn.clicked.connect(self._clear_cache_and_restart)
        header_layout.addWidget(clear_cache_btn)

        close_btn = QPushButton("✕ Close")
        close_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        close_btn.setStyleSheet(
            f"""
            QPushButton {{
                background-color: {COLORS.red};
                color: {COLORS.fg};
                border: none;
                border-radius: 6px;
                padding: 6px 16px;
                font-weight: bold;
            }}
            QPushButton:hover {{
                background-color: {COLORS.bright_red};
            }}
            """
        )
        close_btn.clicked.connect(self.accept)
        header_layout.addWidget(close_btn)
        layout.addWidget(header)

        # ── Body ─────────────────────────────────────────────────────────
        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setStyleSheet(
            f"QSplitter::handle {{ background-color: {COLORS.border}; width: 2px; }}"
        )

        # Left column
        left_pane = QWidget()
        left_layout = QVBoxLayout(left_pane)
        left_layout.setContentsMargins(8, 8, 4, 8)
        left_layout.setSpacing(8)

        heartbeat = _make_widget(
            "gui_qt.widgets.live_source_monitor",
            "LiveSourceHeartbeatMonitor",
            "Live Source Heartbeat Monitor",
        )
        self._heartbeat_widget = heartbeat
        left_layout.addWidget(heartbeat, 2)

        pipeline = _make_widget(
            "gui_qt.widgets.pipeline_visualizer",
            "PipelineVisualizer",
            "Pipeline Visualizer",
        )
        self._pipeline_widget = pipeline
        left_layout.addWidget(pipeline, 2)

        matrix = _make_widget(
            "gui_qt.widgets.source_activity_matrix",
            "SourceActivityMatrix",
            "Source Activity Matrix",
        )
        self._matrix_widget = matrix
        left_layout.addWidget(matrix, 1)

        splitter.addWidget(left_pane)

        # Right column
        right_pane = QWidget()
        right_layout = QVBoxLayout(right_pane)
        right_layout.setContentsMargins(4, 8, 8, 8)
        right_layout.setSpacing(8)

        stats_panel = LiveStatisticsPanel()
        self._stats_panel = stats_panel
        right_layout.addWidget(stats_panel, 2)

        activity_log = _make_widget(
            "gui_qt.widgets.live_activity_log",
            "LiveActivityLog",
            "Live Activity Log",
        )
        self._activity_log_widget = activity_log
        right_layout.addWidget(activity_log, 2)

        net_graph = _make_widget(
            "gui_qt.widgets.network_graph",
            "NetworkThroughputGraph",
            "Network Throughput Graph",
        )
        right_layout.addWidget(net_graph, 1)

        article_stream = _make_widget(
            "gui_qt.widgets.live_article_stream",
            "LiveArticleStreamPreview",
            "Live Article Stream",
        )
        self._article_stream_widget = article_stream
        right_layout.addWidget(article_stream, 2)

        splitter.addWidget(right_pane)
        splitter.setSizes([600, 800])
        layout.addWidget(splitter, 1)

    def _push_real_data(self) -> None:
        """Push real article/pipeline data into sub-widgets."""
        articles = self._articles

        # ── Header stats summary ─────────────────────────────────────────
        sources = len({a.get("source", "") for a in articles if a.get("source")})
        self._header_stats.setText(
            f"📰 {len(articles)} articles  |  🌐 {sources} sources  |  "
            f"💥 {self._intel_disruptive} disruptive  |  🔴 {self._intel_high_prio} high-priority"
        )

        # ── LiveStatisticsPanel ──────────────────────────────────────────
        if self._stats_panel is not None:
            avg_score = 0.0
            if articles:
                scores = []
                for a in articles:
                    ts = a.get("tech_score", 0)
                    if isinstance(ts, dict):
                        ts = float(ts.get("score", 0) or 0)
                    else:
                        ts = float(ts or 0)
                    if ts > 0:
                        scores.append(ts)
                if scores:
                    avg_score = sum(scores) / len(scores)

            self._stats_panel.push_real_stats(
                total_articles=len(articles),
                sources_active=self._sources_active or sources,
                high_priority=self._intel_high_prio,
                disruptive=self._intel_disruptive,
                avg_score=round(avg_score, 1),
            )

        # ── LiveActivityLog — inject a startup message ───────────────────
        log_widget = self._activity_log_widget
        if log_widget is not None and hasattr(log_widget, "info"):
            try:
                log_widget.info(  # type: ignore[union-attr]
                    f"Live Monitor opened — {len(articles)} articles loaded from "
                    f"{sources} sources",
                    source="Monitor",
                )
                if self._intel_disruptive > 0:
                    log_widget.warning(  # type: ignore[union-attr]
                        f"{self._intel_disruptive} disruptive articles detected",
                        source="Intelligence",
                    )
                if self._intel_high_prio > 0:
                    log_widget.info(  # type: ignore[union-attr]
                        f"{self._intel_high_prio} high-priority articles in feed",
                        source="Intelligence",
                    )
                # Log most recent 5 articles
                for article in articles[:5]:
                    title = article.get("title", "")[:60]
                    source = article.get("source", "unknown")
                    log_widget.info(  # type: ignore[union-attr]
                        f"[{source}] {title}", source="Feed"
                    )
            except Exception as exc:
                logger.debug("Could not inject log entries: %s", exc)

        # ── LiveArticleStreamPreview — inject real articles ───────────────
        stream_widget = self._article_stream_widget
        if stream_widget is not None and hasattr(stream_widget, "add_article"):
            try:
                # Import StreamArticle dataclass from the module
                from gui_qt.widgets.live_article_stream import StreamArticle

                for article in reversed(articles[:30]):
                    ts_raw = (
                        article.get("published_at")
                        or article.get("fetched_at")
                        or datetime.now()
                    )
                    if isinstance(ts_raw, str):
                        try:
                            ts_raw = datetime.fromisoformat(ts_raw[:19])
                        except ValueError:
                            ts_raw = datetime.now()
                    elif not isinstance(ts_raw, datetime):
                        ts_raw = datetime.now()

                    tech_score = article.get("tech_score", 0)
                    if isinstance(tech_score, dict):
                        tech_score = float(tech_score.get("score", 0) or 0)
                    else:
                        tech_score = float(tech_score or 0)

                    stream_art = StreamArticle(
                        title=article.get("title", "Untitled")[:80],
                        source=article.get("source", "Unknown"),
                        timestamp=ts_raw,
                        score=tech_score,
                        url=article.get("url", ""),
                        id=str(article.get("id", "")),
                    )
                    stream_widget.add_article(stream_art, animate=False)  # type: ignore[union-attr]
            except Exception as exc:
                logger.debug("Could not inject stream articles: %s", exc)

    def _apply_styles(self) -> None:
        self.setStyleSheet(f"QDialog {{ background-color: {COLORS.bg}; }}")

    def _tick_pulse(self) -> None:
        self._pulse_state = not self._pulse_state
        color = COLORS.green if self._pulse_state else COLORS.comment
        self._pulse_lbl.setStyleSheet(
            f"color: {color}; font-weight: bold; font-size: 14px;"
        )

    def _clear_cache_and_restart(self) -> None:
        from PyQt6.QtWidgets import QMessageBox
        reply = QMessageBox.question(
            self, 
            'Confirm Clear Cache', 
            'Are you sure you want to clear all stored articles and fresh start? This action cannot be undone.',
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No
        )
        
        if reply == QMessageBox.StandardButton.Yes:
            try:
                # Clear canonical database if exists
                try:
                    from config.settings import CANONICAL_DB_FILE
                    if CANONICAL_DB_FILE.exists():
                        import sqlite3
                        conn = sqlite3.connect(CANONICAL_DB_FILE)
                        conn.execute("DELETE FROM canonical_articles")
                        conn.commit()
                        conn.close()
                except Exception as ex:
                    logger.debug(f"Failed to clear storage: {ex}")
                
                if hasattr(self.parent(), '_start_live_feed'):
                    self.parent().articles = []
                    self.parent().feed_panel.set_articles([])
                    self.parent()._start_live_feed()
                self.accept()
            except Exception as e:
                logger.error(f"Failed to clear cache: {e}")
