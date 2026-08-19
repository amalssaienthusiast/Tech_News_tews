"""
Unit Tests for Stage 8: Scoring Engine (Subphase 3F).
Location: tests/test_stage_scoring.py
"""

from datetime import datetime, UTC, timedelta
import pytest

from src.domain.enums import EventStatus, FreshnessLevel, SourceTier
from src.domain.models import TechEvent, EventSourceEvidence, TimelineEntry
from src.domain.validators import DomainValidationError
from src.pipeline.protocols import PipelineStage, PipelineContext
from src.pipeline.stages.s08_scoring import (
    ScoringEngine,
    compute_confidence,
    compute_importance,
    compute_novelty,
    compute_event_freshness,
)


@pytest.fixture
def scoring_engine():
    return ScoringEngine()


@pytest.fixture
def make_event():
    def _factory(
        headline="OpenAI Launches Critical Zero-Day Patch CVE-2026-9999",
        first_seen=None,
        sources=None,
        timeline=None,
        topics=("security", "ai"),
    ):
        now = datetime.now(UTC)
        fs = first_seen or now
        src_list = sources or [
            EventSourceEvidence(
                article_id="art_1",
                url="https://techcrunch.com/2026/08/14/patch",
                title=headline,
                source_name="TechCrunch",
                source_tier=SourceTier.TIER_1_PREMIUM,
                discovered_at=fs,
                is_primary=True,
            )
        ]
        tl_list = timeline or [
            TimelineEntry(
                timestamp=fs,
                headline=headline,
                source_name="TechCrunch",
                source_url="https://techcrunch.com/2026/08/14/patch",
                confidence_at_time=0.5,
                entry_type="initial",
            )
        ]
        return TechEvent(
            id="ev_test_123",
            headline=headline,
            first_seen=fs,
            last_updated=fs,
            topics=list(topics),
            sources=src_list,
            timeline=tl_list,
        )
    return _factory


# =============================================================================
# 1. PROTOCOL COMPLIANCE & SCORE BOUNDS
# =============================================================================

def test_scoring_engine_protocol_compliance(scoring_engine):
    assert isinstance(scoring_engine, PipelineStage)
    assert scoring_engine.name == "scoring_engine"
    assert scoring_engine.stage_number == 8


@pytest.mark.asyncio
async def test_score_bounds_and_validity(scoring_engine, make_event):
    event = make_event()
    ctx = PipelineContext()
    scored_event = await scoring_engine.process(event, ctx)

    assert 0.0 <= scored_event.confidence <= 1.0
    assert 0.0 <= scored_event.importance <= 1.0
    assert 0.0 <= scored_event.novelty <= 1.0
    assert 0.0 <= scored_event.freshness_score <= 1.0
    assert "scoring_engine" in ctx.stage_metrics
    assert "scoring_metrics" in ctx.metadata


# =============================================================================
# 2. CONFIDENCE & SOURCE TIER CORROBORATION
# =============================================================================

def test_tier_based_single_source_confidence():
    now = datetime.now(UTC)

    # Tier 1 with primary bonus
    src_t1_primary = [EventSourceEvidence("1", "u1", "t", "Wired", SourceTier.TIER_1_PREMIUM, now, is_primary=True)]
    assert compute_confidence(src_t1_primary) == 0.75

    # Tier 1 standard
    src_t1 = [EventSourceEvidence("1", "u1", "t", "Wired", SourceTier.TIER_1_PREMIUM, now, is_primary=False)]
    assert compute_confidence(src_t1) == 0.70

    # Tier 2
    src_t2 = [EventSourceEvidence("2", "u2", "t", "Hacker News", SourceTier.TIER_2_SPECIALIST, now)]
    assert compute_confidence(src_t2) == 0.50

    # Tier 3
    src_t3 = [EventSourceEvidence("3", "u3", "t", "Dev Blog", SourceTier.TIER_3_COMMUNITY, now)]
    assert compute_confidence(src_t3) == 0.30

    # Tier 4
    src_t4 = [EventSourceEvidence("4", "u4", "t", "Aggregator", SourceTier.TIER_4_DISCOVERY, now)]
    assert compute_confidence(src_t4) == 0.15


def test_multi_source_corroboration_distinct_vs_duplicate_publishers():
    now = datetime.now(UTC)

    # Two distinct Tier 1/2 publishers: Wired + Ars Technica
    sources_distinct = [
        EventSourceEvidence("1", "u1", "t", "Wired", SourceTier.TIER_1_PREMIUM, now, is_primary=False),
        EventSourceEvidence("2", "u2", "t", "Ars Technica", SourceTier.TIER_1_PREMIUM, now, is_primary=False),
    ]
    conf_distinct = compute_confidence(sources_distinct)
    # 0.70 base + 0.15 distinct corroboration = 0.85
    assert conf_distinct == 0.85

    # Two articles from the SAME publisher: Wired + Wired
    sources_same_publisher = [
        EventSourceEvidence("1", "u1", "t", "Wired", SourceTier.TIER_1_PREMIUM, now, is_primary=False),
        EventSourceEvidence("2", "u2", "t", "Wired", SourceTier.TIER_1_PREMIUM, now, is_primary=False),
    ]
    conf_same = compute_confidence(sources_same_publisher)
    # Same publisher does NOT compound corroboration bonus
    assert conf_same == 0.70


# =============================================================================
# 3. CONFIDENCE & IMPORTANCE INDEPENDENCE
# =============================================================================

def test_confidence_and_importance_independence():
    now = datetime.now(UTC)

    # Case A: Critical Zero-Day from weak single source (Tier 4)
    headline_cve = "Critical Remote Code Execution Zero-Day CVE-2026-9999 Found"
    src_t4 = [EventSourceEvidence("1", "u1", headline_cve, "Unknown Aggregator", SourceTier.TIER_4_DISCOVERY, now)]
    conf_a = compute_confidence(src_t4)
    imp_a = compute_importance(headline_cve, ["security"])
    # High importance, low confidence
    assert imp_a >= 0.75
    assert conf_a <= 0.20

    # Case B: Minor Routine Tutorial from Tier 1 Primary Source
    headline_tut = "Getting Started with Python: How to Print Hello World Tutorial"
    src_t1 = [EventSourceEvidence("2", "u2", headline_tut, "TechCrunch", SourceTier.TIER_1_PREMIUM, now, is_primary=True)]
    conf_b = compute_confidence(src_t1)
    imp_b = compute_importance(headline_tut, ["python"])
    # High confidence, low importance
    assert conf_b >= 0.75
    assert imp_b <= 0.30


# =============================================================================
# 4. NOVELTY & FRESHNESS BEHAVIOR
# =============================================================================

def test_novelty_decay_across_updates():
    assert compute_novelty(timeline_count=1, source_count=1) == 1.0
    # As timeline and sources grow, novelty decays
    nov_updated = compute_novelty(timeline_count=4, source_count=3)
    assert nov_updated < 0.60
    assert nov_updated >= 0.20


def test_compute_event_freshness():
    now = datetime.now(UTC)
    src = [EventSourceEvidence("1", "u1", "t", "Wired", SourceTier.TIER_1_PREMIUM, now - timedelta(minutes=2))]

    level, score = compute_event_freshness(now - timedelta(minutes=2), src)
    assert level == FreshnessLevel.BREAKING
    assert score == 1.00

    level_old, score_old = compute_event_freshness(now - timedelta(hours=80), src)
    assert level_old == FreshnessLevel.STALE
    assert score_old == 0.00


# =============================================================================
# 5. DERIVED BREAKING NEWS VERIFICATION
# =============================================================================

@pytest.mark.asyncio
async def test_exact_breaking_news_event(scoring_engine, make_event):
    now = datetime.now(UTC)
    # 1. Freshness <= 5m
    # 2. Tier 1 primary source (confidence = 0.75 >= 0.70)
    # 3. Critical CVE in headline (importance = 0.75 >= 0.60)
    event = make_event(
        headline="Critical Remote Code Execution Zero-Day CVE-2026-9999 Exploited in Wild",
        first_seen=now - timedelta(minutes=2),
        sources=[
            EventSourceEvidence(
                article_id="art_breaking",
                url="https://wired.com/story/zeroday-cve",
                title="Critical Remote Code Execution Zero-Day CVE-2026-9999",
                source_name="Wired",
                source_tier=SourceTier.TIER_1_PREMIUM,
                discovered_at=now - timedelta(minutes=2),
                is_primary=True,
            )
        ],
        topics=["security", "zeroday"],
    )
    ctx = PipelineContext()
    scored = await scoring_engine.process(event, ctx)

    assert scored.freshness == FreshnessLevel.BREAKING
    assert scored.confidence >= 0.70
    assert scored.importance >= 0.60
    assert scored.is_breaking is True


@pytest.mark.asyncio
async def test_non_breaking_when_confidence_too_low(scoring_engine, make_event):
    now = datetime.now(UTC)
    # Tier 2 source (confidence 0.50 < 0.70)
    event = make_event(
        headline="Critical Remote Code Execution Zero-Day CVE-2026-9999",
        first_seen=now - timedelta(minutes=2),
        sources=[
            EventSourceEvidence(
                article_id="art_low_conf",
                url="https://hn.com/item/1",
                title="Critical Remote Code Execution Zero-Day CVE-2026-9999",
                source_name="Hacker News",
                source_tier=SourceTier.TIER_2_SPECIALIST,
                discovered_at=now - timedelta(minutes=2),
            )
        ],
    )
    ctx = PipelineContext()
    scored = await scoring_engine.process(event, ctx)

    assert scored.confidence < 0.70
    assert scored.is_breaking is False


@pytest.mark.asyncio
async def test_non_breaking_when_stale(scoring_engine, make_event):
    now = datetime.now(UTC)
    # 12 hours old (freshness AGING) -> Not breaking even with high confidence and importance
    event = make_event(
        headline="Critical Remote Code Execution Zero-Day CVE-2026-9999",
        first_seen=now - timedelta(hours=12),
        sources=[
            EventSourceEvidence(
                article_id="art_old",
                url="https://wired.com/story/cve",
                title="Critical CVE",
                source_name="Wired",
                source_tier=SourceTier.TIER_1_PREMIUM,
                discovered_at=now - timedelta(hours=12),
                is_primary=True,
            )
        ],
    )
    ctx = PipelineContext()
    scored = await scoring_engine.process(event, ctx)

    assert scored.freshness != FreshnessLevel.BREAKING
    assert scored.is_breaking is False


@pytest.mark.asyncio
async def test_deterministic_repeated_scoring(scoring_engine, make_event):
    event = make_event()
    ctx1 = PipelineContext()
    ctx2 = PipelineContext()

    s1 = await scoring_engine.process(event, ctx1)
    conf1, imp1, nov1 = s1.confidence, s1.importance, s1.novelty

    s2 = await scoring_engine.process(event, ctx2)
    assert s2.confidence == conf1
    assert s2.importance == imp1
    assert s2.novelty == nov1
