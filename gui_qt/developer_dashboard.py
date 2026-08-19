"""
Redirect shim — the canonical DeveloperDashboard lives in
gui_qt/dialogs/developer_dashboard.py (6-tab version).

All imports from this module are forwarded there so that any
code still referencing gui_qt.developer_dashboard continues to work.
"""

from gui_qt.dialogs.developer_dashboard import DeveloperDashboard  # noqa: F401


def show_developer_dashboard(parent=None, orchestrator=None):
    """Show the canonical 6-tab developer dashboard."""
    dialog = DeveloperDashboard(parent, orchestrator)
    dialog.exec()
