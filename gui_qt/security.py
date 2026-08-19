"""
Security Manager for gui_qt.

Handles passcode verification, authentication state and lockout.
Uses QMessageBox for dialogs instead of Tkinter messagebox.
"""

import hashlib
import logging
from typing import Optional

from PyQt6.QtWidgets import QMessageBox, QWidget

logger = logging.getLogger(__name__)


class SecurityManager:
    """
    Manages security context for the application.

    Handles authentication state, locking mechanisms, and credential
    verification (SHA-256 hashed passcode).
    """

    _PASSCODE_HASH = (
        "07334386287751ba02a4588c1a0875dbd074a61bd9e6ab7c48d244eacd0c99e0"
    )

    def __init__(self) -> None:
        self._is_locked = False
        self._is_authenticated = False

    # -- properties ----------------------------------------------------------

    @property
    def is_locked(self) -> bool:
        return self._is_locked

    @property
    def is_authenticated(self) -> bool:
        return self._is_authenticated

    # -- passcode ------------------------------------------------------------

    def check_passcode(self, input_code: str) -> bool:
        """Verify *input_code* against the stored hash."""
        if self._is_locked:
            return False
        input_hash = hashlib.sha256(input_code.encode()).hexdigest()
        if input_hash == self._PASSCODE_HASH:
            self._is_authenticated = True
            return True
        self._is_locked = True
        return False

    def lock(self) -> None:
        """Force-lock the system."""
        self._is_locked = True
        self._is_authenticated = False

    def reset_lock_debug(self) -> None:
        """Debug-only: reset the lockout (never exposed in production UI)."""
        self._is_locked = False

    def verify_developer_access(self, parent: Optional[QWidget] = None) -> bool:
        """
        Verify developer access.

        If already authenticated, returns *True* immediately.
        If locked, shows an error dialog and returns *False*.

        Note: the actual passcode *dialog* lives in
        ``gui_qt.mode_manager.PasscodeDialog`` — this method is the
        programmatic check used before opening protected features.
        """
        if self._is_authenticated:
            return True
        if self._is_locked:
            QMessageBox.critical(
                parent,
                "Access Denied",
                "⛔ System is locked.\nRestart the application to retry.",
            )
            return False
        # Caller should show PasscodeDialog if this returns False
        return False


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------

_security_manager: Optional[SecurityManager] = None


def get_security_manager() -> SecurityManager:
    """Return the global SecurityManager instance."""
    global _security_manager
    if _security_manager is None:
        _security_manager = SecurityManager()
    return _security_manager
