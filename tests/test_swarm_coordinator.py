"""
Unit Tests for Swarm Coordinator and Partitioning.
Location: tests/test_swarm_coordinator.py
"""

import asyncio
import unittest

import pytest

from src.zombies.coordinator import (
    LeaseResult,
    LeaseStatus,
    LocalSwarmCoordinator,
    SwarmCoordinatorProtocol,
)


class TestLocalSwarmCoordinator(unittest.IsolatedAsyncioTestCase):
    """Test cases for LocalSwarmCoordinator."""

    async def asyncSetUp(self):
        self.coordinator = LocalSwarmCoordinator()

    async def test_deterministic_sharding(self):
        all_sources = [f"source_{i}" for i in range(100)]
        shard_0 = self.coordinator.get_assigned_sources(all_sources, total_shards=4, worker_shard_index=0)
        shard_1 = self.coordinator.get_assigned_sources(all_sources, total_shards=4, worker_shard_index=1)
        shard_2 = self.coordinator.get_assigned_sources(all_sources, total_shards=4, worker_shard_index=2)
        shard_3 = self.coordinator.get_assigned_sources(all_sources, total_shards=4, worker_shard_index=3)

        # No overlap
        all_assigned = set(shard_0) | set(shard_1) | set(shard_2) | set(shard_3)
        self.assertEqual(len(all_assigned), 100)
        self.assertEqual(len(set(shard_0) & set(shard_1)), 0)

    async def test_acquire_lease_success(self):
        res = await self.coordinator.acquire_lease("techcrunch", "worker_1", duration_seconds=60)
        self.assertEqual(res.status, LeaseStatus.ACQUIRED)
        self.assertEqual(res.lease_owner, "worker_1")
        self.assertIsNotNone(res.token)
        self.assertTrue(res.is_successful)

    async def test_acquire_already_owned_by_same_worker(self):
        res1 = await self.coordinator.acquire_lease("arstechnica", "worker_1", duration_seconds=60)
        res2 = await self.coordinator.acquire_lease("arstechnica", "worker_1", duration_seconds=60)
        self.assertEqual(res2.status, LeaseStatus.ALREADY_OWNED)
        self.assertEqual(res1.token, res2.token)

    async def test_acquire_blocked_when_owned_by_another_worker(self):
        await self.coordinator.acquire_lease("theverge", "worker_1", duration_seconds=60)
        res2 = await self.coordinator.acquire_lease("theverge", "worker_2", duration_seconds=60)
        self.assertEqual(res2.status, LeaseStatus.OWNED_BY_OTHER)
        self.assertIsNone(res2.token)
        self.assertFalse(res2.is_successful)

    async def test_renew_lease_with_valid_token(self):
        acq = await self.coordinator.acquire_lease("hackernews", "worker_1", duration_seconds=10)
        renew = await self.coordinator.renew_lease("hackernews", "worker_1", acq.token, duration_seconds=60)
        self.assertEqual(renew.status, LeaseStatus.ACQUIRED)
        self.assertEqual(renew.token, acq.token)

    async def test_renew_lease_fails_with_invalid_token(self):
        await self.coordinator.acquire_lease("wired", "worker_1", duration_seconds=10)
        renew = await self.coordinator.renew_lease("wired", "worker_1", "invalid-token-123", duration_seconds=60)
        self.assertEqual(renew.status, LeaseStatus.INVALID_TOKEN)

    async def test_release_lease(self):
        acq = await self.coordinator.acquire_lease("venturebeat", "worker_1", duration_seconds=60)
        released = await self.coordinator.release_lease("venturebeat", "worker_1", acq.token)
        self.assertTrue(released)

        # Other worker can now acquire
        acq2 = await self.coordinator.acquire_lease("venturebeat", "worker_2", duration_seconds=60)
        self.assertEqual(acq2.status, LeaseStatus.ACQUIRED)
        self.assertEqual(acq2.lease_owner, "worker_2")

    async def test_reclaim_expired_lease(self):
        # Acquire with 0 duration (immediately expired)
        await self.coordinator.acquire_lease("engadget", "worker_1", duration_seconds=-1)
        res = await self.coordinator.acquire_lease("engadget", "worker_2", duration_seconds=60)
        self.assertEqual(res.status, LeaseStatus.EXPIRED_AND_RECLAIMED)
        self.assertEqual(res.lease_owner, "worker_2")
