"""
Quick test to debug PyQt6 app window display
"""
import sys
import logging
sys.path.insert(0, '.')

logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

from PyQt6.QtWidgets import QApplication, QMainWindow, QLabel, QVBoxLayout, QWidget, QPushButton
from PyQt6.QtCore import Qt

from gui_qt.theme import apply_theme, COLORS

class TestWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Tech News Scraper - TEST")
        self.setMinimumSize(800, 600)
        
        # Central widget
        central = QWidget()
        self.setCentralWidget(central)
        
        layout = QVBoxLayout(central)
        
        # Simple label
        label = QLabel("🚀 If you see this, the window is working!")
        label.setStyleSheet(f"font-size: 24px; color: {COLORS.cyan};")
        label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(label)
        
        # Button
        btn = QPushButton("Click Me")
        btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {COLORS.cyan};
                color: {COLORS.black};
                padding: 10px 20px;
                font-size: 16px;
                border-radius: 8px;
            }}
        """)
        btn.clicked.connect(lambda: label.setText("✅ Button clicked!"))
        layout.addWidget(btn)
        
        logger.info("Test window created")

def main():
    app = QApplication(sys.argv)
    apply_theme(app)
    
    window = TestWindow()
    window.show()
    
    logger.info("Window shown - entering event loop")
    sys.exit(app.exec())

if __name__ == "__main__":
    main()
