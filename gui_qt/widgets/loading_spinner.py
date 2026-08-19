"""
Loading Spinner Widget
Animated circular loading indicator
"""

import math
from PyQt6.QtWidgets import QWidget, QVBoxLayout, QLabel
from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QPainter, QColor, QPen, QConicalGradient

from ..theme import COLORS


class LoadingSpinner(QWidget):
    """Animated spinning loading indicator"""

    def __init__(
        self, parent=None, size: int = 60, color: str = COLORS.cyan, thickness: int = 6
    ):
        super().__init__(parent)

        self._size = size
        self._color = color
        self._thickness = thickness
        self._angle = 0
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._rotate)

        self.setFixedSize(size, size)

    def _rotate(self):
        """Rotate the spinner"""
        self._angle = (self._angle + 6) % 360
        self.update()

    def paintEvent(self, event):
        """Paint the spinning arc"""
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        # Center the arc
        center_x = self.width() // 2
        center_y = self.height() // 2
        radius = min(center_x, center_y) - self._thickness

        # Create gradient for the arc
        gradient = QConicalGradient(center_x, center_y, self._angle)
        gradient.setColorAt(0, QColor(self._color))
        gradient.setColorAt(0.25, QColor(self._color))
        gradient.setColorAt(0.75, QColor(COLORS.bg))
        gradient.setColorAt(1, QColor(COLORS.bg))

        # Draw the arc
        pen = QPen(gradient, self._thickness)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(pen)

        rect = self.rect().adjusted(
            self._thickness, self._thickness, -self._thickness, -self._thickness
        )
        painter.drawArc(rect, self._angle * 16, 270 * 16)

    def start(self):
        """Start the spinner animation"""
        self._timer.start(20)  # ~50 FPS

    def stop(self):
        """Stop the spinner animation"""
        self._timer.stop()
        self._angle = 0
        self.update()

    def is_spinning(self) -> bool:
        """Check if spinner is active"""
        return self._timer.isActive()


class LoadingOverlay(QWidget):
    """Full loading overlay with spinner and text"""

    def __init__(self, parent=None, text: str = "Loading...", spinner_size: int = 80):
        super().__init__(parent)

        self._text = text

        self._setup_ui(spinner_size)
        self.hide()

    def _setup_ui(self, spinner_size: int):
        """Build the overlay UI"""
        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.setSpacing(20)

        # Spinner
        self.spinner = LoadingSpinner(self, size=spinner_size)
        layout.addWidget(self.spinner, 0, Qt.AlignmentFlag.AlignCenter)

        # Loading text
        self.text_label = QLabel(self._text, self)
        self.text_label.setStyleSheet(f"""
            QLabel {{
                color: {COLORS.fg};
                font-size: 16px;
                font-weight: bold;
            }}
        """)
        self.text_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.text_label, 0, Qt.AlignmentFlag.AlignCenter)

        # Overlay background
        self.setStyleSheet(f"""
            QWidget {{
                background-color: rgba(26, 27, 38, 0.9);
            }}
        """)

    def set_text(self, text: str):
        """Update loading text"""
        self._text = text
        self.text_label.setText(text)

    def show_loading(self, text: str = None):
        """Show the overlay and start spinner"""
        if text:
            self.set_text(text)
        self.spinner.start()
        self.show()
        self.raise_()

    def hide_loading(self):
        """Hide the overlay and stop spinner"""
        self.spinner.stop()
        self.hide()


class LoadingScreen(QWidget):
    """Full-screen loading state with progress info"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._setup_ui()

    def _setup_ui(self):
        """Build the loading screen UI"""
        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.setSpacing(24)

        # Icon
        icon_label = QLabel("📰", self)
        icon_label.setStyleSheet(f"""
            QLabel {{
                font-size: 48px;
            }}
        """)
        icon_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(icon_label)

        # Spinner
        self.spinner = LoadingSpinner(self, size=80, color=COLORS.cyan)
        layout.addWidget(self.spinner, 0, Qt.AlignmentFlag.AlignCenter)

        # Status text
        self.status_label = QLabel("Fetching tech news...", self)
        self.status_label.setStyleSheet(f"""
            QLabel {{
                color: {COLORS.fg};
                font-size: 18px;
                font-weight: bold;
            }}
        """)
        self.status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.status_label)

        # Substatus
        self.substatus_label = QLabel("Connecting to sources...", self)
        self.substatus_label.setStyleSheet(f"""
            QLabel {{
                color: {COLORS.fg_dark};
                font-size: 14px;
            }}
        """)
        self.substatus_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.substatus_label)

        # Background
        self.setStyleSheet(f"""
            QWidget {{
                background-color: {COLORS.bg};
            }}
        """)

    def set_status(self, status: str, substatus: str = None):
        """Update status text"""
        self.status_label.setText(status)
        if substatus:
            self.substatus_label.setText(substatus)
            self.substatus_label.show()
        else:
            self.substatus_label.hide()

    def start(self):
        """Start loading animation"""
        self.spinner.start()
        self.show()

    def stop(self):
        """Stop loading animation"""
        self.spinner.stop()
        self.hide()
