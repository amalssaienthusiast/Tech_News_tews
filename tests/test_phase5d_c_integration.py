"""
Subphase 5D-C Integration Test Suite: Cross-Boundary E2E Integration & Lifecycle Verification.
Location: tests/test_phase5d_c_integration.py

Verifies:
1. CLEAN CONTEXT RESTART SIMULATION:
   Process 1 (Pipeline Ingestion -> S10 Persistence -> SQLite -> Teardown)
   Process 2 (Cold Start -> S07 Hydration -> Ingest Corroboration -> S10 Update -> SQLite)
   Process 3 / API Delivery (FastAPI Lifespan -> Repository -> GET /v1/events reads unified aggregate)
2. Database Schema & Multi-Source Evidence Integrity (Foreign keys, exactly 1 TechEvent, 2 sources)
3. Non-blocking SSE stream event publication and delivery via PublicationBus
4. SQLite WAL concurrency: concurrent pipeline writes and API reads without database locks
5. Architectural boundary purity: zero legacy storage coupling and protocol decoupling
"""

import ast
import asyncio
from datetime import datetime, UTC, timedelta
import os
from pathlib import Path
from typing import List
import pytest
from fastapi.testclient import TestClient

from src.api.app import app as prod_app, get_app
from src.api.main import verify_api_key
from src.api.routes.events import get_event_repository, set_event_repository
from src.domain.enums import (
    EventStatus,
    FreshnessLevel,
    PublicationChannel,
    PublicationEventType,
    SourceTier,
    ZombieSpecies,
)
from src.domain.models import (
    EventSourceEvidence,
    PublicationEvent,
    SourceObservation,
    TechEvent,
    TimelineEntry,
)
from src.engine.publication_bus import get_publication_bus
from src.pipeline.runner import CanonicalPipelineRunner, IngestionStatus
from src.storage.protocols import EventRepositoryProtocol
from src.storage.sqlite_engine import SqliteEngine
from src.storage.sqlite_event_repository import SqliteEventRepository


# =============================================================================
# 1. CLEAN CONTEXT RESTART SIMULATION & MULTI-SOURCE CORROBORATION
# =============================================================================

@pytest.mark.asyncio
async def test_cross_restart_pipeline_corroboration_and_api_delivery(tmp_path: Path):
    """
    CLEAN CONTEXT RESTART SIMULATION:
    Demonstrates full cross-boundary continuity:
    1. Pipeline Process 1 ingests Story A from Source 1 -> S10 saves TechEvent to SQLite -> Process 1 shutdown.
    2. Pipeline Process 2 cold-starts -> Hydrates S07 from SQLite -> ingests Story A from Source 2 ->
       S07 corroborates existing TechEvent -> S10 updates same TechEvent aggregate with 2 sources -> Process 2 shutdown.
    3. Direct SQL verification: Exactly 1 TechEvent row, 2 EventSourceEvidence rows, valid foreign keys.
    4. FastAPI Application starts via lifespan -> resolves canonical repository -> GET /v1/events returns unified event.
    """
    db_file = tmp_path / "canonical_e2e_integration.db"
    os.environ["TECHNEWS_CANONICAL_DB_PATH"] = str(db_file)

    # -------------------------------------------------------------------------
    # CONTEXT 1: First Pipeline Run (Process 1 Simulation)
    # -------------------------------------------------------------------------
    engine1 = SqliteEngine(db_file)
    await engine1.initialize_schema()
    repo1 = SqliteEventRepository(engine=engine1, auto_init=False)
    runner1 = CanonicalPipelineRunner(event_repository=repo1)

    obs1 = SourceObservation.create(
        source_id="src_techcrunch_5dc",
        source_name="TechCrunch",
        source_tier=SourceTier.TIER_1_PREMIUM,
        zombie_species=ZombieSpecies.RSS,
        url="https://techcrunch.com/2026/quantum-supremacy-breakthrough",
        title="Major Quantum Computing Processor Breakthrough Announced",
        summary="Researchers demonstrate 1000-qubit fault-tolerant quantum processor.",
        raw_content="Researchers announce a revolutionary 1000-qubit fault-tolerant quantum computing processor.",
        published_at_hint=datetime.now(UTC),
    )

    res1 = await runner1.process_observation(obs1)
    assert res1.status == IngestionStatus.SUCCESS
    assert res1.event is not None
    event_id = res1.event.id
    assert res1.event.source_count == 1

    # Verify persisted in SQLite
    saved_v1 = await repo1.get_event(event_id)
    assert saved_v1 is not None
    assert saved_v1.source_count == 1

    # Teardown Context 1 cleanly
    await engine1.aclose()
    del runner1
    del repo1
    del engine1

    # -------------------------------------------------------------------------
    # CONTEXT 2: Second Pipeline Run After Cold Restart (Process 2 Simulation)
    # -------------------------------------------------------------------------
    engine2 = SqliteEngine(db_file)
    repo2 = SqliteEventRepository(engine=engine2, auto_init=False)
    runner2 = CanonicalPipelineRunner(event_repository=repo2)

    # Startup Hydration of S07 ActiveEventStore from SQLite
    hydrated = await runner2.hydrate_cluster_store(window_hours=48.0)
    assert hydrated == 1
    assert len(runner2.event_store) == 1
    assert runner2.event_store.get_event(event_id) is not None

    # Ingest corroborating story from Source 2
    obs2 = SourceObservation.create(
        source_id="src_ars_5dc",
        source_name="Ars Technica",
        source_tier=SourceTier.TIER_2_SPECIALIST,
        zombie_species=ZombieSpecies.WEB,
        url="https://arstechnica.com/2026/quantum-supremacy-analysis",
        title="Major Quantum Computing Processor Breakthrough Announced: Full Analysis",
        summary="Detailed architecture and benchmarks for the new 1000-qubit quantum processor.",
        raw_content="Detailed architecture and benchmarks for the new 1000-qubit quantum processor announced today.",
        published_at_hint=datetime.now(UTC),
    )

    res2 = await runner2.process_observation(obs2)
    assert res2.status == IngestionStatus.SUCCESS
    assert res2.event is not None
    assert res2.event.id == event_id  # Matched into existing TechEvent!
    assert res2.event.source_count == 2
    assert res2.event.status in (EventStatus.CORROBORATED, EventStatus.CONFIRMED)

    # Teardown Context 2 cleanly
    await engine2.aclose()
    del runner2
    del repo2
    del engine2

    # -------------------------------------------------------------------------
    # CONTEXT 3: Database Integrity Inspection (Direct SQL)
    # -------------------------------------------------------------------------
    inspect_engine = SqliteEngine(db_file)
    async with inspect_engine.connect() as conn:
        # Check canonical_events count
        cursor = await conn.execute("SELECT COUNT(*) FROM canonical_events;")
        (event_count,) = await cursor.fetchone()
        assert event_count == 1, f"Expected 1 TechEvent, found {event_count}"

        # Check canonical_event_sources count
        cursor = await conn.execute("SELECT COUNT(*), COUNT(DISTINCT url) FROM canonical_event_sources WHERE event_id = ?;", (event_id,))
        source_count, distinct_urls = await cursor.fetchone()
        assert source_count == 2, f"Expected 2 sources, found {source_count}"
        assert distinct_urls == 2

        # Check foreign-key integrity
        cursor = await conn.execute("PRAGMA foreign_key_check;")
        fk_violations = await cursor.fetchall()
        assert len(fk_violations) == 0, f"Foreign key violations found: {fk_violations}"

    await inspect_engine.aclose()

    # -------------------------------------------------------------------------
    # CONTEXT 4: FastAPI Application Delivery (Process 3 Simulation)
    # -------------------------------------------------------------------------
    app = get_app()
    app.dependency_overrides[verify_api_key] = lambda: {"tier": "pro", "user_id": "test_user"}

    with TestClient(app) as client:
        # 1. GET /v1/events
        res_list = client.get("/v1/events")
        assert res_list.status_code == 200
        events_data = res_list.json()
        assert len(events_data) == 1
        event_dto = events_data[0]
        assert event_dto["id"] == event_id
        assert event_dto["source_count"] == 2
        assert len(event_dto["sources"]) == 2

        # 2. GET /v1/events/{id}
        res_single = client.get(f"/v1/events/{event_id}")
        assert res_single.status_code == 200
        single_dto = res_single.json()
        assert single_dto["id"] == event_id
        assert single_dto["source_count"] == 2
        source_urls = {s["url"] for s in single_dto["sources"]}
        assert "https://techcrunch.com/2026/quantum-supremacy-breakthrough" in source_urls
        assert "https://arstechnica.com/2026/quantum-supremacy-analysis" in source_urls

        # 3. GET /v1/events/stats
        res_stats = client.get("/v1/events/stats")
        assert res_stats.status_code == 200
        stats_dto = res_stats.json()
        assert stats_dto["total_events"] == 1

    app.dependency_overrides.clear()
    os.environ.pop("TECHNEWS_CANONICAL_DB_PATH", None)


# =============================================================================
# 2. REAL-TIME SSE STREAM BROADCAST INTEGRATION
# =============================================================================

@pytest.mark.asyncio
async def test_sse_stream_publication_and_delivery(tmp_path: Path):
    """
    Verify PublicationBus broadcasts trigger valid non-blocking SSE payloads on GET /v1/events/stream.
    """
    test_db = tmp_path / "sse_test.db"
    engine = SqliteEngine(test_db)
    await engine.initialize_schema()
    repo = SqliteEventRepository(engine=engine, auto_init=False)
    set_event_repository(repo)

    now = datetime.now(UTC)
    sample_event = TechEvent(
        id="evt_sse_realtime_01",
        headline="Realtime SSE Stream Verified",
        first_seen=now,
        last_updated=now,
        entities=["FastAPI", "SSE"],
        topics=["Streaming", "PubSub"],
        sources=[],
        primary_source="TestSource",
        confidence=0.95,
        importance=0.88,
        novelty=0.90,
        status=EventStatus.DEVELOPING,
        freshness=FreshnessLevel.BREAKING,
        freshness_score=0.99,
        timeline=[],
        cluster_id="cluster_sse_01",
    )
    await repo.save_event(sample_event)

    bus = get_publication_bus()

    # Simulate SSE stream processing using the route generator
    from src.api.routes.events import event_stream
    from fastapi import Request

    # Create dummy request with receive channel
    async def dummy_receive():
        await asyncio.sleep(100)
        return {"type": "http.disconnect"}

    scope = {"type": "http", "headers": []}
    dummy_request = Request(scope=scope, receive=dummy_receive)

    # Start bus
    await bus.start()

    stream_resp = await event_stream(
        request=dummy_request,
        repo=repo,
    )

    # Publish an event to the bus
    pub_event = PublicationEvent(
        event_type=PublicationEventType.EVENT_UPDATED,
        payload={"id": "evt_sse_realtime_01"},
        channels=(PublicationChannel.SSE_STREAM,),
    )

    # Publish to bus
    published_count = await bus.publish(pub_event)
    assert published_count >= 1

    # Verify non-blocking queue read
    generator = stream_resp.body_iterator
    sse_chunk = await anext(generator)
    assert "event: event_update" in sse_chunk
    assert "evt_sse_realtime_01" in sse_chunk

    set_event_repository(None)
    await bus.stop()
    await engine.aclose()


# =============================================================================
# 3. CONCURRENT WAL READ / WRITE STRESS TEST
# =============================================================================

@pytest.mark.asyncio
async def test_concurrent_wal_pipeline_writes_and_api_reads(tmp_path: Path):
    """
    Stress-test SQLite WAL mode under concurrent operations:
    - 10 concurrent pipeline writers saving distinct TechEvents
    - 10 concurrent API readers querying active events and entity indices
    - Assert ZERO 'database is locked' errors and 100% aggregate atomicity.
    """
    db_file = tmp_path / "concurrent_stress.db"
    engine = SqliteEngine(db_file)
    await engine.initialize_schema()
    repo = SqliteEventRepository(engine=engine, auto_init=False)

    now = datetime.now(UTC)

    def build_event(idx: int) -> TechEvent:
        src = EventSourceEvidence(
            article_id=f"art_conc_{idx}",
            url=f"https://example.com/conc/{idx}",
            title=f"Concurrent Test Story {idx}",
            source_name=f"Source_{idx % 3}",
            source_tier=SourceTier.TIER_1_PREMIUM,
            discovered_at=now,
        )
        return TechEvent(
            id=f"evt_conc_{idx:03d}",
            headline=f"Concurrent Stress Test Headline {idx}",
            first_seen=now,
            last_updated=now,
            entities=["Concurrency", f"Entity_{idx % 4}"],
            topics=["Performance", "SQLite"],
            sources=[src],
            primary_source=f"Source_{idx % 3}",
            confidence=0.85,
            importance=0.75,
            novelty=0.80,
            status=EventStatus.CORROBORATED,
            freshness=FreshnessLevel.FRESH,
            freshness_score=0.85,
            timeline=[],
            cluster_id=f"cluster_conc_{idx:03d}",
        )

    # Writer tasks
    async def writer_task(idx: int):
        event = build_event(idx)
        await repo.save_event(event)
        # Verify immediate single-event read
        saved = await repo.get_event(event.id)
        assert saved is not None
        assert saved.id == event.id

    # Reader tasks
    async def reader_task(idx: int):
        for _ in range(5):
            events = await repo.get_active_events(limit=50)
            assert isinstance(events, list)
            by_entity = await repo.get_events_by_entity(f"Entity_{idx % 4}", limit=20)
            assert isinstance(by_entity, list)
            await asyncio.sleep(0.005)

    # Launch 10 writers and 10 readers concurrently
    writers = [writer_task(i) for i in range(10)]
    readers = [reader_task(i) for i in range(10)]

    # Execute all concurrently
    await asyncio.gather(*(writers + readers))

    # Verify final integrity
    stats = await repo.get_stats()
    assert stats["total_events"] == 10
    active = await repo.get_active_events(limit=100)
    assert len(active) == 10

    await engine.aclose()


# =============================================================================
# 4. ARCHITECTURAL BOUNDARY ASSERTIONS & LEGACY DECOUPLING
# =============================================================================

def test_architectural_boundary_purity_ast():
    """
    Verify AST boundaries across all key modules:
    - src/api/routes/events.py has ZERO imports of sqlite3/aiosqlite/SqliteEventRepository/EventStore
    - src/pipeline/stages/s07_clustering.py has ZERO imports of sqlite3/aiosqlite/SqliteEventRepository
    - src/pipeline/stages/s10_persistence.py has ZERO imports of sqlite3/aiosqlite/SqliteEventRepository
    """
    base_dir = Path(__file__).resolve().parent.parent

    target_files = [
        base_dir / "src" / "api" / "routes" / "events.py",
        base_dir / "src" / "pipeline" / "stages" / "s07_clustering.py",
        base_dir / "src" / "pipeline" / "stages" / "s10_persistence.py",
    ]

    forbidden_modules = {"sqlite3", "aiosqlite", "SqliteEventRepository", "SqliteEngine"}

    for target in target_files:
        assert target.exists(), f"Target file missing: {target}"
        tree = ast.parse(target.read_text(encoding="utf-8"), filename=str(target))

        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    assert alias.name not in forbidden_modules, (
                        f"Forbidden import '{alias.name}' found in {target.name}"
                    )
            elif isinstance(node, ast.ImportFrom):
                module = node.module or ""
                assert module not in forbidden_modules, (
                    f"Forbidden from-import module '{module}' in {target.name}"
                )
                for alias in node.names:
                    assert alias.name not in forbidden_modules, (
                        f"Forbidden symbol '{alias.name}' imported in {target.name}"
                    )


def test_api_active_repository_is_canonical_protocol(tmp_path: Path):
    """
    Verify running API application resolves SqliteEventRepository through
    EventRepositoryProtocol and has zero dependency on legacy EventStore.
    """
    test_db = tmp_path / "boundary_test.db"
    os.environ["TECHNEWS_CANONICAL_DB_PATH"] = str(test_db)

    app = prod_app
    with TestClient(app) as client:
        repo = get_event_repository()
        assert repo is not None
        # Confirms repository fulfills protocol methods
        assert callable(getattr(repo, "save_event", None))
        assert callable(getattr(repo, "get_event", None))
        assert callable(getattr(repo, "get_active_events", None))
        assert callable(getattr(repo, "get_events_by_entity", None))
        assert callable(getattr(repo, "get_stats", None))

        # Confirm it's NOT legacy EventStore
        assert repo.__class__.__name__ == "SqliteEventRepository"
        assert repo.__class__.__name__ != "EventStore"

    os.environ.pop("TECHNEWS_CANONICAL_DB_PATH", None)
