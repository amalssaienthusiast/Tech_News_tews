"""Lazy exports for dialogs to avoid eager cross-Qt runtime imports."""

from importlib import import_module
from typing import Any

_EXPORTS = {
    "ArticlePopup": (".article_popup", "ArticlePopup"),
    "HistoryPopup": (".history_popup", "HistoryPopup"),
    "PreferencesDialog": (".preferences", "PreferencesDialog"),
    "DeveloperDashboard": (".developer_dashboard", "DeveloperDashboard"),
    "CrawlerDialog": (".crawler_dialog", "CrawlerDialog"),
    "StatisticsPopup": (".statistics_popup", "StatisticsPopup"),
    "NewsletterDialog": (".newsletter_dialog", "NewsletterDialog"),
    "show_newsletter_dialog": (".newsletter_dialog", "show_newsletter_dialog"),
    "AlertConfigDialog": (".alert_dialog", "AlertConfigDialog"),
    "show_alert_config": (".alert_dialog", "show_alert_config"),
    "URLBypassDialog": (".url_bypass_dialog", "URLBypassDialog"),
    "show_url_bypass_dialog": (".url_bypass_dialog", "show_url_bypass_dialog"),
    "ArticleContentViewer": (".article_viewer", "ArticleContentViewer"),
    "show_article_viewer": (".article_viewer", "show_article_viewer"),
    "CustomSourcesDialog": (".custom_sources_dialog", "CustomSourcesDialog"),
    "show_custom_sources_dialog": (".custom_sources_dialog", "show_custom_sources_dialog"),
}

__all__ = list(_EXPORTS.keys())


def __getattr__(name: str) -> Any:
    if name not in _EXPORTS:
        raise AttributeError(f"module '{__name__}' has no attribute '{name}'")
    module_name, attr_name = _EXPORTS[name]
    module = import_module(module_name, package=__name__)
    value = getattr(module, attr_name)
    globals()[name] = value
    return value
