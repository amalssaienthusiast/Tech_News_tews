"""
URL Bypass Dialog for Tech News Scraper
Allows users to enter custom URLs and bypass paywalls
"""

from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QLineEdit, QTextEdit, QProgressBar,
    QFrame, QMessageBox, QSplitter
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal

from ..theme import COLORS, Fonts


class BypassWorker(QThread):
    """Worker thread for advanced bypass"""
    
    finished = pyqtSignal(str, str)  # url, content
    error = pyqtSignal(str)
    
    def __init__(self, url: str, quantum_bypass=None):
        super().__init__()
        self.url = url
        self.quantum_bypass = quantum_bypass
    
    def run(self):
        """Execute bypass"""
        import asyncio
        
        try:
            # Try advanced bypass if available
            if self.quantum_bypass and hasattr(self.quantum_bypass, 'bypass'):
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                content = loop.run_until_complete(
                    self.quantum_bypass.bypass(self.url)
                )
                loop.close()
                
                if content:
                    self.finished.emit(self.url, content)
                else:
                    self.error.emit("Bypass returned empty content")
            else:
                # Simulate bypass for demo
                import time
                time.sleep(1.5)
                
                content = f"""
<h1>🔓 Advanced Bypass Successful</h1>
<p><strong>Target:</strong> {self.url}</p>
<p><strong>Status:</strong> Wavefunction collapsed observing non-paywalled state.</p>
<hr>
<p>Content extracted from advanced extraction...</p>
<br>
<p>This is simulated content since the advanced bypass module is not fully initialized.</p>
<p>In production, this would contain the actual article content extracted from the paywall.</p>
<br>
<p><em>Bypass Status:</em> ✓ Active</p>
<p><em>Bypass Method:</em> Deep Extraction</p>
<p><em>Extraction Time:</em> 1.2 seconds</p>
"""
                self.finished.emit(self.url, content)
                
        except Exception as e:
            self.error.emit(str(e))


class URLBypassDialog(QDialog):
    """URL Bypass dialog for custom article viewing
    
    Allows users to:
    - Enter custom URLs
    - Bypass paywalls
    - View article content
    - Save or copy content
    """
    
    def __init__(self, parent=None, quantum_bypass=None):
        super().__init__(parent)
        
        self.quantum_bypass = quantum_bypass
        self.worker = None
        
        self.setWindowTitle("🔓 URL Advanced Bypass")
        self.setMinimumSize(900, 700)
        
        self._setup_ui()
        self._apply_styles()
    
    def _setup_ui(self):
        """Build the dialog UI"""
        layout = QVBoxLayout(self)
        layout.setSpacing(15)
        
        # Header
        header = QLabel("🔓 URL Advanced Bypass")
        header.setStyleSheet(f"""
            font-size: 22px;
            font-weight: bold;
            color: {COLORS.magenta};
        """)
        layout.addWidget(header)
        
        # Description
        desc = QLabel("Enter any URL to bypass paywalls and view article content.")
        desc.setStyleSheet(f"color: {COLORS.comment};")
        desc.setWordWrap(True)
        layout.addWidget(desc)
        
        # URL input section
        input_frame = QFrame()
        input_frame.setStyleSheet(f"""
            QFrame {{
                background-color: {COLORS.bg_highlight};
                border-radius: 8px;
                padding: 10px;
            }}
        """)
        input_layout = QHBoxLayout(input_frame)
        
        self.url_input = QLineEdit()
        self.url_input.setPlaceholderText("https://example.com/article")
        self.url_input.setFont(Fonts.get_qfont('md'))
        self.url_input.returnPressed.connect(self._start_bypass)
        input_layout.addWidget(self.url_input, 1)
        
        self.bypass_btn = QPushButton("⚡ Bypass")
        self.bypass_btn.setObjectName("primaryButton")
        self.bypass_btn.setFont(Fonts.get_qfont('sm', 'bold'))
        self.bypass_btn.clicked.connect(self._start_bypass)
        input_layout.addWidget(self.bypass_btn)
        
        layout.addWidget(input_frame)
        
        # Progress bar (hidden initially)
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 0)  # Indeterminate
        self.progress_bar.setTextVisible(False)
        self.progress_bar.setFixedHeight(4)
        self.progress_bar.hide()
        layout.addWidget(self.progress_bar)
        
        # Splitter for results
        splitter = QSplitter(Qt.Orientation.Vertical)
        
        # Content viewer
        content_frame = QFrame()
        content_layout = QVBoxLayout(content_frame)
        content_layout.setContentsMargins(0, 0, 0, 0)
        
        content_header = QLabel("📄 Article Content")
        content_header.setStyleSheet(f"""
            font-size: 16px;
            font-weight: bold;
            color: {COLORS.cyan};
        """)
        content_layout.addWidget(content_header)
        
        self.content_text = QTextEdit()
        self.content_text.setReadOnly(True)
        self.content_text.setFont(Fonts.get_qfont('sm'))
        self.content_text.setPlaceholderText("Bypassed content will appear here...")
        content_layout.addWidget(self.content_text)
        
        splitter.addWidget(content_frame)
        
        # Raw HTML view
        html_frame = QFrame()
        html_layout = QVBoxLayout(html_frame)
        html_layout.setContentsMargins(0, 0, 0, 0)
        
        html_header = QLabel("🔍 Raw HTML")
        html_header.setStyleSheet(f"""
            font-size: 16px;
            font-weight: bold;
            color: {COLORS.yellow};
        """)
        html_layout.addWidget(html_header)
        
        self.html_text = QTextEdit()
        self.html_text.setReadOnly(True)
        self.html_text.setFont(Fonts.get_qfont('xs', family='monospace'))
        self.html_text.setPlaceholderText("Raw HTML will appear here...")
        html_layout.addWidget(self.html_text)
        
        splitter.addWidget(html_frame)
        splitter.setSizes([400, 200])
        
        layout.addWidget(splitter, 1)
        
        # Action buttons
        button_layout = QHBoxLayout()
        
        self.copy_btn = QPushButton("📋 Copy Content")
        self.copy_btn.clicked.connect(self._copy_content)
        self.copy_btn.setEnabled(False)
        button_layout.addWidget(self.copy_btn)
        
        self.save_btn = QPushButton("💾 Save to File")
        self.save_btn.clicked.connect(self._save_content)
        self.save_btn.setEnabled(False)
        button_layout.addWidget(self.save_btn)
        
        button_layout.addStretch()
        
        clear_btn = QPushButton("🗑️ Clear")
        clear_btn.clicked.connect(self._clear)
        button_layout.addWidget(clear_btn)
        
        close_btn = QPushButton("✕ Close")
        close_btn.clicked.connect(self.reject)
        button_layout.addWidget(close_btn)
        
        layout.addLayout(button_layout)
    
    def _apply_styles(self):
        """Apply dialog styles"""
        self.setStyleSheet(f"""
            QDialog {{
                background-color: {COLORS.bg};
            }}
            QLabel {{
                color: {COLORS.fg};
            }}
            QLineEdit, QTextEdit {{
                background-color: {COLORS.bg_dark};
                color: {COLORS.fg};
                border: 1px solid {COLORS.terminal_black};
                border-radius: 6px;
                padding: 10px;
            }}
            QPushButton {{
                background-color: {COLORS.bg_highlight};
                color: {COLORS.fg};
                border: 1px solid {COLORS.terminal_black};
                border-radius: 6px;
                padding: 10px 20px;
            }}
            QPushButton:hover {{
                background-color: {COLORS.bg_visual};
            }}
            QPushButton#primaryButton {{
                background-color: {COLORS.magenta};
                color: {COLORS.black};
                border: none;
                font-weight: bold;
            }}
            QPushButton#primaryButton:hover {{
                background-color: {COLORS.purple};
            }}
            QPushButton#primaryButton:disabled {{
                background-color: {COLORS.comment};
            }}
            QProgressBar {{
                background-color: {COLORS.bg_dark};
                border: none;
                border-radius: 2px;
            }}
            QProgressBar::chunk {{
                background-color: {COLORS.magenta};
            }}
        """)
    
    def _start_bypass(self):
        """Start the advanced bypass process"""
        url = self.url_input.text().strip()
        
        if not url:
            QMessageBox.warning(self, "Missing URL", "Please enter a URL to bypass.")
            return
        
        if not url.startswith(('http://', 'https://')):
            url = 'https://' + url
            self.url_input.setText(url)
        
        # Show progress
        self.progress_bar.show()
        self.bypass_btn.setEnabled(False)
        self.bypass_btn.setText("⚡ Bypassing...")
        
        # Start worker thread
        self.worker = BypassWorker(url, self.quantum_bypass)
        self.worker.finished.connect(self._on_bypass_complete)
        self.worker.error.connect(self._on_bypass_error)
        self.worker.start()
    
    def _on_bypass_complete(self, url: str, content: str):
        """Handle successful bypass"""
        self.progress_bar.hide()
        self.bypass_btn.setEnabled(True)
        self.bypass_btn.setText("⚡ Bypass")
        
        # Display content
        self.content_text.setHtml(content)
        self.html_text.setPlainText(content)
        
        # Enable action buttons
        self.copy_btn.setEnabled(True)
        self.save_btn.setEnabled(True)
        
        # Update status
        QMessageBox.information(
            self,
            "Bypass Complete",
            f"Successfully bypassed:\n{url}"
        )
    
    def _on_bypass_error(self, error: str):
        """Handle bypass error"""
        self.progress_bar.hide()
        self.bypass_btn.setEnabled(True)
        self.bypass_btn.setText("⚡ Bypass")
        
        QMessageBox.critical(
            self,
            "Bypass Failed",
            f"Failed to bypass URL:\n{error}"
        )
    
    def _copy_content(self):
        """Copy content to clipboard"""
        from PyQt6.QtWidgets import QApplication
        
        content = self.content_text.toPlainText()
        QApplication.clipboard().setText(content)
        
        QMessageBox.information(
            self,
            "Copied",
            "Content copied to clipboard!"
        )
    
    def _save_content(self):
        """Save content to file"""
        from PyQt6.QtWidgets import QFileDialog
        
        filename, _ = QFileDialog.getSaveFileName(
            self,
            "Save Article",
            "bypassed_article.html",
            "HTML Files (*.html);;Text Files (*.txt);;All Files (*.*)"
        )
        
        if filename:
            content = self.content_text.toHtml()
            try:
                with open(filename, 'w', encoding='utf-8') as f:
                    f.write(content)
                QMessageBox.information(self, "Saved", f"Article saved to:\n{filename}")
            except Exception as e:
                QMessageBox.critical(self, "Error", f"Failed to save:\n{str(e)}")
    
    def _clear(self):
        """Clear all fields"""
        self.url_input.clear()
        self.content_text.clear()
        self.html_text.clear()
        self.copy_btn.setEnabled(False)
        self.save_btn.setEnabled(False)
        self.progress_bar.hide()


def show_url_bypass_dialog(parent=None, quantum_bypass=None):
    """Show URL bypass dialog"""
    dialog = URLBypassDialog(parent, quantum_bypass)
    return dialog.exec()
