"""
Application-Scoped Asynchronous Publication Bus.
Location: src/engine/publication_bus.py

Decouples ingestion and pipeline processing (Layer 4) from delivery surfaces (Layer 5).
Features:
- Application-scoped lifecycle (start, stop with graceful drain)
- Bounded subscriber queues (default maxsize=1000)
- Non-blocking publishing with DROP_OLDEST policy on overflow
- Channel-based filtering (SSE, Telegram, WebSocket, FeedBuffer)
- Consumer idempotency tracking via PublicationEvent.idempotency_key
"""

from __future__ import annotations

import asyncio
from collections import OrderedDict
from dataclasses import dataclass, field
from datetime import datetime, UTC
import logging
from typing import Dict, List, Optional, Set, Tuple
from uuid import uuid4

from ..domain.enums import PublicationChannel, PublicationEventType, PublicationPriority
from ..domain.models import PublicationEvent

logger = logging.getLogger(__name__)


@dataclass
class Subscription:
    """Represents an active subscriber queue and its channel filter."""
    subscriber_id: str
    channels: Set[PublicationChannel]
    queue: asyncio.Queue[Optional[PublicationEvent]]
    dropped_count: int = 0
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))


class PublicationBus:
    """
    Asynchronous event bus for domain publication events.
    
    Provides bounded fan-out dispatch to delivery surfaces with DROP_OLDEST
    backpressure mitigation and graceful shutdown.
    """

    def __init__(self, max_idempotency_cache: int = 5000):
        self._subscriptions: Dict[str, Subscription] = {}
        self._lock: Optional[asyncio.Lock] = None
        self._running: bool = False
        self._idempotency_cache: OrderedDict[str, float] = OrderedDict()
        self._max_idempotency_cache = max_idempotency_cache

    def _get_lock(self) -> asyncio.Lock:
        """Lazy initialization of asyncio.Lock within the active event loop."""
        if self._lock is None:
            self._lock = asyncio.Lock()
        return self._lock

    @property
    def is_running(self) -> bool:
        return self._running

    @property
    def subscriber_count(self) -> int:
        return len(self._subscriptions)

    async def start(self) -> None:
        """Start the publication bus."""
        if self._running:
            return
        self._running = True
        logger.info("PublicationBus started.")

    async def stop(self, drain_timeout: float = 5.0) -> None:
        """
        Gracefully stop the bus, sending sentinels and waiting for queues to drain.
        """
        if not self._running:
            return

        self._running = False
        logger.info(f"PublicationBus stopping (drain timeout: {drain_timeout}s)...")

        # Inject None sentinel into all subscriber queues
        async with self._get_lock():
            for sub in self._subscriptions.values():
                try:
                    sub.queue.put_nowait(None)
                except asyncio.QueueFull:
                    try:
                        sub.queue.get_nowait()
                        sub.queue.put_nowait(None)
                    except Exception:
                        pass

        # Allow subscribers up to drain_timeout seconds to empty their queues
        start_time = asyncio.get_running_loop().time()
        while any(not sub.queue.empty() for sub in self._subscriptions.values()):
            elapsed = asyncio.get_running_loop().time() - start_time
            if elapsed >= drain_timeout:
                logger.warning(f"PublicationBus drain timeout ({drain_timeout}s) exceeded. Forcing shutdown.")
                break
            await asyncio.sleep(0.05)

        async with self._get_lock():
            self._subscriptions.clear()
            self._idempotency_cache.clear()

        logger.info("PublicationBus stopped cleanly.")

    async def subscribe(
        self,
        subscriber_id: Optional[str] = None,
        channels: Optional[Tuple[PublicationChannel, ...]] = None,
        maxsize: int = 1000,
    ) -> Tuple[str, asyncio.Queue[Optional[PublicationEvent]]]:
        """
        Register a new subscriber with dedicated bounded queue and channel filter.
        
        Returns:
            (subscriber_id, queue)
        """
        sub_id = subscriber_id or f"sub_{uuid4().hex[:12]}"
        channel_set = set(channels) if channels else set(PublicationChannel)
        queue: asyncio.Queue[Optional[PublicationEvent]] = asyncio.Queue(maxsize=maxsize)

        sub = Subscription(
            subscriber_id=sub_id,
            channels=channel_set,
            queue=queue,
        )

        async with self._get_lock():
            self._subscriptions[sub_id] = sub

        logger.debug(f"Subscriber '{sub_id}' registered for channels: {[c.value for c in channel_set]}")
        return sub_id, queue

    async def unsubscribe(self, subscriber_id: str) -> bool:
        """Unregister a subscriber and release its queue."""
        async with self._get_lock():
            if subscriber_id in self._subscriptions:
                del self._subscriptions[subscriber_id]
                logger.debug(f"Subscriber '{subscriber_id}' unsubscribed.")
                return True
            return False

    def is_duplicate(self, idempotency_key: str) -> bool:
        """Check if an idempotency_key has already been processed recently."""
        if not idempotency_key:
            return False
        if idempotency_key in self._idempotency_cache:
            return True
        # Track new key in LRU cache
        self._idempotency_cache[idempotency_key] = asyncio.get_running_loop().time() if self._running else 0.0
        if len(self._idempotency_cache) > self._max_idempotency_cache:
            self._idempotency_cache.popitem(last=False)
        return False

    async def publish(self, event: PublicationEvent) -> int:
        """
        Publish an event to all matching subscribers.
        
        Non-blocking dispatch with DROP_OLDEST overflow policy.
        Returns the number of subscribers that received the event.
        """
        if not self._running:
            logger.warning(f"PublicationBus is not running. Dropping event '{event.event_id}'.")
            return 0

        # Idempotency check
        if event.idempotency_key and self.is_duplicate(event.idempotency_key):
            logger.debug(f"Duplicate event '{event.idempotency_key}' dropped by PublicationBus idempotency filter.")
            return 0

        target_channels = set(event.channels)
        dispatched_count = 0

        async with self._get_lock():
            subscribers = list(self._subscriptions.values())

        for sub in subscribers:
            # Check if subscriber is interested in any target channel
            if not (sub.channels & target_channels):
                continue

            try:
                sub.queue.put_nowait(event)
                dispatched_count += 1
            except asyncio.QueueFull:
                # DROP_OLDEST policy: Evict oldest pending event to prevent head-of-line blocking
                try:
                    sub.queue.get_nowait()
                    sub.queue.put_nowait(event)
                    sub.dropped_count += 1
                    dispatched_count += 1
                    if sub.dropped_count % 50 == 0:
                        logger.warning(
                            f"Subscriber '{sub.subscriber_id}' is slow! "
                            f"Dropped {sub.dropped_count} oldest events due to queue overflow."
                        )
                except Exception as e:
                    logger.error(f"Error applying DROP_OLDEST to subscriber '{sub.subscriber_id}': {e}")

        return dispatched_count


# =============================================================================
# ACCESSOR FUNCTIONS (APPLICATION-SCOPED SINGLETON)
# =============================================================================

_global_publication_bus: Optional[PublicationBus] = None


def get_publication_bus() -> PublicationBus:
    """Get or lazily instantiate the shared application PublicationBus."""
    global _global_publication_bus
    if _global_publication_bus is None:
        _global_publication_bus = PublicationBus()
    return _global_publication_bus


def set_publication_bus(bus: PublicationBus) -> None:
    """Inject a custom PublicationBus instance (e.g. for testing)."""
    global _global_publication_bus
    _global_publication_bus = bus


def reset_publication_bus() -> None:
    """Reset global bus singleton instance."""
    global _global_publication_bus
    _global_publication_bus = None
