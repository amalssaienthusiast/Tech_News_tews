"""
User Preferences Module for Tech News Scraper v7.0

Provides comprehensive user personalization including:
- Topic subscriptions with weights
- Company watchlist for tracking
- Source preferences (preferred/blocked)
- Alert thresholds and delivery settings
- Reading history for ML personalization

Architecture:
- Pydantic models for validation
- SQLite persistence via Database class
- Event-based preference change notifications
"""

import hashlib
import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, UTC
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Set

from pydantic import BaseModel, Field, field_validator

logger = logging.getLogger(__name__)


# =============================================================================
# ENUMS
# =============================================================================

class DeliveryFrequency(str, Enum):
    """Email/notification delivery frequency."""
    REALTIME = "realtime"
    HOURLY = "hourly"
    DAILY = "daily"
    WEEKLY = "weekly"
    DISABLED = "disabled"


class TopicCategory(str, Enum):
    """Pre-defined tech topic categories."""
    AI_ML = "AI & Machine Learning"
    CYBERSECURITY = "Cybersecurity"
    CLOUD = "Cloud Computing"
    BLOCKCHAIN = "Blockchain & Crypto"
    STARTUPS = "Startups & Funding"
    HARDWARE = "Hardware & Devices"
    SOFTWARE = "Software Development"
    DATA = "Data & Analytics"
    NETWORKING = "Networking & 5G"
    GAMING = "Gaming & VR"
    SPACE = "Space Tech"
    BIOTECH = "Biotech & Health Tech"
    FINTECH = "FinTech"
    GREEN_TECH = "Green Tech & Sustainability"
    ROBOTICS = "Robotics & Automation"
    OTHER = "Other"


# =============================================================================
# DATA MODELS
# =============================================================================

class TopicSubscription(BaseModel):
    """User subscription to a specific topic."""
    topic: str = Field(description="Topic name or category")
    weight: float = Field(default=1.0, ge=0.0, le=2.0, description="Preference weight (0-2)")
    keywords: List[str] = Field(default_factory=list, description="Custom keywords for this topic")
    enabled: bool = Field(default=True)
    
    @field_validator('weight')
    @classmethod
    def validate_weight(cls, v):
        return round(v, 2)


class CompanyWatchItem(BaseModel):
    """Company in user's watchlist."""
    name: str = Field(description="Company name")
    ticker: Optional[str] = Field(default=None, description="Stock ticker symbol")
    aliases: List[str] = Field(default_factory=list, description="Alternative names")
    priority: int = Field(default=1, ge=1, le=3, description="1=High, 2=Medium, 3=Low")
    enabled: bool = Field(default=True)


class SourcePreference(BaseModel):
    """User preference for a specific news source."""
    source_domain: str = Field(description="Source domain (e.g., techcrunch.com)")
    source_name: str = Field(default="", description="Display name")
    preferred: bool = Field(default=False, description="Higher ranking for this source")
    blocked: bool = Field(default=False, description="Never show from this source")
    trust_score: float = Field(default=0.5, ge=0.0, le=1.0)


class DeliverySettings(BaseModel):
    """User notification and delivery preferences."""
    # Email
    email_enabled: bool = Field(default=False)
    email_address: str = Field(default="")
    email_frequency: DeliveryFrequency = Field(default=DeliveryFrequency.DAILY)
    email_digest_time: str = Field(default="08:00", description="HH:MM format for digest")
    
    # Push/Desktop
    desktop_notifications: bool = Field(default=True)
    
    # External Channels
    telegram_enabled: bool = Field(default=False)
    telegram_chat_id: str = Field(default="")
    
    discord_enabled: bool = Field(default=False)
    discord_webhook_url: str = Field(default="")
    
    slack_enabled: bool = Field(default=False)
    slack_channel: str = Field(default="")
    
    # Webhook
    webhook_enabled: bool = Field(default=False)
    webhook_url: str = Field(default="")
    webhook_secret: str = Field(default="")


class AlertThresholds(BaseModel):
    """User-configurable alert thresholds."""
    min_criticality: int = Field(default=7, ge=1, le=10, description="Min score to trigger alerts")
    min_sentiment_change: float = Field(default=0.3, ge=0.0, le=1.0)
    watched_company_threshold: int = Field(default=5, description="Lower threshold for watched companies")
    max_alerts_per_hour: int = Field(default=10)
    quiet_hours_start: str = Field(default="22:00", description="HH:MM")
    quiet_hours_end: str = Field(default="07:00", description="HH:MM")
    quiet_hours_enabled: bool = Field(default=False)


class UserPreferences(BaseModel):
    """Complete user preferences model."""
    # Identity
    user_id: str = Field(description="Unique user identifier")
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    
    # Display
    display_name: str = Field(default="User")
    theme: str = Field(default="tokyo_night")
    articles_per_page: int = Field(default=20, ge=5, le=100)
    
    # Content Preferences
    topics: List[TopicSubscription] = Field(default_factory=list)
    watchlist: List[CompanyWatchItem] = Field(default_factory=list)
    sources: List[SourcePreference] = Field(default_factory=list)
    
    # Delivery & Alerts
    delivery: DeliverySettings = Field(default_factory=DeliverySettings)
    alerts: AlertThresholds = Field(default_factory=AlertThresholds)
    
    # Reading History (for personalization ML)
    reading_history_enabled: bool = Field(default=True)
    
    model_config = {
        "json_encoders": {
            datetime: lambda v: v.isoformat()
        }
    }
    
    def get_topic_weights(self) -> Dict[str, float]:
        """Get topic weights as dictionary for scoring."""
        return {t.topic: t.weight for t in self.topics if t.enabled}
    
    def get_watched_companies(self) -> List[str]:
        """Get list of all watched company names and aliases."""
        companies = []
        for item in self.watchlist:
            if item.enabled:
                companies.append(item.name.lower())
                companies.extend([a.lower() for a in item.aliases])
        return companies
    
    def is_source_blocked(self, domain: str) -> bool:
        """Check if a source domain is blocked."""
        for pref in self.sources:
            if pref.source_domain.lower() == domain.lower():
                return pref.blocked
        return False
    
    def is_source_preferred(self, domain: str) -> bool:
        """Check if a source domain is preferred."""
        for pref in self.sources:
            if pref.source_domain.lower() == domain.lower():
                return pref.preferred
        return False
    
    def get_enabled_channels(self) -> List[str]:
        """Get list of enabled notification channels."""
        channels = []
        if self.delivery.desktop_notifications:
            channels.append("desktop")
        if self.delivery.email_enabled:
            channels.append("email")
        if self.delivery.telegram_enabled:
            channels.append("telegram")
        if self.delivery.discord_enabled:
            channels.append("discord")
        if self.delivery.slack_enabled:
            channels.append("slack")
        if self.delivery.webhook_enabled:
            channels.append("webhook")
        return channels


# =============================================================================
# PREFERENCES MANAGER
# =============================================================================

class UserPreferencesManager:
    """
    Manages user preferences with SQLite persistence.
    
    Features:
    - CRUD operations for preferences
    - Change notifications via callbacks
    - Default preferences for new users
    - Import/Export support
    
    Example:
        manager = UserPreferencesManager(db)
        
        # Get or create user
        prefs = manager.get_preferences("user_123")
        
        # Update topics
        prefs.topics.append(TopicSubscription(topic="AI & ML", weight=1.5))
        manager.save_preferences(prefs)
        
        # Watch a company
        manager.add_watched_company("user_123", "OpenAI", ticker="OPENAI")
    """
    
    DEFAULT_TOPICS = [
        TopicSubscription(topic=TopicCategory.AI_ML.value, weight=1.0),
        TopicSubscription(topic=TopicCategory.CYBERSECURITY.value, weight=1.0),
        TopicSubscription(topic=TopicCategory.STARTUPS.value, weight=0.8),
    ]
    
    def __init__(self, database=None):
        """
        Initialize the preferences manager.
        
        Args:
            database: Optional Database instance. If not provided,
                     will create/use the default database.
        """
        self._db = database
        self._cache: Dict[str, UserPreferences] = {}
        self._change_callbacks: List[Callable[[str, UserPreferences], None]] = []
        
        # Ensure schema exists
        self._ensure_schema()
        
    def _get_connection(self):
        """Get or create database connection."""
        if self._db is not None and hasattr(self._db, "_get_connection"):
            return self._db._get_connection()
        import sqlite3
        from pathlib import Path
        if isinstance(self._db, (str, Path)):
            db_path = Path(self._db)
        else:
            from src.storage.sqlite_engine import DEFAULT_CANONICAL_DB_PATH
            db_path = DEFAULT_CANONICAL_DB_PATH
        if not db_path.parent.exists():
            db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON;")
        return conn
    
    def _ensure_schema(self):
        """Ensure user preferences tables exist in database."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            
            # Main preferences table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS user_preferences (
                    user_id TEXT PRIMARY KEY,
                    display_name TEXT DEFAULT 'User',
                    theme TEXT DEFAULT 'tokyo_night',
                    articles_per_page INTEGER DEFAULT 20,
                    reading_history_enabled INTEGER DEFAULT 1,
                    delivery_settings TEXT DEFAULT '{}',
                    alert_thresholds TEXT DEFAULT '{}',
                    created_at TEXT,
                    updated_at TEXT
                )
            """)
            
            # Topic subscriptions
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS user_topics (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id TEXT NOT NULL,
                    topic TEXT NOT NULL,
                    weight REAL DEFAULT 1.0,
                    keywords TEXT DEFAULT '[]',
                    enabled INTEGER DEFAULT 1,
                    UNIQUE(user_id, topic),
                    FOREIGN KEY (user_id) REFERENCES user_preferences(user_id)
                )
            """)
            
            # Company watchlist
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS user_watchlist (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id TEXT NOT NULL,
                    company_name TEXT NOT NULL,
                    ticker TEXT,
                    aliases TEXT DEFAULT '[]',
                    priority INTEGER DEFAULT 1,
                    enabled INTEGER DEFAULT 1,
                    UNIQUE(user_id, company_name),
                    FOREIGN KEY (user_id) REFERENCES user_preferences(user_id)
                )
            """)
            
            # Source preferences
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS user_sources (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id TEXT NOT NULL,
                    source_domain TEXT NOT NULL,
                    source_name TEXT,
                    preferred INTEGER DEFAULT 0,
                    blocked INTEGER DEFAULT 0,
                    trust_score REAL DEFAULT 0.5,
                    UNIQUE(user_id, source_domain),
                    FOREIGN KEY (user_id) REFERENCES user_preferences(user_id)
                )
            """)
            
            # Reading history (for ML personalization)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS user_reading_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id TEXT NOT NULL,
                    article_id TEXT NOT NULL,
                    read_at TEXT,
                    time_spent_seconds INTEGER,
                    clicked_links INTEGER DEFAULT 0,
                    FOREIGN KEY (user_id) REFERENCES user_preferences(user_id)
                )
            """)
            
            # Create indexes
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_user_topics_user ON user_topics(user_id)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_user_watchlist_user ON user_watchlist(user_id)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_user_history_user ON user_reading_history(user_id)")
            
            conn.commit()
            
        logger.info("User preferences schema ensured")
    
    def get_preferences(self, user_id: str) -> UserPreferences:
        """
        Get preferences for a user, creating defaults if not exists.
        
        Args:
            user_id: Unique user identifier
            
        Returns:
            UserPreferences instance
        """
        # Check cache first
        if user_id in self._cache:
            return self._cache[user_id]
        
        with self._get_connection() as conn:
            cursor = conn.cursor()
            
            # Get main preferences
            cursor.execute(
                "SELECT * FROM user_preferences WHERE user_id = ?",
                (user_id,)
            )
            row = cursor.fetchone()
            
            if not row:
                # Create default preferences
                prefs = self._create_default_preferences(user_id)
                self.save_preferences(prefs)
                return prefs
            
            # Build preferences from database
            prefs = UserPreferences(
                user_id=row['user_id'],
                display_name=row['display_name'] or 'User',
                theme=row['theme'] or 'tokyo_night',
                articles_per_page=row['articles_per_page'] or 20,
                reading_history_enabled=bool(row['reading_history_enabled']),
                delivery=DeliverySettings(**json.loads(row['delivery_settings'] or '{}')),
                alerts=AlertThresholds(**json.loads(row['alert_thresholds'] or '{}')),
                created_at=datetime.fromisoformat(row['created_at']) if row['created_at'] else datetime.now(UTC),
                updated_at=datetime.fromisoformat(row['updated_at']) if row['updated_at'] else datetime.now(UTC),
            )
            
            # Load topics
            cursor.execute(
                "SELECT * FROM user_topics WHERE user_id = ?",
                (user_id,)
            )
            for topic_row in cursor.fetchall():
                prefs.topics.append(TopicSubscription(
                    topic=topic_row['topic'],
                    weight=topic_row['weight'],
                    keywords=json.loads(topic_row['keywords'] or '[]'),
                    enabled=bool(topic_row['enabled'])
                ))
            
            # Load watchlist
            cursor.execute(
                "SELECT * FROM user_watchlist WHERE user_id = ?",
                (user_id,)
            )
            for watch_row in cursor.fetchall():
                prefs.watchlist.append(CompanyWatchItem(
                    name=watch_row['company_name'],
                    ticker=watch_row['ticker'],
                    aliases=json.loads(watch_row['aliases'] or '[]'),
                    priority=watch_row['priority'],
                    enabled=bool(watch_row['enabled'])
                ))
            
            # Load source preferences
            cursor.execute(
                "SELECT * FROM user_sources WHERE user_id = ?",
                (user_id,)
            )
            for src_row in cursor.fetchall():
                prefs.sources.append(SourcePreference(
                    source_domain=src_row['source_domain'],
                    source_name=src_row['source_name'] or '',
                    preferred=bool(src_row['preferred']),
                    blocked=bool(src_row['blocked']),
                    trust_score=src_row['trust_score'] or 0.5
                ))
            
            # Cache and return
            self._cache[user_id] = prefs
            return prefs
    
    def _create_default_preferences(self, user_id: str) -> UserPreferences:
        """Create default preferences for a new user."""
        return UserPreferences(
            user_id=user_id,
            topics=self.DEFAULT_TOPICS.copy(),
            watchlist=[],
            sources=[],
        )
    
    def save_preferences(self, prefs: UserPreferences) -> bool:
        """
        Save user preferences to database.
        
        Args:
            prefs: UserPreferences to save
            
        Returns:
            True if saved successfully
        """
        prefs.updated_at = datetime.now(UTC)
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                
                # Upsert main preferences
                cursor.execute("""
                    INSERT OR REPLACE INTO user_preferences
                    (user_id, display_name, theme, articles_per_page, 
                     reading_history_enabled, delivery_settings, alert_thresholds,
                     created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    prefs.user_id,
                    prefs.display_name,
                    prefs.theme,
                    prefs.articles_per_page,
                    int(prefs.reading_history_enabled),
                    prefs.delivery.model_dump_json(),
                    prefs.alerts.model_dump_json(),
                    prefs.created_at.isoformat(),
                    prefs.updated_at.isoformat()
                ))
                
                # Clear and reinsert topics
                cursor.execute("DELETE FROM user_topics WHERE user_id = ?", (prefs.user_id,))
                for topic in prefs.topics:
                    cursor.execute("""
                        INSERT INTO user_topics (user_id, topic, weight, keywords, enabled)
                        VALUES (?, ?, ?, ?, ?)
                    """, (
                        prefs.user_id,
                        topic.topic,
                        topic.weight,
                        json.dumps(topic.keywords),
                        int(topic.enabled)
                    ))
                
                # Clear and reinsert watchlist
                cursor.execute("DELETE FROM user_watchlist WHERE user_id = ?", (prefs.user_id,))
                for item in prefs.watchlist:
                    cursor.execute("""
                        INSERT INTO user_watchlist 
                        (user_id, company_name, ticker, aliases, priority, enabled)
                        VALUES (?, ?, ?, ?, ?, ?)
                    """, (
                        prefs.user_id,
                        item.name,
                        item.ticker,
                        json.dumps(item.aliases),
                        item.priority,
                        int(item.enabled)
                    ))
                
                # Clear and reinsert sources
                cursor.execute("DELETE FROM user_sources WHERE user_id = ?", (prefs.user_id,))
                for src in prefs.sources:
                    cursor.execute("""
                        INSERT INTO user_sources 
                        (user_id, source_domain, source_name, preferred, blocked, trust_score)
                        VALUES (?, ?, ?, ?, ?, ?)
                    """, (
                        prefs.user_id,
                        src.source_domain,
                        src.source_name,
                        int(src.preferred),
                        int(src.blocked),
                        src.trust_score
                    ))
                
                conn.commit()
            
            # Update cache
            self._cache[prefs.user_id] = prefs
            
            # Notify callbacks
            for callback in self._change_callbacks:
                try:
                    callback(prefs.user_id, prefs)
                except Exception as e:
                    logger.error(f"Preference change callback error: {e}")
            
            logger.info(f"Saved preferences for user {prefs.user_id}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to save preferences: {e}")
            return False
    
    def add_topic(self, user_id: str, topic: str, weight: float = 1.0) -> bool:
        """Add or update a topic subscription."""
        prefs = self.get_preferences(user_id)
        
        # Check if already exists
        for t in prefs.topics:
            if t.topic.lower() == topic.lower():
                t.weight = weight
                t.enabled = True
                return self.save_preferences(prefs)
        
        # Add new
        prefs.topics.append(TopicSubscription(topic=topic, weight=weight))
        return self.save_preferences(prefs)
    
    def remove_topic(self, user_id: str, topic: str) -> bool:
        """Remove a topic subscription."""
        prefs = self.get_preferences(user_id)
        prefs.topics = [t for t in prefs.topics if t.topic.lower() != topic.lower()]
        return self.save_preferences(prefs)
    
    def add_watched_company(
        self, 
        user_id: str, 
        company: str, 
        ticker: Optional[str] = None,
        aliases: Optional[List[str]] = None
    ) -> bool:
        """Add a company to the watchlist."""
        prefs = self.get_preferences(user_id)
        
        # Check if already exists
        for item in prefs.watchlist:
            if item.name.lower() == company.lower():
                if ticker:
                    item.ticker = ticker
                if aliases:
                    item.aliases = aliases
                item.enabled = True
                return self.save_preferences(prefs)
        
        # Add new
        prefs.watchlist.append(CompanyWatchItem(
            name=company,
            ticker=ticker,
            aliases=aliases or []
        ))
        return self.save_preferences(prefs)
    
    def remove_watched_company(self, user_id: str, company: str) -> bool:
        """Remove a company from the watchlist."""
        prefs = self.get_preferences(user_id)
        prefs.watchlist = [w for w in prefs.watchlist if w.name.lower() != company.lower()]
        return self.save_preferences(prefs)
    
    def block_source(self, user_id: str, domain: str) -> bool:
        """Block a source domain."""
        prefs = self.get_preferences(user_id)
        
        for src in prefs.sources:
            if src.source_domain.lower() == domain.lower():
                src.blocked = True
                src.preferred = False
                return self.save_preferences(prefs)
        
        prefs.sources.append(SourcePreference(
            source_domain=domain,
            blocked=True
        ))
        return self.save_preferences(prefs)
    
    def prefer_source(self, user_id: str, domain: str) -> bool:
        """Mark a source as preferred."""
        prefs = self.get_preferences(user_id)
        
        for src in prefs.sources:
            if src.source_domain.lower() == domain.lower():
                src.preferred = True
                src.blocked = False
                return self.save_preferences(prefs)
        
        prefs.sources.append(SourcePreference(
            source_domain=domain,
            preferred=True
        ))
        return self.save_preferences(prefs)
    
    def update_delivery_settings(self, user_id: str, settings: DeliverySettings) -> bool:
        """Update delivery settings."""
        prefs = self.get_preferences(user_id)
        prefs.delivery = settings
        return self.save_preferences(prefs)
    
    def update_alert_thresholds(self, user_id: str, thresholds: AlertThresholds) -> bool:
        """Update alert thresholds."""
        prefs = self.get_preferences(user_id)
        prefs.alerts = thresholds
        return self.save_preferences(prefs)
    
    def record_article_read(
        self, 
        user_id: str, 
        article_id: str,
        time_spent_seconds: int = 0
    ) -> None:
        """Record that a user read an article (for ML personalization)."""
        prefs = self.get_preferences(user_id)
        if not prefs.reading_history_enabled:
            return
        
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    INSERT INTO user_reading_history 
                    (user_id, article_id, read_at, time_spent_seconds)
                    VALUES (?, ?, ?, ?)
                """, (
                    user_id,
                    article_id,
                    datetime.now(UTC).isoformat(),
                    time_spent_seconds
                ))
                conn.commit()
        except Exception as e:
            logger.debug(f"Failed to record reading history: {e}")
    
    def get_reading_history(
        self, 
        user_id: str, 
        limit: int = 100
    ) -> List[Dict[str, Any]]:
        """Get user's reading history."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT article_id, read_at, time_spent_seconds
                FROM user_reading_history
                WHERE user_id = ?
                ORDER BY read_at DESC
                LIMIT ?
            """, (user_id, limit))
            
            return [dict(row) for row in cursor.fetchall()]
    
    def on_preferences_change(self, callback: Callable[[str, UserPreferences], None]):
        """Register a callback for preference changes."""
        self._change_callbacks.append(callback)
    
    def export_preferences(self, user_id: str) -> str:
        """Export preferences as JSON string."""
        prefs = self.get_preferences(user_id)
        return prefs.model_dump_json(indent=2)
    
    def import_preferences(self, user_id: str, json_data: str) -> bool:
        """Import preferences from JSON string."""
        try:
            data = json.loads(json_data)
            data['user_id'] = user_id  # Ensure correct user_id
            prefs = UserPreferences(**data)
            return self.save_preferences(prefs)
        except Exception as e:
            logger.error(f"Failed to import preferences: {e}")
            return False
    
    def clear_cache(self, user_id: Optional[str] = None):
        """Clear preferences cache."""
        if user_id:
            self._cache.pop(user_id, None)
        else:
            self._cache.clear()


# =============================================================================
# SINGLETON INSTANCE
# =============================================================================

_preferences_manager: Optional[UserPreferencesManager] = None


def get_preferences_manager() -> UserPreferencesManager:
    """Get or create the global preferences manager."""
    global _preferences_manager
    if _preferences_manager is None:
        _preferences_manager = UserPreferencesManager()
    return _preferences_manager
