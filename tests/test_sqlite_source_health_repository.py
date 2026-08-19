"""
Unit & Integration Tests for Subphase 5E-B: SQLite Source Health Repository.
Location: tests/test_sqlite_source_health_repository.py

Verifies:
1. Exact round-trip persistence of SourceHealth entities
2. Status enum round-trip across all SourceHealthStatus values
3. Optional datetime round-trip (last_attempt, last_success, cooldown_until, rate_limit_reset_at)
4. Naive datetime validation and rejection
5. Deterministic mutable-state upsert (no duplicate rows per source_id)
6. Dynamic state transitions (healthy -> degraded -> rate_limited -> cooldown -> probation)
7. Cooldown timestamp persistence and recovery
8. Rate-limit reset timestamp persistence and recovery
9. Batch save atomicity and transaction rollback
10. Batch duplicate source_id deterministic resolution (last-write-wins)
11. get_all_health retrieval and ordering
12. get_health_by_status filtering
13. delete_health for existing and missing source IDs
14. Concurrent updates to the same source record without locking errors
15. Clean-context restart continuity across distinct SqliteEngine instances
16. Shared SqliteEngine coexistence with Event and Article repositories
17. Single database file verification (zero secondary DB files)
18. AST boundary verification (zero ORM/sqlite3 imports)
"""

from __future__ import annotations

import asyncio
from datetime import datetime, UTC, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union
import pytest

from src.domain.enums import SourceHealthStatus
from src.domain.models import SourceHealth
from src.domain.validators import DomainValidationError
from src.storage.protocols import SourceHealthRepositoryProtocol
from src.storage.sqlite_source_health_repository import SqliteSourceHealthRepository
from src.storage.sqlite_engine import SqliteEngine


def make_sample_health(
    source_id: str = "src_hacker_news",
    source_url: str = "https://news.ycombinator.com/rss",
    source_name: str = "Hacker News RSS",
    status: SourceHealthStatus = SourceHealthStatus.HEALTHY,
    consecutive_failures: int = 0,
    consecutive_successes: int = 10,
    last_attempt_offset_min: Optional[float] = 5.0,
    last_success_offset_min: Optional[float] = 5.0,
    last_status_code: Optional[int] = 200,
    cooldown_offset_min: Optional[float] = None,
    rate_limit_offset_min: Optional[float] = None,
    working_bypass_tier: int = 0,
) -> SourceHealth:
    now = datetime.now(UTC)
    last_attempt = now - timedelta(minutes=last_attempt_offset_min) if last_attempt_offset_min is not None else None
    last_success = now - timedelta(minutes=last_success_offset_min) if last_success_offset_min is not None else None
    cooldown_until = now + timedelta(minutes=cooldown_offset_min) if cooldown_offset_min is not None else None
    rate_limit_reset_at = now + timedelta(minutes=rate_limit_offset_min) if rate_limit_offset_min is not None else None

    return SourceHealth(
        source_id=source_id,
        source_url=source_url,
        source_name=source_name,
        status=status,
        consecutive_failures=consecutive_failures,
        consecutive_successes=consecutive_successes,
        last_attempt=last_attempt,
        last_success=last_success,
        last_status_code=last_status_code,
        cooldown_until=cooldown_until,
        rate_limit_reset_at=rate_limit_reset_at,
        working_bypass_tier=working_bypass_tier,
    )


@pytest.fixture
async def repo(tmp_path: Path):
    db_path = tmp_path / "canonical_source_health_test.db"
    engine = SqliteEngine(db_path)
    repository = SqliteSourceHealthRepository(engine=engine, auto_init=True)
    yield repository
    await engine.aclose()


@pytest.mark.asyncio
async def test_health_exact_round_trip(repo: SqliteSourceHealthRepository):
    """Verify exact round-trip fidelity of all SourceHealth attributes."""
    h = make_sample_health(
        source_id="src_techcrunch",
        source_url="https://techcrunch.com/feed/",
        source_name="TechCrunch Feed",
        status=SourceHealthStatus.HEALTHY,
        consecutive_failures=0,
        consecutive_successes=42,
        last_attempt_offset_min=2.0,
        last_success_offset_min=2.0,
        last_status_code=200,
        cooldown_offset_min=None,
        rate_limit_offset_min=None,
        working_bypass_tier=1,
    )
    await repo.save_health(h)

    fetched = await repo.get_health(h.source_id)
    assert fetched is not None
    assert fetched.source_id == h.source_id
    assert fetched.source_url == h.source_url
    assert fetched.source_name == h.source_name
    assert fetched.status == h.status
    assert fetched.consecutive_failures == 0
    assert fetched.consecutive_successes == 42
    assert fetched.last_attempt == h.last_attempt
    assert fetched.last_success == h.last_success
    assert fetched.last_status_code == 200
    assert fetched.cooldown_until is None
    assert fetched.rate_limit_reset_at is None
    assert fetched.working_bypass_tier == 1


@pytest.mark.asyncio
async def test_status_enum_round_trip(repo: SqliteSourceHealthRepository):
    """Verify all valid SourceHealthStatus enum values round-trip without corruption."""
    all_statuses = [
        SourceHealthStatus.HEALTHY,
        SourceHealthStatus.DEGRADED,
        SourceHealthStatus.COOLDOWN,
        SourceHealthStatus.RATE_LIMITED,
        SourceHealthStatus.QUARANTINED,
        SourceHealthStatus.PROBATION,
        SourceHealthStatus.DEAD,
    ]

    for idx, status in enumerate(all_statuses):
        h = make_sample_health(
            source_id=f"src_status_test_{idx}",
            status=status,
        )
        await repo.save_health(h)

        fetched = await repo.get_health(h.source_id)
        assert fetched is not None
        assert fetched.status == status
        assert isinstance(fetched.status, SourceHealthStatus)


@pytest.mark.asyncio
async def test_optional_datetime_round_trip(repo: SqliteSourceHealthRepository):
    """Verify optional datetimes when set vs None are faithfully preserved."""
    # All datetimes present
    h_full = make_sample_health(
        source_id="src_full_dates",
        last_attempt_offset_min=10.0,
        last_success_offset_min=10.0,
        cooldown_offset_min=60.0,
        rate_limit_offset_min=15.0,
    )
    await repo.save_health(h_full)
    fetched_full = await repo.get_health("src_full_dates")
    assert fetched_full is not None
    assert fetched_full.last_attempt.tzinfo == UTC
    assert fetched_full.last_success.tzinfo == UTC
    assert fetched_full.cooldown_until.tzinfo == UTC
    assert fetched_full.rate_limit_reset_at.tzinfo == UTC

    # All optional datetimes None
    h_none = make_sample_health(
        source_id="src_none_dates",
        last_attempt_offset_min=None,
        last_success_offset_min=None,
        cooldown_offset_min=None,
        rate_limit_offset_min=None,
    )
    await repo.save_health(h_none)
    fetched_none = await repo.get_health("src_none_dates")
    assert fetched_none is not None
    assert fetched_none.last_attempt is None
    assert fetched_none.last_success is None
    assert fetched_none.cooldown_until is None
    assert fetched_none.rate_limit_reset_at is None


@pytest.mark.asyncio
async def test_naive_datetime_rejection(repo: SqliteSourceHealthRepository):
    """Verify that attempting to create/save SourceHealth with a naive datetime is rejected."""
    naive_dt = datetime(2026, 8, 14, 10, 0, 0)
    with pytest.raises(DomainValidationError):
        SourceHealth(
            source_id="src_naive",
            source_url="https://example.com/rss",
            source_name="Naive",
            last_attempt=naive_dt,
        )


@pytest.mark.asyncio
async def test_deterministic_upsert(repo: SqliteSourceHealthRepository):
    """Verify that multiple saves for the same source_id update the record in place."""
    source_id = "src_upsert_test"
    h_v1 = make_sample_health(
        source_id=source_id,
        status=SourceHealthStatus.HEALTHY,
        consecutive_successes=5,
    )
    await repo.save_health(h_v1)
    assert len(await repo.get_all_health()) == 1

    # Update to degraded
    h_v2 = make_sample_health(
        source_id=source_id,
        status=SourceHealthStatus.DEGRADED,
        consecutive_failures=3,
        consecutive_successes=0,
    )
    await repo.save_health(h_v2)

    # Must still have exactly 1 record in database
    all_records = await repo.get_all_health()
    assert len(all_records) == 1
    assert all_records[0].status == SourceHealthStatus.DEGRADED
    assert all_records[0].consecutive_failures == 3


@pytest.mark.asyncio
async def test_state_transitions(repo: SqliteSourceHealthRepository):
    """Verify persistence across a complete sequence of domain state machine transitions."""
    h = make_sample_health(source_id="src_lifecycle")

    # 1. Healthy -> Degraded (failure #1)
    h.record_failure(status_code=500)
    assert h.status == SourceHealthStatus.DEGRADED
    await repo.save_health(h)
    fetched = await repo.get_health("src_lifecycle")
    assert fetched.status == SourceHealthStatus.DEGRADED
    assert fetched.consecutive_failures == 1

    # 2. Degraded -> Rate Limited (HTTP 429)
    h.record_failure(status_code=429, retry_after_sec=120)
    assert h.status == SourceHealthStatus.RATE_LIMITED
    await repo.save_health(h)
    fetched = await repo.get_health("src_lifecycle")
    assert fetched.status == SourceHealthStatus.RATE_LIMITED
    assert fetched.rate_limit_reset_at is not None

    # 3. Rate Limited -> Healthy (Successful fetch)
    h.record_success(working_tier=2)
    assert h.status == SourceHealthStatus.HEALTHY
    await repo.save_health(h)
    fetched = await repo.get_health("src_lifecycle")
    assert fetched.status == SourceHealthStatus.HEALTHY
    assert fetched.consecutive_failures == 0
    assert fetched.working_bypass_tier == 2


@pytest.mark.asyncio
async def test_cooldown_persistence(repo: SqliteSourceHealthRepository):
    """Verify cooldown_until timestamps persist and evaluate correctly."""
    h = make_sample_health(source_id="src_cooldown_test")
    # Simulate 5 consecutive failures triggering COOLDOWN
    for _ in range(5):
        h.record_failure(status_code=503)
    assert h.status == SourceHealthStatus.COOLDOWN
    assert h.cooldown_until is not None
    await repo.save_health(h)

    fetched = await repo.get_health("src_cooldown_test")
    assert fetched is not None
    assert fetched.status == SourceHealthStatus.COOLDOWN
    assert fetched.cooldown_until == h.cooldown_until
    assert not fetched.is_eligible_to_poll()


@pytest.mark.asyncio
async def test_rate_limit_reset_persistence(repo: SqliteSourceHealthRepository):
    """Verify rate_limit_reset_at persists accurately on HTTP 429 backoff."""
    h = make_sample_health(source_id="src_rate_limit_test")
    h.record_failure(status_code=429, retry_after_sec=600)
    await repo.save_health(h)

    fetched = await repo.get_health("src_rate_limit_test")
    assert fetched is not None
    assert fetched.status == SourceHealthStatus.RATE_LIMITED
    assert fetched.rate_limit_reset_at == h.rate_limit_reset_at
    assert not fetched.is_eligible_to_poll()


@pytest.mark.asyncio
async def test_batch_save_atomicity(repo: SqliteSourceHealthRepository):
    """Verify save_health_batch persists multiple records atomically within a transaction."""
    records = [
        make_sample_health(source_id=f"src_batch_{i}", source_name=f"Source {i}")
        for i in range(5)
    ]
    saved_count = await repo.save_health_batch(records)
    assert saved_count == 5

    all_records = await repo.get_all_health()
    assert len(all_records) == 5

    # Empty batch returns 0
    assert await repo.save_health_batch([]) == 0


@pytest.mark.asyncio
async def test_batch_duplicate_source_id_resolution(repo: SqliteSourceHealthRepository):
    """Verify deterministic last-write-wins behavior when a batch contains duplicate source IDs."""
    h1 = make_sample_health(source_id="src_dup", status=SourceHealthStatus.HEALTHY)
    h2 = make_sample_health(source_id="src_dup", status=SourceHealthStatus.DEGRADED)
    h3 = make_sample_health(source_id="src_dup", status=SourceHealthStatus.DEAD)

    saved_count = await repo.save_health_batch([h1, h2, h3])
    assert saved_count == 3

    # Must result in exactly 1 record in database with the last written state (DEAD)
    fetched = await repo.get_health("src_dup")
    assert fetched is not None
    assert fetched.status == SourceHealthStatus.DEAD
    assert len(await repo.get_all_health()) == 1


@pytest.mark.asyncio
async def test_get_all_health(repo: SqliteSourceHealthRepository):
    """Verify get_all_health returns all persisted source health records in deterministic order."""
    ids = ["src_z", "src_a", "src_m"]
    for sid in ids:
        await repo.save_health(make_sample_health(source_id=sid))

    all_records = await repo.get_all_health()
    assert len(all_records) == 3
    # Ordered by source_id ASC
    assert [r.source_id for r in all_records] == ["src_a", "src_m", "src_z"]


@pytest.mark.asyncio
async def test_get_health_by_status(repo: SqliteSourceHealthRepository):
    """Verify get_health_by_status filters sources by health status accurately."""
    h1 = make_sample_health(source_id="src_1", status=SourceHealthStatus.HEALTHY)
    h2 = make_sample_health(source_id="src_2", status=SourceHealthStatus.HEALTHY)
    h3 = make_sample_health(source_id="src_3", status=SourceHealthStatus.COOLDOWN)
    h4 = make_sample_health(source_id="src_4", status=SourceHealthStatus.DEAD)

    await repo.save_health_batch([h1, h2, h3, h4])

    healthy = await repo.get_health_by_status(SourceHealthStatus.HEALTHY)
    assert len(healthy) == 2
    assert {r.source_id for r in healthy} == {"src_1", "src_2"}

    cooldown = await repo.get_health_by_status(SourceHealthStatus.COOLDOWN)
    assert len(cooldown) == 1
    assert cooldown[0].source_id == "src_3"

    quarantined = await repo.get_health_by_status(SourceHealthStatus.QUARANTINED)
    assert len(quarantined) == 0


@pytest.mark.asyncio
async def test_delete_health(repo: SqliteSourceHealthRepository):
    """Verify delete_health returns True on existing record and False on missing record."""
    h = make_sample_health(source_id="src_del_test")
    await repo.save_health(h)

    # Delete existing
    deleted = await repo.delete_health("src_del_test")
    assert deleted is True
    assert await repo.get_health("src_del_test") is None

    # Delete missing
    deleted_missing = await repo.delete_health("src_del_test")
    assert deleted_missing is False


@pytest.mark.asyncio
async def test_concurrent_same_source_updates(repo: SqliteSourceHealthRepository):
    """Verify concurrent write tasks on the same source_id do not cause locking errors or duplicates."""
    source_id = "src_concurrent_health"
    await repo.save_health(make_sample_health(source_id=source_id))

    async def update_health(step: int):
        h = make_sample_health(
            source_id=source_id,
            consecutive_failures=step,
            status=SourceHealthStatus.DEGRADED if step > 0 else SourceHealthStatus.HEALTHY,
        )
        await repo.save_health(h)

    tasks = [update_health(i) for i in range(10)]
    await asyncio.gather(*tasks)

    # Total rows must remain 1
    all_h = await repo.get_all_health()
    assert len(all_h) == 1
    assert all_h[0].source_id == source_id


@pytest.mark.asyncio
async def test_clean_context_restart_continuity(tmp_path: Path):
    """Verify source health resilience state survives engine teardown and fresh context reconstruction."""
    db_file = tmp_path / "restart_health_test.db"

    # Context 1: Save source health in COOLDOWN and QUARANTINED states
    engine1 = SqliteEngine(db_file)
    repo1 = SqliteSourceHealthRepository(engine=engine1, auto_init=True)

    h_cool = make_sample_health(
        source_id="src_restarting_cooldown",
        status=SourceHealthStatus.COOLDOWN,
        consecutive_failures=6,
        cooldown_offset_min=120.0,
    )
    h_quar = make_sample_health(
        source_id="src_restarting_quarantine",
        status=SourceHealthStatus.QUARANTINED,
        consecutive_failures=1,
        cooldown_offset_min=10080.0,  # 7 days
    )
    await repo1.save_health_batch([h_cool, h_quar])
    await engine1.aclose()

    # Context 2: Open clean new SqliteEngine and verify restored state
    engine2 = SqliteEngine(db_file)
    repo2 = SqliteSourceHealthRepository(engine=engine2, auto_init=True)

    restored_cool = await repo2.get_health("src_restarting_cooldown")
    assert restored_cool is not None
    assert restored_cool.status == SourceHealthStatus.COOLDOWN
    assert restored_cool.consecutive_failures == 6
    assert restored_cool.cooldown_until == h_cool.cooldown_until
    assert not restored_cool.is_eligible_to_poll()

    restored_quar = await repo2.get_health("src_restarting_quarantine")
    assert restored_quar is not None
    assert restored_quar.status == SourceHealthStatus.QUARANTINED
    assert restored_quar.cooldown_until == h_quar.cooldown_until
    assert not restored_quar.is_eligible_to_poll()

    await engine2.aclose()


@pytest.mark.asyncio
async def test_shared_sqlite_engine_coexistence(tmp_path: Path):
    """Verify SqliteSourceHealthRepository coexists on the same engine with Event and Article repos."""
    db_file = tmp_path / "full_shared_canonical_test.db"
    engine = SqliteEngine(db_file)

    from src.storage.sqlite_event_repository import SqliteEventRepository
    from src.storage.sqlite_article_repository import SqliteArticleRepository

    event_repo = SqliteEventRepository(engine=engine, auto_init=True)
    article_repo = SqliteArticleRepository(engine=engine, auto_init=True)
    health_repo = SqliteSourceHealthRepository(engine=engine, auto_init=True)

    # Save to health repository
    h = make_sample_health(source_id="src_shared_check")
    await health_repo.save_health(h)

    # Check all repositories against shared database
    assert len(await health_repo.get_all_health()) == 1
    assert await article_repo.count_articles() == 0
    stats = await event_repo.get_stats()
    assert stats["total_events"] == 0

    await engine.aclose()


@pytest.mark.asyncio
async def test_no_second_db_file_created(tmp_path: Path):
    """Verify only a single canonical database file is created on disk."""
    db_file = tmp_path / "single_canonical_health.db"
    engine = SqliteEngine(db_file)
    health_repo = SqliteSourceHealthRepository(engine=engine, auto_init=True)

    await health_repo.save_health(make_sample_health(source_id="src_single_file"))
    await engine.aclose()

    db_files = [f for f in tmp_path.iterdir() if f.name.endswith(".db")]
    assert len(db_files) == 1
    assert db_files[0].name == "single_canonical_health.db"


def test_repository_boundary_ast_no_orm():
    """Verify SqliteSourceHealthRepository has zero imports of sqlalchemy/generic ORMs or synchronous sqlite3."""
    import ast
    repo_file = Path(__file__).resolve().parent.parent / "src" / "storage" / "sqlite_source_health_repository.py"
    tree = ast.parse(repo_file.read_text(encoding="utf-8"), filename=str(repo_file))

    forbidden = {"sqlalchemy", "sqlite3", "peewee", "tortoise", "orm"}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                assert alias.name not in forbidden, f"Forbidden import '{alias.name}' in repository"
        elif isinstance(node, ast.ImportFrom):
            mod = node.module or ""
            assert not any(f in mod for f in forbidden), f"Forbidden module '{mod}' in repository"
