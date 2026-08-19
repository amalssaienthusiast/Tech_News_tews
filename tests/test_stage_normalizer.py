"""
Unit Tests for Stage 1: Observation Normalizer (Subphase 3B).
Location: tests/test_stage_normalizer.py
"""

from datetime import datetime, UTC
import pytest

from src.domain.enums import SourceTier, ZombieSpecies
from src.domain.models import SourceObservation, NormalizedArticle
from src.domain.validators import DomainValidationError
from src.pipeline.protocols import PipelineStage, PipelineContext
from src.pipeline.stages.s01_normalizer import ObservationNormalizer, clean_headline_text, clean_summary_text


@pytest.fixture
def normalizer():
    return ObservationNormalizer()


@pytest.fixture
def context():
    return PipelineContext()


# =============================================================================
# 1. PROTOCOL COMPLIANCE TESTS
# =============================================================================

def test_normalizer_protocol_compliance(normalizer):
    assert isinstance(normalizer, PipelineStage)
    assert normalizer.name == "observation_normalizer"
    assert normalizer.stage_number == 1


# =============================================================================
# 2. URL CANONICALIZATION & PRESERVATION TESTS
# =============================================================================

@pytest.mark.asyncio
async def test_normalizer_dirty_url_canonicalization(normalizer, context):
    dirty_url = (
        "HTTPS://Www.TechCrunch.COM:443/2026/08/ai-agents/?"
        "utm_source=twitter&utm_medium=social&category=ai&fbclid=IwAR123&article_id=987#comments"
    )
    obs = SourceObservation.create(
        source_id="tc_feed",
        source_name="TechCrunch",
        source_tier=SourceTier.TIER_1_PREMIUM,
        zombie_species=ZombieSpecies.RSS,
        url=dirty_url,
        title="OpenAI Unveils Autonomous Code Agent",
    )

    article = await normalizer.process(obs, context)

    assert isinstance(article, NormalizedArticle)
    # Original URL is preserved verbatim
    assert article.original_url == dirty_url
    # Canonical URL has lowercased host, port stripped, tracking params stripped, anchor stripped, query sorted
    assert article.canonical_url == "https://www.techcrunch.com/2026/08/ai-agents?article_id=987&category=ai"
    # Deterministic SHA-256 ID
    assert len(article.id) == 16
    # Metric was recorded
    assert "observation_normalizer" in context.stage_metrics


@pytest.mark.asyncio
async def test_normalizer_default_http_port_removal(normalizer, context):
    obs = SourceObservation.create(
        source_id="arstechnica",
        source_name="Ars Technica",
        source_tier=SourceTier.TIER_1_PREMIUM,
        zombie_species=ZombieSpecies.RSS,
        url="http://arstechnica.com:80/gadgets/2026/review/",
        title="Flagship Laptop Review",
    )
    article = await normalizer.process(obs, context)
    assert article.canonical_url == "http://arstechnica.com/gadgets/2026/review"


# =============================================================================
# 3. TITLE & SUMMARY CLEANUP TESTS
# =============================================================================

def test_clean_headline_text_entities_and_tags():
    raw = "  <b>Breaking:</b> AT&amp;T &amp; Verizon Settle &#8217;Mega&#8217; Dispute &lt;span&gt;Today&lt;/span&gt; \n\t  "
    cleaned = clean_headline_text(raw)
    assert cleaned == "Breaking: AT&T & Verizon Settle 'Mega' Dispute Today"


def test_clean_summary_text():
    raw_summary = "<p>The companies reached an <i>amicable agreement</i>.</p><br/>Read more at link."
    cleaned = clean_summary_text(raw_summary)
    assert cleaned == "The companies reached an amicable agreement . Read more at link."


@pytest.mark.asyncio
async def test_normalizer_cleans_title_and_summary(normalizer, context):
    obs = SourceObservation.create(
        source_id="hn",
        source_name="Hacker News",
        source_tier=SourceTier.TIER_2_SPECIALIST,
        zombie_species=ZombieSpecies.HACKER_NEWS,
        url="https://news.ycombinator.com/item?id=123",
        title="Show HN: A &amp; B &lt;b&gt;Testing&lt;/b&gt; Framework",
        summary="&lt;p&gt;High-performance framework for Rust.&lt;/p&gt;",
    )
    article = await normalizer.process(obs, context)
    assert article.title == "Show HN: A & B Testing Framework"
    assert article.summary == "High-performance framework for Rust."


# =============================================================================
# 4. TIMESTAMPS & PROVENANCE METADATA PRESERVATION
# =============================================================================

@pytest.mark.asyncio
async def test_normalizer_preserves_provenance_and_metadata(normalizer, context):
    pub_dt = datetime(2026, 8, 14, 10, 0, 0, tzinfo=UTC)
    obs_dt = datetime(2026, 8, 14, 10, 5, 0, tzinfo=UTC)

    obs = SourceObservation.create(
        source_id="src_wired_sec",
        source_name="Wired Security",
        source_tier=SourceTier.TIER_1_PREMIUM,
        zombie_species=ZombieSpecies.SECURITY,
        url="https://wired.com/story/zero-day-found",
        title="Critical Zero-Day Exploit Discovered",
        raw_content="Exploit payload details...",
        summary="Researchers find critical flaw.",
        image_url="https://wired.com/hero.png",
        published_at_hint=pub_dt,
        observed_at=obs_dt,
        metadata={"cve": "CVE-2026-9999", "tags": ["security", "zero-day"], "authors": ["Alice Doe"]},
    )

    article = await normalizer.process(obs, context)

    assert article.source_id == "src_wired_sec"
    assert article.source_name == "Wired Security"
    assert article.source_tier == SourceTier.TIER_1_PREMIUM
    assert article.zombie_species == ZombieSpecies.SECURITY
    assert article.published_at == pub_dt
    assert article.discovered_at == obs_dt
    assert article.clean_text == "Exploit payload details..."
    assert article.image_url == "https://wired.com/hero.png"
    assert article.tags == ("security", "zero-day")
    assert article.authors == ("Alice Doe",)
    assert article.metadata.get("cve") == "CVE-2026-9999"


# =============================================================================
# 5. ERROR HANDLING & VALIDATION TESTS
# =============================================================================

def test_clean_headline_too_short_raises_domain_validation_error():
    with pytest.raises(DomainValidationError, match="is too short"):
        clean_headline_text("<b>OK</b>")  # only 2 chars 'OK'


def test_clean_headline_empty_raises_domain_validation_error():
    with pytest.raises(DomainValidationError, match="Title must be a non-empty string"):
        clean_headline_text("   ")


@pytest.mark.asyncio
async def test_normalizer_rejects_invalid_input_type(normalizer, context):
    with pytest.raises(DomainValidationError, match="expects SourceObservation"):
        await normalizer.process("not_an_observation", context)  # type: ignore


# =============================================================================
# 6. IDEMPOTENCY & ADVANCED NORMALIZATION TESTS
# =============================================================================

@pytest.mark.asyncio
async def test_normalizer_idempotent_url_processing(normalizer, context):
    clean_url = "https://example.com/article/100?sort=asc"
    obs = SourceObservation.create(
        source_id="src_1",
        source_name="Source 1",
        source_tier=SourceTier.TIER_3_COMMUNITY,
        zombie_species=ZombieSpecies.RSS,
        url=clean_url,
        title="Already Clean Headline",
    )
    article1 = await normalizer.process(obs, context)
    assert article1.canonical_url == clean_url
    assert article1.title == "Already Clean Headline"


def test_clean_headline_multiline_and_tabs():
    raw = "\n\tMajor Breakthrough\n\tIn Quantum Computing\t  \n"
    assert clean_headline_text(raw) == "Major Breakthrough In Quantum Computing"
