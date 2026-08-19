"""
Infrastructure module for real-time news scraper.

Provides:
- Redis-based event bus for pub/sub messaging
- Message queue integration for distributed workers
"""

from src.infrastructure.redis_event_bus import (
    RedisEventBus,
    LocalEventBus,
    Event,
    EventType,
    create_event_bus,
)

__all__ = [
    "RedisEventBus",
    "LocalEventBus",
    "Event",
    "EventType",
    "create_event_bus",
]
