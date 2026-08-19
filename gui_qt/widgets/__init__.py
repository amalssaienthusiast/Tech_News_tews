"""Widgets package with lazy exports to avoid eager cross-Qt imports."""

from importlib import import_module
from typing import Any

_EXPORTS = {
    "ArticleCard": ("gui_qt.widgets.article_card", "ArticleCard"),
    "TechScoreBar": ("gui_qt.widgets.article_card", "TechScoreBar"),
    "TierBadge": ("gui_qt.widgets.article_card", "TierBadge"),
    "SearchBar": ("gui_qt.widgets.search_bar", "SearchBar"),
    "ArticleListView": ("gui_qt.widgets.article_list", "ArticleListView"),
    "StatsPanel": ("gui_qt.widgets.stats_panel", "StatsPanel"),
    "LoadingSpinner": ("gui_qt.widgets.loading_spinner", "LoadingSpinner"),
    "WelcomeScreen": ("gui_qt.widgets.welcome_screen", "WelcomeScreen"),
    "LiveFeedContainer": ("gui_qt.widgets.live_feed_container", "LiveFeedContainer"),
    "GlobalDiscoveryPage": ("gui_qt.widgets.global_discovery_page", "GlobalDiscoveryPage"),
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
