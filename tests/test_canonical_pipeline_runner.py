"""
Unit and Integration Tests for Canonical Pipeline Runner (Subphase 3G).
Location: tests/test_canonical_pipeline_runner.py
"""

import asyncio
from datetime import datetime, UTC, timedelta
import os
import pytest
from unittest.mock import patch

from src.domain.enums import (
    EventStatus,
    FreshnessLevel,
    PublicationChannel,
    PublicationPriority,
    SourceTier,
    ZombieSpecies,
)
from src.domain.models import SourceObservation, TechEvent
from src.engine.publication_bus import PublicationBus
from src.engine.unified_chain import UnifiedFeedChainEngine, get_pipeline_mode
from src.pipeline.runner import CanonicalPipelineRunner, IngestionStatus


@pytest.fixture
def test_bus():
    bus = PublicationBus()
    return bus


@pytest.fixture
def runner(test_bus):
    return CanonicalPipelineRunner(bus=test_bus, max_concurrency=16)


@pytest.fixture
def make_observation():
    def _factory(
        url="https://techcrunch.com/2026/08/14/openai-release",
        title="OpenAI Releases New Deep Learning Architecture",
        raw_content="Comprehensive technical overview of deep learning transformers.",
        summary="OpenAI releases new coding model with reasoning capabilities.",
        source_tier=SourceTier.TIER_1_PREMIUM,
        source_name="TechCrunch",
        discovered_at=None,
        published_at_hint=None,
        tags=("ai", "llm"),
    ):
        now = datetime.now(UTC)
        return SourceObservation.create(
            url=url,
            title=title,
            raw_content=raw_content,
            summary=summary,
            source_id="tc_feed",
            source_name=source_name,
            source_tier=source_tier,
            zombie_species=ZombieSpecies.RSS,
            observed_at=discovered_at or now,
            published_at_hint=published_at_hint or now,
            metadata={"tags": list(tags)},
        )
    return _factory


# =============================================================================
# 1. FULL PIPELINE HAPPY PATH (S01–S11)
# =============================================================================

@pytest.mark.asyncio
async def test_full_pipeline_happy_path(runner, test_bus, make_observation):
    await test_bus.start()
    sub_id, queue = await test_bus.subscribe(channels=(PublicationChannel.SSE_STREAM,))

    obs = make_observation(
        url="https://techcrunch.com/2026/08/14/ai-quantum-breakthrough",
        title="OpenAI and Google Announce Joint Quantum Computing Milestone",
        summary="Scientists achieve breakthrough in quantum neural networks.",
        source_tier=SourceTier.TIER_1_PREMIUM,
    )

    res = await runner.process_observation(obs)

    assert res.status == IngestionStatus.SUCCESS
    assert res.event is not None
    assert res.event.headline == "OpenAI and Google Announce Joint Quantum Computing Milestone"
    assert res.event.confidence >= 0.70
    assert "observation_normalizer" in res.stage_metrics
    assert "publication_stage" in res.stage_metrics
    assert res.total_latency_ms > 0.0

    # Verify event reached subscriber via PublicationBus
    pub_event = await asyncio.wait_for(queue.get(), timeout=2.0)
    assert pub_event is not None
    assert pub_event.payload.id == res.event.id
    assert pub_event.priority == PublicationPriority.NORMAL

    await test_bus.stop()


# =============================================================================
# 2. STAGE DROP TESTS (S02, S03, S04, S05)
# =============================================================================

@pytest.mark.asyncio
async def test_pipeline_drops_stale_at_s02(runner, test_bus, make_observation):
    await test_bus.start()
    _, queue = await test_bus.subscribe()

    stale_time = datetime.now(UTC) - timedelta(hours=80)
    obs = make_observation(
        url="https://techcrunch.com/2026/08/01/old-story",
        title="Historical Tech Event From Last Week",
        discovered_at=stale_time,
        published_at_hint=stale_time,
    )

    res = await runner.process_observation(obs)

    assert res.status == IngestionStatus.DROPPED
    assert res.rejected_at_stage == "s02_freshness"
    assert "STALE" in str(res.abort_reason)
    assert queue.empty()

    await test_bus.stop()


@pytest.mark.asyncio
async def test_pipeline_drops_non_tech_at_s03(runner, test_bus, make_observation):
    await test_bus.start()
    _, queue = await test_bus.subscribe()

    obs = make_observation(
        url="https://example.com/celebrity-gossip-story",
        title="Celebrity Red Carpet Fashion Review and Hollywood Drama",
        raw_content="Discussion of celebrity actors, red carpet outfits and movie awards.",
        summary="Hollywood gossip and fashion analysis.",
        tags=["celebrity", "fashion"],
    )

    res = await runner.process_observation(obs)

    assert res.status == IngestionStatus.DROPPED
    assert res.rejected_at_stage == "s03_relevance"
    assert "TechRelevanceFilter" in str(res.abort_reason)
    assert queue.empty()

    await test_bus.stop()


@pytest.mark.asyncio
async def test_pipeline_drops_low_quality_at_s04(runner, test_bus, make_observation):
    await test_bus.start()
    _, queue = await test_bus.subscribe()

    obs = make_observation(
        url="https://example.com/clickbait-spam",
        title="You Won't Believe This One Weird Secret Trick!",
        raw_content="Check it out now.",
        summary="Click here to read more.",
    )

    res = await runner.process_observation(obs)

    assert res.status == IngestionStatus.DROPPED
    assert res.rejected_at_stage == "s04_quality"
    assert "QualityGate" in str(res.abort_reason)
    # Ensure dedup index was not poisoned
    assert len(runner.dedup_index) == 0
    assert queue.empty()

    await test_bus.stop()


@pytest.mark.asyncio
async def test_pipeline_drops_duplicate_at_s05(runner, test_bus, make_observation):
    await test_bus.start()
    _, queue = await test_bus.subscribe()

    obs = make_observation(
        url="https://wired.com/story/ai-security-breakthrough",
        title="Researchers Unveil Robust AI Defense Against Jailbreaks",
    )

    # 1. First Ingestion: Success
    res1 = await runner.process_observation(obs)
    assert res1.status == IngestionStatus.SUCCESS
    assert len(runner.dedup_index) == 1

    # 2. Second Ingestion: Dropped at S05 Dedup Evaluator
    res2 = await runner.process_observation(obs)
    assert res2.status == IngestionStatus.DROPPED
    assert res2.rejected_at_stage == "s05_dedup_evaluator"
    assert "duplicate" in str(res2.abort_reason).lower()

    # Bus should receive exactly 1 event
    pub_event1 = await queue.get()
    assert pub_event1 is not None
    assert queue.empty()

    await test_bus.stop()


# =============================================================================
# 3. MULTI-SOURCE CORROBORATION & BREAKING NEWS
# =============================================================================

@pytest.mark.asyncio
async def test_multi_source_event_corroboration(runner, test_bus, make_observation):
    await test_bus.start()
    _, queue = await test_bus.subscribe()

    # Article 1 from Tier 2 source
    obs1 = make_observation(
        url="https://news.ycombinator.com/item?id=99991",
        title="Show HN: DeepMind Unveils New Protein Folding Model",
        source_tier=SourceTier.TIER_2_SPECIALIST,
        source_name="Hacker News",
        tags=["biology", "ai"],
    )
    res1 = await runner.process_observation(obs1)
    assert res1.status == IngestionStatus.SUCCESS
    assert res1.event.confidence == 0.50
    initial_confidence = res1.event.confidence

    # Article 2 related story from Tier 1 source
    obs2 = make_observation(
        url="https://nature.com/articles/deepmind-protein-open-source",
        title="DeepMind Unveils Revolutionary New Protein Folding Model in Nature",
        source_tier=SourceTier.TIER_1_PREMIUM,
        source_name="Nature",
        tags=["biotech", "ai"],
    )
    res2 = await runner.process_observation(obs2)
    assert res2.status == IngestionStatus.SUCCESS

    # Converged to same event ID with increased confidence and corroborated sources
    assert res2.event.id == res1.event.id
    assert res2.event.source_count == 2
    assert res2.event.confidence > initial_confidence  # 0.90 > 0.50
    assert len(res2.event.timeline) == 2

    await test_bus.stop()


@pytest.mark.asyncio
async def test_breaking_news_event_publication(runner, test_bus, make_observation):
    await test_bus.start()
    _, queue = await test_bus.subscribe()

    now = datetime.now(UTC)
    obs = make_observation(
        url="https://wired.com/story/cve-2026-critical-zeroday",
        title="Critical Remote Code Execution Zero-Day CVE-2026-8888 Exploited in Wild",
        source_tier=SourceTier.TIER_1_PREMIUM,
        source_name="Wired",
        discovered_at=now - timedelta(minutes=1),
        published_at_hint=now - timedelta(minutes=1),
        tags=["security", "zeroday"],
    )

    res = await runner.process_observation(obs)
    assert res.status == IngestionStatus.SUCCESS
    assert res.event.is_breaking is True

    pub_event = await asyncio.wait_for(queue.get(), timeout=2.0)
    assert pub_event.priority == PublicationPriority.HIGH

    await test_bus.stop()


# =============================================================================
# 4. SHADOW MODE & CONCURRENCY
# =============================================================================

@pytest.mark.asyncio
async def test_shadow_mode_dry_run_skips_publication(runner, test_bus, make_observation):
    await test_bus.start()
    _, queue = await test_bus.subscribe()

    obs = make_observation(
        url="https://techcrunch.com/2026/08/14/shadow-test",
        title="High Quality Tech News Item Processed In Shadow Mode",
    )

    res = await runner.process_observation(obs, dry_run=True)

    assert res.status == IngestionStatus.SUCCESS
    assert res.event is not None
    # S01–S08 executed
    assert "observation_normalizer" in res.stage_metrics
    assert "scoring_engine" in res.stage_metrics
    # S09–S11 skipped in dry-run
    assert "publication_stage" not in res.stage_metrics
    # Zero publication to bus
    assert queue.empty()

    await test_bus.stop()


@pytest.mark.asyncio
async def test_concurrency_and_error_isolation(runner, test_bus, make_observation):
    # 20 concurrent items processed in parallel
    observations = [
        make_observation(
            url=f"https://example.com/concurrent/item_{i}",
            title=f"Distinct Concurrency Subject {i} In Technology Realm Architecture",
        )
        for i in range(20)
    ]

    results = await asyncio.gather(*(runner.process_observation(obs) for obs in observations))

    assert len(results) == 20
    assert all(r.status == IngestionStatus.SUCCESS for r in results)
    assert len(runner.dedup_index) == 20


# =============================================================================
# 5. UNIFIED ENGINE INTEGRATION & MODE RESOLUTION
# =============================================================================

def test_pipeline_mode_resolution():
    # 1. Default (no environment variables) resolves to 'active'
    with patch.dict(os.environ, {}, clear=True):
        assert get_pipeline_mode() == "active"

    # 2. Explicit CANONICAL_PIPELINE_MODE overrides
    with patch.dict(os.environ, {"CANONICAL_PIPELINE_MODE": "active"}):
        assert get_pipeline_mode() == "active"

    with patch.dict(os.environ, {"CANONICAL_PIPELINE_MODE": "shadow"}):
        assert get_pipeline_mode() == "shadow"

    with patch.dict(os.environ, {"CANONICAL_PIPELINE_MODE": "legacy"}):
        assert get_pipeline_mode() == "legacy"

    # 3. Fallback ENABLE_CANONICAL_PIPELINE when MODE is unset
    with patch.dict(os.environ, {"ENABLE_CANONICAL_PIPELINE": "true", "CANONICAL_PIPELINE_MODE": ""}):
        assert get_pipeline_mode() == "active"

    with patch.dict(os.environ, {"ENABLE_CANONICAL_PIPELINE": "false", "CANONICAL_PIPELINE_MODE": ""}):
        assert get_pipeline_mode() == "legacy"

    # 4. Invalid mode strings safely default to 'active'
    with patch.dict(os.environ, {"CANONICAL_PIPELINE_MODE": "invalid_mode"}):
        assert get_pipeline_mode() == "active"


@pytest.mark.asyncio
async def test_unified_engine_active_mode_routes_to_canonical():
    with patch.dict(os.environ, {"CANONICAL_PIPELINE_MODE": "active"}):
        engine = UnifiedFeedChainEngine()
        engine.initialize()

        source = SourceObservation.create(
            source_id="src_active_1",
            source_name="TechCrunch",
            source_tier=SourceTier.TIER_1_PREMIUM,
            zombie_species=ZombieSpecies.RSS,
            url="https://techcrunch.com/2026/08/14/engine-active-test",
            title="OpenAI Announces New Autonomous System in Active Mode",
            summary="Autonomous system released by OpenAI.",
            published_at_hint=datetime.now(UTC),
        )

        await engine._on_zombie_found_source(source)
        assert len(engine.canonical_runner.dedup_index) == 1

        engine.stop()
