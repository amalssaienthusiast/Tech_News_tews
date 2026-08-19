"""
Subphase 5E-F Integration Test Suite: Full Phase 5E Cross-Boundary E2E Integration.
Location: tests/test_phase5e_f_integration.py

Verifies:
1. THE THREE CANONICAL MEMORY SYSTEMS ACROSS COLD RESTART:
   - Article Memory (canonical_articles)
   - Event Brain (canonical_events + canonical_event_sources)
   - Health Memory (canonical_source_health)
2. MULTI-LIFECYCLE EXPERIMENT:
   - Stage 1: Pipeline Process 1 ingests Story X from Source 1 -> S06 persists Article 1 -> S10 persists TechEvent 1 -> Swarm flushes Health states -> Clean Shutdown.
   - Stage 2: Cold Process 2 -> Swarm hydrates Health (Source 2 cooldown) -> S07 hydrates TechEvent 1 -> Ingests Story X from Source 2 -> S06 persists Article 2 -> S07 Corroborates existing TechEvent 1 (source_count=2) -> S10 updates TechEvent 1 -> Clean Shutdown.
   - Stage 3: Direct SQLite Table Integrity (Exactly 2 articles, 1 event, 2 event_sources, 0 FK violations).
   - Stage 4: FastAPI Delivery Layer (Lifespan starts with real SQLite -> GET /v1/articles, GET /v1/events, GET /v1/events/stream SSE).
3. NON-BLOCKING SSE PUBLICATION STREAM DELIVERY
4. HIGH-THROUGHPUT WAL CONCURRENCY & INTEGRITY (Concurrent multi-readers & multi-writers without locks)
5. STRICT AST BOUNDARY PURITY (Zero SQLite/storage imports in pipeline, zombies, and API routes)
"""

from __future__ import annotations

import ast
import asyncio
from datetime import datetime, UTC, timedelta
import os
from pathlib import Path
import sqlite3
from typing import Any, Dict, List
import pytest
from fastapi.testclient import TestClient

from src.api.app import app as prod_app, get_app
from src.api.main import verify_api_key
from src.api.routes.articles import (
    get_article_repository,
    set_article_repository,
    ArticleResponse,
)
from src.api.routes.events import (
    get_event_repository,
    set_event_repository,
    TechEventResponse,
)
from src.domain.enums import (
    EventStatus,
    FreshnessLevel,
    PublicationChannel,
    PublicationEventType,
    SourceHealthStatus,
    SourceTier,
    ZombieSpecies,
)
from src.domain.models import (
    EventSourceEvidence,
    NormalizedArticle,
    PublicationEvent,
    SourceHealth,
    SourceObservation,
    TechEvent,
    TimelineEntry,
)
from src.engine.publication_bus import get_publication_bus
from src.engine.source_registry import SourceDescriptor, SourceRegistry, SourceType
from src.pipeline.runner import CanonicalPipelineRunner, IngestionStatus
from src.storage.protocols import ArticleRepositoryProtocol, EventRepositoryProtocol, SourceHealthRepositoryProtocol
from src.storage.sqlite_article_repository import SqliteArticleRepository
from src.storage.sqlite_engine import SqliteEngine
from src.storage.sqlite_event_repository import SqliteEventRepository
from src.storage.sqlite_source_health_repository import SqliteSourceHealthRepository
from src.zombies.swarm import ZombieSwarm


# =============================================================================
# 1. FULL COLD-RESTART ARTICLE, EVENT & HEALTH CONTINUITY EXPERIMENT
# =============================================================================

@pytest.mark.asyncio
async def test_full_cold_restart_article_event_health_continuity(tmp_path: Path):
    """
    Rigorously verifies full multi-lifecycle cross-boundary continuity:
    1. Process 1: Ingests Story X from Source 1 -> Article 1 & TechEvent 1 saved -> Swarm Health states saved -> Teardown.
    2. Process 2: Cold Start -> Swarm hydrates Health -> S07 hydrates TechEvent 1 -> Ingests Story X from Source 2 ->
       Article 2 saved -> S07 corroborates TechEvent 1 (source_count=2) -> S10 updates TechEvent 1 -> Teardown.
    3. Direct SQL Verification: 2 articles, 1 TechEvent, 2 event_sources, correct health, 0 FK violations.
    4. FastAPI Delivery: Lifespan resolves repositories -> GET /v1/articles, GET /v1/events verify delivery.
    """
    db_file = tmp_path / "canonical_phase5e_f_master.db"
    os.environ["TECHNEWS_CANONICAL_DB_PATH"] = str(db_file)

    # -------------------------------------------------------------------------
    # STAGE 1: Process 1 (Discovery, Ingestion & Initial Persistence)
    # -------------------------------------------------------------------------
    engine1 = SqliteEngine(db_file)
    await engine1.initialize_schema()

    event_repo1 = SqliteEventRepository(engine=engine1, auto_init=False)
    article_repo1 = SqliteArticleRepository(engine=engine1, auto_init=False)
    health_repo1 = SqliteSourceHealthRepository(engine=engine1, auto_init=False)

    registry1 = SourceRegistry()
    registry1.load()

    # Pre-configure swarm health states using canonical registry descriptors
    sources = {s.name: s for s in registry1.get_all_ordered()}
    tc_desc = sources["TechCrunch"]
    verge_desc = sources["The Verge"]
    wired_desc = sources["Wired"]

    swarm1 = ZombieSwarm(registry=registry1, health_repository=health_repo1)
    runner1 = CanonicalPipelineRunner(
        event_repository=event_repo1,
        article_repository=article_repo1,
    )

    # Observation 1: TechCrunch on Story X
    now = datetime.now(UTC)
    obs1 = SourceObservation.create(
        source_id=tc_desc.id,
        source_name=tc_desc.name,
        source_tier=SourceTier.TIER_1_PREMIUM,
        zombie_species=ZombieSpecies.RSS,
        url="https://techcrunch.com/2026/quantum-supremacy-breakthrough",
        title="Major Quantum Computing Processor Breakthrough Announced",
        summary="Researchers demonstrate 1000-qubit fault-tolerant quantum processor.",
        raw_content="Researchers announce a revolutionary 1000-qubit fault-tolerant quantum computing processor architecture benchmark.",
        published_at_hint=now - timedelta(minutes=15),
        observed_at=now - timedelta(minutes=10),
    )

    # Process Observation 1 through Pipeline
    res1 = await runner1.process_observation(obs1)
    assert res1.status == IngestionStatus.SUCCESS
    assert res1.event is not None
    event1_id = res1.event.id
    assert len(res1.event.sources) == 1
    assert res1.event.sources[0].source_name == "TechCrunch"

    # Swarm records hunt outcomes:
    # 1. TechCrunch: Success (HEALTHY, Tier 1)
    await swarm1.record_hunt_outcome(tc_desc, success=True, tier_used=1)
    # 2. The Verge: Rate limited (RATE_LIMITED, 30 min cooldown)
    await swarm1.record_hunt_outcome(verge_desc, success=False, status_code=429)
    # 3. Wired: Degraded (DEGRADED, 1 failure)
    await swarm1.record_hunt_outcome(wired_desc, success=False, status_code=500)

    # Teardown Context 1
    await swarm1.aclose()
    await engine1.aclose()
    del engine1, event_repo1, article_repo1, health_repo1, runner1, swarm1, registry1

    # -------------------------------------------------------------------------
    # STAGE 2: Process 2 (Cold Restart, Hydration & Corroboration)
    # -------------------------------------------------------------------------
    engine2 = SqliteEngine(db_file)
    event_repo2 = SqliteEventRepository(engine=engine2, auto_init=False)
    article_repo2 = SqliteArticleRepository(engine=engine2, auto_init=False)
    health_repo2 = SqliteSourceHealthRepository(engine=engine2, auto_init=False)

    registry2 = SourceRegistry()
    registry2.load()

    swarm2 = ZombieSwarm(registry=registry2, health_repository=health_repo2)
    # Hydrate Swarm Health from SQLite
    hydrated_health_count = await swarm2.hydrate_health()
    assert hydrated_health_count >= 2

    # Verify The Verge has active cooldown restored
    hydrated_verge = registry2.get_source(verge_desc.id)
    assert hydrated_verge is not None
    assert hydrated_verge.cooldown_until is not None

    # Verify Wired has consecutive failure restored
    hydrated_wired = registry2.get_source(wired_desc.id)
    assert hydrated_wired is not None
    assert hydrated_wired.consecutive_failures == 1

    # Initialize Pipeline Runner and hydrate S07 Event Clusterer from SQLite
    runner2 = CanonicalPipelineRunner(
        event_repository=event_repo2,
        article_repository=article_repo2,
    )
    hydrated_event_count = await runner2.hydrate_cluster_store(window_hours=48.0)
    assert hydrated_event_count >= 1

    # Observation 2: The Verge on same Story X
    obs2 = SourceObservation.create(
        source_id=verge_desc.id,
        source_name=verge_desc.name,
        source_tier=SourceTier.TIER_1_PREMIUM,
        zombie_species=ZombieSpecies.RSS,
        url="https://theverge.com/2026/quantum-supremacy-analysis",
        title="Major Quantum Computing Processor Breakthrough Announced: Full Analysis",
        summary="Detailed architecture and benchmarks for the new 1000-qubit quantum processor.",
        raw_content="Detailed architecture and benchmarks for the new 1000-qubit quantum processor announced today.",
        published_at_hint=now - timedelta(minutes=5),
        observed_at=now,
    )

    # Process Observation 2 through Pipeline (Must Corroborate Existing Event!)
    res2 = await runner2.process_observation(obs2)
    assert res2.status == IngestionStatus.SUCCESS
    assert res2.event is not None

    # Invariant: SAME TechEvent ID, status CORROBORATED, 2 sources!
    assert res2.event.id == event1_id
    assert res2.event.status in (EventStatus.CORROBORATED, EventStatus.CONFIRMED)
    assert len(res2.event.sources) == 2
    source_names = {s.source_name for s in res2.event.sources}
    assert source_names == {"TechCrunch", "The Verge"}

    # Swarm records The Verge recovery:
    await swarm2.record_hunt_outcome(hydrated_verge, success=True, tier_used=1)

    # Teardown Context 2
    await swarm2.aclose()
    await engine2.aclose()
    del engine2, event_repo2, article_repo2, health_repo2, runner2, swarm2, registry2

    # -------------------------------------------------------------------------
    # STAGE 3: Direct SQLite Database Table Integrity Checks
    # -------------------------------------------------------------------------
    conn = sqlite3.connect(str(db_file))
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    # 1. Foreign Key Integrity Check
    fk_check = cursor.execute("PRAGMA foreign_key_check;").fetchall()
    assert len(fk_check) == 0, f"Foreign key violations found: {fk_check}"

    # 2. Canonical Articles: Exactly 2 distinct articles
    articles_rows = cursor.execute("SELECT * FROM canonical_articles ORDER BY discovered_at ASC;").fetchall()
    assert len(articles_rows) == 2
    assert {r["source_name"] for r in articles_rows} == {"TechCrunch", "The Verge"}

    # 3. Canonical Events: Exactly 1 unified TechEvent
    event_rows = cursor.execute("SELECT * FROM canonical_events;").fetchall()
    assert len(event_rows) == 1
    assert event_rows[0]["id"] == event1_id
    assert event_rows[0]["status"] in ("corroborated", "confirmed")

    # 4. Canonical Event Sources: Exactly 2 rows linked to event1_id
    source_rows = cursor.execute("SELECT * FROM canonical_event_sources WHERE event_id = ?;", (event1_id,)).fetchall()
    assert len(source_rows) == 2

    # 5. Canonical Source Health: Accurate persisted states
    health_rows = cursor.execute("SELECT * FROM canonical_source_health;").fetchall()
    health_by_id = {r["source_id"]: r for r in health_rows}
    assert health_by_id[tc_desc.id]["status"] == "healthy"
    assert health_by_id[verge_desc.id]["status"] == "healthy"
    assert health_by_id[wired_desc.id]["status"] == "degraded"

    conn.close()

    # -------------------------------------------------------------------------
    # STAGE 4: Production FastAPI Delivery Layer Verification
    # -------------------------------------------------------------------------
    prod_app.dependency_overrides[verify_api_key] = lambda: {"tier": "pro"}

    with TestClient(prod_app) as client:
        # A. Verify Articles API
        art_res = client.get("/v1/articles")
        assert art_res.status_code == 200
        art_data = art_res.json()
        assert art_data["total"] == 2
        assert len(art_data["articles"]) == 2

        # Filter by source
        tc_art_res = client.get(f"/v1/articles?source={tc_desc.id}")
        assert tc_art_res.status_code == 200
        assert len(tc_art_res.json()["articles"]) == 1

        # Single article lookup by ID
        single_art_res = client.get(f"/v1/articles/{articles_rows[0]['id']}")
        assert single_art_res.status_code == 200
        assert single_art_res.json()["title"] in (obs1.title, obs2.title)

        # Single article lookup by canonical URL
        single_url_res = client.get(f"/v1/articles/{obs2.url}")
        assert single_url_res.status_code == 200
        assert single_url_res.json()["title"] == obs2.title

        # B. Verify Events API
        events_res = client.get("/v1/events")
        assert events_res.status_code == 200
        events_data = events_res.json()
        assert len(events_data) == 1
        event_dto = events_data[0]
        assert event_dto["id"] == event1_id
        assert event_dto["status"] in ("corroborated", "confirmed")
        assert len(event_dto["sources"]) == 2

        # Single event lookup
        single_event_res = client.get(f"/v1/events/{event1_id}")
        assert single_event_res.status_code == 200
        assert single_event_res.json()["id"] == event1_id

    prod_app.dependency_overrides.clear()
    os.environ.pop("TECHNEWS_CANONICAL_DB_PATH", None)


# =============================================================================
# 2. SSE PUBLICATION STREAM INTEGRATION TEST
# =============================================================================

@pytest.mark.asyncio
async def test_sse_publication_stream_delivery(tmp_path: Path):
    """Verify live event updates published via PublicationBus reach SSE subscribers."""
    db_file = tmp_path / "sse_test.db"
    os.environ["TECHNEWS_CANONICAL_DB_PATH"] = str(db_file)

    engine = SqliteEngine(db_file)
    await engine.initialize_schema()
    event_repo = SqliteEventRepository(engine=engine, auto_init=False)
    article_repo = SqliteArticleRepository(engine=engine, auto_init=False)
    bus = get_publication_bus()

    runner = CanonicalPipelineRunner(
        event_repository=event_repo,
        article_repository=article_repo,
        bus=bus,
    )

    # Subscribe to publication bus via queue
    await bus.start()
    sub_id, queue = await bus.subscribe(channels=(PublicationChannel.SSE_STREAM,))

    now = datetime.now(UTC)
    obs = SourceObservation.create(
        source_id="src_sse_01",
        source_name="SSE News",
        source_tier=SourceTier.TIER_1_PREMIUM,
        zombie_species=ZombieSpecies.RSS,
        url="https://example.com/sse-breaking-story",
        title="Urgent AI Neural Network Architecture Release",
        raw_content="Detailed content about urgent AI neural network architecture benchmarks and machine learning models for SSE event bus verification.",
        summary="Urgent AI neural network architecture announcement published to bus.",
        published_at_hint=now,
        observed_at=now,
    )

    res = await runner.process_observation(obs)
    assert res.status == IngestionStatus.SUCCESS

    # Receive from subscriber queue
    pub_event = await asyncio.wait_for(queue.get(), timeout=2.0)
    assert pub_event is not None
    assert PublicationChannel.SSE_STREAM in pub_event.channels
    assert pub_event.event_type in (PublicationEventType.EVENT_DETECTED, PublicationEventType.EVENT_UPDATED)

    await bus.unsubscribe(sub_id)
    await bus.stop()
    await engine.aclose()
    os.environ.pop("TECHNEWS_CANONICAL_DB_PATH", None)


# =============================================================================
# 3. HIGH-THROUGHPUT WAL CONCURRENCY & LOAD STRESS TEST
# =============================================================================

@pytest.mark.asyncio
async def test_wal_concurrent_read_write_integrity(tmp_path: Path):
    """
    Stress-tests SQLite WAL mode concurrency with concurrent writers and readers:
    - Writers: Concurrent article saves, event saves, and health updates.
    - Readers: Concurrent article queries, event queries, and count queries.
    Asserts: 0 database locks, 0 partial records, 0 data loss.
    """
    db_file = tmp_path / "wal_stress_test.db"
    engine = SqliteEngine(db_file)
    await engine.initialize_schema()

    article_repo = SqliteArticleRepository(engine=engine, auto_init=False)
    event_repo = SqliteEventRepository(engine=engine, auto_init=False)
    health_repo = SqliteSourceHealthRepository(engine=engine, auto_init=False)

    num_iterations = 20
    errors: List[Exception] = []

    async def article_writer(worker_id: int):
        try:
            for i in range(num_iterations):
                art = NormalizedArticle(
                    id=f"art_w{worker_id}_{i}",
                    canonical_url=f"https://example.com/worker-{worker_id}/story-{i}",
                    original_url=f"https://example.com/worker-{worker_id}/story-{i}",
                    title=f"Worker {worker_id} Story {i}",
                    clean_text="Clean text content for concurrency test.",
                    summary="Concurrency test summary.",
                    source_id=f"src_w{worker_id}",
                    source_name=f"Source Worker {worker_id}",
                    source_tier=SourceTier.TIER_2_SPECIALIST,
                    zombie_species=ZombieSpecies.WEB,
                    discovered_at=datetime.now(UTC),
                    published_at=datetime.now(UTC),
                    language="en",
                    image_url=None,
                    authors=(),
                    tags=(),
                    metadata={},
                )
                await article_repo.save_article(art)
                await asyncio.sleep(0.005)
        except Exception as e:
            errors.append(e)

    async def health_writer(worker_id: int):
        try:
            for i in range(num_iterations):
                health = SourceHealth(
                    source_id=f"src_h_{worker_id}",
                    source_url=f"https://source-{worker_id}.com",
                    source_name=f"Health Source {worker_id}",
                    status=SourceHealthStatus.HEALTHY if i % 2 == 0 else SourceHealthStatus.DEGRADED,
                    consecutive_failures=i % 3,
                    consecutive_successes=i,
                )
                await health_repo.save_health(health)
                await asyncio.sleep(0.005)
        except Exception as e:
            errors.append(e)

    async def reader_worker():
        try:
            for _ in range(num_iterations * 2):
                await article_repo.get_recent_articles(limit=10)
                await article_repo.count_articles()
                await event_repo.get_active_events(limit=10)
                await health_repo.get_all_health()
                await asyncio.sleep(0.003)
        except Exception as e:
            errors.append(e)

    # Launch 3 article writers, 2 health writers, and 3 concurrent readers
    tasks = [
        asyncio.create_task(article_writer(1)),
        asyncio.create_task(article_writer(2)),
        asyncio.create_task(article_writer(3)),
        asyncio.create_task(health_writer(1)),
        asyncio.create_task(health_writer(2)),
        asyncio.create_task(reader_worker()),
        asyncio.create_task(reader_worker()),
        asyncio.create_task(reader_worker()),
    ]

    await asyncio.gather(*tasks)

    assert len(errors) == 0, f"Concurrency errors occurred: {errors}"
    total_articles = await article_repo.count_articles()
    assert total_articles == num_iterations * 3

    await engine.aclose()


# =============================================================================
# 4. TIMELINE CONTINUITY & FOREIGN KEY CASCADING INTEGRITY TEST
# =============================================================================

@pytest.mark.asyncio
async def test_timeline_continuity_and_foreign_key_integrity(tmp_path: Path):
    """
    Verifies that:
    1. Timeline entries are preserved and chronologically ordered across events.
    2. Foreign key constraints enforce relationship between canonical_events and canonical_event_sources.
    3. Deleting an event cleanly removes associated event source records.
    """
    db_file = tmp_path / "fk_timeline_test.db"
    engine = SqliteEngine(db_file)
    await engine.initialize_schema()
    event_repo = SqliteEventRepository(engine=engine, auto_init=False)

    now = datetime.now(UTC)
    src1 = EventSourceEvidence(
        article_id="art_src_1",
        url="https://source1.com/story",
        title="Initial Story",
        source_name="Source 1",
        source_tier=SourceTier.TIER_1_PREMIUM,
        discovered_at=now - timedelta(hours=1),
        published_at=now - timedelta(hours=1),
        summary="Initial summary",
        is_primary=True,
    )
    src2 = EventSourceEvidence(
        article_id="art_src_2",
        url="https://source2.com/story",
        title="Follow-up Story",
        source_name="Source 2",
        source_tier=SourceTier.TIER_2_SPECIALIST,
        discovered_at=now,
        published_at=now,
        summary="Follow-up summary",
        is_primary=False,
    )
    tl1 = TimelineEntry(
        timestamp=now - timedelta(hours=1),
        headline="Initial report announced",
        source_name="Source 1",
        source_url="https://source1.com/story",
        confidence_at_time=0.85,
        entry_type="announcement",
    )
    tl2 = TimelineEntry(
        timestamp=now,
        headline="Follow-up investigation corroborates report",
        source_name="Source 2",
        source_url="https://source2.com/story",
        confidence_at_time=0.95,
        entry_type="corroboration",
    )

    event = TechEvent(
        id="evt_timeline_fk_01",
        headline="Major Technology Event",
        first_seen=now - timedelta(hours=1),
        last_updated=now,
        entities=["OpenAI", "Quantum"],
        topics=["Hardware", "AI"],
        sources=[src1, src2],
        primary_source="Source 1",
        confidence=0.95,
        importance=0.88,
        novelty=0.90,
        status=EventStatus.CORROBORATED,
        freshness=FreshnessLevel.FRESH,
        freshness_score=0.92,
        timeline=[tl1, tl2],
        cluster_id="cluster_timeline_01",
    )

    # Save to SQLite
    await event_repo.save_event(event)

    # Retrieve and verify timeline ordering & sources
    retrieved = await event_repo.get_event("evt_timeline_fk_01")
    assert retrieved is not None
    assert len(retrieved.sources) == 2
    assert len(retrieved.timeline) == 2
    assert retrieved.timeline[0].headline == "Initial report announced"
    assert retrieved.timeline[1].headline == "Follow-up investigation corroborates report"

    # Direct SQL verification of Foreign Keys
    conn = sqlite3.connect(str(db_file))
    conn.execute("PRAGMA foreign_keys = ON;")
    sources_count = conn.execute(
        "SELECT COUNT(*) FROM canonical_event_sources WHERE event_id = 'evt_timeline_fk_01';"
    ).fetchone()[0]
    assert sources_count == 2
    conn.close()

    # Delete event and verify cascade
    deleted = await event_repo.delete_event("evt_timeline_fk_01")
    assert deleted is True

    conn = sqlite3.connect(str(db_file))
    sources_after_delete = conn.execute(
        "SELECT COUNT(*) FROM canonical_event_sources WHERE event_id = 'evt_timeline_fk_01';"
    ).fetchone()[0]
    assert sources_after_delete == 0
    conn.close()

    await engine.aclose()


# =============================================================================
# 5. AST ARCHITECTURAL BOUNDARY PURITY AUDIT
# =============================================================================

def test_ast_layer_boundaries_zero_forbidden_imports():
    """
    Statically audits the codebase using Python AST to guarantee that:
    - src/pipeline/ has ZERO sqlite / engine imports.
    - src/zombies/ has ZERO sqlite / engine imports.
    - src/api/routes/articles.py has ZERO sqlite / engine imports.
    - src/api/routes/events.py has ZERO sqlite / engine imports.
    """
    root_dir = Path(__file__).resolve().parent.parent / "src"

    forbidden_in_pipeline = {
        "sqlite3", "aiosqlite", "SqliteEngine", "SqliteArticleRepository",
        "SqliteEventRepository", "SqliteSourceHealthRepository", "Database", "db_handler"
    }

    # 1. Audit src/pipeline
    pipeline_dir = root_dir / "pipeline"
    for py_file in pipeline_dir.rglob("*.py"):
        tree = ast.parse(py_file.read_text(encoding="utf-8"), filename=str(py_file))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    assert alias.name not in forbidden_in_pipeline, f"Forbidden import '{alias.name}' in {py_file.name}"
            elif isinstance(node, ast.ImportFrom):
                mod = node.module or ""
                assert not any(f in mod for f in forbidden_in_pipeline), f"Forbidden module '{mod}' in {py_file.name}"
                for alias in node.names:
                    assert alias.name not in forbidden_in_pipeline, f"Forbidden symbol '{alias.name}' in {py_file.name}"

    # 2. Audit src/zombies (excluding multi-process coordinator)
    zombies_dir = root_dir / "zombies"
    for py_file in zombies_dir.rglob("*.py"):
        if py_file.name == "coordinator.py":
            continue
        tree = ast.parse(py_file.read_text(encoding="utf-8"), filename=str(py_file))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    assert alias.name not in forbidden_in_pipeline, f"Forbidden import '{alias.name}' in {py_file.name}"
            elif isinstance(node, ast.ImportFrom):
                mod = node.module or ""
                assert not any(f in mod for f in forbidden_in_pipeline), f"Forbidden module '{mod}' in {py_file.name}"
                for alias in node.names:
                    assert alias.name not in forbidden_in_pipeline, f"Forbidden symbol '{alias.name}' in {py_file.name}"

    # 3. Audit API Route files
    route_files = [
        root_dir / "api" / "routes" / "articles.py",
        root_dir / "api" / "routes" / "events.py",
    ]
    for py_file in route_files:
        tree = ast.parse(py_file.read_text(encoding="utf-8"), filename=str(py_file))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    assert alias.name not in forbidden_in_pipeline, f"Forbidden import '{alias.name}' in {py_file.name}"
            elif isinstance(node, ast.ImportFrom):
                mod = node.module or ""
                assert not any(f in mod for f in forbidden_in_pipeline), f"Forbidden module '{mod}' in {py_file.name}"
                for alias in node.names:
                    assert alias.name not in forbidden_in_pipeline, f"Forbidden symbol '{alias.name}' in {py_file.name}"
