"""
Redis-based Event Bus for Real-Time News Streaming.

This module provides a Redis pub/sub implementation for:
- Publishing events when new articles are discovered
- Subscribing to channels for real-time updates
- Pattern-based subscriptions (e.g., `news:breaking:*`)

Architecture:
    Publishers (scrapers) -> Redis Channels -> Subscribers (WebSocket servers)

Channels:
    - news:all          - All new articles
    - news:breaking     - Breaking/urgent news
    - news:topic:{name} - Topic-specific channels
    - news:source:{id}  - Source-specific channels

Usage:
    # Publishing
    event_bus = RedisEventBus()
    await event_bus.connect()
    await event_bus.publish_article(article)

    # Subscribing
    async for article in event_bus.subscribe('news:all'):
        process(article)
"""

import asyncio
import json
import logging
from datetime import datetime, UTC
from typing import (
    Any,
    AsyncIterator,
    Callable,
    Dict,
    List,
    Optional,
    Set,
    Union,
)
from dataclasses import dataclass, asdict
from enum import Enum

logger = logging.getLogger(__name__)


# =============================================================================
# EVENT TYPES
# =============================================================================

class EventType(str, Enum):
    """Types of events that can be published."""
    ARTICLE_NEW = "article:new"
    ARTICLE_UPDATED = "article:updated"
    SOURCE_DISCOVERED = "source:discovered"
    SOURCE_ERROR = "source:error"
    SYSTEM_HEALTH = "system:health"
    REFRESH_COMPLETE = "refresh:complete"


@dataclass
class Event:
    """Base event structure for pub/sub messaging."""
    type: EventType
    payload: Dict[str, Any]
    timestamp: str
    source: str = "realtime_feeder"
    
    def to_json(self) -> str:
        """Serialize event to JSON."""
        return json.dumps({
            "type": self.type.value,
            "payload": self.payload,
            "timestamp": self.timestamp,
            "source": self.source,
        })
    
    @classmethod
    def from_json(cls, data: str) -> "Event":
        """Deserialize event from JSON."""
        d = json.loads(data)
        return cls(
            type=EventType(d["type"]),
            payload=d["payload"],
            timestamp=d["timestamp"],
            source=d.get("source", "unknown"),
        )


# =============================================================================
# REDIS EVENT BUS
# =============================================================================

class RedisEventBus:
    """
    Redis-based event bus for real-time news distribution.
    
    Supports both single-channel and pattern-based subscriptions,
    with automatic reconnection and graceful degradation.
    
    Example:
        async with RedisEventBus() as bus:
            # Publisher
            await bus.publish('news:all', article_data)
            
            # Subscriber
            async for event in bus.subscribe('news:*'):
                print(f"Received: {event}")
    """
    
    # Default channel prefixes
    CHANNEL_ALL = "news:all"
    CHANNEL_BREAKING = "news:breaking"
    CHANNEL_TOPIC = "news:topic:{topic}"
    CHANNEL_SOURCE = "news:source:{source}"
    
    def __init__(
        self,
        redis_url: str = "redis://localhost:6379/0",
        max_reconnect_attempts: int = 5,
        reconnect_delay: float = 1.0,
    ):
        """
        Initialize the Redis event bus.
        
        Args:
            redis_url: Redis connection URL
            max_reconnect_attempts: Max retry attempts for connection
            reconnect_delay: Initial delay between reconnection attempts
        """
        self._redis_url = redis_url
        self._max_reconnect_attempts = max_reconnect_attempts
        self._reconnect_delay = reconnect_delay
        
        # Connection state
        self._redis: Optional[Any] = None
        self._pubsub: Optional[Any] = None
        self._connected = False
        self._subscriptions: Set[str] = set()
        
        # Callbacks for local event handling
        self._listeners: Dict[str, List[Callable]] = {}
        
        # Statistics
        self._stats = {
            "messages_published": 0,
            "messages_received": 0,
            "reconnect_count": 0,
            "errors": 0,
        }
    
    async def connect(self) -> bool:
        """
        Connect to Redis server.
        
        Returns:
            True if connected successfully, False otherwise
        """
        try:
            import redis.asyncio as aioredis
        except ImportError:
            logger.warning(
                "redis package not installed. Install with: pip install redis"
            )
            return False
        
        for attempt in range(self._max_reconnect_attempts):
            try:
                self._redis = aioredis.from_url(
                    self._redis_url,
                    encoding="utf-8",
                    decode_responses=True,
                )
                # Test connection
                await self._redis.ping()
                self._connected = True
                logger.info(f"Connected to Redis at {self._redis_url}")
                return True
                
            except Exception as e:
                delay = self._reconnect_delay * (2 ** attempt)
                logger.warning(
                    f"Redis connection attempt {attempt + 1} failed: {e}. "
                    f"Retrying in {delay:.1f}s..."
                )
                self._stats["reconnect_count"] += 1
                await asyncio.sleep(delay)
        
        logger.error(
            f"Failed to connect to Redis after {self._max_reconnect_attempts} attempts"
        )
        return False
    
    async def disconnect(self) -> None:
        """Disconnect from Redis server."""
        if self._pubsub:
            await self._pubsub.close()
            self._pubsub = None
        
        if self._redis:
            await self._redis.close()
            self._redis = None
        
        self._connected = False
        self._subscriptions.clear()
        logger.info("Disconnected from Redis")
    
    @property
    def is_connected(self) -> bool:
        """Check if connected to Redis."""
        return self._connected and self._redis is not None
    
    async def __aenter__(self):
        """Async context manager entry."""
        await self.connect()
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit."""
        await self.disconnect()
        return False
    
    # =========================================================================
    # PUBLISHING
    # =========================================================================
    
    async def publish(self, channel: str, data: Union[str, Dict]) -> bool:
        """
        Publish data to a channel.
        
        Args:
            channel: Channel name (e.g., 'news:all')
            data: Data to publish (string or dict)
        
        Returns:
            True if published successfully, False otherwise
        """
        if not self.is_connected:
            logger.warning("Not connected to Redis, cannot publish")
            return False
        
        try:
            if isinstance(data, dict):
                message = json.dumps(data)
            else:
                message = data
            
            await self._redis.publish(channel, message)
            self._stats["messages_published"] += 1
            logger.debug(f"Published to {channel}: {message[:100]}...")
            return True
            
        except Exception as e:
            logger.error(f"Failed to publish to {channel}: {e}")
            self._stats["errors"] += 1
            return False
    
    async def publish_event(self, event: Event, channels: List[str] = None) -> bool:
        """
        Publish an event to one or more channels.
        
        Args:
            event: Event to publish
            channels: List of channels (defaults to news:all)
        
        Returns:
            True if all publishes succeeded
        """
        if channels is None:
            channels = [self.CHANNEL_ALL]
        
        success = True
        for channel in channels:
            if not await self.publish(channel, event.to_json()):
                success = False
        
        return success
    
    async def publish_article(
        self,
        article: Dict[str, Any],
        is_breaking: bool = False,
        topics: List[str] = None,
    ) -> bool:
        """
        Publish a new article discovery event.
        
        Args:
            article: Article data dictionary
            is_breaking: Is this breaking news?
            topics: Optional list of topics for topic-specific channels
        
        Returns:
            True if published successfully
        """
        event = Event(
            type=EventType.ARTICLE_NEW,
            payload=article,
            timestamp=datetime.now(UTC).isoformat(),
        )
        
        # Determine channels
        channels = [self.CHANNEL_ALL]
        
        if is_breaking:
            channels.append(self.CHANNEL_BREAKING)
        
        if topics:
            for topic in topics:
                channels.append(self.CHANNEL_TOPIC.format(topic=topic.lower()))
        
        # Add source channel
        source = article.get("source", "")
        if source:
            channels.append(self.CHANNEL_SOURCE.format(source=source))
        
        return await self.publish_event(event, channels)
    
    # =========================================================================
    # SUBSCRIBING
    # =========================================================================
    
    async def subscribe(
        self,
        *channels: str,
        use_patterns: bool = False,
    ) -> AsyncIterator[Dict[str, Any]]:
        """
        Subscribe to one or more channels and yield messages.
        
        Args:
            *channels: Channel names or patterns (if use_patterns=True)
            use_patterns: If True, treat channels as patterns (e.g., 'news:*')
        
        Yields:
            Parsed message dictionaries
        
        Example:
            async for msg in event_bus.subscribe('news:all'):
                print(msg)
            
            # Pattern subscription
            async for msg in event_bus.subscribe('news:*', use_patterns=True):
                print(msg)
        """
        if not self.is_connected:
            await self.connect()
            if not self.is_connected:
                logger.error("Cannot subscribe: not connected to Redis")
                return
        
        try:
            self._pubsub = self._redis.pubsub()
            
            if use_patterns:
                await self._pubsub.psubscribe(*channels)
            else:
                await self._pubsub.subscribe(*channels)
            
            self._subscriptions.update(channels)
            logger.info(f"Subscribed to channels: {channels}")
            
            async for message in self._pubsub.listen():
                if message["type"] in ("message", "pmessage"):
                    self._stats["messages_received"] += 1
                    
                    try:
                        data = json.loads(message["data"])
                        yield data
                    except json.JSONDecodeError:
                        yield {"raw": message["data"]}
                        
        except asyncio.CancelledError:
            logger.info("Subscription cancelled")
            raise
        except Exception as e:
            logger.error(f"Subscription error: {e}")
            self._stats["errors"] += 1
        finally:
            if self._pubsub:
                await self._pubsub.unsubscribe(*channels)
                self._subscriptions.difference_update(channels)
    
    async def subscribe_with_callback(
        self,
        channel: str,
        callback: Callable[[Dict[str, Any]], None],
        use_pattern: bool = False,
    ) -> asyncio.Task:
        """
        Subscribe to a channel with a callback function.
        
        Args:
            channel: Channel name or pattern
            callback: Function to call for each message
            use_pattern: Treat channel as pattern
        
        Returns:
            Background task that can be cancelled
        """
        async def _listen():
            async for message in self.subscribe(channel, use_patterns=use_pattern):
                try:
                    callback(message)
                except Exception as e:
                    logger.error(f"Callback error: {e}")
        
        task = asyncio.create_task(_listen())
        return task
    
    # =========================================================================
    # LOCAL EVENT HANDLING (Fallback when Redis unavailable)
    # =========================================================================
    
    def add_local_listener(
        self,
        event_type: EventType,
        callback: Callable[[Event], None],
    ) -> None:
        """
        Add a local event listener (used when Redis is unavailable).
        
        Args:
            event_type: Type of event to listen for
            callback: Function to call when event occurs
        """
        if event_type.value not in self._listeners:
            self._listeners[event_type.value] = []
        self._listeners[event_type.value].append(callback)
    
    def emit_local(self, event: Event) -> None:
        """
        Emit event to local listeners.
        
        Used as fallback when Redis is unavailable.
        """
        listeners = self._listeners.get(event.type.value, [])
        for callback in listeners:
            try:
                callback(event)
            except Exception as e:
                logger.error(f"Local listener error: {e}")
    
    # =========================================================================
    # UTILITIES
    # =========================================================================
    
    def get_stats(self) -> Dict[str, Any]:
        """Get event bus statistics."""
        return {
            **self._stats,
            "connected": self.is_connected,
            "active_subscriptions": list(self._subscriptions),
        }
    
    async def health_check(self) -> bool:
        """Check Redis connection health."""
        if not self.is_connected:
            return False
        
        try:
            await self._redis.ping()
            return True
        except Exception:
            return False


# =============================================================================
# FALLBACK EVENT BUS (No Redis Required)
# =============================================================================

class LocalEventBus:
    """
    In-memory event bus for when Redis is not available.
    
    Provides the same interface as RedisEventBus but using
    asyncio queues for local process communication.
    """
    
    def __init__(self):
        self._queues: Dict[str, List[asyncio.Queue]] = {}
        self._connected = True
        self._stats = {
            "messages_published": 0,
            "messages_received": 0,
        }
    
    @property
    def is_connected(self) -> bool:
        return self._connected
    
    async def connect(self) -> bool:
        logger.info("Using local in-memory event bus (no Redis)")
        return True
    
    async def disconnect(self) -> None:
        self._queues.clear()
    
    async def __aenter__(self):
        return self
    
    async def __aexit__(self, *args):
        await self.disconnect()
    
    async def publish(self, channel: str, data: Union[str, Dict]) -> bool:
        """Publish to local queues."""
        message = data if isinstance(data, dict) else json.loads(data)
        
        for queue in self._queues.get(channel, []):
            await queue.put(message)
        
        # Also publish to pattern-matched queues
        for pattern, queues in self._queues.items():
            if pattern.endswith("*"):
                prefix = pattern[:-1]
                if channel.startswith(prefix):
                    for queue in queues:
                        await queue.put(message)
        
        self._stats["messages_published"] += 1
        return True
    
    async def publish_article(
        self,
        article: Dict[str, Any],
        is_breaking: bool = False,
        topics: List[str] = None,
    ) -> bool:
        return await self.publish("news:all", article)
    
    async def subscribe(
        self,
        *channels: str,
        use_patterns: bool = False,
    ) -> AsyncIterator[Dict[str, Any]]:
        """Subscribe using local queues."""
        queue: asyncio.Queue = asyncio.Queue()
        
        for channel in channels:
            if channel not in self._queues:
                self._queues[channel] = []
            self._queues[channel].append(queue)
        
        try:
            while True:
                message = await queue.get()
                self._stats["messages_received"] += 1
                yield message
        finally:
            for channel in channels:
                if channel in self._queues:
                    self._queues[channel].remove(queue)
    
    def get_stats(self) -> Dict[str, Any]:
        return {**self._stats, "connected": True, "type": "local"}


# =============================================================================
# FACTORY
# =============================================================================

async def create_event_bus(
    redis_url: str = None,
    fallback_to_local: bool = True,
) -> Union[RedisEventBus, LocalEventBus]:
    """
    Create an event bus, falling back to local if Redis unavailable.
    
    Args:
        redis_url: Redis URL (uses settings if None)
        fallback_to_local: Use LocalEventBus if Redis fails
    
    Returns:
        Connected event bus instance
    """
    # Try to import settings
    try:
        from config.settings import REDIS_URL
        redis_url = redis_url or REDIS_URL
    except ImportError:
        redis_url = redis_url or "redis://localhost:6379/0"
    
    # Try Redis first
    redis_bus = RedisEventBus(redis_url)
    if await redis_bus.connect():
        return redis_bus
    
    # Fallback to local
    if fallback_to_local:
        logger.warning("Redis unavailable, using local event bus")
        return LocalEventBus()
    
    raise ConnectionError("Failed to connect to Redis and fallback disabled")
