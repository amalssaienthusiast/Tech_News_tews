"""
Comprehensive Test Suite for Canonical Domain Contracts.
Location: tests/test_domain_contracts.py

Tests:
  - SourceObservation invariants, immutability, mapping protection, deterministic hash, UTC validation
  - NormalizedArticle canonicalization, tracking stripping, tuple conversion, identity
  - QualityReport score invariants, explainable rejection codes
  - DedupDecision action invariants, duplicate consistency
  - FreshnessLevel exact boundary definitions and UNKNOWN policy
  - TechEvent multi-dimensional scoring, derived breaking rule, timeline sorting, source deduplication
  - PublicationEvent payload typing, idempotency key generation, schema versioning
  - SourceHealth complete state transition matrix (HEALTHY, DEGRADED, RATE_LIMITED, COOLDOWN, QUARANTINED, PROBATION, DEAD)
  - Serialization roundtrip for all domain models
"""

from datetime import datetime, UTC, timedelta
from types import MappingProxyType
import pytest

from src.domain.enums import (
    DedupAction,
    EventStatus,
    FreshnessLevel,
    PublicationChannel,
    PublicationEventType,
    PublicationPriority,
    QualityCheckLevel,
    SourceHealthStatus,
    SourceTier,
    ZombieSpecies,
)
from src.domain.models import (
    DedupDecision,
    EventSourceEvidence,
    NormalizedArticle,
    PublicationEvent,
    QualityReport,
    SourceHealth,
    SourceObservation,
    TechEvent,
    TimelineEntry,
)
from src.domain.validators import (
    DomainValidationError,
    canonicalize_url,
    validate_score_range,
    validate_utc_datetime,
)


# =============================================================================
# 1. SOURCE OBSERVATION TESTS
# =============================================================================

class TestSourceObservation:
    def test_create_valid_observation(self):
        obs = SourceObservation.create(
            source_id="techcrunch_rss",
            source_name="TechCrunch",
            source_tier=SourceTier.TIER_1_PREMIUM,
            zombie_species=ZombieSpecies.RSS,
            url="https://techcrunch.com/2026/08/14/openai-announcement",
            title="OpenAI Announces Next-Gen Architecture",
            summary="A major announcement on AI models.",
            headers={"User-Agent": "TechNewsScraper/2.0"},
            metadata={"feed_etag": "12345"},
        )
        assert len(obs.id) == 20
        assert obs.source_id == "techcrunch_rss"
        assert obs.source_tier == SourceTier.TIER_1_PREMIUM
        assert obs.zombie_species == ZombieSpecies.RSS
        assert obs.observed_at.tzinfo == UTC
        assert isinstance(obs.headers, MappingProxyType)
        assert isinstance(obs.metadata, MappingProxyType)

    def test_immutability_and_mapping_protection(self):
        obs = SourceObservation.create(
            source_id="test_src",
            source_name="Test",
            source_tier=SourceTier.TIER_2_SPECIALIST,
            zombie_species=ZombieSpecies.WEB,
            url="https://example.com/news/1",
            title="Sample Headline",
            headers={"key": "value"},
            metadata={"meta_key": "meta_val"},
        )
        # Frozen dataclass mutation attempts raise error
        with pytest.raises(AttributeError):
            obs.title = "Changed Title"

        # MappingProxyType mutation attempts raise TypeError
        with pytest.raises(TypeError):
            obs.headers["new_key"] = "new_value"

        with pytest.raises(TypeError):
            obs.metadata["meta_key"] = "hacked"

    def test_deterministic_identity(self):
        obs1 = SourceObservation.create(
            source_id="src_1",
            source_name="Source One",
            source_tier=SourceTier.TIER_1_PREMIUM,
            zombie_species=ZombieSpecies.RSS,
            url="https://example.com/article?id=123",
            title="Title A",
        )
        obs2 = SourceObservation.create(
            source_id="src_1",
            source_name="Source One",
            source_tier=SourceTier.TIER_1_PREMIUM,
            zombie_species=ZombieSpecies.RSS,
            url="https://example.com/article?id=123",
            title="Title A",
        )
        assert obs1.id == obs2.id

    def test_timezone_validation(self):
        # Naive datetime must raise DomainValidationError
        naive_dt = datetime(2026, 8, 14, 12, 0, 0)
        with pytest.raises(DomainValidationError, match="timezone-aware"):
            SourceObservation(
                id="test_id",
                source_id="test_src",
                source_name="Test",
                source_tier=SourceTier.TIER_1_PREMIUM,
                zombie_species=ZombieSpecies.RSS,
                url="https://example.com/1",
                title="Title",
                observed_at=naive_dt,
            )

    def test_serialization_roundtrip(self):
        obs = SourceObservation.create(
            source_id="nvd_security",
            source_name="NVD",
            source_tier=SourceTier.TIER_2_SPECIALIST,
            zombie_species=ZombieSpecies.SECURITY,
            url="https://nvd.nist.gov/vuln/detail/CVE-2026-9999",
            title="Critical Remote Code Execution Advisory",
            summary="Severe zero-day advisory",
            published_at_hint=datetime(2026, 8, 14, 10, 30, 0, tzinfo=UTC),
            headers={"Content-Type": "application/json"},
            metadata={"cve_score": 9.8},
        )
        d = obs.to_dict()
        restored = SourceObservation.from_dict(d)
        assert restored.id == obs.id
        assert restored.source_id == obs.source_id
        assert restored.url == obs.url
        assert restored.title == obs.title
        assert restored.published_at_hint == obs.published_at_hint
        assert restored.metadata["cve_score"] == 9.8


# =============================================================================
# 2. NORMALIZED ARTICLE TESTS
# =============================================================================

class TestNormalizedArticle:
    def test_canonical_url_identity_and_tracking_stripping(self):
        raw_url = "HTTPS://TechCrunch.COM:443/2026/08/article/?utm_source=twitter&utm_medium=social&ref=feed#comments"
        art = NormalizedArticle.create(
            canonical_url=raw_url,
            original_url=raw_url,
            title="Clean Headline Here",
            clean_text="Body content paragraphs.",
            summary="Brief summary.",
            source_id="tc",
            source_name="TechCrunch",
            source_tier=SourceTier.TIER_1_PREMIUM,
            zombie_species=ZombieSpecies.RSS,
            authors=["Alice", "Bob"],
            tags=["AI", "Startups"],
        )
        assert art.canonical_url == "https://techcrunch.com/2026/08/article"
        assert len(art.id) == 16
        assert isinstance(art.authors, tuple)
        assert isinstance(art.tags, tuple)
        assert art.authors == ("Alice", "Bob")

    def test_invalid_url_and_title_invariants(self):
        with pytest.raises(DomainValidationError):
            NormalizedArticle.create(
                canonical_url="ftp://invalid-scheme.com/file",
                original_url="ftp://invalid-scheme.com/file",
                title="Valid Title",
                clean_text="",
                summary="",
                source_id="src",
                source_name="Name",
                source_tier=SourceTier.TIER_3_COMMUNITY,
                zombie_species=ZombieSpecies.WEB,
            )

        with pytest.raises(DomainValidationError):
            NormalizedArticle.create(
                canonical_url="https://example.com/article",
                original_url="https://example.com/article",
                title="No",  # too short (<3 chars)
                clean_text="",
                summary="",
                source_id="src",
                source_name="Name",
                source_tier=SourceTier.TIER_3_COMMUNITY,
                zombie_species=ZombieSpecies.WEB,
            )

    def test_serialization_roundtrip(self):
        now = datetime.now(UTC)
        art = NormalizedArticle.create(
            canonical_url="https://arstechnica.com/gadgets/2026/08/new-chip",
            original_url="https://arstechnica.com/gadgets/2026/08/new-chip",
            title="Ars Technica Hardware Review",
            clean_text="In-depth analysis of semiconductor architecture.",
            summary="Review summary.",
            source_id="ars",
            source_name="Ars Technica",
            source_tier=SourceTier.TIER_1_PREMIUM,
            zombie_species=ZombieSpecies.RSS,
            discovered_at=now,
            published_at=now - timedelta(minutes=15),
            authors=["Tech Journalist"],
            tags=["hardware", "semiconductors"],
        )
        d = art.to_dict()
        restored = NormalizedArticle.from_dict(d)
        assert restored.id == art.id
        assert restored.canonical_url == art.canonical_url
        assert restored.authors == ("Tech Journalist",)
        assert restored.tags == ("hardware", "semiconductors")


# =============================================================================
# 3. QUALITY REPORT TESTS
# =============================================================================

class TestQualityReport:
    def test_valid_passed_report(self):
        rep = QualityReport(
            article_id="art_123",
            is_passed=True,
            quality_score=0.92,
            relevance_score=0.88,
            check_level=QualityCheckLevel.STANDARD,
            matched_keywords=("artificial intelligence", "neural network"),
            detected_categories=("AI", "Machine Learning"),
        )
        assert rep.is_passed is True
        assert rep.quality_score == 0.92
        assert rep.relevance_score == 0.88
        assert rep.rejection_reasons == ()

    def test_rejected_report_must_have_rejection_reasons(self):
        with pytest.raises(DomainValidationError, match="must specify at least one rejection reason"):
            QualityReport(
                article_id="art_123",
                is_passed=False,
                quality_score=0.2,
                relevance_score=0.1,
                rejection_reasons=(),  # Invalid: rejected report cannot have empty reasons
            )

    def test_score_range_validation(self):
        with pytest.raises(DomainValidationError, match="must be between 0.0 and 1.0"):
            QualityReport(
                article_id="art_123",
                is_passed=True,
                quality_score=1.5,  # Invalid: > 1.0
                relevance_score=0.5,
            )

    def test_serialization_roundtrip(self):
        rep = QualityReport(
            article_id="art_456",
            is_passed=False,
            quality_score=0.35,
            relevance_score=0.10,
            check_level=QualityCheckLevel.STRICT,
            rejection_reasons=("not_tech", "spam_detected"),
            matched_keywords=(),
            detected_categories=(),
        )
        d = rep.to_dict()
        restored = QualityReport.from_dict(d)
        assert restored.article_id == "art_456"
        assert restored.is_passed is False
        assert "not_tech" in restored.rejection_reasons


# =============================================================================
# 4. DEDUP DECISION TESTS
# =============================================================================

class TestDedupDecision:
    def test_accepted_decision(self):
        dec = DedupDecision(
            article_id="art_789",
            action=DedupAction.ACCEPTED,
            is_duplicate=False,
            canonical_url="https://example.com/unique-article",
            similarity_score=0.0,
        )
        assert dec.action == DedupAction.ACCEPTED
        assert dec.is_duplicate is False

    def test_invalid_duplicate_flag_with_accepted_action(self):
        with pytest.raises(DomainValidationError, match="is_duplicate=True cannot have action=ACCEPTED"):
            DedupDecision(
                article_id="art_789",
                action=DedupAction.ACCEPTED,
                is_duplicate=True,  # Invariant violation
                canonical_url="https://example.com/unique-article",
            )

    def test_exact_and_similar_duplicate_decisions(self):
        exact_dec = DedupDecision(
            article_id="art_dup",
            action=DedupAction.EXACT_URL_DUPLICATE,
            is_duplicate=True,
            canonical_url="https://example.com/article-1",
            matched_article_id="art_original",
            similarity_score=1.0,
        )
        assert exact_dec.action == DedupAction.EXACT_URL_DUPLICATE
        assert exact_dec.matched_article_id == "art_original"

        sim_dec = DedupDecision(
            article_id="art_dup_2",
            action=DedupAction.SIMILAR_TITLE_DUPLICATE,
            is_duplicate=True,
            canonical_url="https://example.com/article-2",
            matched_article_id="art_original_2",
            similarity_score=0.88,
        )
        assert sim_dec.similarity_score == 0.88

    def test_serialization_roundtrip(self):
        dec = DedupDecision(
            article_id="art_101",
            action=DedupAction.SIMILAR_TITLE_DUPLICATE,
            is_duplicate=True,
            canonical_url="https://example.com/101",
            matched_article_id="art_099",
            similarity_score=0.85,
        )
        d = dec.to_dict()
        restored = DedupDecision.from_dict(d)
        assert restored.article_id == dec.article_id
        assert restored.action == DedupAction.SIMILAR_TITLE_DUPLICATE
        assert restored.similarity_score == 0.85


# =============================================================================
# 5. FRESHNESS LEVEL BOUNDARY TESTS
# =============================================================================

class TestFreshnessLevel:
    def test_deterministic_exact_boundaries(self):
        # BREAKING <= 5m
        assert FreshnessLevel.from_age_minutes(0.0) == FreshnessLevel.BREAKING
        assert FreshnessLevel.from_age_minutes(5.0) == FreshnessLevel.BREAKING

        # VERY_FRESH <= 30m
        assert FreshnessLevel.from_age_minutes(5.01) == FreshnessLevel.VERY_FRESH
        assert FreshnessLevel.from_age_minutes(30.0) == FreshnessLevel.VERY_FRESH

        # FRESH <= 120m (2 hours)
        assert FreshnessLevel.from_age_minutes(30.01) == FreshnessLevel.FRESH
        assert FreshnessLevel.from_age_minutes(120.0) == FreshnessLevel.FRESH

        # RECENT <= 360m (6 hours)
        assert FreshnessLevel.from_age_minutes(120.01) == FreshnessLevel.RECENT
        assert FreshnessLevel.from_age_minutes(360.0) == FreshnessLevel.RECENT

        # AGING <= 1440m (24 hours)
        assert FreshnessLevel.from_age_minutes(360.01) == FreshnessLevel.AGING
        assert FreshnessLevel.from_age_minutes(1440.0) == FreshnessLevel.AGING

        # OLD <= 4320m (72 hours)
        assert FreshnessLevel.from_age_minutes(1440.01) == FreshnessLevel.OLD
        assert FreshnessLevel.from_age_minutes(4320.0) == FreshnessLevel.OLD

        # STALE > 4320m (> 72 hours)
        assert FreshnessLevel.from_age_minutes(4320.01) == FreshnessLevel.STALE
        assert FreshnessLevel.from_age_minutes(10000.0) == FreshnessLevel.STALE

        # UNKNOWN fallback for undated articles
        assert FreshnessLevel.from_age_minutes(None) == FreshnessLevel.UNKNOWN

    def test_badges_and_labels(self):
        assert FreshnessLevel.BREAKING.badge == "🔴"
        assert FreshnessLevel.VERY_FRESH.badge == "🟠"
        assert FreshnessLevel.FRESH.badge == "🟡"
        assert FreshnessLevel.RECENT.badge == "🟢"
        assert FreshnessLevel.AGING.badge == "🔵"
        assert FreshnessLevel.OLD.badge == "⚫"
        assert FreshnessLevel.STALE.badge == "❌"
        assert FreshnessLevel.UNKNOWN.badge == "❓"


# =============================================================================
# 6. TECH EVENT INTELLIGENCE AGGREGATE TESTS
# =============================================================================

class TestTechEvent:
    def test_multi_dimensional_scoring_and_derived_breaking_rule(self):
        now = datetime.now(UTC)
        event = TechEvent(
            id="evt_quantum_breakthrough",
            headline="Researchers Achieve 1 Million Qubit Quantum Coherence",
            first_seen=now,
            last_updated=now,
            confidence=0.85,
            importance=0.90,
            novelty=0.95,
            freshness=FreshnessLevel.BREAKING,
            freshness_score=0.98,
        )
        # Meets all 3 breaking criteria: BREAKING freshness + confidence >= 0.70 + importance >= 0.60
        assert event.is_breaking is True

        # Fails if freshness is not BREAKING
        event.freshness = FreshnessLevel.VERY_FRESH
        assert event.is_breaking is False

        # Fails if confidence is too low
        event.freshness = FreshnessLevel.BREAKING
        event.confidence = 0.65
        assert event.is_breaking is False

        # Fails if importance is too low (e.g. routine patch)
        event.confidence = 0.90
        event.importance = 0.50
        assert event.is_breaking is False

    def test_source_evidence_addition_and_deduplication(self):
        now = datetime.now(UTC)
        event = TechEvent(
            id="evt_amd_gpu",
            headline="AMD Unveils New AI GPU Lineup",
            first_seen=now,
            last_updated=now,
        )
        src1 = EventSourceEvidence(
            article_id="art_1",
            url="https://techcrunch.com/amd-gpu",
            title="AMD Launches AI Chip",
            source_name="TechCrunch",
            source_tier=SourceTier.TIER_1_PREMIUM,
            discovered_at=now,
            is_primary=True,
        )
        src2 = EventSourceEvidence(
            article_id="art_2",
            url="https://theverge.com/amd-gpu",
            title="The Verge on AMD",
            source_name="The Verge",
            source_tier=SourceTier.TIER_1_PREMIUM,
            discovered_at=now,
        )

        assert event.add_source(src1) is True
        assert event.source_count == 1
        assert event.primary_source == "TechCrunch"

        assert event.add_source(src2) is True
        assert event.source_count == 2

        # Re-adding existing URL returns False and prevents duplicate
        duplicate_src1 = EventSourceEvidence(
            article_id="art_1_dup",
            url="https://techcrunch.com/amd-gpu",
            title="Duplicate Entry",
            source_name="TechCrunch",
            source_tier=SourceTier.TIER_1_PREMIUM,
            discovered_at=now,
        )
        assert event.add_source(duplicate_src1) is False
        assert event.source_count == 2

    def test_timeline_sorting(self):
        now = datetime.now(UTC)
        event = TechEvent(
            id="evt_timeline",
            headline="Developing Story",
            first_seen=now,
            last_updated=now,
        )
        t3 = TimelineEntry(timestamp=now + timedelta(minutes=10), headline="Official Statement", source_name="Reuters", source_url="https://reuters.com", confidence_at_time=0.9)
        t1 = TimelineEntry(timestamp=now, headline="First Signal", source_name="Twitter", source_url="https://x.com", confidence_at_time=0.3)
        t2 = TimelineEntry(timestamp=now + timedelta(minutes=5), headline="Secondary Corroboration", source_name="Wired", source_url="https://wired.com", confidence_at_time=0.6)

        # Add out of chronological order
        event.add_timeline_entry(t3)
        event.add_timeline_entry(t1)
        event.add_timeline_entry(t2)

        # Verified sorted order: t1 -> t2 -> t3
        assert [t.headline for t in event.timeline] == [
            "First Signal",
            "Secondary Corroboration",
            "Official Statement",
        ]

    def test_serialization_roundtrip(self):
        now = datetime.now(UTC)
        event = TechEvent(
            id="evt_test",
            headline="Headline",
            first_seen=now,
            last_updated=now,
            entities=["NVIDIA", "CUDA"],
            topics=["AI", "GPUs"],
            confidence=0.88,
            importance=0.75,
            novelty=0.90,
            status=EventStatus.CONFIRMED,
            freshness=FreshnessLevel.FRESH,
            freshness_score=0.70,
            category="Hardware",
        )
        d = event.to_dict()
        restored = TechEvent.from_dict(d)
        assert restored.id == event.id
        assert restored.entities == ["NVIDIA", "CUDA"]
        assert restored.confidence == 0.88
        assert restored.status == EventStatus.CONFIRMED


# =============================================================================
# 7. PUBLICATION EVENT TESTS
# =============================================================================

class TestPublicationEvent:
    def test_create_and_auto_idempotency_key(self):
        art = NormalizedArticle.create(
            canonical_url="https://wired.com/story/cybersecurity",
            original_url="https://wired.com/story/cybersecurity",
            title="Zero-Day Vulnerability Discovered",
            clean_text="Body text",
            summary="Summary text",
            source_id="wired",
            source_name="Wired",
            source_tier=SourceTier.TIER_1_PREMIUM,
            zombie_species=ZombieSpecies.RSS,
        )
        pub_event = PublicationEvent(
            event_type=PublicationEventType.ARTICLE_PUBLISHED,
            payload=art,
            channels=(PublicationChannel.SSE_STREAM, PublicationChannel.TELEGRAM_BOT),
            priority=PublicationPriority.HIGH,
        )
        assert pub_event.schema_version == 1
        assert pub_event.idempotency_key == f"article_published:{art.id}"
        assert PublicationChannel.SSE_STREAM in pub_event.channels

    def test_serialization_roundtrip(self):
        now = datetime.now(UTC)
        pub_event = PublicationEvent(
            event_id="pub_12345",
            event_type=PublicationEventType.BREAKING_ALERT,
            payload={"headline": "Breaking Alert Message", "id": "alert_001"},
            channels=(PublicationChannel.TELEGRAM_BOT,),
            priority=PublicationPriority.HIGH,
            published_at=now,
        )
        d = pub_event.to_dict()
        assert d["event_id"] == "pub_12345"
        assert d["event_type"] == "breaking_alert"
        assert d["channels"] == ["telegram_bot"]
        assert d["idempotency_key"] == "breaking_alert:alert_001"


# =============================================================================
# 8. SOURCE HEALTH STATE MACHINE TESTS
# =============================================================================

class TestSourceHealthStateMachine:
    def test_complete_lifecycle_transitions(self):
        sh = SourceHealth(
            source_id="test_feed",
            source_url="https://example.com/rss",
            source_name="Example News",
        )
        assert sh.status == SourceHealthStatus.HEALTHY
        assert sh.is_eligible_to_poll() is True

        # 1-4 failures -> DEGRADED
        sh.record_failure(status_code=500)
        assert sh.status == SourceHealthStatus.DEGRADED
        assert sh.consecutive_failures == 1
        assert sh.is_eligible_to_poll() is True

        sh.record_failure(status_code=503)
        sh.record_failure(status_code=504)
        sh.record_failure(status_code=502)
        assert sh.status == SourceHealthStatus.DEGRADED
        assert sh.consecutive_failures == 4

        # 5th failure -> COOLDOWN with exponential backoff
        sh.record_failure(status_code=500)
        assert sh.status == SourceHealthStatus.COOLDOWN
        assert sh.consecutive_failures == 5
        assert sh.cooldown_until is not None
        # In cooldown -> not eligible to poll immediately
        assert sh.is_eligible_to_poll() is False

        # Success resets back to HEALTHY
        sh.record_success(working_tier=1)
        assert sh.status == SourceHealthStatus.HEALTHY
        assert sh.consecutive_failures == 0
        assert sh.consecutive_successes == 1
        assert sh.cooldown_until is None
        assert sh.working_bypass_tier == 1

        # HTTP 429 -> RATE_LIMITED with custom Retry-After
        sh.record_failure(status_code=429, retry_after_sec=60)
        assert sh.status == SourceHealthStatus.RATE_LIMITED
        assert sh.is_eligible_to_poll() is False

        # HTTP 404 -> QUARANTINED for 7 days
        sh.record_failure(status_code=404)
        assert sh.status == SourceHealthStatus.QUARANTINED
        assert sh.is_eligible_to_poll() is False

        # Quarantine duration expires -> PROBATION
        sh.cooldown_until = datetime.now(UTC) - timedelta(seconds=1)
        assert sh.check_probation_eligibility() is True
        assert sh.status == SourceHealthStatus.PROBATION
        assert sh.is_eligible_to_poll() is True

        # Failed probe on probation -> DEAD
        sh.record_failure(status_code=404)
        assert sh.status == SourceHealthStatus.DEAD
        assert sh.is_eligible_to_poll() is False

    def test_serialization_roundtrip(self):
        now = datetime.now(UTC)
        sh = SourceHealth(
            source_id="wired_rss",
            source_url="https://wired.com/feed",
            source_name="Wired",
            status=SourceHealthStatus.HEALTHY,
            consecutive_successes=25,
            last_success=now,
            last_attempt=now,
            working_bypass_tier=0,
        )
        d = sh.to_dict()
        restored = SourceHealth.from_dict(d)
        assert restored.source_id == "wired_rss"
        assert restored.status == SourceHealthStatus.HEALTHY
        assert restored.consecutive_successes == 25
