"""
Toast Notification Widget for Tech News Scraper
Shows temporary notifications for search results, new articles, etc.
"""

from PyQt6.QtWidgets import (
    QFrame, QVBoxLayout, QHBoxLayout, QLabel, 
    QPushButton, QGraphicsDropShadowEffect
)
from PyQt6.QtCore import pyqtSignal, Qt, QTimer, QPropertyAnimation, QEasingCurve, QPoint, QObject
from PyQt6.QtGui import QColor

from ..theme import COLORS, Fonts


class ToastNotification(QFrame):
    """Toast notification widget that appears temporarily
    
    Signals:
        action_clicked(str): Emitted when action button is clicked
        dismissed(): Emitted when toast is dismissed
    """
    
    action_clicked = pyqtSignal(str)
    dismissed = pyqtSignal()
    
    # Toast types with colors
    TYPES = {
        "success": (COLORS.green, "✅"),
        "info": (COLORS.blue, "ℹ️"),
        "warning": (COLORS.yellow, "⚠️"),
        "error": (COLORS.red, "❌"),
    }
    
    def __init__(
        self, 
        parent=None,
        message: str = "",
        toast_type: str = "info",
        action_text: str = None,
        duration_ms: int = 5000
    ):
        super().__init__(parent)
        
        self._message = message
        self._toast_type = toast_type
        self._action_text = action_text
        self._duration_ms = duration_ms
        self._opacity = 1.0
        
        self._setup_ui()
        self._apply_styles()
        self._setup_animation()
    
    def _setup_ui(self):
        """Build toast UI"""
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        
        layout = QHBoxLayout(self)
        layout.setContentsMargins(16, 12, 16, 12)
        layout.setSpacing(12)
        
        # Icon
        color, emoji = self.TYPES.get(self._toast_type, self.TYPES["info"])
        self.icon_label = QLabel(emoji, self)
        self.icon_label.setStyleSheet(f"font-size: 18px;")
        layout.addWidget(self.icon_label)
        
        # Message
        self.message_label = QLabel(self._message, self)
        self.message_label.setFont(Fonts.get_qfont('sm'))
        self.message_label.setStyleSheet(f"color: {COLORS.fg};")
        self.message_label.setWordWrap(True)
        layout.addWidget(self.message_label, 1)
        
        # Action button (optional)
        if self._action_text:
            self.action_btn = QPushButton(self._action_text, self)
            self.action_btn.setFont(Fonts.get_qfont('xs', 'bold'))
            self.action_btn.setCursor(Qt.CursorShape.PointingHandCursor)
            self.action_btn.setStyleSheet(f"""
                QPushButton {{
                    background-color: {COLORS.bg_visual};
                    color: {COLORS.cyan};
                    border: 1px solid {COLORS.terminal_black};
                    border-radius: 4px;
                    padding: 6px 12px;
                }}
                QPushButton:hover {{
                    background-color: {COLORS.cyan};
                    color: {COLORS.black};
                }}
            """)
            self.action_btn.clicked.connect(self._on_action_clicked)
            layout.addWidget(self.action_btn)
        
        # Close button
        self.close_btn = QPushButton("✕", self)
        self.close_btn.setFixedSize(24, 24)
        self.close_btn.setFont(Fonts.get_qfont('xs', 'bold'))
        self.close_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.close_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: transparent;
                color: {COLORS.comment};
                border: none;
                border-radius: 12px;
            }}
            QPushButton:hover {{
                background-color: {COLORS.bg_visual};
                color: {COLORS.fg};
            }}
        """)
        self.close_btn.clicked.connect(self.dismiss)
        layout.addWidget(self.close_btn)
        
        # Auto-dismiss timer
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._start_fade_out)
        self._timer.start(self._duration_ms)
    
    def _apply_styles(self):
        """Apply toast styles with shadow"""
        color, _ = self.TYPES.get(self._toast_type, self.TYPES["info"])
        
        self.setStyleSheet(f"""
            ToastNotification {{
                background-color: {COLORS.bg_highlight};
                border: 1px solid {color};
                border-radius: 8px;
            }}
        """)
        
        # Add drop shadow
        shadow = QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(20)
        shadow.setColor(QColor(0, 0, 0, 100))
        shadow.setOffset(0, 4)
        self.setGraphicsEffect(shadow)
    
    def _setup_animation(self):
        """Setup fade animation"""
        self._fade_animation = QPropertyAnimation(self, b"windowOpacity")
        self._fade_animation.setDuration(300)
        self._fade_animation.setEasingCurve(QEasingCurve.Type.InOutQuad)
    
    def show_at(self, position: QPoint):
        """Show toast at specific position"""
        self.move(position)
        self.show()
        self.raise_()
    
    def _on_action_clicked(self):
        """Handle action button click"""
        self.action_clicked.emit(self._action_text)
        self.dismiss()
    
    def _start_fade_out(self):
        """Start fade out animation"""
        self._fade_animation.setStartValue(1.0)
        self._fade_animation.setEndValue(0.0)
        self._fade_animation.finished.connect(self.close)
        self._fade_animation.start()
    
    def dismiss(self):
        """Dismiss the toast"""
        self._timer.stop()
        self.dismissed.emit()
        self._start_fade_out()


class ToastManager(QObject):
    """Manages toast notifications with positioning
    
    Usage:
        manager = ToastManager(parent_window)
        manager.show_toast("Message", "success", action_text="View")
    """
    
    def __init__(self, parent_window=None):
        super().__init__(parent_window)
        self._parent = parent_window
        self._toasts: list = []
        self._spacing = 10
    
    def show_toast(
        self,
        message: str,
        toast_type: str = "info",
        action_text: str = None,
        duration_ms: int = 5000
    ) -> ToastNotification:
        """Show a toast notification
        
        Args:
            message: Toast message text
            toast_type: success, info, warning, or error
            action_text: Optional action button text
            duration_ms: How long to show toast (ms)
        
        Returns:
            ToastNotification instance
        """
        toast = ToastNotification(
            self._parent,
            message,
            toast_type,
            action_text,
            duration_ms
        )
        
        # Position toast
        self._position_toast(toast)
        
        # Connect dismissal
        toast.dismissed.connect(lambda: self._remove_toast(toast))
        
        self._toasts.append(toast)
        toast.show()
        
        return toast
    
    def show_search_results(self, count: int, query: str = ""):
        """Show toast for search results"""
        if count > 0:
            message = f"Found {count} results"
            if query:
                message += f' for "{query}"'
            return self.show_toast(
                message,
                "success",
                action_text="View All",
                duration_ms=6000
            )
        else:
            return self.show_toast(
                f'No results found for "{query}"' if query else "No results found",
                "warning",
                duration_ms=4000
            )
    
    def show_new_articles(self, count: int):
        """Show toast for new articles during live feed"""
        if count > 0:
            return self.show_toast(
                f"📰 {count} new articles available",
                "info",
                action_text="Refresh",
                duration_ms=8000
            )
    
    def _position_toast(self, toast: ToastNotification):
        """Position toast in bottom-right corner"""
        if not self._parent:
            return
        
        # Calculate position
        parent_rect = self._parent.geometry()
        toast_width = 350
        toast_height = 60
        
        x = parent_rect.right() - toast_width - 20
        y = parent_rect.bottom() - toast_height - 20
        
        # Stack multiple toasts
        index = len(self._toasts)
        y -= index * (toast_height + self._spacing)
        
        toast.setFixedWidth(toast_width)
        toast.move(x, max(50, y))  # Keep at least 50px from top
    
    def _remove_toast(self, toast: ToastNotification):
        """Remove toast from list and reposition others"""
        if toast in self._toasts:
            self._toasts.remove(toast)
        
        # Reposition remaining toasts
        for i, t in enumerate(self._toasts):
            self._position_toast(t)
    
    def dismiss_all(self):
        """Dismiss all active toasts"""
        for toast in self._toasts[:]:
            toast.dismiss()
