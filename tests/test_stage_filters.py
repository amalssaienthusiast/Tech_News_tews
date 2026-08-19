"""
Unit Tests for Stages 2, 3, and 4: Freshness, Relevance, and Quality Gates (Subphase 3C).
Location: tests/test_stage_filters.py
"""

from datetime import datetime, UTC, timedelta
import pytest

from src.domain.enums import FreshnessLevel, QualityCheckLevel, SourceTier, ZombieSpecies
from src.domain.models import NormalizedArticle, QualityReport
from src.domain.validators import DomainValidationError
from src.pipeline.protocols import PipelineStage, PipelineContext
from src.pipeline.stages.s02_freshness import FreshnessEvaluator, FreshnessResult, calculate_freshness_score
from src.pipeline.stages.s03_relevance import TechRelevanceFilter, RelevanceResult, evaluate_tech_relevance
from src.pipeline.stages.s04_quality import QualityGate, evaluate_content_hygiene


@pytest.fixture
def make_article():
    def _factory(
        title="OpenAI Releases New Deep Learning Architecture",
        clean_text="A comprehensive paper explaining transformer attention mechanisms.",
        summary="Breakthrough in artificial intelligence models.",
        published_at=None,
        tags=("ai", "machine-learning"),
    ):
        return NormalizedArticle.create(
            canonical_url="https://techcrunch.com/2026/08/14/ai-breakthrough",
            original_url="https://techcrunch.com/2026/08/14/ai-breakthrough?utm_source=twitter",
            title=title,
            clean_text=clean_text,
            summary=summary,
            source_id="tc_feed",
            source_name="TechCrunch",
            source_tier=SourceTier.TIER_1_PREMIUM,
            zombie_species=ZombieSpecies.RSS,
            published_at=published_at,
            tags=tags,
        )
    return _factory


# =============================================================================
# 1. STAGE 2: FRESHNESS EVALUATOR TESTS
# =============================================================================

class TestFreshnessEvaluator:
    def test_protocol_satisfaction(self):
        evaluator = FreshnessEvaluator()
        assert isinstance(evaluator, PipelineStage)
        assert evaluator.name == "freshness_evaluator"
        assert evaluator.stage_number == 2

    @pytest.mark.asyncio
    async def test_exact_freshness_boundaries(self, make_article):
        evaluator = FreshnessEvaluator()
        now = datetime.now(UTC)

        test_cases = [
            (timedelta(minutes=2), FreshnessLevel.BREAKING, True),
            (timedelta(minutes=15), FreshnessLevel.VERY_FRESH, True),
            (timedelta(minutes=60), FreshnessLevel.FRESH, True),
            (timedelta(hours=4), FreshnessLevel.RECENT, True),
            (timedelta(hours=12), FreshnessLevel.AGING, True),
            (timedelta(hours=48), FreshnessLevel.OLD, True),
            (timedelta(hours=80), FreshnessLevel.STALE, False),  # Stale is dropped
        ]

        for delta, expected_level, should_pass in test_cases:
            ctx = PipelineContext()
            pub_time = now - delta
            article = make_article(published_at=pub_time)
            result = await evaluator.process(article, ctx)

            res: FreshnessResult = ctx.get("freshness_result")
            assert res.level == expected_level
            if should_pass:
                assert result is not None
                assert ctx.is_aborted is False
            else:
                assert result is None
                assert ctx.is_aborted is True

    @pytest.mark.asyncio
    async def test_undated_article_freshness_unknown(self, make_article):
        evaluator = FreshnessEvaluator()
        ctx = PipelineContext()
        article = make_article(published_at=None)

        result = await evaluator.process(article, ctx)
        assert result is not None
        res: FreshnessResult = ctx.get("freshness_result")
        assert res.level == FreshnessLevel.UNKNOWN
        assert res.age_minutes is None
        assert res.score == 0.50

    @pytest.mark.asyncio
    async def test_future_timestamp_clamped_to_breaking(self, make_article):
        evaluator = FreshnessEvaluator()
        ctx = PipelineContext()
        future_pub = datetime.now(UTC) + timedelta(minutes=30)
        article = make_article(published_at=future_pub)

        result = await evaluator.process(article, ctx)
        assert result is not None
        res: FreshnessResult = ctx.get("freshness_result")
        assert res.level == FreshnessLevel.BREAKING
        assert res.age_minutes == 0.0

    def test_calculate_freshness_score_bounds(self):
        assert calculate_freshness_score(0) == 1.00
        assert calculate_freshness_score(4) == 1.00
        assert 0.05 <= calculate_freshness_score(1440) <= 0.95
        assert calculate_freshness_score(5000) == 0.00
        assert calculate_freshness_score(None) == 0.50


# =============================================================================
# 2. STAGE 3: TECH RELEVANCE FILTER TESTS
# =============================================================================

class TestTechRelevanceFilter:
    def test_protocol_satisfaction(self):
        filter_stage = TechRelevanceFilter()
        assert isinstance(filter_stage, PipelineStage)
        assert filter_stage.name == "tech_relevance_filter"
        assert filter_stage.stage_number == 3

    @pytest.mark.asyncio
    async def test_high_relevance_tech_article(self, make_article):
        filter_stage = TechRelevanceFilter()
        ctx = PipelineContext()
        article = make_article(
            title="Critical Zero-Day Vulnerability Patched in Linux Kernel",
            clean_text="Security researchers discovered an exploit in the TCP stack.",
            summary="Patch CVE-2026-1111 released.",
            tags=("security", "linux"),
        )

        res_article = await filter_stage.process(article, ctx)
        assert res_article is not None
        assert ctx.is_aborted is False

        rel: RelevanceResult = ctx.get("relevance_result")
        assert rel.is_relevant is True
        assert rel.relevance_score >= 0.70
        assert "CYBERSECURITY" in rel.detected_categories

    @pytest.mark.asyncio
    async def test_non_tech_exclusion_rejected(self, make_article):
        filter_stage = TechRelevanceFilter()
        ctx = PipelineContext()
        article = make_article(
            title="Celebrity Gossip: Hollywood Romance on the Red Carpet",
            clean_text="Actor spotted with new partner at film festival.",
            summary="Full story on relationship updates.",
            tags=("gossip", "hollywood"),
        )

        res_article = await filter_stage.process(article, ctx)
        assert res_article is None
        assert ctx.is_aborted is True

        rel: RelevanceResult = ctx.get("relevance_result")
        assert rel.is_relevant is False
        assert rel.relevance_score <= 0.20


# =============================================================================
# 3. STAGE 4: QUALITY GATE TESTS
# =============================================================================

class TestQualityGate:
    def test_protocol_satisfaction(self):
        gate = QualityGate()
        assert isinstance(gate, PipelineStage)
        assert gate.name == "quality_gate"
        assert gate.stage_number == 4

    @pytest.mark.asyncio
    async def test_high_quality_article_passes(self, make_article):
        gate = QualityGate()
        ctx = PipelineContext()
        # Seed relevance result in context from Stage 3
        ctx.set("relevance_result", RelevanceResult(
            relevance_score=0.85,
            is_relevant=True,
            detected_categories=("AI_ML",),
            matched_keywords=("machine learning", "transformer"),
            evaluated_at=datetime.now(UTC),
        ))

        article = make_article(
            title="Deep Learning Framework Benchmarks for 2026",
            clean_text="Comprehensive empirical evaluation across diverse model architectures with full reproducible source code." * 5,
            summary="A detailed performance comparison.",
        )

        res = await gate.process(article, ctx)
        assert res is not None
        res_article, report = res

        assert isinstance(report, QualityReport)
        assert report.is_passed is True
        assert report.quality_score >= 0.70
        assert report.relevance_score == 0.85
        assert len(report.rejection_reasons) == 0
        assert "AI_ML" in report.detected_categories

    @pytest.mark.asyncio
    async def test_clickbait_and_all_caps_penalized(self, make_article):
        gate = QualityGate()
        ctx = PipelineContext()
        ctx.set("relevance_result", RelevanceResult(
            relevance_score=0.75,
            is_relevant=True,
            detected_categories=("AI_ML",),
            matched_keywords=("ai",),
            evaluated_at=datetime.now(UTC),
        ))

        article = make_article(
            title="YOU WON'T BELIEVE WHAT THIS NEW AI CAN DO!!!",
            clean_text="Short content.",
            summary="Clickbait snippet.",
        )

        res = await gate.process(article, ctx)
        assert res is None
        assert ctx.is_aborted is True

        report: QualityReport = ctx.get("quality_report")
        assert report.is_passed is False
        assert "CLICKBAIT_HEADLINE" in report.rejection_reasons
        assert "ALL_CAPS_HEADLINE" in report.rejection_reasons
        assert len(report.rejection_reasons) >= 1

    @pytest.mark.asyncio
    async def test_paywall_truncated_penalized(self, make_article):
        gate = QualityGate()
        ctx = PipelineContext()
        ctx.set("relevance_result", RelevanceResult(
            relevance_score=0.75,
            is_relevant=True,
            detected_categories=("SOFTWARE_ENG",),
            matched_keywords=("python",),
            evaluated_at=datetime.now(UTC),
        ))

        article = make_article(
            title="Modern Python Best Practices",
            clean_text="Subscribe to read the full article on our platform.",
            summary="Premium snippet.",
        )

        res = await gate.process(article, ctx)
        assert res is None
        report: QualityReport = ctx.get("quality_report")
        assert report.is_passed is False
        assert "PAYWALL_TRUNCATED" in report.rejection_reasons

    @pytest.mark.asyncio
    async def test_off_topic_article_propagated_to_quality_report(self, make_article):
        gate = QualityGate()
        ctx = PipelineContext()
        # Simulated low relevance from Stage 3
        ctx.set("relevance_result", RelevanceResult(
            relevance_score=0.15,
            is_relevant=False,
            detected_categories=(),
            matched_keywords=(),
            evaluated_at=datetime.now(UTC),
        ))

        article = make_article(
            title="Baking Sourdough Bread at Home",
            clean_text="A simple recipe for artisanal sourdough bread with perfect crust." * 10,
            summary="Baking guide.",
        )

        res = await gate.process(article, ctx)
        assert res is None
        report: QualityReport = ctx.get("quality_report")
        assert report.is_passed is False
        assert "OFF_TOPIC" in report.rejection_reasons
