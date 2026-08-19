"""
Protocol Definitions for Tech News Scraper System.

This module acts as the IDL (Interface Definition Language) for the system,
defining strict data schemas (Protobuf-style) for inter-component communication.

We use Python dataclasses to simulate gRPC message structures, enforcing
strict typing and cleaner interfaces.
"""

from dataclasses import dataclass, field
from datetime import datetime, UTC
from enum import Enum, auto
from typing import Any, Dict, List, Optional
from uuid import uuid4


class EventType(Enum):
    """Enumeration of all system event types."""
    # System
    SYSTEM_STARTUP = auto()
    SYSTEM_SHUTDOWN = auto()
    ERROR_OCCURRED = auto()
    
    # Logging
    LOG_MESSAGE = auto()
    
    # Stats
    STATS_UPDATE = auto()
    
    # Scraping Workflow
    SCRAPE_STARTED = auto()
    SCRAPE_COMPLETED = auto()
    SOURCE_SCRAPED = auto()
    ARTICLE_FOUND = auto()
    
    # Real-time Feed
    NEW_ARTICLE_STREAMED = auto()


@dataclass
class SystemEvent:
    """Base class for all system events (like a gRPC Message)."""
    event_id: str = field(default_factory=lambda: str(uuid4()))
    timestamp: datetime = field(default_factory=lambda: datetime.now(UTC))
    event_type: EventType = EventType.SYSTEM_STARTUP
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary (like MessageToDict)."""
        return {
            "event_id": self.event_id,
            "timestamp": self.timestamp.isoformat(),
            "event_type": self.event_type.name,
        }


@dataclass
class LogMessage(SystemEvent):
    """Structured log message event."""
    level: str = "INFO"
    component: str = "System"
    message: str = ""
    event_type: EventType = EventType.LOG_MESSAGE


@dataclass
class StatsUpdate(SystemEvent):
    """Real-time system statistics snapshot."""
    total_articles: int = 0
    total_sources: int = 0
    total_requests: int = 0
    success_rate: float = 0.0
    cache_hits: int = 0
    event_type: EventType = EventType.STATS_UPDATE


@dataclass
class SourceStatus(SystemEvent):
    """Status update for a specific source."""
    source_url: str = ""
    status: str = "IDLE"  # IDLE, SCRAPING, ERROR, SUCCESS
    articles_found: int = 0
    latency_ms: float = 0.0
    error_message: Optional[str] = None
    event_type: EventType = EventType.SOURCE_SCRAPED


@dataclass
class RealTimeArticleEvent(SystemEvent):
    """Event fired when a new article is discovered in real-time."""
    article_id: str = ""
    title: str = ""
    url: str = ""
    source: str = ""
    published_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    tech_score: float = 0.0
    event_type: EventType = EventType.NEW_ARTICLE_STREAMED
