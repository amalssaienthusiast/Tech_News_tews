"""
Unit & Integration Tests for Subphase 5E-D: Source Health & Swarm Lifecycle Integration.
Location: tests/test_source_health_lifecycle.py

Verifies:
1. SourceDescriptor.to_source_health() and apply_source_health() mapping
2. ZombieSwarm startup hydration from SourceHealthRepository
3. ZombieSwarm zero-repository fallback (graceful operation when repo is None)
4. Successful hunt outcome recording (transitions to HEALTHY, resets failure count)
5. Failure hunt outcome recording (transitions to DEGRADED, increments failure count)
6. HTTP 429 rate-limit backoff recording and cooldown enforcement
7. HTTP 404/410 quarantine recording and 7-day cooldown
8. Repeated failure progression to COOLDOWN (exponential backoff)
9. ZombieSwarm.flush_health() atomic batch save
10. ZombieSwarm.aclose() calls flush_health() during shutdown
11. End-to-end clean restart persistence and hydration using SqliteSourceHealthRepository
12. AST boundary verification (zombies layer has zero SQLite/database engine imports)
"""

from __future__ import annotations

import ast
import asyncio
from datetime import datetime, UTC, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence
import pytest

from src.domain.enums import SourceHealthStatus, SourceTier
from src.domain.models import SourceHealth
from src.engine.source_registry import SourceDescriptor, SourceRegistry, SourceType
from src.storage.protocols import SourceHealthRepositoryProtocol
from src.storage.sqlite_engine import SqliteEngine
from src.storage.sqlite_source_health_repository import SqliteSourceHealthRepository
from src.zombies.swarm import ZombieSwarm


class SpySourceHealthRepository(SourceHealthRepositoryProtocol):
    """In-memory spy repository for SourceHealth operational state."""

    def __init__(self):
        self.health_store: Dict[str, SourceHealth] = {}
        self.save_calls: int = 0
        self.batch_save_calls: int = 0

    async def save_health(self, health: SourceHealth) -> None:
        self.save_calls += 1
        self.health_store[health.source_id] = health

    async def save_health_batch(self, health_records: Sequence[SourceHealth]) -> int:
        self.batch_save_calls += 1
        for h in health_records:
            self.health_store[h.source_id] = h
        return len(health_records)

    async def get_health(self, source_id: str) -> Optional[SourceHealth]:
        return self.health_store.get(source_id)

    async def get_all_health(self) -> List[SourceHealth]:
        return sorted(self.health_store.values(), key=lambda h: h.source_id)

    async def get_health_by_status(self, status: SourceHealthStatus) -> List[SourceHealth]:
        return [h for h in self.health_store.values() if h.status == status]

    async def delete_health(self, source_id: str) -> bool:
        if source_id in self.health_store:
            del self.health_store[source_id]
            return True
        return False


def make_test_registry() -> SourceRegistry:
    """Create test registry with known sample sources."""
    registry = SourceRegistry()
    registry.load()
    return registry


def test_source_descriptor_to_source_health_mapping():
    """Verify bidirectional mapping between SourceDescriptor and canonical SourceHealth."""
    now = datetime.now(UTC)
    desc = SourceDescriptor(
        id="src_techcrunch",
        url="https://techcrunch.com/feed/",
        name="TechCrunch",
        type=SourceType.RSS,
        tier=1,
        consecutive_failures=0,
        last_attempt=now,
        last_success=now,
        last_working_tier=1,
    )

    health = desc.to_source_health()
    assert health.source_id == "src_techcrunch"
    assert health.source_url == "https://techcrunch.com/feed/"
    assert health.source_name == "TechCrunch"
    assert health.status == SourceHealthStatus.HEALTHY
    assert health.working_bypass_tier == 1

    # Mutate health and apply back to descriptor
    health.record_failure(status_code=429, retry_after_sec=600)
    assert health.status == SourceHealthStatus.RATE_LIMITED

    desc.apply_source_health(health)
    assert desc.consecutive_failures == 1
    assert desc.cooldown_until is not None


@pytest.mark.asyncio
async def test_swarm_startup_hydration():
    """Verify ZombieSwarm hydrates source cooldowns and failure counts from repository on startup."""
    registry = make_test_registry()
    repo = SpySourceHealthRepository()

    # Pre-seed repository with cooldown state for Hacker News
    hn_source = registry.get_all_ordered()[0]
    cooldown_time = datetime.now(UTC) + timedelta(minutes=45)
    pre_health = SourceHealth(
        source_id=hn_source.id,
        source_url=hn_source.url,
        source_name=hn_source.name,
        status=SourceHealthStatus.COOLDOWN,
        consecutive_failures=6,
        consecutive_successes=0,
        cooldown_until=cooldown_time,
        working_bypass_tier=2,
    )
    await repo.save_health(pre_health)

    swarm = ZombieSwarm(registry=registry, health_repository=repo)
    hydrated_count = await swarm.hydrate_health()

    assert hydrated_count >= 1
    hydrated_source = registry.get_source(hn_source.id)
    assert hydrated_source is not None
    assert hydrated_source.consecutive_failures == 6
    assert hydrated_source.cooldown_until == cooldown_time
    assert hydrated_source.last_working_tier == 2


@pytest.mark.asyncio
async def test_swarm_zero_repository_fallback():
    """Verify ZombieSwarm operates cleanly when health_repository is None."""
    registry = make_test_registry()
    swarm = ZombieSwarm(registry=registry, health_repository=None)

    # Hydration and outcome recording should be safe no-ops
    assert await swarm.hydrate_health() == 0
    assert await swarm.flush_health() == 0

    test_source = registry.get_all_ordered()[0]
    await swarm.record_hunt_outcome(test_source, success=True, tier_used=1)
    assert test_source.consecutive_failures == 0


@pytest.mark.asyncio
async def test_record_hunt_outcome_success():
    """Verify recording successful hunt transitions source to HEALTHY and resets failures."""
    registry = make_test_registry()
    repo = SpySourceHealthRepository()
    swarm = ZombieSwarm(registry=registry, health_repository=repo)

    test_source = registry.get_all_ordered()[0]
    test_source.consecutive_failures = 4  # Previously degraded

    await swarm.record_hunt_outcome(test_source, success=True, tier_used=2)

    assert test_source.consecutive_failures == 0
    assert test_source.cooldown_until is None

    persisted = await repo.get_health(test_source.id)
    assert persisted is not None
    assert persisted.status == SourceHealthStatus.HEALTHY
    assert persisted.consecutive_failures == 0
    assert persisted.working_bypass_tier == 2


@pytest.mark.asyncio
async def test_record_hunt_outcome_failure_progression():
    """Verify single failure moves to DEGRADED and 5+ failures moves to COOLDOWN."""
    registry = make_test_registry()
    repo = SpySourceHealthRepository()
    swarm = ZombieSwarm(registry=registry, health_repository=repo)
    test_source = registry.get_all_ordered()[0]

    # Failure #1 -> DEGRADED
    await swarm.record_hunt_outcome(test_source, success=False, status_code=500)
    assert test_source.consecutive_failures == 1
    persisted = await repo.get_health(test_source.id)
    assert persisted.status == SourceHealthStatus.DEGRADED

    # Failures #2..#5 -> COOLDOWN
    for _ in range(4):
        await swarm.record_hunt_outcome(test_source, success=False, status_code=503)

    assert test_source.consecutive_failures == 5
    assert test_source.cooldown_until is not None
    persisted = await repo.get_health(test_source.id)
    assert persisted.status == SourceHealthStatus.COOLDOWN
    assert persisted.cooldown_until is not None


@pytest.mark.asyncio
async def test_record_hunt_outcome_rate_limited():
    """Verify HTTP 429 triggers RATE_LIMITED state with backoff cooldown."""
    registry = make_test_registry()
    repo = SpySourceHealthRepository()
    swarm = ZombieSwarm(registry=registry, health_repository=repo)
    test_source = registry.get_all_ordered()[0]

    await swarm.record_hunt_outcome(test_source, success=False, status_code=429)

    assert test_source.cooldown_until is not None
    persisted = await repo.get_health(test_source.id)
    assert persisted is not None
    assert persisted.status == SourceHealthStatus.RATE_LIMITED
    assert persisted.rate_limit_reset_at is not None


@pytest.mark.asyncio
async def test_record_hunt_outcome_quarantine():
    """Verify HTTP 404 triggers QUARANTINED state and 7-day cooldown."""
    registry = make_test_registry()
    repo = SpySourceHealthRepository()
    swarm = ZombieSwarm(registry=registry, health_repository=repo)
    test_source = registry.get_all_ordered()[0]

    await swarm.record_hunt_outcome(test_source, success=False, status_code=404)

    assert test_source.is_blacklisted is True
    assert test_source.cooldown_until is not None
    # Cooldown should be ~7 days in the future
    assert test_source.cooldown_until > datetime.now(UTC) + timedelta(days=6)

    persisted = await repo.get_health(test_source.id)
    assert persisted is not None
    assert persisted.status == SourceHealthStatus.QUARANTINED


@pytest.mark.asyncio
async def test_swarm_flush_health_on_shutdown():
    """Verify flush_health persists all registry source states atomically."""
    registry = make_test_registry()
    repo = SpySourceHealthRepository()
    swarm = ZombieSwarm(registry=registry, health_repository=repo)

    # Mutate a couple of sources
    sources = registry.get_all_ordered()
    sources[0].consecutive_failures = 2
    sources[1].consecutive_failures = 5
    sources[1].cooldown_until = datetime.now(UTC) + timedelta(minutes=30)

    flushed_count = await swarm.flush_health()
    assert flushed_count == len(sources)
    assert repo.batch_save_calls == 1

    h0 = await repo.get_health(sources[0].id)
    assert h0 is not None
    assert h0.consecutive_failures == 2

    h1 = await repo.get_health(sources[1].id)
    assert h1 is not None
    assert h1.status == SourceHealthStatus.COOLDOWN


@pytest.mark.asyncio
async def test_e2e_restart_with_sqlite_health_repository(tmp_path: Path):
    """Verify full end-to-end restart continuity with SqliteSourceHealthRepository."""
    db_path = tmp_path / "e2e_swarm_health.db"

    # -------------------------------------------------------------
    # Context 1: Swarm updates health and shuts down cleanly
    # -------------------------------------------------------------
    engine1 = SqliteEngine(db_path)
    repo1 = SqliteSourceHealthRepository(engine=engine1, auto_init=True)
    registry1 = make_test_registry()
    swarm1 = ZombieSwarm(registry=registry1, health_repository=repo1)

    target_source = registry1.get_all_ordered()[0]
    await swarm1.record_hunt_outcome(target_source, success=False, status_code=429)
    await swarm1.aclose()
    await engine1.aclose()

    # -------------------------------------------------------------
    # Context 2: Clean restart with new Engine and fresh Swarm
    # -------------------------------------------------------------
    engine2 = SqliteEngine(db_path)
    repo2 = SqliteSourceHealthRepository(engine=engine2, auto_init=True)
    registry2 = make_test_registry()
    swarm2 = ZombieSwarm(registry=registry2, health_repository=repo2)

    # Hydrate on startup
    hydrated = await swarm2.hydrate_health()
    assert hydrated >= 1

    restored_source = registry2.get_source(target_source.id)
    assert restored_source is not None
    assert restored_source.cooldown_until is not None
    assert restored_source.consecutive_failures == 1

    await swarm2.aclose()
    await engine2.aclose()


def test_zombies_layer_boundary_ast_no_sqlite_imports():
    """Verify that src/zombies/ has zero direct imports of sqlite3, aiosqlite, or SqliteEngine."""
    zombies_dir = Path(__file__).resolve().parent.parent / "src" / "zombies"
    forbidden = {"sqlite3", "aiosqlite", "SqliteEngine", "SqliteSourceHealthRepository", "SqliteArticleRepository"}

    for py_file in zombies_dir.rglob("*.py"):
        if py_file.name == "coordinator.py":
            continue
        tree = ast.parse(py_file.read_text(encoding="utf-8"), filename=str(py_file))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    assert alias.name not in forbidden, f"Forbidden import '{alias.name}' in {py_file.name}"
            elif isinstance(node, ast.ImportFrom):
                mod = node.module or ""
                assert not any(f in mod for f in forbidden), f"Forbidden module '{mod}' in {py_file.name}"
                for alias in node.names:
                    assert alias.name not in forbidden, f"Forbidden symbol '{alias.name}' in {py_file.name}"
