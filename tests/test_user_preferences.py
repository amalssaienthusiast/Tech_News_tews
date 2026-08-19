"""
Test suite for User Preferences Module

Tests UserPreferencesManager CRUD operations, data validation,
and SQLite persistence.
"""

import json
import pytest
import tempfile
from pathlib import Path
from datetime import datetime

from src.user import (
    UserPreferencesManager,
    UserPreferences,
    TopicSubscription,
    CompanyWatchItem,
    DeliverySettings,
)
from src.user.preferences import (
    TopicCategory,
    SourcePreference,
    AlertThresholds,
    DeliveryFrequency,
)


class TestUserPreferences:
    """Tests for UserPreferences model."""
    
    def test_create_preferences(self):
        """Test creating UserPreferences with defaults."""
        prefs = UserPreferences(user_id="test_user")
        
        assert prefs.user_id == "test_user"
        assert prefs.display_name == "User"
        assert prefs.theme == "tokyo_night"
        assert prefs.articles_per_page == 20
        assert prefs.topics == []
        assert prefs.watchlist == []
        assert prefs.sources == []
    
    def test_topic_weights_calculation(self):
        """Test get_topic_weights helper."""
        prefs = UserPreferences(
            user_id="test_user",
            topics=[
                TopicSubscription(topic="AI", weight=1.5, enabled=True),
                TopicSubscription(topic="Crypto", weight=0.8, enabled=True),
                TopicSubscription(topic="Gaming", weight=1.0, enabled=False),
            ]
        )
        
        weights = prefs.get_topic_weights()
        
        assert weights == {"AI": 1.5, "Crypto": 0.8}
        assert "Gaming" not in weights  # Disabled topics excluded
    
    def test_watched_companies(self):
        """Test get_watched_companies helper."""
        prefs = UserPreferences(
            user_id="test_user",
            watchlist=[
                CompanyWatchItem(name="OpenAI", aliases=["Open AI", "openai"]),
                CompanyWatchItem(name="Google", aliases=["Alphabet"], enabled=False),
            ]
        )
        
        companies = prefs.get_watched_companies()
        
        assert "openai" in companies
        assert "open ai" in companies
        assert "google" not in companies  # Disabled company excluded
    
    def test_source_blocking(self):
        """Test is_source_blocked helper."""
        prefs = UserPreferences(
            user_id="test_user",
            sources=[
                SourcePreference(source_domain="example.com", blocked=True),
                SourcePreference(source_domain="techcrunch.com", blocked=False),
            ]
        )
        
        assert prefs.is_source_blocked("example.com") == True
        assert prefs.is_source_blocked("Example.COM") == True  # Case insensitive
        assert prefs.is_source_blocked("techcrunch.com") == False
        assert prefs.is_source_blocked("unknown.com") == False
    
    def test_enabled_channels(self):
        """Test get_enabled_channels helper."""
        prefs = UserPreferences(
            user_id="test_user",
            delivery=DeliverySettings(
                desktop_notifications=True,
                email_enabled=True,
                telegram_enabled=True,
                discord_enabled=False,
            )
        )
        
        channels = prefs.get_enabled_channels()
        
        assert "desktop" in channels
        assert "email" in channels
        assert "telegram" in channels
        assert "discord" not in channels


class TestTopicSubscription:
    """Tests for TopicSubscription model."""
    
    def test_weight_validation(self):
        """Test weight is rounded to 2 decimal places."""
        topic = TopicSubscription(topic="AI", weight=1.333333)
        assert topic.weight == 1.33
    
    def test_weight_bounds(self):
        """Test weight bounds (0-2)."""
        with pytest.raises(ValueError):
            TopicSubscription(topic="AI", weight=-0.1)
        
        with pytest.raises(ValueError):
            TopicSubscription(topic="AI", weight=2.1)


class TestUserPreferencesManager:
    """Tests for UserPreferencesManager."""
    
    @pytest.fixture
    def manager(self, tmp_path):
        """Create a fresh manager with temp database."""
        db_path = tmp_path / "test_prefs.db"
        return UserPreferencesManager(database=db_path)
    
    def test_get_creates_default(self, manager):
        """Test get_preferences creates defaults for new user."""
        prefs = manager.get_preferences("new_user")
        
        assert prefs.user_id == "new_user"
        assert len(prefs.topics) == 3  # Default topics
    
    def test_add_topic(self, manager):
        """Test adding a topic."""
        manager.add_topic("user1", "Quantum Computing", weight=1.5)
        prefs = manager.get_preferences("user1")
        
        topics = [t.topic for t in prefs.topics]
        assert "Quantum Computing" in topics
        
        # Check weight
        quantum = next(t for t in prefs.topics if t.topic == "Quantum Computing")
        assert quantum.weight == 1.5
    
    def test_remove_topic(self, manager):
        """Test removing a topic."""
        manager.add_topic("user1", "Temp Topic")
        manager.remove_topic("user1", "Temp Topic")
        
        prefs = manager.get_preferences("user1")
        topics = [t.topic.lower() for t in prefs.topics]
        assert "temp topic" not in topics
    
    def test_add_watched_company(self, manager):
        """Test adding a company to watchlist."""
        manager.add_watched_company(
            "user1",
            "OpenAI",
            ticker="OPENAI",
            aliases=["Open AI"]
        )
        
        prefs = manager.get_preferences("user1")
        
        assert len(prefs.watchlist) == 1
        assert prefs.watchlist[0].name == "OpenAI"
        assert prefs.watchlist[0].ticker == "OPENAI"
        assert "Open AI" in prefs.watchlist[0].aliases
    
    def test_block_source(self, manager):
        """Test blocking a source."""
        manager.block_source("user1", "spam.com")
        prefs = manager.get_preferences("user1")
        
        assert prefs.is_source_blocked("spam.com") == True
    
    def test_prefer_source(self, manager):
        """Test preferring a source."""
        manager.prefer_source("user1", "techcrunch.com")
        prefs = manager.get_preferences("user1")
        
        assert prefs.is_source_preferred("techcrunch.com") == True
    
    def test_export_import(self, manager):
        """Test export and import preferences."""
        # Setup
        manager.add_topic("user1", "Custom Topic")
        manager.add_watched_company("user1", "Tesla")
        
        # Export
        exported = manager.export_preferences("user1")
        assert "Custom Topic" in exported
        assert "Tesla" in exported
        
        # Import to new user
        success = manager.import_preferences("user2", exported)
        assert success == True
        
        # Verify import
        prefs2 = manager.get_preferences("user2")
        topics = [t.topic for t in prefs2.topics]
        assert "Custom Topic" in topics
    
    def test_update_delivery_settings(self, manager):
        """Test updating delivery settings."""
        settings = DeliverySettings(
            email_enabled=True,
            email_address="test@example.com",
            email_frequency=DeliveryFrequency.WEEKLY
        )
        
        manager.update_delivery_settings("user1", settings)
        prefs = manager.get_preferences("user1")
        
        assert prefs.delivery.email_enabled == True
        assert prefs.delivery.email_address == "test@example.com"
        assert prefs.delivery.email_frequency == DeliveryFrequency.WEEKLY
    
    def test_change_callback(self, manager):
        """Test preference change callbacks."""
        called = []
        
        def callback(user_id, prefs):
            called.append(user_id)
        
        manager.on_preferences_change(callback)
        manager.add_topic("user1", "Trigger Callback")
        
        assert "user1" in called
    
    def test_reading_history(self, manager):
        """Test recording and retrieving reading history."""
        manager.record_article_read("user1", "article_123", time_spent_seconds=60)
        
        history = manager.get_reading_history("user1")
        
        assert len(history) == 1
        assert history[0]["article_id"] == "article_123"
        assert history[0]["time_spent_seconds"] == 60


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
