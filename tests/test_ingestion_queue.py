"""
Unit Tests for StarvationSafeIngestionQueue.
Location: tests/test_ingestion_queue.py
"""

import asyncio
from datetime import datetime, UTC
import unittest

from src.domain.enums import SourceTier, ZombieSpecies
from src.domain.models import SourceObservation
from src.queue.priority_queue import (
    IngestionPriority,
    QueueMetrics,
    StarvationSafeIngestionQueue,
)


class TestStarvationSafeIngestionQueue(unittest.IsolatedAsyncioTestCase):
    """Test cases for StarvationSafeIngestionQueue."""

    def _make_obs(self, title: str) -> SourceObservation:
        return SourceObservation.create(
            source_id="test_src",
            source_name="Test Source",
            source_tier=SourceTier.TIER_1,
            zombie_species=ZombieSpecies.RSS,
            url=f"https://example.com/news/{title.lower().replace(' ', '-')}",
            title=title,
        )

    async def test_push_and_pop_critical_precedence(self):
        queue = StarvationSafeIngestionQueue(capacity=10)

        obs_normal = self._make_obs("Normal News")
        obs_critical = self._make_obs("Breaking Alert")

        await queue.push(obs_normal, priority=IngestionPriority.NORMAL)
        await queue.push(obs_critical, priority=IngestionPriority.CRITICAL)

        # Critical must be popped first even though enqueued second
        first = await queue.pop()
        self.assertEqual(first.title, "Breaking Alert")

        second = await queue.pop()
        self.assertEqual(second.title, "Normal News")

    async def test_starvation_prevention_aging(self):
        # Aging rate = 10.0 per sec -> in 0.5s, LOW (3) effective score becomes 3 - 5 = -2, beating fresh NORMAL (2)
        queue = StarvationSafeIngestionQueue(capacity=10, aging_rate_per_sec=10.0)

        obs_low = self._make_obs("Low Priority Old Item")
        await queue.push(obs_low, priority=IngestionPriority.LOW)

        # Simulate wait time
        await asyncio.sleep(0.4)

        obs_fresh_high = self._make_obs("Fresh High Priority Item")
        await queue.push(obs_fresh_high, priority=IngestionPriority.HIGH)

        # Aged low item should now outrank or compete strongly
        first = await queue.pop()
        self.assertEqual(first.title, "Low Priority Old Item")

    async def test_capacity_drop(self):
        queue = StarvationSafeIngestionQueue(capacity=2)
        obs1 = self._make_obs("Item 1")
        obs2 = self._make_obs("Item 2")
        obs3 = self._make_obs("Item 3")

        self.assertTrue(await queue.push(obs1))
        self.assertTrue(await queue.push(obs2))
        # Third push should be dropped
        self.assertFalse(await queue.push(obs3))

        metrics = queue.get_metrics()
        self.assertEqual(metrics.items_dropped, 1)
        self.assertEqual(metrics.depth, 2)

    async def test_hysteresis_backpressure_transitions(self):
        state_changes = []
        queue = StarvationSafeIngestionQueue(
            capacity=10,
            high_watermark=0.80, # 8 items
            low_watermark=0.40,  # 4 items
            on_backpressure_change=lambda is_bp: state_changes.append(is_bp),
        )

        for i in range(8):
            await queue.push(self._make_obs(f"Item {i}"))

        self.assertTrue(queue.is_in_backpressure)
        self.assertIn(True, state_changes)

        # Pop 2 items (depth = 6, still >= 40%) -> still in backpressure
        await queue.pop()
        await queue.pop()
        self.assertTrue(queue.is_in_backpressure)

        # Pop 3 more items (depth = 3, <= 40%) -> exits backpressure
        await queue.pop()
        await queue.pop()
        await queue.pop()
        self.assertFalse(queue.is_in_backpressure)
        self.assertEqual(state_changes[-1], False)
