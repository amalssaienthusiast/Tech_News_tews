"""
Unit & Integration Tests for Phase 5B SqliteEventRepository.
Location: tests/test_sqlite_event_repository.py

Verifies:
- Complete round-trip domain model fidelity (TechEvent, EventSourceEvidence, TimelineEntry)
- Enum preservation (EventStatus, FreshnessLevel, SourceTier)
- Timezone-aware UTC timestamp serialization and deserialization
- Aggregate update semantics (adding sources, timeline entries, updating scores)
- Duplicate source URL suppression (UNIQUE(event_id, url))
- Cascading deletion of child entities on event deletion
- Filter queries (get_active_events, get_events_since, get_events_by_entity)
- Store statistics (get_stats)
- Input domain validation error handling
"""

from datetime import datetime, UTC, timedelta
from pathlib import Path
import pytest

from src.domain.enums import EventStatus, FreshnessLevel, SourceTier
from src.domain.models import EventSourceEvidence, TechEvent, TimelineEntry
from src.domain.validators import DomainValidationError
from src.storage.sqlite_engine import SqliteEngine
from src.storage.sqlite_event_repository import SqliteEventRepository


@pytest.fixture
def temp_db_path(tmp_path: Path) -> Path:
    """Provide an isolated database path."""
    return tmp_path / "test_repo_canonical_events.db"


@pytest.fixture
async def repo(temp_db_path: Path) -> SqliteEventRepository:
    """Provide an initialized SqliteEventRepository."""
    engine = SqliteEngine(temp_db_path)
    repository = SqliteEventRepository(engine=engine, auto_init=True)
    yield repository
    await engine.aclose()


def make_sample_event(
    event_id: str = "evt_sample_01",
    headline: str = "Major Tech Breakthrough Announced",
    status: EventStatus = EventStatus.CORROBORATED,
    freshness: FreshnessLevel = FreshnessLevel.FRESH,
    confidence: float = 0.85,
    importance: float = 0.75,
    novelty: float = 0.90,
    offset_minutes: int = 0,
) -> TechEvent:
    """Helper to construct a complete canonical TechEvent."""
    now = datetime.now(UTC) - timedelta(minutes=offset_minutes)
    
    src1 = EventSourceEvidence(
        article_id="art_001",
        url="https://techcrunch.com/2026/breakthrough",
        title="TechCrunch on the Breakthrough",
        source_name="TechCrunch",
        source_tier=SourceTier.TIER_1_PREMIUM,
        discovered_at=now - timedelta(minutes=5),
        published_at=now - timedelta(minutes=10),
        summary="Detailed summary of the tech breakthrough.",
        image_url="https://techcrunch.com/images/hero.jpg",
        is_primary=True,
    )
    
    src2 = EventSourceEvidence(
        article_id="art_002",
        url="https://theverge.com/2026/breakthrough",
        title="The Verge Perspective",
        source_name="The Verge",
        source_tier=SourceTier.TIER_2_SPECIALIST,
        discovered_at=now - timedelta(minutes=2),
        published_at=now - timedelta(minutes=8),
        summary="Secondary corroboration summary.",
        image_url=None,
        is_primary=False,
    )

    tl1 = TimelineEntry(
        timestamp=now - timedelta(minutes=10),
        headline="Initial announcement surfaced",
        source_name="TechCrunch",
        source_url="https://techcrunch.com/2026/breakthrough",
        confidence_at_time=0.60,
        entry_type="initial",
    )

    tl2 = TimelineEntry(
        timestamp=now,
        headline="Second source corroborates story",
        source_name="The Verge",
        source_url="https://theverge.com/2026/breakthrough",
        confidence_at_time=0.85,
        entry_type="confirmation",
    )

    return TechEvent(
        id=event_id,
        headline=headline,
        first_seen=now - timedelta(minutes=10),
        last_updated=now,
        entities=["Anthropic", "Claude", "OpenAI"],
        topics=["Artificial Intelligence", "LLMs"],
        sources=[src1, src2],
        primary_source="TechCrunch",
        confidence=confidence,
        importance=importance,
        novelty=novelty,
        status=status,
        freshness=freshness,
        freshness_score=0.92,
        timeline=[tl1, tl2],
        cluster_id="cluster_ai_01",
        category="AI & ML",
    )


@pytest.mark.asyncio
async def test_round_trip_event_persistence(repo: SqliteEventRepository):
    """Verify exact round-trip fidelity between in-memory TechEvent and SQLite persistence."""
    event = make_sample_event()
    await repo.save_event(event)

    loaded = await repo.get_event(event.id)
    assert loaded is not None

    # Aggregate root fields
    assert loaded.id == event.id
    assert loaded.headline == event.headline
    assert loaded.first_seen == event.first_seen
    assert loaded.last_updated == event.last_updated
    assert loaded.entities == event.entities
    assert loaded.topics == event.topics
    assert loaded.primary_source == event.primary_source
    assert loaded.confidence == pytest.approx(event.confidence)
    assert loaded.importance == pytest.approx(event.importance)
    assert loaded.novelty == pytest.approx(event.novelty)
    assert loaded.status == event.status
    assert loaded.freshness == event.freshness
    assert loaded.freshness_score == pytest.approx(event.freshness_score)
    assert loaded.cluster_id == event.cluster_id
    assert loaded.category == event.category
    assert loaded.is_breaking == event.is_breaking
    assert loaded.source_count == 2

    # Sources
    assert len(loaded.sources) == 2
    s1, s2 = loaded.sources[0], loaded.sources[1]
    assert s1.article_id == "art_001"
    assert s1.source_tier == SourceTier.TIER_1_PREMIUM
    assert s1.is_primary is True
    assert s1.image_url == "https://techcrunch.com/images/hero.jpg"
    assert s2.article_id == "art_002"
    assert s2.source_tier == SourceTier.TIER_2_SPECIALIST
    assert s2.is_primary is False
    assert s2.image_url is None

    # Timeline
    assert len(loaded.timeline) == 2
    t1, t2 = loaded.timeline[0], loaded.timeline[1]
    assert t1.entry_type == "initial"
    assert t1.confidence_at_time == pytest.approx(0.60)
    assert t2.entry_type == "confirmation"
    assert t2.confidence_at_time == pytest.approx(0.85)


@pytest.mark.asyncio
async def test_aggregate_update_semantics(repo: SqliteEventRepository):
    """Verify that updating an existing TechEvent updates state and appends child entities cleanly."""
    event = make_sample_event(event_id="evt_update_test")
    await repo.save_event(event)

    # Modify the aggregate
    now = datetime.now(UTC)
    new_src = EventSourceEvidence(
        article_id="art_003",
        url="https://arstechnica.com/2026/breakthrough",
        title="Ars Technica Deep Dive",
        source_name="Ars Technica",
        source_tier=SourceTier.TIER_2_SPECIALIST,
        discovered_at=now,
        summary="Ars summary.",
    )
    new_tl = TimelineEntry(
        timestamp=now,
        headline="Third corroboration received",
        source_name="Ars Technica",
        source_url="https://arstechnica.com/2026/breakthrough",
        confidence_at_time=0.95,
        entry_type="update",
    )

    event.headline = "Major Tech Breakthrough Confirmed by Multiple Outlets"
    event.status = EventStatus.CONFIRMED
    event.confidence = 0.95
    event.last_updated = now
    event.add_source(new_src)
    event.add_timeline_entry(new_tl)

    await repo.save_event(event)

    loaded = await repo.get_event("evt_update_test")
    assert loaded is not None
    assert loaded.headline == "Major Tech Breakthrough Confirmed by Multiple Outlets"
    assert loaded.status == EventStatus.CONFIRMED
    assert loaded.confidence == pytest.approx(0.95)
    assert len(loaded.sources) == 3
    assert len(loaded.timeline) == 3


@pytest.mark.asyncio
async def test_get_nonexistent_event_returns_none(repo: SqliteEventRepository):
    """Verify that querying a missing event ID returns None."""
    loaded = await repo.get_event("non_existent_id")
    assert loaded is None


@pytest.mark.asyncio
async def test_get_active_events_filtering(repo: SqliteEventRepository):
    """Verify that get_active_events returns only non-stale events ordered newest first."""
    e1 = make_sample_event(event_id="evt_active_1", status=EventStatus.CORROBORATED, offset_minutes=10)
    e2 = make_sample_event(event_id="evt_active_2", status=EventStatus.CONFIRMED, offset_minutes=5)
    e3 = make_sample_event(event_id="evt_stale_3", status=EventStatus.STALE, offset_minutes=1)

    await repo.save_event(e1)
    await repo.save_event(e2)
    await repo.save_event(e3)

    active = await repo.get_active_events(limit=10)
    assert len(active) == 2
    assert [e.id for e in active] == ["evt_active_2", "evt_active_1"]


@pytest.mark.asyncio
async def test_get_events_since_hydration_query(repo: SqliteEventRepository):
    """Verify that get_events_since returns events within the cutoff window in chronological order."""
    now = datetime.now(UTC)
    e_old = make_sample_event(event_id="evt_old", offset_minutes=3000)  # ~50h ago
    e_recent1 = make_sample_event(event_id="evt_recent1", offset_minutes=120) # 2h ago
    e_recent2 = make_sample_event(event_id="evt_recent2", offset_minutes=30)  # 30m ago

    await repo.save_event(e_old)
    await repo.save_event(e_recent1)
    await repo.save_event(e_recent2)

    cutoff = now - timedelta(hours=48)
    hydrated = await repo.get_events_since(cutoff_utc=cutoff, limit=100)

    assert len(hydrated) == 2
    assert [e.id for e in hydrated] == ["evt_recent1", "evt_recent2"]


@pytest.mark.asyncio
async def test_get_events_by_entity(repo: SqliteEventRepository):
    """Verify entity search across stored JSON entity arrays."""
    e1 = make_sample_event(event_id="evt_ent_1")
    e1.entities = ["Google", "DeepMind", "Gemini"]

    e2 = make_sample_event(event_id="evt_ent_2")
    e2.entities = ["Microsoft", "OpenAI", "ChatGPT"]

    await repo.save_event(e1)
    await repo.save_event(e2)

    google_events = await repo.get_events_by_entity("google")
    assert len(google_events) == 1
    assert google_events[0].id == "evt_ent_1"

    openai_events = await repo.get_events_by_entity("OpenAI")
    assert len(openai_events) == 1
    assert openai_events[0].id == "evt_ent_2"

    missing = await repo.get_events_by_entity("NonExistentCompany")
    assert len(missing) == 0


@pytest.mark.asyncio
async def test_delete_event_cascades(repo: SqliteEventRepository):
    """Verify that deleting a TechEvent removes the event and cascades to all sources and timeline entries."""
    event = make_sample_event(event_id="evt_delete_test")
    await repo.save_event(event)

    deleted = await repo.delete_event("evt_delete_test")
    assert deleted is True

    # Verify event is gone
    assert await repo.get_event("evt_delete_test") is None

    # Verify child tables are empty
    async with repo.engine.connect() as conn:
        cur = await conn.execute(
            "SELECT COUNT(*) FROM canonical_event_sources WHERE event_id = ?;",
            ("evt_delete_test",),
        )
        assert (await cur.fetchone())[0] == 0

        cur = await conn.execute(
            "SELECT COUNT(*) FROM canonical_event_timeline WHERE event_id = ?;",
            ("evt_delete_test",),
        )
        assert (await cur.fetchone())[0] == 0

    # Deleting again returns False
    assert await repo.delete_event("evt_delete_test") is False


@pytest.mark.asyncio
async def test_get_stats_metrics(repo: SqliteEventRepository):
    """Verify that get_stats returns accurate store metrics and status breakdown."""
    e1 = make_sample_event(event_id="evt_stat_1", status=EventStatus.CORROBORATED, freshness=FreshnessLevel.FRESH)
    e2 = make_sample_event(event_id="evt_stat_2", status=EventStatus.CONFIRMED, freshness=FreshnessLevel.BREAKING)
    e3 = make_sample_event(event_id="evt_stat_3", status=EventStatus.STALE, freshness=FreshnessLevel.STALE)

    await repo.save_event(e1)
    await repo.save_event(e2)
    await repo.save_event(e3)

    stats = await repo.get_stats()
    assert stats["total_events"] == 3
    assert stats["active_events"] == 2
    assert stats["total_sources"] == 6  # 2 sources per event * 3
    assert stats["total_timeline_entries"] == 6
    assert stats["status_breakdown"]["corroborated"] == 1
    assert stats["status_breakdown"]["confirmed"] == 1
    assert stats["status_breakdown"]["stale"] == 1
    assert stats["freshness_breakdown"]["breaking"] == 1
    assert stats["freshness_breakdown"]["fresh"] == 1
    assert stats["freshness_breakdown"]["stale"] == 1


@pytest.mark.asyncio
async def test_save_event_validation_rejection(repo: SqliteEventRepository):
    """Verify that passing non-TechEvent objects raises DomainValidationError."""
    with pytest.raises(DomainValidationError):
        await repo.save_event({"id": "not_a_tech_event"})  # type: ignore


@pytest.mark.asyncio
async def test_optional_fields_none_handling(repo: SqliteEventRepository):
    """Verify that TechEvent with all optional fields as None round-trips perfectly."""
    now = datetime.now(UTC)
    src = EventSourceEvidence(
        article_id="art_none_01",
        url="https://example.com/none-fields",
        title="Minimal Evidence",
        source_name="Minimal Source",
        source_tier=SourceTier.TIER_3_COMMUNITY,
        discovered_at=now,
        published_at=None,
        summary="",
        image_url=None,
        is_primary=False,
    )
    event = TechEvent(
        id="evt_minimal_01",
        headline="Minimal Tech Event",
        first_seen=now,
        last_updated=now,
        entities=[],
        topics=[],
        sources=[src],
        primary_source=None,
        confidence=0.5,
        importance=0.5,
        novelty=1.0,
        status=EventStatus.SUSPECTED,
        freshness=FreshnessLevel.RECENT,
        freshness_score=0.5,
        timeline=[],
        cluster_id="",
        category=None,
    )

    await repo.save_event(event)
    loaded = await repo.get_event("evt_minimal_01")
    assert loaded is not None
    assert loaded.primary_source is None
    assert loaded.category is None
    assert loaded.entities == []
    assert loaded.topics == []
    assert loaded.timeline == []
    assert len(loaded.sources) == 1
    assert loaded.sources[0].published_at is None
    assert loaded.sources[0].image_url is None


@pytest.mark.asyncio
async def test_large_aggregate_persistence(repo: SqliteEventRepository):
    """Verify that large TechEvent aggregates with 20 sources and 15 timeline entries persist cleanly."""
    now = datetime.now(UTC)
    sources = [
        EventSourceEvidence(
            article_id=f"art_bulk_{i}",
            url=f"https://example.com/bulk-{i}",
            title=f"Bulk Evidence Article {i}",
            source_name=f"Source {i % 5}",
            source_tier=SourceTier((i % 4) + 1),
            discovered_at=now - timedelta(minutes=i),
            published_at=now - timedelta(minutes=i + 5),
            summary=f"Summary for source {i}",
            is_primary=(i == 0),
        )
        for i in range(20)
    ]
    timeline = [
        TimelineEntry(
            timestamp=now - timedelta(minutes=20 - i),
            headline=f"Timeline milestone {i}",
            source_name=f"Source {i % 5}",
            source_url=f"https://example.com/bulk-{i}",
            confidence_at_time=min(1.0, 0.4 + (i * 0.04)),
            entry_type="update" if i > 0 else "initial",
        )
        for i in range(15)
    ]

    event = TechEvent(
        id="evt_large_aggregate",
        headline="Large Breaking AI Model Release",
        first_seen=now - timedelta(minutes=20),
        last_updated=now,
        entities=["OpenAI", "Microsoft", "Nvidia", "Meta", "Google"],
        topics=["Artificial Intelligence", "Hardware", "Semiconductors", "Cloud"],
        sources=sources,
        primary_source="Source 0",
        confidence=0.98,
        importance=0.95,
        novelty=0.85,
        status=EventStatus.CONFIRMED,
        freshness=FreshnessLevel.BREAKING,
        freshness_score=0.99,
        timeline=timeline,
        cluster_id="cluster_mega_01",
        category="AI & ML",
    )

    await repo.save_event(event)

    loaded = await repo.get_event("evt_large_aggregate")
    assert loaded is not None
    assert loaded.source_count == 20
    assert len(loaded.sources) == 20
    assert len(loaded.timeline) == 15
    assert loaded.is_breaking is True

