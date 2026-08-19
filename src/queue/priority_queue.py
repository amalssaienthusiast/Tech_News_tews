"""
Starvation-Safe Prioritized Ingestion Queue with Hysteresis Backpressure.
Location: src/queue/priority_queue.py
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import datetime, UTC, timedelta
from enum import IntEnum
import heapq
import logging
import time
from typing import Any, Callable, Dict, List, Optional, Tuple

from src.domain.models import SourceObservation

logger = logging.getLogger(__name__)


class IngestionPriority(IntEnum):
    """Priority tiers for ingestion dispatching."""
    CRITICAL = 0  # Breaking alerts, WebSub push webhooks
    HIGH = 1      # Tier-1 fast feeds, major tech news
    NORMAL = 2    # Standard RSS / blog feeds
    LOW = 3       # Deep crawl, discovery validation


@dataclass(order=True)
class PrioritizedItem:
    """Heap wrapper computing dynamic effective priority with anti-starvation aging."""
    sort_key: float
    sequence: int
    priority: IngestionPriority = field(compare=False)
    enqueued_at: float = field(compare=False)
    observation: SourceObservation = field(compare=False)


@dataclass(frozen=True, slots=True)
class QueueMetrics:
    """Snapshot of ingestion queue health and utilization."""
    depth: int
    capacity: int
    utilization_ratio: float
    is_in_backpressure: bool
    items_enqueued: int
    items_dequeued: int
    items_dropped: int
    avg_wait_ms: float


class StarvationSafeIngestionQueue:
    """
    Thread/async safe priority queue with:
    - Aging-based dynamic priority computation (guarantees LOW cannot starve).
    - Hysteresis backpressure (Enters at >= 80%, Exits at <= 60%).
    - Comprehensive metric telemetry.
    """

    def __init__(
        self,
        capacity: int = 5000,
        high_watermark: float = 0.80,
        low_watermark: float = 0.60,
        aging_rate_per_sec: float = 0.05,
        on_backpressure_change: Optional[Callable[[bool], Any]] = None,
    ):
        if capacity <= 0:
            raise ValueError("Queue capacity must be positive")
        if not (0.0 < low_watermark < high_watermark <= 1.0):
            raise ValueError("Watermarks must satisfy: 0.0 < low_watermark < high_watermark <= 1.0")

        self.capacity = capacity
        self.high_watermark = high_watermark
        self.low_watermark = low_watermark
        self.aging_rate = aging_rate_per_sec
        self.on_backpressure_change = on_backpressure_change

        self._heap: List[PrioritizedItem] = []
        self._seq = 0
        self._lock = asyncio.Lock()
        self._has_items = asyncio.Event()

        # State & Metrics
        self._in_backpressure = False
        self._items_enqueued = 0
        self._items_dequeued = 0
        self._items_dropped = 0
        self._total_wait_seconds = 0.0

    @property
    def depth(self) -> int:
        return len(self._heap)

    @property
    def is_in_backpressure(self) -> bool:
        return self._in_backpressure

    def _check_backpressure_transitions(self) -> None:
        """Evaluate hysteresis watermarks."""
        utilization = len(self._heap) / self.capacity
        if not self._in_backpressure and utilization >= self.high_watermark:
            self._in_backpressure = True
            logger.warning("🚨 Ingestion Queue entered BACKPRESSURE state (utilization=%.1f%%)", utilization * 100)
            try:
                from src.observability.metrics import get_metrics_registry
                get_metrics_registry().queue_backpressure_active.set(1.0)
            except Exception:
                pass

            if self.on_backpressure_change:
                try:
                    self.on_backpressure_change(True)
                except Exception as e:
                    logger.error("Error in on_backpressure_change callback: %s", e)

        elif self._in_backpressure and utilization <= self.low_watermark:
            self._in_backpressure = False
            logger.info("🟢 Ingestion Queue exited BACKPRESSURE state (utilization=%.1f%%)", utilization * 100)
            try:
                from src.observability.metrics import get_metrics_registry
                get_metrics_registry().queue_backpressure_active.set(0.0)
            except Exception:
                pass

            if self.on_backpressure_change:
                try:
                    self.on_backpressure_change(False)
                except Exception as e:
                    logger.error("Error in on_backpressure_change callback: %s", e)

    async def push(
        self,
        observation: SourceObservation,
        priority: IngestionPriority = IngestionPriority.NORMAL,
    ) -> bool:
        """
        Push observation into queue. If full, drops item and increments drop count.
        Returns True if enqueued, False if dropped due to capacity.
        """
        async with self._lock:
            if len(self._heap) >= self.capacity:
                self._items_dropped += 1
                logger.warning("Ingestion queue capacity (%d) reached; dropped observation %s", self.capacity, observation.id)
                try:
                    from src.observability.metrics import get_metrics_registry
                    get_metrics_registry().queue_items_dropped_total.inc(reason="capacity_overflow")
                except Exception:
                    pass
                return False

            now = time.monotonic()
            self._seq += 1
            # Base sort key = priority value (0=CRITICAL, 1=HIGH, 2=NORMAL, 3=LOW)
            item = PrioritizedItem(
                sort_key=float(priority),
                sequence=self._seq,
                priority=priority,
                enqueued_at=now,
                observation=observation,
            )
            heapq.heappush(self._heap, item)
            self._items_enqueued += 1
            try:
                from src.observability.metrics import get_metrics_registry
                m = get_metrics_registry()
                m.queue_depth.set(len(self._heap))
                m.queue_items_enqueued_total.inc(priority=priority.name)
            except Exception:
                pass

            self._check_backpressure_transitions()
            self._has_items.set()
            return True

    async def pop(self) -> SourceObservation:
        """
        Pop the observation with the lowest effective priority score (accounting for aging).
        Blocks until an item is available.
        """
        while True:
            await self._has_items.wait()
            async with self._lock:
                if not self._heap:
                    self._has_items.clear()
                    continue

                now = time.monotonic()

                # Recompute effective priority with aging bonus:
                # effective_priority = base_priority - (wait_time * aging_rate)
                # Find the item with minimal effective priority score
                best_idx = 0
                best_effective_score = float("inf")

                for i, item in enumerate(self._heap):
                    wait_time = max(0.0, now - item.enqueued_at)
                    effective_score = float(item.priority) - (wait_time * self.aging_rate)
                    if effective_score < best_effective_score:
                        best_effective_score = effective_score
                        best_idx = i

                # Extract best item
                item = self._heap.pop(best_idx)
                heapq.heapify(self._heap)

                wait_duration = max(0.0, now - item.enqueued_at)
                self._items_dequeued += 1
                self._total_wait_seconds += wait_duration

                try:
                    from src.observability.metrics import get_metrics_registry
                    m = get_metrics_registry()
                    m.queue_depth.set(len(self._heap))
                    m.queue_avg_wait_seconds.set(self._total_wait_seconds / max(1, self._items_dequeued))
                except Exception:
                    pass

                self._check_backpressure_transitions()
                if not self._heap:
                    self._has_items.clear()

                return item.observation

    async def try_pop(self) -> Optional[SourceObservation]:
        """Non-blocking pop. Returns None if empty."""
        async with self._lock:
            if not self._heap:
                return None

            now = time.monotonic()
            best_idx = 0
            best_effective_score = float("inf")

            for i, item in enumerate(self._heap):
                wait_time = max(0.0, now - item.enqueued_at)
                effective_score = float(item.priority) - (wait_time * self.aging_rate)
                if effective_score < best_effective_score:
                    best_effective_score = effective_score
                    best_idx = i

            item = self._heap.pop(best_idx)
            heapq.heapify(self._heap)

            self._items_dequeued += 1
            wait_sec = max(0.0, now - item.enqueued_at)
            self._total_wait_seconds += wait_sec

            if not self._heap:
                self._has_items.clear()

            self._check_backpressure_transitions()
            return item.observation

    def get_metrics(self) -> QueueMetrics:
        """Get snapshot of queue metrics."""
        depth = len(self._heap)
        avg_wait_ms = (
            (self._total_wait_seconds / self._items_dequeued * 1000.0)
            if self._items_dequeued > 0
            else 0.0
        )
        return QueueMetrics(
            depth=depth,
            capacity=self.capacity,
            utilization_ratio=depth / self.capacity if self.capacity > 0 else 0.0,
            is_in_backpressure=self._in_backpressure,
            items_enqueued=self._items_enqueued,
            items_dequeued=self._items_dequeued,
            items_dropped=self._items_dropped,
            avg_wait_ms=avg_wait_ms,
        )
