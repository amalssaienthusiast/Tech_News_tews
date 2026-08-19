# User module for Tech News Scraper
# Provides user preferences, personalization, and settings management

from .preferences import (
    UserPreferences,
    UserPreferencesManager,
    TopicSubscription,
    CompanyWatchItem,
    DeliverySettings,
    get_preferences_manager,
)

__all__ = [
    "UserPreferences",
    "UserPreferencesManager",
    "TopicSubscription",
    "CompanyWatchItem",
    "DeliverySettings",
    "get_preferences_manager",
]
