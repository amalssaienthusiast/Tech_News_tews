"""
Admin Control Panel for gui_qt.

Full admin dashboard providing management & monitoring of all backend
services from within the PyQt6 GUI.

Sections:
- Service Management (FastAPI, Redis, Celery, Elasticsearch)
- Scraper Scheduler control (start / stop / status)
- Telegram Bot status
- API Key management
- System Health overview
- Configuration editor (tied to config_manager)
"""

import asyncio
import logging
import os
import signal
import subprocess
import sys
from datetime import datetime
from multiprocessing import Process
from pathlib import Path
from typing import Any, Dict, List, Optional

from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtWidgets import (
    QDialog,
    QFormLayout,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QTabWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from gui_qt.theme import COLORS

logger = logging.getLogger(__name__)

_PROJECT_ROOT = Path(__file__).resolve().parent.parent


# ──────────────────────────────────────────────────────────────────────────
# Helper: status indicator dot
# ──────────────────────────────────────────────────────────────────────────

class StatusDot(QLabel):
    """Small coloured circle indicating service status."""

    _CSS = """
        QLabel {{
            background-color: {colour};
            border-radius: 6px;
            min-width: 12px; max-width: 12px;
            min-height: 12px; max-height: 12px;
        }}
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.set_status("offline")

    def set_status(self, status: str) -> None:
        colour = {
            "online": COLORS.green,
            "starting": COLORS.yellow,
            "error": COLORS.red,
            "offline": COLORS.comment,
        }.get(status, COLORS.comment)
        self.setStyleSheet(self._CSS.format(colour=colour))
        self.setToolTip(status.capitalize())


# ──────────────────────────────────────────────────────────────────────────
# Service Row widget
# ──────────────────────────────────────────────────────────────────────────

class ServiceRow(QFrame):
    """One row: [status dot] [name] [description] [action btn]."""

    status_changed = pyqtSignal(str, str)  # service_name, new_status

    def __init__(
        self,
        name: str,
        description: str,
        *,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.service_name = name
        self._status = "offline"
        self._process: Optional[subprocess.Popen] = None

        self.setStyleSheet(f"""
            QFrame {{
                background-color: {COLORS.bg_highlight};
                border-radius: 6px;
                padding: 4px;
            }}
        """)

        lay = QHBoxLayout(self)
        lay.setContentsMargins(12, 8, 12, 8)

        self._dot = StatusDot()
        lay.addWidget(self._dot)

        info = QVBoxLayout()
        info.setSpacing(0)
        lbl = QLabel(name)
        lbl.setStyleSheet(f"font-weight: bold; color: {COLORS.fg};")
        info.addWidget(lbl)
        desc = QLabel(description)
        desc.setStyleSheet(f"font-size: 11px; color: {COLORS.fg_dark};")
        info.addWidget(desc)
        lay.addLayout(info, stretch=1)

        self._status_label = QLabel("Offline")
        self._status_label.setStyleSheet(f"color: {COLORS.comment}; font-size: 11px;")
        lay.addWidget(self._status_label)

        self._btn = QPushButton("Start")
        self._btn.setFixedWidth(80)
        self._btn.setStyleSheet(
            f"background-color: {COLORS.green}; color: {COLORS.bg_dark};"
            "border-radius: 4px; padding: 6px;"
        )
        self._btn.clicked.connect(self._toggle)
        lay.addWidget(self._btn)

    # -- public API --

    def set_status(self, status: str) -> None:
        self._status = status
        self._dot.set_status(status)
        self._status_label.setText(status.capitalize())
        if status == "online":
            self._btn.setText("Stop")
            self._btn.setStyleSheet(
                f"background-color: {COLORS.red}; color: {COLORS.fg};"
                "border-radius: 4px; padding: 6px;"
            )
        else:
            self._btn.setText("Start")
            self._btn.setStyleSheet(
                f"background-color: {COLORS.green}; color: {COLORS.bg_dark};"
                "border-radius: 4px; padding: 6px;"
            )

    def get_status(self) -> str:
        return self._status

    # -- toggle --------------------------------------------------------------

    def _toggle(self) -> None:
        if self._status == "online":
            self._stop_service()
        else:
            self._start_service()

    def _start_service(self) -> None:
        self.set_status("starting")
        self.status_changed.emit(self.service_name, "starting")

    def _stop_service(self) -> None:
        self.set_status("offline")
        self.status_changed.emit(self.service_name, "offline")


# ──────────────────────────────────────────────────────────────────────────
# Services Tab
# ──────────────────────────────────────────────────────────────────────────

class ServicesTab(QWidget):
    """Start / stop / monitor backend services."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._api_process: Optional[Process] = None
        lay = QVBoxLayout(self)
        lay.setSpacing(8)

        title = QLabel("🖧  Service Management")
        title.setStyleSheet(f"font-size: 15px; font-weight: bold; color: {COLORS.cyan};")
        lay.addWidget(title)

        self._services: Dict[str, ServiceRow] = {}
        services_info = [
            ("FastAPI Server", "REST API + WebSocket (port 8000)"),
            ("Redis", "Pub/sub & caching layer"),
            ("Celery Worker", "Distributed task queue"),
            ("Elasticsearch", "Full-text search index"),
            ("Telegram Bot", "Notification bot service"),
            ("Scraper Scheduler", "Periodic scraping task runner"),
        ]
        for name, desc in services_info:
            row = ServiceRow(name, desc)
            row.status_changed.connect(self._on_status_change)
            self._services[name] = row
            lay.addWidget(row)

        lay.addStretch()

        # Auto-probe on first show
        self._probe_timer = QTimer(self)
        self._probe_timer.setSingleShot(True)
        self._probe_timer.timeout.connect(self._probe_services)
        self._probe_timer.start(500)

    def _on_status_change(self, name: str, status: str) -> None:
        if name == "FastAPI Server":
            if status == "starting":
                self._start_api()
            elif status == "offline":
                self._stop_api()
        logger.info("Service %s → %s", name, status)

    # -- FastAPI management --------------------------------------------------

    def _start_api(self) -> None:
        try:
            import uvicorn  # noqa: F401

            def _run():
                uvicorn.run(
                    "api.main:app",
                    host="0.0.0.0",
                    port=8000,
                    reload=False,
                    log_level="info",
                )

            self._api_process = Process(target=_run, daemon=True)
            self._api_process.start()
            self._services["FastAPI Server"].set_status("online")
        except Exception as exc:  # noqa: BLE001
            logger.error("Failed to start FastAPI: %s", exc)
            self._services["FastAPI Server"].set_status("error")

    def _stop_api(self) -> None:
        if self._api_process and self._api_process.is_alive():
            self._api_process.terminate()
            self._api_process.join(timeout=3)
            self._api_process = None
        self._services["FastAPI Server"].set_status("offline")

    # -- service probing -----------------------------------------------------

    def _probe_services(self) -> None:
        """Best-effort detection of running services."""
        # Redis
        try:
            import redis as _redis
            r = _redis.Redis.from_url(os.getenv("REDIS_URL", "redis://localhost:6379/0"))
            r.ping()
            self._services["Redis"].set_status("online")
        except Exception:
            self._services["Redis"].set_status("offline")

        # Elasticsearch
        try:
            from elasticsearch import Elasticsearch
            es = Elasticsearch(os.getenv("ELASTICSEARCH_URL", "http://localhost:9200"))
            if es.ping():
                self._services["Elasticsearch"].set_status("online")
            else:
                self._services["Elasticsearch"].set_status("offline")
        except Exception:
            self._services["Elasticsearch"].set_status("offline")


# ──────────────────────────────────────────────────────────────────────────
# API Keys Tab
# ──────────────────────────────────────────────────────────────────────────

class APIKeysTab(QWidget):
    """View & edit API keys (environment variables)."""

    _KEYS = [
        ("GOOGLE_API_KEY", "Google Custom Search"),
        ("GOOGLE_CSE_ID", "Google CSE ID"),
        ("GEMINI_API_KEY", "Google Gemini AI"),
        ("NEWSAPI_KEY", "NewsAPI.org"),
        ("BING_API_KEY", "Bing News Search"),
        ("OPENAI_API_KEY", "OpenAI (GPT)"),
        ("ANTHROPIC_API_KEY", "Anthropic (Claude)"),
        ("REDDIT_CLIENT_ID", "Reddit Client ID"),
        ("REDDIT_CLIENT_SECRET", "Reddit Secret"),
        ("TELEGRAM_BOT_TOKEN", "Telegram Bot Token"),
        ("DISCORD_WEBHOOK_URL", "Discord Webhook"),
    ]

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        lay = QVBoxLayout(self)

        title = QLabel("🔑  API Key Management")
        title.setStyleSheet(f"font-size: 15px; font-weight: bold; color: {COLORS.cyan};")
        lay.addWidget(title)

        note = QLabel(
            "Keys are read from environment / .env.  Edit values below to update "
            "for this session (changes are NOT written to .env)."
        )
        note.setWordWrap(True)
        note.setStyleSheet(f"color: {COLORS.fg_dark}; font-size: 11px; margin-bottom: 8px;")
        lay.addWidget(note)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet("QScrollArea { border: none; }")
        inner = QWidget()
        form = QFormLayout(inner)
        form.setSpacing(8)

        self._edits: Dict[str, QLineEdit] = {}
        for env_var, label in self._KEYS:
            current = os.getenv(env_var, "")
            masked = self._mask(current)
            le = QLineEdit(masked)
            le.setEchoMode(QLineEdit.EchoMode.Password)
            le.setStyleSheet(f"""
                QLineEdit {{
                    background-color: {COLORS.bg_dark};
                    color: {COLORS.fg};
                    border: 1px solid {COLORS.border};
                    border-radius: 4px; padding: 6px;
                }}
            """)
            le.setProperty("env_var", env_var)
            self._edits[env_var] = le
            lbl = QLabel(f"{label}  ({env_var})")
            lbl.setStyleSheet(f"color: {COLORS.fg}; font-size: 12px;")
            form.addRow(lbl, le)

        scroll.setWidget(inner)
        lay.addWidget(scroll, stretch=1)

        # Save button
        save_btn = QPushButton("💾  Apply Keys for Session")
        save_btn.setStyleSheet(
            f"background-color: {COLORS.cyan}; color: {COLORS.bg_dark};"
            "border-radius: 4px; padding: 10px; font-weight: bold;"
        )
        save_btn.clicked.connect(self._apply_keys)
        lay.addWidget(save_btn)

    @staticmethod
    def _mask(value: str) -> str:
        if len(value) <= 4:
            return "•" * len(value)
        return value[:2] + "•" * (len(value) - 4) + value[-2:]

    def _apply_keys(self) -> None:
        count = 0
        for env_var, le in self._edits.items():
            val = le.text().strip()
            if val and "•" not in val:
                os.environ[env_var] = val
                count += 1
        QMessageBox.information(
            self, "Keys Applied",
            f"{count} key(s) updated for this session.",
        )


# ──────────────────────────────────────────────────────────────────────────
# Config Editor Tab
# ──────────────────────────────────────────────────────────────────────────

class ConfigEditorTab(QWidget):
    """Read / write unified configuration (ties to config_manager)."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        lay = QVBoxLayout(self)

        title = QLabel("📝  Configuration Editor")
        title.setStyleSheet(f"font-size: 15px; font-weight: bold; color: {COLORS.cyan};")
        lay.addWidget(title)

        self._text = QTextEdit()
        self._text.setStyleSheet(f"""
            QTextEdit {{
                background-color: {COLORS.bg_dark};
                color: {COLORS.fg};
                border: 1px solid {COLORS.border};
                border-radius: 4px;
                font-family: 'JetBrains Mono', 'SF Mono', 'Consolas', monospace;
                font-size: 12px;
            }}
        """)
        lay.addWidget(self._text, stretch=1)

        btn_row = QHBoxLayout()
        reload_btn = QPushButton("🔄 Reload")
        reload_btn.setStyleSheet(
            f"background-color: {COLORS.bg_highlight}; color: {COLORS.fg};"
            "border-radius: 4px; padding: 8px;"
        )
        reload_btn.clicked.connect(self._reload)
        btn_row.addWidget(reload_btn)

        save_btn = QPushButton("💾 Save")
        save_btn.setStyleSheet(
            f"background-color: {COLORS.green}; color: {COLORS.bg_dark};"
            "border-radius: 4px; padding: 8px; font-weight: bold;"
        )
        save_btn.clicked.connect(self._save)
        btn_row.addWidget(save_btn)

        reset_btn = QPushButton("♻️ Reset Defaults")
        reset_btn.setStyleSheet(
            f"background-color: {COLORS.red}; color: {COLORS.fg};"
            "border-radius: 4px; padding: 8px;"
        )
        reset_btn.clicked.connect(self._reset)
        btn_row.addWidget(reset_btn)

        lay.addLayout(btn_row)
        self._reload()

    def _reload(self) -> None:
        import json
        try:
            from gui_qt.config_manager import get_config
            cfg = get_config()
            self._text.setPlainText(json.dumps(cfg.get_config_summary(), indent=2))
        except Exception as exc:  # noqa: BLE001
            self._text.setPlainText(f"Error loading config: {exc}")

    def _save(self) -> None:
        import json
        try:
            from gui_qt.config_manager import get_config
            data = json.loads(self._text.toPlainText())
            sections = data.get("sections", data)
            cfg = get_config()
            for section_name in ("system", "ai", "bypass", "resilience", "user"):
                section_data = sections.get(section_name, {})
                for key, value in section_data.items():
                    cfg.set(f"{section_name}.{key}", value, save=False)
            cfg._save()
            QMessageBox.information(self, "Saved", "Configuration saved successfully.")
        except Exception as exc:  # noqa: BLE001
            QMessageBox.warning(self, "Error", f"Failed to save: {exc}")

    def _reset(self) -> None:
        reply = QMessageBox.question(
            self, "Reset", "Reset ALL settings to defaults?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.Yes:
            from gui_qt.config_manager import get_config
            get_config().reset_to_defaults()
            self._reload()


# ──────────────────────────────────────────────────────────────────────────
# System Health Tab
# ──────────────────────────────────────────────────────────────────────────

class SystemHealthTab(QWidget):
    """Live system health metrics (CPU, memory, uptime, etc.)."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        lay = QVBoxLayout(self)

        title = QLabel("💓  System Health")
        title.setStyleSheet(f"font-size: 15px; font-weight: bold; color: {COLORS.cyan};")
        lay.addWidget(title)

        self._metrics: Dict[str, QLabel] = {}
        grid = QVBoxLayout()
        for key, label, default in [
            ("cpu", "CPU Usage", "—"),
            ("memory", "Memory Usage", "—"),
            ("disk", "Disk Usage", "—"),
            ("uptime", "Process Uptime", "—"),
            ("articles_db", "Articles in DB", "—"),
            ("sources_active", "Active Sources", "—"),
            ("errors_1h", "Errors (last hour)", "—"),
            ("scrape_rate", "Scrape Rate", "—"),
        ]:
            row = QHBoxLayout()
            lbl = QLabel(label)
            lbl.setStyleSheet(f"color: {COLORS.fg_dark}; font-size: 13px;")
            row.addWidget(lbl)
            row.addStretch()
            val = QLabel(default)
            val.setStyleSheet(f"color: {COLORS.fg}; font-weight: bold; font-size: 13px;")
            self._metrics[key] = val
            row.addWidget(val)
            grid.addLayout(row)
        lay.addLayout(grid)
        lay.addStretch()

        # Refresh timer
        self._timer = QTimer(self)
        self._timer.setInterval(3000)
        self._timer.timeout.connect(self._refresh)
        self._timer.start()
        self._refresh()

    def _refresh(self) -> None:
        try:
            import psutil
            self._metrics["cpu"].setText(f"{psutil.cpu_percent():.1f}%")
            mem = psutil.virtual_memory()
            self._metrics["memory"].setText(f"{mem.percent:.1f}%  ({mem.used // (1024**2)} MB)")
            disk = psutil.disk_usage("/")
            self._metrics["disk"].setText(f"{disk.percent:.1f}%")
            import time, os
            pid = os.getpid()
            p = psutil.Process(pid)
            create_time = p.create_time()
            uptime_s = time.time() - create_time
            mins, secs = divmod(int(uptime_s), 60)
            hours, mins = divmod(mins, 60)
            self._metrics["uptime"].setText(f"{hours}h {mins}m {secs}s")
        except ImportError:
            self._metrics["cpu"].setText("psutil not installed")
        except Exception as exc:  # noqa: BLE001
            logger.debug("Health refresh error: %s", exc)

        # Articles in DB
        try:
            from config.settings import CANONICAL_DB_FILE
            import sqlite3
            if CANONICAL_DB_FILE.exists():
                with sqlite3.connect(CANONICAL_DB_FILE) as conn:
                    cur = conn.cursor()
                    cur.execute("SELECT COUNT(*) FROM canonical_articles")
                    count = cur.fetchone()[0]
                    self._metrics["articles_db"].setText(str(count))
            else:
                self._metrics["articles_db"].setText("0")
        except Exception as e:
            logger.debug(f"admin_panel: could not read article count from DB: {e}")


# ──────────────────────────────────────────────────────────────────────────
# Main Admin Panel Dialog
# ──────────────────────────────────────────────────────────────────────────

class AdminControlPanel(QDialog):
    """
    Full admin control panel presented as a tabbed dialog.

    Tabs:
    1. Services   — start / stop backend services
    2. API Keys   — view / update environment keys
    3. Config     — unified configuration editor
    4. Health     — live system metrics
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("🛠️ Admin Control Panel")
        self.resize(900, 640)
        self.setModal(False)

        self.setStyleSheet(f"""
            QDialog {{
                background-color: {COLORS.bg};
                color: {COLORS.fg};
            }}
            QTabWidget::pane {{
                border: 1px solid {COLORS.border};
                background-color: {COLORS.bg};
            }}
            QTabBar::tab {{
                background-color: {COLORS.bg_highlight};
                color: {COLORS.fg_dark};
                padding: 10px 18px;
                border-top-left-radius: 4px;
                border-top-right-radius: 4px;
                margin-right: 2px;
            }}
            QTabBar::tab:selected {{
                background-color: {COLORS.bg};
                color: {COLORS.cyan};
                font-weight: bold;
            }}
            QGroupBox {{
                color: {COLORS.fg};
                border: 1px solid {COLORS.border};
                border-radius: 4px;
                margin-top: 12px;
                padding-top: 12px;
            }}
            QGroupBox::title {{
                subcontrol-origin: margin;
                left: 10px;
            }}
        """)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)

        tabs = QTabWidget()
        tabs.addTab(ServicesTab(), "🖧 Services")
        tabs.addTab(APIKeysTab(), "🔑 API Keys")
        tabs.addTab(ConfigEditorTab(), "📝 Config")
        tabs.addTab(SystemHealthTab(), "💓 Health")
        root.addWidget(tabs)


def show_admin_panel(parent: QWidget | None = None) -> None:
    """Convenience launcher (non-modal)."""
    dlg = AdminControlPanel(parent)
    dlg.show()
