"""
Unit & Integration Tests for Phase 5C: Pipeline Persistence Integration & S07 Hydration.
Location: tests/test_persistence_hydration.py

Verifies:
- S10 PersistenceStage asynchronous persistence via EventRepositoryProtocol
- S10 error propagation on repository failure
- S07 ActiveEventStore cold-start hydration within temporal window
- S07 index/shingle precomputation during hydration
- Hydration idempotency (calling hydrate multiple times)
- Window bounds enforcement (events older than window_hours excluded)
- Full daemon restart simulation:
    Runner 1 -> Ingest Observation -> S10 Persist -> Destroy
    Runner 2 -> Cold Start -> Hydrate S07 -> Ingest Corroboration -> S07 Corroboration Matched
- Architecture boundaries (S07 and S10 have zero imports of sqlite3/aiosqlite/SqliteEventRepository)
"""

import ast
from datetime import datetime, UTC, timedelta
from pathlib import Path
import pytest

from src.domain.enums import EventStatus, FreshnessLevel, SourceTier, ZombieSpecies
from src.domain.models import EventSourceEvidence, SourceObservation, TechEvent, TimelineEntry
from src.pipeline.protocols import PipelineContext
from src.pipeline.runner import CanonicalPipelineRunner, IngestionStatus
from src.pipeline.stages.s07_clustering import ActiveEventStore, EventClusterer
from src.pipeline.stages.s10_persistence import PersistenceStage
from src.storage.sqlite_engine import SqliteEngine
from src.storage.sqlite_event_repository import SqliteEventRepository


@pytest.fixture
def temp_db_path(tmp_path: Path) -> Path:
    """Provide an isolated database path."""
    return tmp_path / "test_5c_canonical.db"


@pytest.fixture
async def repo(temp_db_path: Path) -> SqliteEventRepository:
    """Provide an initialized SqliteEventRepository."""
    engine = SqliteEngine(temp_db_path)
    repository = SqliteEventRepository(engine=engine, auto_init=True)
    yield repository
    await engine.aclose()


def make_test_event(
    event_id: str = "evt_5c_test_01",
    headline: str = "Major Artificial Intelligence Model Breakthrough",
    offset_hours: float = 0.0,
) -> TechEvent:
    """Construct a canonical TechEvent for hydration tests."""
    now = datetime.now(UTC) - timedelta(hours=offset_hours)
    src = EventSourceEvidence(
        article_id="art_5c_01",
        url=f"https://example.com/events/{event_id}",
        title="AI Breakthrough Coverage",
        source_name="TechDaily",
        source_tier=SourceTier.TIER_1_PREMIUM,
        discovered_at=now,
    )
    tl = TimelineEntry(
        timestamp=now,
        headline="Initial disclosure",
        source_name="TechDaily",
        source_url=f"https://example.com/events/{event_id}",
        confidence_at_time=0.80,
    )
    return TechEvent(
        id=event_id,
        headline=headline,
        first_seen=now,
        last_updated=now,
        entities=["OpenAI", "Anthropic"],
        topics=["Artificial Intelligence", "Deep Learning"],
        sources=[src],
        primary_source="TechDaily",
        confidence=0.85,
        importance=0.80,
        novelty=0.90,
        status=EventStatus.CORROBORATED,
        freshness=FreshnessLevel.FRESH,
        freshness_score=0.90,
        timeline=[tl],
        cluster_id=f"cluster_{event_id}",
    )


@pytest.mark.asyncio
async def test_s10_persistence_asynchronous_save(repo: SqliteEventRepository):
    """Verify S10 calls repository.save_event() and populates context metadata."""
    stage = PersistenceStage(repository=repo)
    event = make_test_event(event_id="evt_s10_direct")
    context = PipelineContext(correlation_id=event.id)

    processed = await stage.process(event, context)
    assert processed is event
    assert context.get("persisted_at") is not None

    # Verify event exists in underlying database
    persisted = await repo.get_event("evt_s10_direct")
    assert persisted is not None
    assert persisted.headline == event.headline
    assert len(persisted.sources) == 1


@pytest.mark.asyncio
async def test_s10_persistence_error_propagation():
    """Verify that a repository failure in S10 raises an exception and does not claim success."""
    class FailingRepo:
        async def save_event(self, event: TechEvent) -> None:
            raise RuntimeError("Database connection severed")

    stage = PersistenceStage(repository=FailingRepo())  # type: ignore
    event = make_test_event(event_id="evt_s10_fail")
    context = PipelineContext(correlation_id=event.id)

    with pytest.raises(RuntimeError, match="Database connection severed"):
        await stage.process(event, context)

    assert context.get("persisted_at") is None


@pytest.mark.asyncio
async def test_s07_hydration_populates_store_and_shingles(repo: SqliteEventRepository):
    """Verify S07 ActiveEventStore hydrates events and precomputes title shingles."""
    # Pre-populate repository with 3 events
    e1 = make_test_event(event_id="evt_hyd_1", headline="Quantum Computer Breakthrough", offset_hours=2.0)
    e2 = make_test_event(event_id="evt_hyd_2", headline="New Semiconductor Architecture Announced", offset_hours=10.0)
    e3 = make_test_event(event_id="evt_hyd_3", headline="Autonomous Drone Navigation System", offset_hours=20.0)

    await repo.save_event(e1)
    await repo.save_event(e2)
    await repo.save_event(e3)

    # Empty store
    store = ActiveEventStore(window_hours=48.0)
    assert len(store) == 0

    # Hydrate
    hydrated_count = await store.hydrate(repository=repo, window_hours=48.0)
    assert hydrated_count == 3
    assert len(store) == 3

    # Verify events and shingles
    assert store.get_event("evt_hyd_1") is not None
    assert store.get_event("evt_hyd_2") is not None
    assert store.get_event("evt_hyd_3") is not None
    assert "evt_hyd_1" in store._event_shingles
    assert len(store._event_shingles["evt_hyd_1"]) > 0


@pytest.mark.asyncio
async def test_s07_hydration_respects_temporal_window(repo: SqliteEventRepository):
    """Verify S07 hydration strictly excludes events older than window_hours."""
    now = datetime.now(UTC)
    e_recent = make_test_event(event_id="evt_win_recent", offset_hours=12.0)
    e_expired = make_test_event(event_id="evt_win_expired", offset_hours=60.0)  # 60h > 48h window

    await repo.save_event(e_recent)
    await repo.save_event(e_expired)

    store = ActiveEventStore(window_hours=48.0)
    hydrated_count = await store.hydrate(repository=repo, window_hours=48.0)

    assert hydrated_count == 1
    assert len(store) == 1
    assert store.get_event("evt_win_recent") is not None
    assert store.get_event("evt_win_expired") is None


@pytest.mark.asyncio
async def test_s07_hydration_idempotency(repo: SqliteEventRepository):
    """Verify calling hydrate() multiple times does not duplicate or corrupt store."""
    e1 = make_test_event(event_id="evt_idem_1", offset_hours=1.0)
    await repo.save_event(e1)

    store = ActiveEventStore(window_hours=48.0)
    await store.hydrate(repository=repo)
    assert len(store) == 1

    # Call hydrate a second and third time
    await store.hydrate(repository=repo)
    await store.hydrate(repository=repo)
    assert len(store) == 1
    assert store.get_event("evt_idem_1") is not None


@pytest.mark.asyncio
async def test_full_pipeline_restart_simulation(temp_db_path: Path):
    """
    Simulate full system lifecycle across restarts:
    1. Boot Runner 1 with SQLite EventRepository.
    2. Process Observation 1 -> Passes S01-S11 -> S10 persists to SQLite.
    3. Destroy Runner 1.
    4. Boot Runner 2 with same SQLite database -> Call hydrate_cluster_store().
    5. Verify S07 active store contains the previously persisted event.
    6. Process Observation 2 (corroborating article on same story) -> Matches cluster -> S10 updates DB.
    7. Verify database contains 1 consolidated event with 2 sources.
    """
    engine = SqliteEngine(temp_db_path)
    repo1 = SqliteEventRepository(engine=engine, auto_init=True)

    # -------------------------------------------------------------
    # RUN 1: Ingest Initial Story
    # -------------------------------------------------------------
    runner1 = CanonicalPipelineRunner(event_repository=repo1)
    obs1 = SourceObservation.create(
        source_id="src_techcrunch",
        source_name="TechCrunch",
        source_tier=SourceTier.TIER_1_PREMIUM,
        zombie_species=ZombieSpecies.RSS,
        url="https://techcrunch.com/2026/openai-gpt5-release",
        title="OpenAI Officially Unveils GPT-5 Architecture",
        summary="OpenAI has announced GPT-5 with multimodal reasoning capabilities.",
        raw_content="OpenAI has announced GPT-5 with multimodal reasoning capabilities and autonomous tools.",
        published_at_hint=datetime.now(UTC),
    )

    res1 = await runner1.process_observation(obs1)
    assert res1.status == IngestionStatus.SUCCESS
    assert res1.event is not None
    created_event_id = res1.event.id

    # Verify event is in SQLite
    persisted_v1 = await repo1.get_event(created_event_id)
    assert persisted_v1 is not None
    assert persisted_v1.source_count == 1
    assert persisted_v1.sources[0].url == "https://techcrunch.com/2026/openai-gpt5-release"

    # -------------------------------------------------------------
    # RESTART: Destroy Runner 1 & Create Runner 2
    # -------------------------------------------------------------
    del runner1
    del repo1

    repo2 = SqliteEventRepository(engine=engine, auto_init=False)
    runner2 = CanonicalPipelineRunner(event_repository=repo2)

    # Hydrate on startup
    hydrated_count = await runner2.hydrate_cluster_store(window_hours=48.0)
    assert hydrated_count == 1
    assert len(runner2.event_store) == 1
    assert runner2.event_store.get_event(created_event_id) is not None

    # -------------------------------------------------------------
    # RUN 2: Ingest Corroborating Story
    # -------------------------------------------------------------
    obs2 = SourceObservation.create(
        source_id="src_theverge",
        source_name="The Verge",
        source_tier=SourceTier.TIER_2_SPECIALIST,
        zombie_species=ZombieSpecies.WEB,
        url="https://theverge.com/2026/openai-gpt5-hands-on",
        title="OpenAI Officially Unveils GPT-5 Architecture: Hands On",
        summary="Hands-on analysis of OpenAI's new GPT-5 model launch.",
        raw_content="Hands-on analysis of OpenAI's new GPT-5 model launch and benchmark performance.",
        published_at_hint=datetime.now(UTC),
    )

    res2 = await runner2.process_observation(obs2)
    assert res2.status == IngestionStatus.SUCCESS
    assert res2.event is not None
    assert res2.event.id == created_event_id  # Clustered into same TechEvent!
    assert res2.event.source_count == 2

    # Verify SQLite contains the updated aggregate with both sources
    persisted_v2 = await repo2.get_event(created_event_id)
    assert persisted_v2 is not None
    assert persisted_v2.source_count == 2
    source_urls = {s.url for s in persisted_v2.sources}
    assert "https://techcrunch.com/2026/openai-gpt5-release" in source_urls
    assert "https://theverge.com/2026/openai-gpt5-hands-on" in source_urls

    await engine.aclose()


def test_architecture_boundaries_s07_s10_no_sqlite_imports():
    """Verify AST of s07_clustering.py and s10_persistence.py contains zero sqlite/aiosqlite imports."""
    forbidden = {"sqlite3", "aiosqlite", "SqliteEventRepository", "SqliteEngine"}

    files_to_check = [
        Path("src/pipeline/stages/s07_clustering.py"),
        Path("src/pipeline/stages/s10_persistence.py"),
        Path("src/pipeline/runner.py"),
    ]

    for file_path in files_to_check:
        assert file_path.exists(), f"File missing: {file_path}"
        tree = ast.parse(file_path.read_text(encoding="utf-8"))

        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    for bad in forbidden:
                        assert bad not in alias.name, f"{file_path} imports forbidden '{alias.name}'"
            elif isinstance(node, ast.ImportFrom):
                module = node.module or ""
                for bad in forbidden:
                    assert bad not in module, f"{file_path} imports from forbidden '{module}'"
                for alias in node.names:
                    for bad in forbidden:
                        assert bad != alias.name, f"{file_path} imports forbidden symbol '{alias.name}'"
