"""
Custom Sources Manager Widget.
Provides a UI to add, view, and remove custom URLs for the 20-minute scraping cycle.
"""

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, 
    QLineEdit, QPushButton, QListWidget, QFileDialog, QMessageBox
)
from PyQt6.QtCore import pyqtSignal, Qt
from src.sources.custom_source_loader import CustomSourceManager
from gui_qt.theme import COLORS

class CustomSourcesManager(QWidget):
    """Widget to manage permanent custom scraping sources."""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Custom Sources Manager")
        self.setMinimumSize(500, 400)
        self.setStyleSheet(f"background-color: {COLORS.bg}; color: {COLORS.fg};")
        self._init_ui()
        self._load_data()

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(15)

        # Header
        title = QLabel("📡 Custom Sources Manager")
        title.setStyleSheet(f"color: {COLORS.purple}; font-size: 18px; font-weight: bold;")
        layout.addWidget(title)

        desc = QLabel("These URLs are scraped during the 20-minute Deep Scrape cycle.")
        desc.setStyleSheet(f"color: {COLORS.comment}; font-size: 12px;")
        desc.setWordWrap(True)
        layout.addWidget(desc)

        # Input Area
        input_layout = QHBoxLayout()
        self.url_input = QLineEdit()
        self.url_input.setPlaceholderText("Enter URL to scrape (e.g. https://example.com/blog)")
        self.url_input.setStyleSheet(f"""
            QLineEdit {{
                background-color: {COLORS.bg_input};
                border: 1px solid {COLORS.comment};
                border-radius: 4px;
                padding: 8px;
                color: {COLORS.fg};
            }}
        """)
        input_layout.addWidget(self.url_input)

        add_btn = QPushButton("Add Source")
        add_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {COLORS.green};
                color: {COLORS.bg};
                border: none;
                border-radius: 4px;
                padding: 8px 15px;
                font-weight: bold;
            }}
            QPushButton:hover {{ background-color: {COLORS.cyan}; }}
        """)
        add_btn.clicked.connect(self._on_add_clicked)
        input_layout.addWidget(add_btn)

        import_btn = QPushButton("Import TXT")
        import_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {COLORS.selection};
                color: {COLORS.fg};
                border: none;
                border-radius: 4px;
                padding: 8px 15px;
            }}
            QPushButton:hover {{ background-color: {COLORS.bg_input}; }}
        """)
        import_btn.clicked.connect(self._on_import_clicked)
        input_layout.addWidget(import_btn)

        layout.addLayout(input_layout)

        # List Area
        self.source_list = QListWidget()
        self.source_list.setStyleSheet(f"""
            QListWidget {{
                background-color: {COLORS.bg_input};
                border: 1px solid {COLORS.comment};
                border-radius: 4px;
                padding: 5px;
            }}
            QListWidget::item {{ padding: 8px; border-bottom: 1px solid {COLORS.bg}; }}
            QListWidget::item:selected {{ background-color: {COLORS.selection}; }}
        """)
        layout.addWidget(self.source_list)

        # Bottom Actions
        remove_btn = QPushButton("Remove Selected")
        remove_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {COLORS.red};
                color: {COLORS.bg};
                border: none;
                border-radius: 4px;
                padding: 8px 15px;
                font-weight: bold;
            }}
            QPushButton:hover {{ background-color: {COLORS.orange}; }}
        """)
        remove_btn.clicked.connect(self._on_remove_clicked)
        layout.addWidget(remove_btn)

    def _load_data(self):
        self.source_list.clear()
        sources = CustomSourceManager.load_sources()
        for src in sources:
            self.source_list.addItem(src)

    def _on_add_clicked(self):
        url = self.url_input.text().strip()
        if not url: return
        
        if CustomSourceManager.add_source(url):
            self.url_input.clear()
            self._load_data()
            QMessageBox.information(self, "Success", f"Added {url}")
        else:
            QMessageBox.warning(self, "Warning", "URL already exists or is invalid.")

    def _on_remove_clicked(self):
        selected = self.source_list.selectedItems()
        if not selected: return
        
        url = selected[0].text()
        if CustomSourceManager.remove_source(url):
            self._load_data()

    def _on_import_clicked(self):
        file_path, _ = QFileDialog.getOpenFileName(
            self, "Select text file", "", "Text Files (*.txt);;All Files (*)"
        )
        if not file_path:
            return
            
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                urls = [line.strip() for line in f if line.strip()]
                
            added = 0
            for url in urls:
                if CustomSourceManager.add_source(url):
                    added += 1
            
            self._load_data()
            QMessageBox.information(self, "Import Complete", f"Successfully added {added} sources.")
        except Exception as e:
            QMessageBox.critical(self, "Import Error", f"Failed to read file: {e}")
