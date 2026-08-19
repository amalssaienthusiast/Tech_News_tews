"""GUI Qt package with lazy exports to avoid eager backend collisions."""

from importlib import import_module
from typing import Any

_EXPORTS = {
    "COLORS": ("gui_qt.theme", "COLORS"),
    "apply_theme": ("gui_qt.theme", "apply_theme"),
    "get_color": ("gui_qt.theme", "get_color"),
    "TechNewsMainWindow": ("gui_qt.main_window", "TechNewsMainWindow"),
    "TechNewsController": ("gui_qt.controller", "TechNewsController"),
    "run_async": ("gui_qt.utils", "run_async"),
    "cleanup": ("gui_qt.utils", "cleanup"),
    "ArticleCard": ("gui_qt.widgets", "ArticleCard"),
    "FeedPanel": ("gui_qt.panels", "FeedPanel"),
    "get_event_manager": ("gui_qt.event_manager", "get_event_manager"),
    "get_config": ("gui_qt.config_manager", "get_config"),
    "get_security_manager": ("gui_qt.security", "get_security_manager"),
    "show_admin_panel": ("gui_qt.panels.admin_panel", "show_admin_panel"),
}

__all__ = list(_EXPORTS.keys())


def __getattr__(name: str) -> Any:
    if name not in _EXPORTS:
        raise AttributeError(f"module '{__name__}' has no attribute '{name}'")
    module_name, attr_name = _EXPORTS[name]
    module = import_module(module_name)
    value = getattr(module, attr_name)
    globals()[name] = value
    return value
