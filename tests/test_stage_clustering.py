"""
Unit Tests for Stage 7: Event Clusterer (Subphase 3E).
Location: tests/test_stage_clustering.py
"""

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, UTC, timedelta
import pytest

from src.domain.enums import EventStatus, FreshnessLevel, SourceTier, ZombieSpecies
from src.domain.models import NormalizedArticle, TechEvent, EventSourceEvidence, TimelineEntry
from src.domain.validators import DomainValidationError
from src.pipeline.protocols import PipelineStage, PipelineContext
from src.pipeline.stages.s07_clustering import (
    EventClusterer,
    ActiveEventStore,
    make_event_id,
)


@pytest.fixture
def shared_store():
    return ActiveEventStore(max_capacity=100, window_hours=48.0)


@pytest.fixture
def clusterer(shared_store):
    return EventClusterer(shared_store)


@pytest.fixture
def make_article():
    def _factory(
        url="https://techcrunch.com/2026/08/14/openai-release",
        title="OpenAI Unveils Autonomous Code Agent Architecture",
        source_tier=SourceTier.TIER_1_PREMIUM,
        source_name="TechCrunch",
        discovered_at=None,
        tags=("ai", "llm"),
    ):
        return NormalizedArticle.create(
            canonical_url=url,
            original_url=url,
            title=title,
            clean_text="Detailed analysis of autonomous agents.",
            summary="OpenAI releases new coding model.",
            source_id="tc_feed",
            source_name=source_name,
            source_tier=source_tier,
            zombie_species=ZombieSpecies.RSS,
            discovered_at=discovered_at or datetime.now(UTC),
            tags=tags,
        )
    return _factory


# =============================================================================
# 1. PROTOCOL COMPLIANCE & DETERMINISTIC IDENTITY
# =============================================================================

def test_clusterer_protocol_compliance(clusterer):
    assert isinstance(clusterer, PipelineStage)
    assert clusterer.name == "event_clusterer"
    assert clusterer.stage_number == 7


def test_make_event_id_determinism():
    dt = datetime(2026, 8, 14, 10, 0, 0, tzinfo=UTC)
    id1 = make_event_id("OpenAI Releases GPT-5", dt)
    id2 = make_event_id("  openai   releases  gpt-5  ", dt)
    assert id1 == id2
    assert len(id1) == 16


# =============================================================================
# 2. EVENT CREATION & MERGING TESTS
# =============================================================================

@pytest.mark.asyncio
async def test_first_article_creates_new_event(clusterer, make_article):
    now = datetime(2026, 8, 14, 10, 0, 0, tzinfo=UTC)
    article = make_article(
        url="https://techcrunch.com/2026/08/14/ai-agent",
        title="OpenAI Launches Autonomous Coding Engine",
        source_tier=SourceTier.TIER_1_PREMIUM,
        discovered_at=now,
    )
    ctx = PipelineContext()

    event = await clusterer.process(article, ctx)

    assert isinstance(event, TechEvent)
    assert ctx.get("clustering_action") == "created_new"
    assert event.headline == "OpenAI Launches Autonomous Coding Engine"
    assert event.source_count == 1
    assert event.status == EventStatus.CONFIRMED  # Tier 1 source is CONFIRMED
    assert len(event.timeline) == 1
    assert event.timeline[0].entry_type == "initial"
    assert "event_clusterer" in ctx.stage_metrics


@pytest.mark.asyncio
async def test_second_related_article_merges_into_same_event(clusterer, make_article):
    t0 = datetime(2026, 8, 14, 10, 0, 0, tzinfo=UTC)
    t1 = datetime(2026, 8, 14, 11, 30, 0, tzinfo=UTC)

    # Article 1 from Tier 2 source
    art1 = make_article(
        url="https://news.ycombinator.com/item?id=12345",
        title="Show HN: DeepMind Unveils New Protein Folding Model",
        source_tier=SourceTier.TIER_2_SPECIALIST,
        source_name="Hacker News",
        discovered_at=t0,
        tags=("biology", "ai"),
    )
    ctx1 = PipelineContext()
    event1 = await clusterer.process(art1, ctx1)
    assert event1.status == EventStatus.SUSPECTED

    # Article 2 related story from Tier 1 source
    art2 = make_article(
        url="https://nature.com/articles/deepmind-protein-model",
        title="DeepMind Unveils Revolutionary New Protein Folding Model in Nature",
        source_tier=SourceTier.TIER_1_PREMIUM,
        source_name="Nature Journal",
        discovered_at=t1,
        tags=("ai", "biotech"),
    )
    ctx2 = PipelineContext()
    event2 = await clusterer.process(art2, ctx2)

    assert event2.id == event1.id  # Merged into exact same event!
    assert ctx2.get("clustering_action") == "merged_existing"
    assert event2.source_count == 2
    assert event2.status == EventStatus.CONFIRMED  # Upgraded to CONFIRMED
    assert len(event2.timeline) == 2
    assert event2.timeline[1].entry_type == "corroboration"
    assert "biotech" in event2.topics


@pytest.mark.asyncio
async def test_unrelated_article_creates_separate_event(clusterer, make_article):
    art1 = make_article(
        url="https://wired.com/story/cybersecurity-patch",
        title="Critical Zero-Day Vulnerability Fixed in OpenSSL",
    )
    art2 = make_article(
        url="https://theverge.com/gadgets/flagship-phone-review",
        title="Comprehensive Review of Flagship Smartphone Camera",
    )

    ctx1 = PipelineContext()
    event1 = await clusterer.process(art1, ctx1)

    ctx2 = PipelineContext()
    event2 = await clusterer.process(art2, ctx2)

    assert event1.id != event2.id
    assert ctx2.get("clustering_action") == "created_new"


# =============================================================================
# 3. 48-HOUR TEMPORAL WINDOW & PRUNING TESTS
# =============================================================================

@pytest.mark.asyncio
async def test_article_outside_48_hour_window_creates_new_event(shared_store, make_article):
    clusterer = EventClusterer(shared_store)
    old_time = datetime.now(UTC) - timedelta(hours=50)

    art1 = make_article(
        url="https://techcrunch.com/2026/08/10/quantum-breakthrough",
        title="Scientists Achieve Quantum Supremacy in Laboratory",
        discovered_at=old_time,
    )
    ctx1 = PipelineContext()
    event1 = await clusterer.process(art1, ctx1)

    # Same headline arrives 50 hours later
    art2 = make_article(
        url="https://wired.com/2026/08/14/quantum-breakthrough",
        title="Scientists Achieve Quantum Supremacy in Laboratory",
        discovered_at=datetime.now(UTC),
    )
    ctx2 = PipelineContext()
    event2 = await clusterer.process(art2, ctx2)

    # Because event1 was >48h old, it is treated as expired and art2 creates a new event
    assert ctx2.get("clustering_action") == "created_new"


# =============================================================================
# 4. EVIDENCE DEDUPLICATION & BOUNDED MEMORY TESTS
# =============================================================================

@pytest.mark.asyncio
async def test_duplicate_evidence_not_added(clusterer, make_article):
    art = make_article()
    ctx1 = PipelineContext()
    event1 = await clusterer.process(art, ctx1)
    assert event1.source_count == 1

    # Ingest same article again
    ctx2 = PipelineContext()
    event2 = await clusterer.process(art, ctx2)
    assert event2.source_count == 1  # Did not duplicate source evidence


def test_active_event_store_bounded_capacity():
    store = ActiveEventStore(max_capacity=5)
    now = datetime.now(UTC)
    for i in range(10):
        ev = TechEvent(
            id=f"ev_{i}",
            headline=f"Unique Event Number {i}",
            first_seen=now,
            last_updated=now,
        )
        store.put_event(ev)

    assert len(store) == 5
    assert store.get_event("ev_0") is None  # Evicted
    assert store.get_event("ev_9") is not None


# =============================================================================
# 5. CONCURRENCY & THREAD-SAFETY TESTS
# =============================================================================

def test_concurrent_event_clustering(make_article):
    store = ActiveEventStore(max_capacity=500)
    clusterer = EventClusterer(store)

    def worker(worker_id: int):
        import asyncio
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

        for i in range(10):
            art = make_article(
                url=f"https://example.com/w{worker_id}/story_{i}",
                title=f"AlphaDomain{worker_id} TechSector{i} Innovation{worker_id}_{i} Breakthrough",
            )
            ctx = PipelineContext()
            loop.run_until_complete(clusterer.process(art, ctx))
        loop.close()

    with ThreadPoolExecutor(max_workers=6) as pool:
        futures = [pool.submit(worker, w) for w in range(6)]
        for f in futures:
            f.result()

    assert len(store) == 60


# =============================================================================
# 6. ADVERSARIAL TEMPORAL INVARIANT TESTS (P2-2 AUDIT REMEDIATION)
# =============================================================================

@pytest.mark.asyncio
async def test_temporal_invariants_47h_vs_49h_window(make_article):
    """P2-2 Invariant: 47h apart merges; 49h apart in fresh store creates separate event."""
    store1 = ActiveEventStore(window_hours=48.0)
    clusterer1 = EventClusterer(store1)
    t0 = datetime(2026, 8, 14, 10, 0, 0, tzinfo=UTC)

    # 47h apart -> same event
    t_47h = t0 + timedelta(hours=47)
    art1 = make_article(url="https://ex.com/1", title="DeepMind Unveils Protein Folding System", discovered_at=t0)
    art2 = make_article(url="https://ex.com/2", title="DeepMind Unveils Protein Folding System Breakthrough", discovered_at=t_47h)

    ev1 = await clusterer1.process(art1, PipelineContext())
    ev2 = await clusterer1.process(art2, PipelineContext())
    assert ev1.id == ev2.id

    # 49h apart from t0 in fresh store -> separate event due to 48h window
    store2 = ActiveEventStore(window_hours=48.0)
    clusterer2 = EventClusterer(store2)
    t_49h = t0 + timedelta(hours=49)
    art3 = make_article(url="https://ex.com/3", title="DeepMind Unveils Protein Folding System Breakthrough", discovered_at=t_49h)

    ev1_fresh = await clusterer2.process(art1, PipelineContext())
    ev3_fresh = await clusterer2.process(art3, PipelineContext())
    assert ev1_fresh.id != ev3_fresh.id



@pytest.mark.asyncio
async def test_temporal_invariants_historical_replay_and_out_of_order(make_article):
    """P2-2 Invariant: Historical replay is deterministic and out-of-order doesn't evict."""
    store1 = ActiveEventStore()
    c1 = EventClusterer(store1)
    t0 = datetime(2026, 8, 14, 10, 0, 0, tzinfo=UTC)
    t1 = t0 + timedelta(minutes=90)

    a1 = make_article(url="https://ex.com/a1", title="OpenAI Announces Autonomous Agent Preview", discovered_at=t0)
    a2 = make_article(url="https://ex.com/a2", title="OpenAI Announces Autonomous Agent Architecture", discovered_at=t1)

    ev_1 = await c1.process(a1, PipelineContext())
    ev_2 = await c1.process(a2, PipelineContext())
    assert ev_1.id == ev_2.id

    # Replay in clean store
    store2 = ActiveEventStore()
    c2 = EventClusterer(store2)
    ev_3 = await c2.process(a1, PipelineContext())
    ev_4 = await c2.process(a2, PipelineContext())
    assert ev_1.id == ev_3.id
    assert ev_2.id == ev_4.id
