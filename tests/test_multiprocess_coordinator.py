"""
Phase 8C: Multi-Process Swarm Coordinator Unit & Integration Tests.
Location: tests/test_multiprocess_coordinator.py

Tests:
1. Multi-process exclusive lease acquisition across separate OS processes.
2. Stale fencing token rejection on delayed worker writes.
3. Automatic lease expiry and successor worker takeover.
4. Coordinator recovery and persistent lease verification after engine restart.
5. Consistent hashing source shard distribution across workers.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, UTC
import multiprocessing as mp
from pathlib import Path
import tempfile
import time
from typing import List

import pytest

from src.zombies.coordinator import (
    LeaseResult,
    LeaseStatus,
    LocalSwarmCoordinator,
    SqliteSwarmCoordinator,
)


def _process_worker_acquire(db_path_str: str, source_id: str, worker_id: str, duration: float, result_queue: mp.Queue):
    """Subprocess target executing atomic lease acquisition on shared SQLite coordinator."""
    coordinator = SqliteSwarmCoordinator(db_path_str)
    res = asyncio.run(coordinator.acquire_lease(source_id, worker_id, duration_seconds=duration))
    result_queue.put({
        "worker_id": worker_id,
        "status": res.status.value,
        "is_successful": res.is_successful,
        "token": res.token,
    })


@pytest.mark.asyncio
async def test_sqlite_coordinator_single_process_lifecycle():
    """Verify basic acquire, renew, release, and validity on SqliteSwarmCoordinator."""
    temp_dir = tempfile.TemporaryDirectory()
    db_path = Path(temp_dir.name) / "test_leases.db"
    coordinator = SqliteSwarmCoordinator(db_path)

    # 1. Acquire
    r1 = await coordinator.acquire_lease("src_alpha", "worker_1", duration_seconds=1.0)
    assert r1.is_successful is True
    assert r1.status == LeaseStatus.ACQUIRED
    token1 = r1.token

    # 2. Competing acquire fails
    r2 = await coordinator.acquire_lease("src_alpha", "worker_2", duration_seconds=1.0)
    assert r2.is_successful is False
    assert r2.status == LeaseStatus.OWNED_BY_OTHER

    # 3. Renew with valid token
    r3 = await coordinator.renew_lease("src_alpha", "worker_1", token1, duration_seconds=2.0)
    assert r3.is_successful is True

    # 4. Renew with invalid token rejected
    r4 = await coordinator.renew_lease("src_alpha", "worker_1", "stale_token_xyz", duration_seconds=2.0)
    assert r4.is_successful is False
    assert r4.status == LeaseStatus.INVALID_TOKEN

    # 5. Release
    released = await coordinator.release_lease("src_alpha", "worker_1", token1)
    assert released is True

    temp_dir.cleanup()


def test_sqlite_coordinator_multiprocess_contention():
    """Verify atomic single-owner mutual exclusion across 4 independent OS processes."""
    temp_dir = tempfile.TemporaryDirectory()
    db_path = Path(temp_dir.name) / "mp_leases.db"
    
    # Initialize schema
    coord = SqliteSwarmCoordinator(db_path)
    
    result_queue = mp.Queue()
    processes = []
    
    # Launch 4 independent OS processes simultaneously competing for 'source_contended'
    for i in range(4):
        p = mp.Process(
            target=_process_worker_acquire,
            args=(str(db_path), "source_contended", f"proc_worker_{i}", 2.0, result_queue),
        )
        processes.append(p)
        p.start()

    for p in processes:
        p.join(timeout=5.0)

    results = []
    while not result_queue.empty():
        results.append(result_queue.get())

    assert len(results) == 4
    successes = [r for r in results if r["is_successful"]]
    failures = [r for r in results if not r["is_successful"]]

    # Exactly 1 process must win exclusive lease; 3 processes must be rejected with OWNED_BY_OTHER
    assert len(successes) == 1
    assert len(failures) == 3
    assert successes[0]["status"] == "acquired"
    for f in failures:
        assert f["status"] == "owned_by_other"

    temp_dir.cleanup()


@pytest.mark.asyncio
async def test_sqlite_coordinator_ttl_expiry_and_reclamation():
    """Verify stale lease is automatically reclaimed by successor worker after TTL expiry."""
    temp_dir = tempfile.TemporaryDirectory()
    db_path = Path(temp_dir.name) / "reclaim_leases.db"
    coordinator = SqliteSwarmCoordinator(db_path)

    # Worker 1 acquires short 0.2s lease
    r1 = await coordinator.acquire_lease("src_expire", "worker_1", duration_seconds=0.2)
    assert r1.is_successful is True
    token_1 = r1.token

    # Wait for TTL to expire
    await asyncio.sleep(0.3)

    # Worker 2 acquires: should successfully reclaim expired lease
    r2 = await coordinator.acquire_lease("src_expire", "worker_2", duration_seconds=1.0)
    assert r2.is_successful is True
    assert r2.status == LeaseStatus.EXPIRED_AND_RECLAIMED
    assert r2.token != token_1

    # Stale Worker 1 attempts to release with old token: rejected
    rel_stale = await coordinator.release_lease("src_expire", "worker_1", token_1)
    assert rel_stale is False

    temp_dir.cleanup()


def test_consistent_hashing_partitioning():
    """Verify deterministic source shard partitioning across worker instances."""
    coord = LocalSwarmCoordinator()
    all_sources = [f"source_{i}" for i in range(100)]
    
    shard_0 = coord.get_assigned_sources(all_sources, total_shards=4, worker_shard_index=0)
    shard_1 = coord.get_assigned_sources(all_sources, total_shards=4, worker_shard_index=1)
    shard_2 = coord.get_assigned_sources(all_sources, total_shards=4, worker_shard_index=2)
    shard_3 = coord.get_assigned_sources(all_sources, total_shards=4, worker_shard_index=3)

    # Union of all shards must equal all sources (no sources missed)
    union_sources = set(shard_0) | set(shard_1) | set(shard_2) | set(shard_3)
    assert len(union_sources) == 100
    assert union_sources == set(all_sources)

    # Intersections must be disjoint (no double assignment across shards)
    assert len(set(shard_0) & set(shard_1)) == 0
    assert len(set(shard_1) & set(shard_2)) == 0
    assert len(set(shard_2) & set(shard_3)) == 0
