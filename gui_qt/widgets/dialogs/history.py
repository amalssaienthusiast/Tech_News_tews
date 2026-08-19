"""
History Viewer Dialog - View and restore past article batches.

Features:
- Batch-based history with timestamps
- Quick preview of batch content
- Restore batch to main feed
"""

from datetime import datetime
from typing import Any, Callable, Dict, List, Optional

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QDialog, QFrame, QHBoxLayout, QLabel, QListWidget, QListWidgetItem,
    QPushButton, QSplitter, QTextEdit, QVBoxLayout, QWidget
)

from gui_qt.theme import COLORS


class HistoryViewer(QDialog):
    """History viewer dialog for past article batches."""
    
    batch_restored = pyqtSignal(list)  # List of articles
    
    def __init__(
        self,
        history: List[Dict] = None,
        parent: Optional[QWidget] = None
    ) -> None:
        super().__init__(parent)
        
        self.history = history or []
        self.setWindowTitle("📜 Article History")
        self.setMinimumSize(800, 600)
        
        self._setup_ui()
        self._populate_history()
    
    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(16)
        
        # Header
        header = QHBoxLayout()
        title = QLabel("📜 Article History")
        title.setStyleSheet(f"font-size: 20px; font-weight: bold; color: {COLORS.fg};")
        header.addWidget(title)
        
        header.addStretch()
        
        self.count_label = QLabel(f"{len(self.history)} batches")
        self.count_label.setStyleSheet(f"color: {COLORS.comment};")
        header.addWidget(self.count_label)
        
        layout.addLayout(header)
        
        # Splitter: batch list | preview
        splitter = QSplitter(Qt.Orientation.Horizontal)
        
        # Batch list
        self.batch_list = QListWidget()
        self.batch_list.setStyleSheet(f"""
            QListWidget {{
                background-color: {COLORS.bg_input};
                border: 1px solid {COLORS.border};
                border-radius: 8px;
            }}
            QListWidget::item {{
                padding: 12px;
                border-bottom: 1px solid {COLORS.border};
            }}
            QListWidget::item:selected {{
                background-color: {COLORS.bg_visual};
            }}
        """)
        self.batch_list.currentRowChanged.connect(self._on_batch_selected)
        splitter.addWidget(self.batch_list)
        
        # Preview panel
        preview_frame = QFrame()
        preview_frame.setStyleSheet(f"""
            background-color: {COLORS.bg_highlight};
            border-radius: 8px;
        """)
        preview_layout = QVBoxLayout(preview_frame)
        
        preview_header = QLabel("📋 Preview")
        preview_header.setStyleSheet(f"color: {COLORS.cyan}; font-weight: bold;")
        preview_layout.addWidget(preview_header)
        
        self.preview_text = QTextEdit()
        self.preview_text.setReadOnly(True)
        self.preview_text.setStyleSheet(f"""
            background-color: {COLORS.bg_input};
            border: none;
            border-radius: 4px;
            color: {COLORS.fg};
            font-family: monospace;
        """)
        preview_layout.addWidget(self.preview_text)
        
        splitter.addWidget(preview_frame)
        splitter.setSizes([300, 500])
        
        layout.addWidget(splitter)
        
        # Buttons
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()
        
        restore_btn = QPushButton("📥 Restore Batch")
        restore_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {COLORS.green};
                color: {COLORS.black};
                border: none;
                border-radius: 6px;
                padding: 10px 20px;
                font-weight: bold;
            }}
            QPushButton:hover {{
                background-color: {COLORS.cyan};
            }}
        """)
        restore_btn.clicked.connect(self._restore_batch)
        btn_layout.addWidget(restore_btn)
        
        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.reject)
        btn_layout.addWidget(close_btn)
        
        layout.addLayout(btn_layout)
    
    def _populate_history(self) -> None:
        """Populate the batch list."""
        for i, batch in enumerate(self.history):
            timestamp = batch.get("timestamp", "Unknown")
            count = len(batch.get("articles", []))
            
            item = QListWidgetItem(f"Batch {i+1} • {count} articles")
            item.setData(Qt.ItemDataRole.UserRole, batch)
            self.batch_list.addItem(item)
    
    def _on_batch_selected(self, row: int) -> None:
        """Show preview of selected batch."""
        if row < 0:
            return
        
        item = self.batch_list.item(row)
        batch = item.data(Qt.ItemDataRole.UserRole)
        articles = batch.get("articles", [])
        
        preview_lines = []
        for a in articles[:10]:  # Show first 10
            title = a.get("title", "Untitled")[:60]
            source = a.get("source", "Unknown")
            preview_lines.append(f"• [{source}] {title}")
        
        if len(articles) > 10:
            preview_lines.append(f"\n... and {len(articles) - 10} more")
        
        self.preview_text.setPlainText("\n".join(preview_lines))
    
    def _restore_batch(self) -> None:
        """Restore selected batch to main feed."""
        row = self.batch_list.currentRow()
        if row >= 0:
            item = self.batch_list.item(row)
            batch = item.data(Qt.ItemDataRole.UserRole)
            articles = batch.get("articles", [])
            self.batch_restored.emit(articles)
            self.accept()


class ExportDialog(QDialog):
    """Export articles dialog."""
    
    def __init__(
        self,
        articles: List[Dict],
        parent: Optional[QWidget] = None
    ) -> None:
        super().__init__(parent)
        
        self.articles = articles
        self.setWindowTitle("📤 Export Articles")
        self.setMinimumSize(500, 400)
        
        self._setup_ui()
    
    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(16)
        
        # Header
        header = QLabel("📤 Export Articles")
        header.setStyleSheet(f"font-size: 20px; font-weight: bold; color: {COLORS.fg};")
        layout.addWidget(header)
        
        # Info
        info = QLabel(f"Ready to export {len(self.articles)} articles")
        info.setStyleSheet(f"color: {COLORS.comment};")
        layout.addWidget(info)
        
        # Format buttons
        format_frame = QFrame()
        format_frame.setStyleSheet(f"""
            background-color: {COLORS.bg_highlight};
            border-radius: 8px;
            padding: 16px;
        """)
        format_layout = QVBoxLayout(format_frame)
        
        json_btn = QPushButton("💾 Export as JSON")
        json_btn.setMinimumHeight(44)
        json_btn.clicked.connect(lambda: self._export("json"))
        format_layout.addWidget(json_btn)
        
        markdown_btn = QPushButton("📝 Export as Markdown")
        markdown_btn.setMinimumHeight(44)
        markdown_btn.clicked.connect(lambda: self._export("markdown"))
        format_layout.addWidget(markdown_btn)
        
        csv_btn = QPushButton("📊 Export as CSV")
        csv_btn.setMinimumHeight(44)
        csv_btn.clicked.connect(lambda: self._export("csv"))
        format_layout.addWidget(csv_btn)
        
        layout.addWidget(format_frame)
        
        layout.addStretch()
        
        # Close button
        close_btn = QPushButton("Cancel")
        close_btn.clicked.connect(self.reject)
        layout.addWidget(close_btn, alignment=Qt.AlignmentFlag.AlignCenter)
    
    def _export(self, format: str) -> None:
        """Export articles in specified format."""
        import json
        from pathlib import Path
        from datetime import datetime
        
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        
        if format == "json":
            filename = f"articles_{timestamp}.json"
            content = json.dumps(self.articles, indent=2, default=str)
        elif format == "markdown":
            filename = f"articles_{timestamp}.md"
            lines = ["# Exported Articles\n"]
            for a in self.articles:
                lines.append(f"## {a.get('title', 'Untitled')}")
                lines.append(f"- Source: {a.get('source', 'Unknown')}")
                lines.append(f"- URL: {a.get('url', '')}")
                if a.get('ai_summary'):
                    lines.append(f"\n{a['ai_summary']}\n")
                lines.append("---\n")
            content = "\n".join(lines)
        elif format == "csv":
            filename = f"articles_{timestamp}.csv"
            import csv
            import io
            output = io.StringIO()
            writer = csv.DictWriter(output, fieldnames=["title", "source", "url", "published"])
            writer.writeheader()
            for a in self.articles:
                writer.writerow({
                    "title": a.get("title", ""),
                    "source": a.get("source", ""),
                    "url": a.get("url", ""),
                    "published": a.get("published", ""),
                })
            content = output.getvalue()
        else:
            return
        
        # Save to file
        export_dir = Path.home() / "Downloads"
        filepath = export_dir / filename
        filepath.write_text(content)
        
        from PyQt6.QtWidgets import QMessageBox
        QMessageBox.information(self, "Export Complete", f"Saved to:\n{filepath}")
        self.accept()
