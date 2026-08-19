"""
Unit Tests for Canonical Pipeline Protocols & Ingestion Adapters (Phase 3A).
Location: tests/test_pipeline_protocols.py
"""

from datetime import datetime, UTC, timezone, timedelta
from typing import Optional, Dict, Any, List
from types import MappingProxyType
import pytest

from src.core.types import Article, SourceTier as LegacySourceTier
from src.domain.enums import SourceTier, ZombieSpecies
from src.domain.models import SourceObservation
from src.domain.validators import DomainValidationError
from dataclasses import dataclass, field
from src.engine.source_registry import SourceDescriptor, SourceType
from src.pipeline.protocols import PipelineStage, PipelineContext
from src.pipeline.adapters import SourceObservationAdapter


# =============================================================================
# 1. PIPELINE PROTOCOL & CONTEXT TESTS
# =============================================================================

class MockStage:
    """Concrete mock stage to verify protocol satisfaction."""
    @property
    def name(self) -> str:
        return "mock_stage"

    @property
    def stage_number(self) -> int:
        return 1

    async def process(self, input_item: SourceObservation, context: PipelineContext) -> SourceObservation:
        context.record_metric(self.name, 1.25)
        return input_item


class TestPipelineProtocols:
    def test_pipeline_stage_protocol_satisfaction(self):
        stage = MockStage()
        assert isinstance(stage, PipelineStage)
        assert stage.name == "mock_stage"
        assert stage.stage_number == 1

    def test_pipeline_context_initialization(self):
        ctx = PipelineContext()
        assert len(ctx.pipeline_id) == 16
        assert len(ctx.correlation_id) == 16
        assert ctx.is_aborted is False
        assert ctx.abort_reason is None
        assert isinstance(ctx.started_at, datetime)
        assert ctx.started_at.tzinfo == UTC

    def test_pipeline_context_metrics_and_abort(self):
        ctx = PipelineContext()
        ctx.record_metric("stage_1", 2.3456)
        assert ctx.stage_metrics["stage_1"] == 2.346

        ctx.set("custom_key", "custom_val")
        assert ctx.get("custom_key") == "custom_val"
        assert ctx.get("nonexistent", 42) == 42

        ctx.abort("Dedup duplicate detected")
        assert ctx.is_aborted is True
        assert ctx.abort_reason == "Dedup duplicate detected"


# =============================================================================
# 2. ADAPTER TESTS: EventSource -> SourceObservation
# =============================================================================

@dataclass
class MockLegacyEventSource:
    article_id: str
    url: str
    title: str
    source_name: str
    source_tier: int = 3
    published_at: Optional[datetime] = None
    summary: Optional[str] = None
    image_url: Optional[str] = None
    zombie_species: str = "rss"
    is_primary: bool = False


class TestEventSourceAdapter:
    def test_from_event_source_valid(self):
        legacy_source = MockLegacyEventSource(
            article_id="art_12345",
            url="https://techcrunch.com/2026/08/14/ai-breakthrough/",
            title="Massive Breakthrough in AI Models",
            source_name="TechCrunch",
            source_tier=1,
            published_at=datetime(2026, 8, 14, 8, 0, 0, tzinfo=UTC),
            summary="New model breaks benchmarks.",
            image_url="https://techcrunch.com/img.jpg",
            zombie_species="z_rss",
            is_primary=True,
        )

        obs = SourceObservationAdapter.from_event_source(legacy_source)

        assert isinstance(obs, SourceObservation)
        assert obs.source_id == "art_12345"
        assert obs.source_name == "TechCrunch"
        assert obs.source_tier == SourceTier.TIER_1_PREMIUM
        assert obs.zombie_species == ZombieSpecies.RSS
        assert obs.url == "https://techcrunch.com/2026/08/14/ai-breakthrough/"
        assert obs.title == "Massive Breakthrough in AI Models"
        assert obs.summary == "New model breaks benchmarks."
        assert obs.image_url == "https://techcrunch.com/img.jpg"
        assert obs.published_at_hint == datetime(2026, 8, 14, 8, 0, 0, tzinfo=UTC)
        assert obs.metadata.get("is_primary") is True
        assert isinstance(obs.headers, MappingProxyType)
        assert isinstance(obs.metadata, MappingProxyType)

    def test_from_event_source_naive_timestamp_converted_to_utc(self):
        naive_dt = datetime(2026, 8, 14, 10, 30, 0)
        legacy_source = MockLegacyEventSource(
            article_id="art_naive",
            url="https://example.com/naive",
            title="Naive Time Title",
            source_name="Example",
            source_tier=2,
            published_at=naive_dt,
        )

        obs = SourceObservationAdapter.from_event_source(legacy_source)
        assert obs.published_at_hint is not None
        assert obs.published_at_hint.tzinfo == UTC
        assert obs.published_at_hint.year == 2026


# =============================================================================
# 3. ADAPTER TESTS: SourceDescriptor -> SourceObservation
# =============================================================================

class TestSourceDescriptorAdapter:
    def test_from_source_descriptor_valid(self):
        descriptor = SourceDescriptor(
            id="src_hn_trending",
            url="https://news.ycombinator.com/",
            name="Hacker News Trending",
            type=SourceType.HTML,
            tier=2,
        )

        obs = SourceObservationAdapter.from_source_descriptor(
            descriptor=descriptor,
            title="Show HN: An in-process publication bus",
            url="https://news.ycombinator.com/item?id=99999",
            raw_content="Check out this bus implementation",
            zombie_species="z_hacker",
        )

        assert obs.source_id == "src_hn_trending"
        assert obs.source_name == "Hacker News Trending"
        assert obs.source_tier == SourceTier.TIER_2_SPECIALIST
        assert obs.zombie_species == ZombieSpecies.HACKER_NEWS
        assert obs.url == "https://news.ycombinator.com/item?id=99999"
        assert obs.title == "Show HN: An in-process publication bus"
        assert obs.raw_content == "Check out this bus implementation"
        assert obs.metadata.get("source_type") == "html"


# =============================================================================
# 4. ADAPTER TESTS: Article (core.types) -> SourceObservation
# =============================================================================

class TestArticleAdapter:
    def test_from_legacy_article_valid(self):
        article = Article(
            id="art_md5_hash",
            url="https://wired.com/story/cybersecurity-update",
            title="Major Zero-Day Patched",
            content="Detailed analysis of vulnerability...",
            summary="Patch issued today.",
            source="Wired",
            source_tier=LegacySourceTier.TIER_1,
            published_at=datetime(2026, 8, 14, 7, 0, 0, tzinfo=UTC),
            category="Security",
            pipeline="breaking",
            keywords=("zeroday", "security"),
            entities={"ORG": ["Microsoft", "Google"]},
        )

        obs = SourceObservationAdapter.from_legacy_article(article, zombie_species="z_security")

        assert obs.source_id == "art_md5_hash"
        assert obs.source_name == "Wired"
        assert obs.source_tier == SourceTier.TIER_1_PREMIUM
        assert obs.zombie_species == ZombieSpecies.SECURITY
        assert obs.url == "https://wired.com/story/cybersecurity-update"
        assert obs.raw_content == "Detailed analysis of vulnerability..."
        assert obs.metadata.get("category") == "Security"
        assert obs.metadata.get("pipeline") == "breaking"
        assert obs.metadata.get("keywords") == ["zeroday", "security"]
        assert obs.metadata.get("entities") == {"ORG": ["Microsoft", "Google"]}


# =============================================================================
# 5. ADAPTER TESTS: Raw Dictionary -> SourceObservation
# =============================================================================

class TestRawDictAdapter:
    def test_from_raw_dict_with_iso_timestamps(self):
        data = {
            "source_id": "custom_feed_1",
            "source_name": "Ars Technica",
            "source_tier": 1,
            "zombie_species": "z_rss",
            "url": "https://arstechnica.com/science/2026/08/new-discovery/",
            "title": "Astronomers Detect Signal",
            "summary": "Deep space signal detected.",
            "published_at": "2026-08-14T06:30:00Z",
            "headers": {"User-Agent": "TechNewsScrapper/2.0"},
            "metadata": {"tags": ["space", "astronomy"]},
        }

        obs = SourceObservationAdapter.from_raw_dict(data)

        assert obs.source_id == "custom_feed_1"
        assert obs.source_name == "Ars Technica"
        assert obs.source_tier == SourceTier.TIER_1_PREMIUM
        assert obs.zombie_species == ZombieSpecies.RSS
        assert obs.published_at_hint == datetime(2026, 8, 14, 6, 30, 0, tzinfo=UTC)
        assert obs.headers.get("User-Agent") == "TechNewsScrapper/2.0"
        assert obs.metadata.get("tags") == ["space", "astronomy"]


# =============================================================================
# 6. ADAPTER ERROR HANDLING & DETERMINISM TESTS
# =============================================================================

class TestAdapterErrorHandling:
    def test_missing_url_raises_domain_validation_error(self):
        with pytest.raises(DomainValidationError, match="data.url must be at least 1 character"):
            SourceObservationAdapter.from_raw_dict({
                "url": "",
                "title": "Valid Title",
                "source_name": "Valid Source",
            })

    def test_missing_title_raises_domain_validation_error(self):
        with pytest.raises(DomainValidationError, match="data.title must be at least 1 character"):
            SourceObservationAdapter.from_raw_dict({
                "url": "https://example.com/test",
                "title": "   ",
                "source_name": "Valid Source",
            })

    def test_missing_source_name_raises_domain_validation_error(self):
        with pytest.raises(DomainValidationError, match="data.source_name must be at least 1 character"):
            SourceObservationAdapter.from_raw_dict({
                "url": "https://example.com/test",
                "title": "Valid Title",
                "source_name": "",
            })

    def test_invalid_source_tier_raises_domain_validation_error(self):
        with pytest.raises(DomainValidationError, match="Invalid source tier integer"):
            SourceObservationAdapter.from_raw_dict({
                "url": "https://example.com/test",
                "title": "Valid Title",
                "source_name": "Valid Source",
                "source_tier": 99,
            })

    def test_malformed_timestamp_raises_domain_validation_error(self):
        with pytest.raises(DomainValidationError, match="Invalid timestamp string"):
            SourceObservationAdapter.from_raw_dict({
                "url": "https://example.com/test",
                "title": "Valid Title",
                "source_name": "Valid Source",
                "published_at": "not-a-valid-date-string",
            })

    def test_deterministic_identity_across_calls(self):
        payload = {
            "source_id": "test_feed",
            "source_name": "Test Feed",
            "url": "https://example.com/story/1",
            "title": "Identical Story",
        }
        obs1 = SourceObservationAdapter.from_raw_dict(payload)
        obs2 = SourceObservationAdapter.from_raw_dict(payload)
        assert obs1.id == obs2.id
