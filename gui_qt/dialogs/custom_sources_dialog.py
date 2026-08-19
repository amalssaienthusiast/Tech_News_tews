"""
Custom Sources Dialog for gui_qt.

Lets the user add / remove custom news-source URLs that are persisted
to ``data/custom_sources.json``.
"""

import json
import logging
from pathlib import Path
from typing import Any, Dict, List

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from gui_qt.theme import COLORS

logger = logging.getLogger(__name__)

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_SOURCES_FILE = _PROJECT_ROOT / "data" / "custom_sources.json"


class CustomSourcesDialog(QDialog):
    """Manage custom news source URLs with Tokyo Night styling."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("⚙️ Manage Custom Sources")
        self.resize(720, 520)
        self.setModal(True)

        self._sources: List[Dict[str, Any]] = []
        self._load_sources()
        self._build_ui()

    # -- persistence ---------------------------------------------------------

    def _load_sources(self) -> None:
        if _SOURCES_FILE.exists():
            try:
                with open(_SOURCES_FILE, "r", encoding="utf-8") as fh:
                    data = json.load(fh)
                    if isinstance(data, dict) and "sources" in data:
                        self._sources = data["sources"]
                    elif isinstance(data, list):
                        self._sources = data
                    else:
                        self._sources = []
            except Exception:  # noqa: BLE001
                self._sources = []

    def _save_sources(self) -> None:
        _SOURCES_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(_SOURCES_FILE, "w", encoding="utf-8") as fh:
            json.dump({"sources": self._sources}, fh, indent=2)

    # -- UI ------------------------------------------------------------------

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setSpacing(12)
        root.setContentsMargins(20, 20, 20, 20)

        self.setStyleSheet(f"""
            QDialog {{
                background-color: {COLORS.bg};
                color: {COLORS.fg};
            }}
            QLabel {{
                color: {COLORS.fg};
            }}
            QLineEdit {{
                background-color: {COLORS.bg_dark};
                color: {COLORS.fg};
                border: 1px solid {COLORS.border};
                border-radius: 4px;
                padding: 8px;
            }}
            QListWidget {{
                background-color: {COLORS.bg_dark};
                color: {COLORS.fg};
                border: 1px solid {COLORS.border};
                border-radius: 4px;
            }}
            QListWidget::item:selected {{
                background-color: {COLORS.selection};
            }}
            QPushButton {{
                padding: 8px 16px;
                border-radius: 4px;
                font-weight: bold;
            }}
        """)

        # -- header --
        header = QLabel("⚙️  MANAGE CUSTOM SOURCES")
        header.setStyleSheet(f"font-size: 16px; font-weight: bold; color: {COLORS.cyan};")
        root.addWidget(header)

        # -- add URL row --
        add_row = QHBoxLayout()
        self._url_input = QLineEdit()
        self._url_input.setPlaceholderText("https://example.com/news")
        self._url_input.returnPressed.connect(self._add_source)
        add_row.addWidget(self._url_input, stretch=1)

        add_btn = QPushButton("➕ Add")
        add_btn.setStyleSheet(
            f"background-color: {COLORS.green}; color: {COLORS.bg_dark};"
        )
        add_btn.clicked.connect(self._add_source)
        add_row.addWidget(add_btn)
        root.addLayout(add_row)

        # -- source count label --
        self._count_label = QLabel(f"📋 Current Custom Sources ({len(self._sources)})")
        self._count_label.setStyleSheet(f"color: {COLORS.cyan}; font-weight: bold;")
        root.addWidget(self._count_label)

        # -- list --
        self._list = QListWidget()
        for src in self._sources:
            url = src.get("url", src) if isinstance(src, dict) else src
            self._list.addItem(url)
        root.addWidget(self._list, stretch=1)

        # -- bottom buttons --
        btn_row = QHBoxLayout()
        btn_row.addStretch()

        del_btn = QPushButton("🗑️ Delete Selected")
        del_btn.setStyleSheet(
            f"background-color: {COLORS.red}; color: {COLORS.fg};"
        )
        del_btn.clicked.connect(self._delete_source)
        btn_row.addWidget(del_btn)

        close_btn = QPushButton("Close")
        close_btn.setStyleSheet(
            f"background-color: {COLORS.bg_highlight}; color: {COLORS.fg};"
        )
        close_btn.clicked.connect(self.accept)
        btn_row.addWidget(close_btn)
        root.addLayout(btn_row)

    # -- actions -------------------------------------------------------------

    def _add_source(self) -> None:
        url = self._url_input.text().strip()
        if not url or not url.startswith(("http://", "https://")):
            QMessageBox.warning(
                self, "Invalid URL",
                "Please enter a valid URL starting with http:// or https://",
            )
            return
        entry = {"url": url, "name": url.split("/")[2], "type": "custom"}
        self._sources.append(entry)
        self._save_sources()
        self._list.addItem(url)
        self._url_input.clear()
        self._count_label.setText(f"📋 Current Custom Sources ({len(self._sources)})")

    def _delete_source(self) -> None:
        item = self._list.currentItem()
        if item is None:
            QMessageBox.warning(self, "No Selection", "Select a source to delete.")
            return
        url = item.text()
        self._sources = [
            s for s in self._sources
            if (s.get("url") if isinstance(s, dict) else s) != url
        ]
        self._save_sources()
        self._list.takeItem(self._list.row(item))
        self._count_label.setText(f"📋 Current Custom Sources ({len(self._sources)})")


def show_custom_sources_dialog(parent: QWidget | None = None) -> None:
    """Convenience launcher."""
    dlg = CustomSourcesDialog(parent)
    dlg.exec()
