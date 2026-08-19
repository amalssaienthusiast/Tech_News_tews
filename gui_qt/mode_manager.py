"""
Mode Manager - PyQt6 Version

Handles switching between User and Developer modes with passcode protection.
Features:
- Dual-mode operation (user/developer)
- Password-protected developer access
- State preservation during mode switches
- Persistent mode preference
- Keyboard shortcuts (F11/F12)
"""

import json
import logging
from pathlib import Path
from typing import Dict, Any, Optional, Callable
from dataclasses import dataclass, asdict
from PyQt6.QtCore import QObject, pyqtSignal, Qt
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, 
    QPushButton, QMessageBox, QWidget
)
from PyQt6.QtGui import QKeySequence, QShortcut

logger = logging.getLogger(__name__)


@dataclass
class ModeState:
    """State preserved during mode switches."""
    scroll_position: float = 0.0
    selected_tab: int = 0
    search_query: str = ""
    filter_settings: Dict[str, Any] = None
    expanded_panels: list = None
    
    def __post_init__(self):
        if self.filter_settings is None:
            self.filter_settings = {}
        if self.expanded_panels is None:
            self.expanded_panels = []


class PasscodeDialog(QDialog):
    """Dialog for entering developer mode passcode."""
    
    def __init__(self, parent=None, is_setup=False):
        super().__init__(parent)
        self.is_setup = is_setup
        self.passcode = None
        self._setup_ui()
    
    def _setup_ui(self):
        self.setWindowTitle("🔐 Developer Mode" if not self.is_setup else "🔐 Set Passcode")
        self.setFixedSize(400, 200)
        self.setStyleSheet("""
            QDialog {
                background-color: #1a1b26;
            }
            QLabel {
                color: #a9b1d6;
                font-size: 13px;
            }
            QLineEdit {
                background-color: #24283b;
                color: #c0caf5;
                border: 2px solid #414868;
                border-radius: 6px;
                padding: 10px;
                font-size: 14px;
            }
            QLineEdit:focus {
                border-color: #7aa2f7;
            }
            QPushButton {
                background-color: #7aa2f7;
                color: #1a1b26;
                border: none;
                border-radius: 6px;
                padding: 10px 20px;
                font-weight: bold;
                font-size: 13px;
            }
            QPushButton:hover {
                background-color: #bb9af7;
            }
            QPushButton:pressed {
                background-color: #565f89;
            }
        """)
        
        layout = QVBoxLayout(self)
        layout.setSpacing(15)
        layout.setContentsMargins(30, 30, 30, 30)
        
        # Title
        title = QLabel("🔐 Enter Developer Passcode" if not self.is_setup else "🔐 Create Developer Passcode")
        title.setStyleSheet("color: #7aa2f7; font-size: 16px; font-weight: bold;")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(title)
        
        # Description
        desc = QLabel(
            "Enter passcode to access developer mode:" if not self.is_setup
            else "Create a passcode to protect developer mode:"
        )
        desc.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(desc)
        
        # Passcode input
        self.passcode_input = QLineEdit()
        self.passcode_input.setEchoMode(QLineEdit.EchoMode.Password)
        self.passcode_input.setPlaceholderText("••••••" if not self.is_setup else "Enter new passcode")
        self.passcode_input.returnPressed.connect(self._on_submit)
        layout.addWidget(self.passcode_input)
        
        if self.is_setup:
            # Confirm passcode
            self.confirm_input = QLineEdit()
            self.confirm_input.setEchoMode(QLineEdit.EchoMode.Password)
            self.confirm_input.setPlaceholderText("Confirm passcode")
            self.confirm_input.returnPressed.connect(self._on_submit)
            layout.addWidget(self.confirm_input)
        
        # Buttons
        btn_layout = QHBoxLayout()
        
        cancel_btn = QPushButton("Cancel")
        cancel_btn.setStyleSheet("""
            QPushButton {
                background-color: #414868;
                color: #c0caf5;
            }
            QPushButton:hover {
                background-color: #565f89;
            }
        """)
        cancel_btn.clicked.connect(self.reject)
        btn_layout.addWidget(cancel_btn)
        
        submit_btn = QPushButton("Unlock" if not self.is_setup else "Set Passcode")
        submit_btn.clicked.connect(self._on_submit)
        btn_layout.addWidget(submit_btn)
        
        layout.addLayout(btn_layout)
        
        # Set focus
        self.passcode_input.setFocus()
    
    def _on_submit(self):
        code = self.passcode_input.text().strip()
        
        if not code:
            QMessageBox.warning(self, "Error", "Please enter a passcode")
            return
        
        if self.is_setup:
            confirm = self.confirm_input.text().strip()
            if code != confirm:
                QMessageBox.warning(self, "Error", "Passcodes do not match")
                return
            if len(code) < 4:
                QMessageBox.warning(self, "Error", "Passcode must be at least 4 characters")
                return
        
        self.passcode = code
        self.accept()
    
    def get_passcode(self) -> str:
        return self.passcode


class ModeManager(QObject):
    """
    Manages switching between User and Developer modes (PyQt6 version).
    
    Signals:
        mode_changed(str, str): Emitted when mode changes (old_mode, new_mode)
        developer_access_denied(): Emitted when passcode is incorrect
    """
    
    mode_changed = pyqtSignal(str, str)
    developer_access_denied = pyqtSignal()
    
    USER_MODE_CONFIG = {
        'name': 'user',
        'display_name': 'User Mode',
        'icon': '👤',
        'panels': ['news_feed', 'search', 'settings'],
        'description': 'Simplified news browsing experience',
        'shortcut': 'F11'
    }
    
    DEVELOPER_MODE_CONFIG = {
        'name': 'developer',
        'display_name': 'Developer Mode',
        'icon': '🛠️',
        'panels': [
            'system_monitor',
            'ai_laboratory',
            'bypass_control',
            'resilience_dashboard',
            'security_tools',
            'debug_console',
            'performance_analytics'
        ],
        'description': 'Full system control and monitoring',
        'shortcut': 'F12'
    }
    
    # Default passcode - should be changed on first use
    DEFAULT_PASSCODE = "dev123"
    
    def __init__(self, parent_widget: Optional[QWidget] = None, config_dir: Optional[Path] = None):
        """
        Initialize mode manager.
        
        Args:
            parent_widget: Parent widget for dialogs
            config_dir: Directory for persistent config
        """
        super().__init__()
        
        self.parent_widget = parent_widget
        self.config_dir = config_dir or Path.home() / '.technews'
        self.config_dir.mkdir(parents=True, exist_ok=True)
        
        self.config_file = self.config_dir / 'mode_config.json'
        self.passcode_file = self.config_dir / '.dev_passcode'
        
        # Current state
        self.current_mode = 'user'
        self.mode_states: Dict[str, ModeState] = {
            'user': ModeState(),
            'developer': ModeState()
        }
        
        # Developer mode settings
        self._dev_passcode = self._load_passcode()
        self._dev_mode_unlocked = False
        self._dev_mode_start_time = None
        
        # Callbacks
        self._on_switch_callbacks: list = []
        
        # Load persistent config
        self._load_config()
        
        logger.info(f"ModeManager (Qt) initialized with mode: {self.current_mode}")
    
    def _load_passcode(self) -> str:
        """Load or create developer passcode."""
        try:
            if self.passcode_file.exists():
                return self.passcode_file.read_text().strip()
        except Exception as e:
            logger.warning(f"Could not load passcode: {e}")
        
        # Create default passcode
        self._save_passcode(self.DEFAULT_PASSCODE)
        return self.DEFAULT_PASSCODE
    
    def _save_passcode(self, passcode: str) -> None:
        """Save developer passcode."""
        try:
            self.passcode_file.write_text(passcode)
            self.passcode_file.chmod(0o600)  # Restrict permissions
        except Exception as e:
            logger.error(f"Could not save passcode: {e}")
    
    def _load_config(self) -> None:
        """Load persistent configuration."""
        try:
            if self.config_file.exists():
                with open(self.config_file, 'r') as f:
                    data = json.load(f)
                    self.current_mode = data.get('last_mode', 'user')
                    # Load saved states
                    if 'states' in data:
                        for mode, state_data in data['states'].items():
                            self.mode_states[mode] = ModeState(**state_data)
                    logger.debug(f"Loaded mode preference: {self.current_mode}")
        except Exception as e:
            logger.warning(f"Could not load mode config: {e}")
            self.current_mode = 'user'
    
    def _save_config(self) -> None:
        """Save persistent configuration."""
        try:
            with open(self.config_file, 'w') as f:
                json.dump({
                    'last_mode': self.current_mode,
                    'states': {k: asdict(v) for k, v in self.mode_states.items()}
                }, f, indent=2)
        except Exception as e:
            logger.warning(f"Could not save mode config: {e}")
    
    def setup_shortcuts(self, widget: QWidget) -> None:
        """
        Setup keyboard shortcuts for mode switching.
        
        Args:
            widget: Widget to attach shortcuts to
        """
        # F11 - User Mode
        user_shortcut = QShortcut(QKeySequence("F11"), widget)
        user_shortcut.activated.connect(lambda: self.request_mode_switch('user'))
        
        # F12 - Developer Mode (requires passcode)
        dev_shortcut = QShortcut(QKeySequence("F12"), widget)
        dev_shortcut.activated.connect(lambda: self.request_mode_switch('developer'))
        
        logger.info("Mode shortcuts registered: F11 (User), F12 (Developer)")
    
    def request_mode_switch(self, target_mode: str) -> bool:
        """
        Request a mode switch with passcode verification for developer mode.
        
        Args:
            target_mode: Mode to switch to
            
        Returns:
            True if switch was successful
        """
        if target_mode == self.current_mode:
            return True
        
        if target_mode == 'developer':
            # Check if already unlocked in this session
            if self._dev_mode_unlocked:
                self.switch_mode('developer')
                return True
            
            # Show passcode dialog
            dialog = PasscodeDialog(self.parent_widget, is_setup=False)
            if dialog.exec() == QDialog.DialogCode.Accepted:
                if dialog.get_passcode() == self._dev_passcode:
                    self._dev_mode_unlocked = True
                    self.switch_mode('developer')
                    return True
                else:
                    QMessageBox.critical(
                        self.parent_widget,
                        "Access Denied",
                        "Incorrect passcode. Developer mode access denied."
                    )
                    self.developer_access_denied.emit()
                    return False
            return False
        else:
            # Switch to user mode (no passcode needed)
            self.switch_mode('user')
            return True
    
    def change_passcode(self) -> bool:
        """
        Change the developer mode passcode.
        
        Returns:
            True if passcode was changed successfully
        """
        # First verify current passcode
        dialog = PasscodeDialog(self.parent_widget, is_setup=False)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            if dialog.get_passcode() == self._dev_passcode:
                # Show setup dialog for new passcode
                setup_dialog = PasscodeDialog(self.parent_widget, is_setup=True)
                if setup_dialog.exec() == QDialog.DialogCode.Accepted:
                    self._save_passcode(setup_dialog.get_passcode())
                    self._dev_passcode = setup_dialog.get_passcode()
                    QMessageBox.information(
                        self.parent_widget,
                        "Success",
                        "Developer passcode has been changed successfully."
                    )
                    return True
            else:
                QMessageBox.critical(
                    self.parent_widget,
                    "Access Denied",
                    "Current passcode is incorrect."
                )
        return False
    
    def get_current_mode(self) -> str:
        """Get current mode name."""
        return self.current_mode
    
    def get_mode_config(self, mode: Optional[str] = None) -> Dict[str, Any]:
        """Get configuration for a mode."""
        mode = mode or self.current_mode
        if mode == 'developer':
            return self.DEVELOPER_MODE_CONFIG.copy()
        return self.USER_MODE_CONFIG.copy()
    
    def save_state(self, mode: str, state: ModeState) -> None:
        """Save state for a mode."""
        self.mode_states[mode] = state
    
    def get_state(self, mode: str) -> ModeState:
        """Get saved state for a mode."""
        return self.mode_states.get(mode, ModeState())
    
    def switch_mode(self, target_mode: str, current_state: Optional[ModeState] = None) -> Dict[str, Any]:
        """
        Switch to a different mode.
        
        Args:
            target_mode: Mode to switch to ('user' or 'developer')
            current_state: Current state to save before switching
        
        Returns:
            Dict with new mode config and restored state
        """
        if target_mode not in ('user', 'developer'):
            raise ValueError(f"Invalid mode: {target_mode}")
        
        # Save current state
        if current_state:
            self.mode_states[self.current_mode] = current_state
        
        # Switch mode
        old_mode = self.current_mode
        self.current_mode = target_mode
        
        # Reset developer unlock if switching to user
        if target_mode == 'user':
            self._dev_mode_unlocked = False
        
        # Get restored state
        restored_state = self.mode_states.get(target_mode, ModeState())
        
        # Save config
        self._save_config()
        
        # Emit signal
        self.mode_changed.emit(old_mode, target_mode)
        
        # Notify callbacks
        for callback in self._on_switch_callbacks:
            try:
                callback(old_mode, target_mode)
            except Exception as e:
                logger.error(f"Mode switch callback error: {e}")
        
        logger.info(f"Switched mode: {old_mode} -> {target_mode}")
        
        return {
            'mode': target_mode,
            'config': self.get_mode_config(target_mode),
            'state': restored_state
        }
    
    def toggle_mode(self, current_state: Optional[ModeState] = None) -> Dict[str, Any]:
        """Toggle between user and developer modes."""
        target = 'developer' if self.current_mode == 'user' else 'user'
        return self.switch_mode(target, current_state)
    
    def on_mode_switch(self, callback: Callable[[str, str], None]) -> None:
        """Register callback for mode switches."""
        self._on_switch_callbacks.append(callback)
    
    def is_developer_mode(self) -> bool:
        """Check if currently in developer mode."""
        return self.current_mode == 'developer'
    
    def is_developer_unlocked(self) -> bool:
        """Check if developer mode is unlocked in current session."""
        return self._dev_mode_unlocked


# Global instance
_mode_manager: Optional[ModeManager] = None


def get_mode_manager(parent_widget: Optional[QWidget] = None) -> ModeManager:
    """Get the global mode manager instance."""
    global _mode_manager
    if _mode_manager is None:
        _mode_manager = ModeManager(parent_widget)
    elif parent_widget is not None:
        _mode_manager.parent_widget = parent_widget
    return _mode_manager
