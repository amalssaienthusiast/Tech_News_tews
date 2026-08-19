# Phase 2A Contract Revisions: Final Approved Domain Models

**Document Status**: Final Approved Technical Specification  
**Authority**: Principal Architect  
**Governing Module Target**: `src/domain/`

---

## 1. Domain Types Architecture

The following specifications are the **authoritative, binding contract models** for Phase 2B implementation.

```python
"""
Core Domain Models for Tech News Scrapper.
Location: src/domain/models.py
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, UTC, timedelta
from enum import Enum, auto
import hashlib
from types import MappingProxyType
from typing import Any, Dict, List, Optional, Tuple, Union
from uuid import uuid4


# =============================================================================
# ENUMS & CONSTANTS
# =============================================================================

class ZombieSpecies(str, Enum):
    RSS = "z_rss"
    GITHUB = "z_github"
    HACKER_NEWS = "z_hacker"
    SECURITY = "z_security"
    CORPORATE = "z_corp"
    WEB = "z_web"
    DISCOVERY = "z_discovery"


class SourceTier(int, Enum):
    TIER_1_PREMIUM = 1       # Curated primary tech news (TechCrunch, Wired, Ars Technica)
    TIER_2_SPECIALIST = 2    # High-signal specialist (Hacker News, GitHub Trending, NVD)
    TIER_3_COMMUNITY = 3     # General community feeds, tech subreddits
    TIER_4_DISCOVERY = 4     # Automated discovery, unverified feeds


class FreshnessLevel(str, Enum):
    BREAKING = "breaking"     # [0, 5] minutes
    VERY_FRESH = "very_fresh" # (5, 30] minutes
    FRESH = "fresh"           # (30, 120] minutes
    RECENT = "recent"         # (120, 360] minutes (2-6h)
    AGING = "aging"           # (360, 1440] minutes (6-24h)
    OLD = "old"               # (1440, 4320] minutes (24-72h)
    STALE = "stale"           # > 4320 minutes (>72h) -> Discard/Archive
    UNKNOWN = "unknown"       # Undated article fallback

    @property
    def badge(self) -> str:
        return {
            "breaking": "🔴",
            "very_fresh": "🟠",
            "fresh": "🟡",
            "recent": "🟢",
            "aging": "🔵",
            "old": "⚫",
            "stale": "❌",
            "unknown": "❓",
        }[self.value]

    @classmethod
    def from_age_minutes(cls, age_minutes: Optional[float]) -> "FreshnessLevel":
        if age_minutes is None:
            return cls.UNKNOWN
        if age_minutes <= 5.0:
            return cls.BREAKING
        elif age_minutes <= 30.0:
            return cls.VERY_FRESH
        elif age_minutes <= 120.0:
            return cls.FRESH
        elif age_minutes <= 360.0:
            return cls.RECENT
        elif age_minutes <= 1440.0:
            return cls.AGING
        elif age_minutes <= 4320.0:
            return cls.OLD
        else:
            return cls.STALE


class EventStatus(str, Enum):
    SUSPECTED = "suspected"         # 1 source, low confidence (<0.30)
    CORROBORATED = "corroborated"   # Multiple sources agree (0.30–0.60)
    CONFIRMED = "confirmed"         # Primary or high-tier source confirmed (0.60–0.85)
    DEVELOPING = "developing"       # Active breaking updates (>0.85 and active updates)
    RESOLVED = "resolved"           # Event complete; no further updates expected
    STALE = "stale"                 # Inactive > 24h


class DedupAction(str, Enum):
    ACCEPTED = "accepted"                          # Genuinely unique -> proceed to indexing
    EXACT_URL_DUPLICATE = "exact_url_duplicate"    # Exact canonical URL match
    SIMILAR_TITLE_DUPLICATE = "similar_title_dup"  # MinHash Jaccard similarity >= threshold
    SUPERSEDED = "superseded"                      # Better revision of existing story


class SourceHealthStatus(str, Enum):
    HEALTHY = "healthy"           # Normal operation, yielding articles
    DEGRADED = "degraded"         # 1-4 consecutive failures, retrying
    RATE_LIMITED = "rate_limited" # 429 received, backing off until Retry-After
    COOLDOWN = "cooldown"         # >=5 consecutive failures, exponential backoff
    QUARANTINED = "quarantined"   # 404/410 received, dormant for 7 days
    PROBATION = "probation"       # Quarantine expired; single probe attempt pending
    DEAD = "dead"                 # Probe failed after quarantine; permanently deactivated


class PublicationChannel(str, Enum):
    SSE_STREAM = "sse_stream"
    TELEGRAM_BOT = "telegram_bot"
    WEBSOCKET = "websocket"
    FEED_BUFFER = "feed_buffer"


class PublicationEventType(str, Enum):
    ARTICLE_PUBLISHED = "article_published"
    EVENT_DETECTED = "event_detected"
    EVENT_UPDATED = "event_updated"
    BREAKING_ALERT = "breaking_alert"
    SYSTEM_STATUS = "system_status"


class PublicationPriority(int, Enum):
    HIGH = 1       # Breaking events, critical CVEs -> immediate dispatch
    NORMAL = 2     # Standard verified articles
    LOW = 3        # Background digests, operational stats


# =============================================================================
# 1. SOURCE OBSERVATION (ACQUISITION CONTRACT)
# =============================================================================

@dataclass(frozen=True, slots=True)
class SourceObservation:
    """Raw, immutable acquisition data emitted by Zombie collectors."""
    id: str                                        # Deterministic sha256(source_id + url)[:20]
    source_id: str                                 # Source registry identifier
    source_name: str                               # Human-readable source name
    source_tier: SourceTier                        # Source quality tier
    zombie_species: ZombieSpecies                  # Ingestion species
    url: str                                       # Raw external URL
    title: str                                     # Raw headline
    raw_content: str = ""                          # Raw HTML or body snippet
    summary: str = ""                              # Summary if provided by RSS/API
    image_url: Optional[str] = None                # Extracted image/thumbnail URL
    published_at_hint: Optional[datetime] = None   # Raw published timestamp if present
    observed_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    headers: Dict[str, str] = field(default_factory=dict)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        if not self.url or not self.url.strip():
            raise ValueError("SourceObservation url must not be empty")
        if not self.title or not self.title.strip():
            raise ValueError("SourceObservation title must not be empty")
        if self.observed_at.tzinfo is None:
            raise ValueError("SourceObservation observed_at must be timezone-aware (UTC)")
        # Freeze internal dicts to guarantee strict immutability
        object.__setattr__(self, 'headers', MappingProxyType(dict(self.headers)))
        object.__setattr__(self, 'metadata', MappingProxyType(dict(self.metadata)))

    @classmethod
    def create(
        cls,
        source_id: str,
        source_name: str,
        source_tier: SourceTier,
        zombie_species: ZombieSpecies,
        url: str,
        title: str,
        raw_content: str = "",
        summary: str = "",
        image_url: Optional[str] = None,
        published_at_hint: Optional[datetime] = None,
        headers: Optional[Dict[str, str]] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> "SourceObservation":
        clean_url = url.strip()
        obs_id = hashlib.sha256(f"{source_id}|{clean_url.lower()}".encode("utf-8")).hexdigest()[:20]
        return cls(
            id=obs_id,
            source_id=source_id,
            source_name=source_name,
            source_tier=source_tier,
            zombie_species=zombie_species,
            url=clean_url,
            title=title.strip(),
            raw_content=raw_content,
            summary=summary.strip(),
            image_url=image_url,
            published_at_hint=published_at_hint,
            headers=headers or {},
            metadata=metadata or {},
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "source_id": self.source_id,
            "source_name": self.source_name,
            "source_tier": self.source_tier.value,
            "zombie_species": self.zombie_species.value,
            "url": self.url,
            "title": self.title,
            "raw_content": self.raw_content,
            "summary": self.summary,
            "image_url": self.image_url,
            "published_at_hint": self.published_at_hint.isoformat() if self.published_at_hint else None,
            "observed_at": self.observed_at.isoformat(),
            "metadata": dict(self.metadata),
        }


# =============================================================================
# 2. NORMALIZED ARTICLE (CLEAN INGESTION CONTRACT)
# =============================================================================

@dataclass(slots=True)
class NormalizedArticle:
    """Standardized article entity after canonicalization and hygiene filtering."""
    id: str                                        # sha256(canonical_url)[:16]
    canonical_url: str                             # Stripped of tracking params, lowercased host/scheme
    original_url: str                              # Raw observed URL
    title: str                                     # Clean Unicode headline
    clean_text: str                                # Extracted plain text body
    summary: str                                   # Summary or excerpt
    source_id: str                                 # Source registry identifier
    source_name: str                               # Human-readable source name
    source_tier: SourceTier                        # Source quality tier
    zombie_species: ZombieSpecies                  # Ingestion species
    discovered_at: datetime                        # Time observed
    published_at: Optional[datetime] = None        # Authoritative publication time
    language: str = "en"                           # ISO 639-1 code
    image_url: Optional[str] = None                # Hero / thumbnail image URL
    authors: Tuple[str, ...] = field(default_factory=tuple)
    tags: Tuple[str, ...] = field(default_factory=tuple)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        if not self.canonical_url.startswith(("http://", "https://")):
            raise ValueError(f"Invalid canonical URL: {self.canonical_url}")
        if len(self.title.strip()) < 3:
            raise ValueError("NormalizedArticle title must be at least 3 characters")
        if self.discovered_at.tzinfo is None:
            raise ValueError("discovered_at must be timezone-aware (UTC)")

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "canonical_url": self.canonical_url,
            "original_url": self.original_url,
            "title": self.title,
            "clean_text": self.clean_text,
            "summary": self.summary,
            "source_id": self.source_id,
            "source_name": self.source_name,
            "source_tier": self.source_tier.value,
            "zombie_species": self.zombie_species.value,
            "discovered_at": self.discovered_at.isoformat(),
            "published_at": self.published_at.isoformat() if self.published_at else None,
            "language": self.language,
            "image_url": self.image_url,
            "authors": list(self.authors),
            "tags": list(self.tags),
            "metadata": self.metadata,
        }


# =============================================================================
# 3. QUALITY REPORT (EVALUATION CONTRACT)
# =============================================================================

@dataclass(frozen=True, slots=True)
class QualityReport:
    """Explainable diagnostic evaluation from quality and relevance gates."""
    article_id: str
    is_passed: bool
    quality_score: float                           # 0.0 to 1.0 (syntactic & hygiene score)
    relevance_score: float                         # 0.0 to 1.0 (technology domain relevance)
    rejection_reasons: Tuple[str, ...] = field(default_factory=tuple)
    matched_keywords: Tuple[str, ...] = field(default_factory=tuple)
    detected_categories: Tuple[str, ...] = field(default_factory=tuple)
    evaluated_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    def __post_init__(self):
        if not 0.0 <= self.quality_score <= 1.0:
            raise ValueError("quality_score must be between 0.0 and 1.0")
        if not 0.0 <= self.relevance_score <= 1.0:
            raise ValueError("relevance_score must be between 0.0 and 1.0")
        if not self.is_passed and not self.rejection_reasons:
            raise ValueError("Rejected QualityReport must specify at least one rejection reason")

    def to_dict(self) -> Dict[str, Any]:
        return {
            "article_id": self.article_id,
            "is_passed": self.is_passed,
            "quality_score": round(self.quality_score, 3),
            "relevance_score": round(self.relevance_score, 3),
            "rejection_reasons": list(self.rejection_reasons),
            "matched_keywords": list(self.matched_keywords),
            "detected_categories": list(self.detected_categories),
            "evaluated_at": self.evaluated_at.isoformat(),
        }


# =============================================================================
# 4. DEDUP DECISION (DEDUPLICATION CONTRACT)
# =============================================================================

@dataclass(frozen=True, slots=True)
class DedupDecision:
    """Outcome of two-tier deduplication check (Bloom Filter + MinHash)."""
    article_id: str
    action: DedupAction
    is_duplicate: bool
    canonical_url: str
    matched_article_id: Optional[str] = None
    similarity_score: float = 0.0                  # 0.0 to 1.0 Jaccard similarity
    minhash_signature: Optional[Tuple[int, ...]] = None
    evaluated_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    def __post_init__(self):
        if not 0.0 <= self.similarity_score <= 1.0:
            raise ValueError("similarity_score must be between 0.0 and 1.0")
        if self.is_duplicate and self.action == DedupAction.ACCEPTED:
            raise ValueError("is_duplicate=True cannot have action=ACCEPTED")

    def to_dict(self) -> Dict[str, Any]:
        return {
            "article_id": self.article_id,
            "action": self.action.value,
            "is_duplicate": self.is_duplicate,
            "canonical_url": self.canonical_url,
            "matched_article_id": self.matched_article_id,
            "similarity_score": round(self.similarity_score, 3),
            "evaluated_at": self.evaluated_at.isoformat(),
        }


# =============================================================================
# 5. TECH EVENT (INTELLIGENCE AGGREGATE ROOT)
# =============================================================================

@dataclass(frozen=True, slots=True)
class EventSourceEvidence:
    """Individual article evidence contributing to a TechEvent aggregate."""
    article_id: str
    url: str
    title: str
    source_name: str
    source_tier: SourceTier
    discovered_at: datetime
    published_at: Optional[datetime] = None
    summary: str = ""
    image_url: Optional[str] = None
    is_primary: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "article_id": self.article_id,
            "url": self.url,
            "title": self.title,
            "source_name": self.source_name,
            "source_tier": self.source_tier.value,
            "discovered_at": self.discovered_at.isoformat(),
            "published_at": self.published_at.isoformat() if self.published_at else None,
            "summary": self.summary,
            "image_url": self.image_url,
            "is_primary": self.is_primary,
        }


@dataclass(frozen=True, slots=True)
class TimelineEntry:
    """Chronological update within an event's lifecycle."""
    timestamp: datetime
    headline: str
    source_name: str
    source_url: str
    confidence_at_time: float
    entry_type: str = "update"      # "initial", "update", "confirmation", "resolution"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "timestamp": self.timestamp.isoformat(),
            "headline": self.headline,
            "source_name": self.source_name,
            "source_url": self.source_url,
            "confidence_at_time": round(self.confidence_at_time, 3),
            "entry_type": self.entry_type,
        }


@dataclass(slots=True)
class TechEvent:
    """The central intelligence aggregate root — groups multiple articles into one story."""
    id: str                                        # Deterministic hash
    headline: str                                  # Synthesized event headline
    first_seen: datetime                           # Detection timestamp of earliest source
    last_updated: datetime                         # Timestamp of most recent source/update
    entities: List[str] = field(default_factory=list)
    topics: List[str] = field(default_factory=list)
    sources: List[EventSourceEvidence] = field(default_factory=list)
    primary_source: Optional[str] = None
    confidence: float = 0.0                        # 0.0 to 1.0 (factual certainty)
    importance: float = 0.5                        # 0.0 to 1.0 (real-world significance)
    novelty: float = 1.0                           # 0.0 to 1.0 (uniqueness vs existing events)
    status: EventStatus = EventStatus.SUSPECTED
    freshness: FreshnessLevel = FreshnessLevel.FRESH
    freshness_score: float = 0.0                   # Composite freshness (0.0 to 1.0)
    timeline: List[TimelineEntry] = field(default_factory=list)
    cluster_id: str = ""
    category: Optional[str] = None

    @property
    def source_count(self) -> int:
        return len(self.sources)

    @property
    def is_breaking(self) -> bool:
        """Breaking news requires strict multi-dimensional criteria."""
        return (
            self.freshness == FreshnessLevel.BREAKING
            and self.confidence >= 0.70
            and self.importance >= 0.60
        )

    def add_source(self, source: EventSourceEvidence) -> bool:
        """Add source evidence if unique. Returns True if newly added."""
        if any(s.url == source.url for s in self.sources):
            return False
        self.sources.append(source)
        self.last_updated = datetime.now(UTC)
        if source.is_primary or (self.primary_source is None and source.source_tier == SourceTier.TIER_1_PREMIUM):
            self.primary_source = source.source_name
        return True

    def add_timeline_entry(self, entry: TimelineEntry) -> None:
        self.timeline.append(entry)
        self.timeline.sort(key=lambda e: e.timestamp)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "headline": self.headline,
            "first_seen": self.first_seen.isoformat(),
            "last_updated": self.last_updated.isoformat(),
            "entities": self.entities,
            "topics": self.topics,
            "sources": [s.to_dict() for s in self.sources],
            "source_count": self.source_count,
            "primary_source": self.primary_source,
            "confidence": round(self.confidence, 3),
            "importance": round(self.importance, 3),
            "novelty": round(self.novelty, 3),
            "status": self.status.value,
            "freshness": self.freshness.value,
            "freshness_badge": self.freshness.badge,
            "freshness_score": round(self.freshness_score, 3),
            "timeline": [t.to_dict() for t in self.timeline],
            "cluster_id": self.cluster_id,
            "category": self.category,
            "is_breaking": self.is_breaking,
        }


# =============================================================================
# 6. PUBLICATION EVENT (DELIVERY CONTRACT)
# =============================================================================

# Discriminated payload union
PayloadType = Union[NormalizedArticle, TechEvent, Dict[str, Any]]

@dataclass(frozen=True, slots=True)
class PublicationEvent:
    """Strongly-typed delivery envelope dispatched to PublicationBus."""
    event_id: str = field(default_factory=lambda: str(uuid4()))
    event_type: PublicationEventType = PublicationEventType.ARTICLE_PUBLISHED
    payload: PayloadType = field(default_factory=dict)
    channels: Tuple[PublicationChannel, ...] = (PublicationChannel.SSE_STREAM, PublicationChannel.TELEGRAM_BOT)
    priority: PublicationPriority = PublicationPriority.NORMAL
    published_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    schema_version: int = 1
    idempotency_key: str = ""

    def __post_init__(self):
        if not self.idempotency_key:
            # Auto-generate idempotency key from event_type + payload identity
            if hasattr(self.payload, "id"):
                object.__setattr__(self, "idempotency_key", f"{self.event_type.value}:{self.payload.id}")
            else:
                object.__setattr__(self, "idempotency_key", self.event_id)

    def to_dict(self) -> Dict[str, Any]:
        payload_dict = self.payload.to_dict() if hasattr(self.payload, "to_dict") else self.payload
        return {
            "event_id": self.event_id,
            "event_type": self.event_type.value,
            "schema_version": self.schema_version,
            "idempotency_key": self.idempotency_key,
            "channels": [c.value for c in self.channels],
            "priority": self.priority.value,
            "published_at": self.published_at.isoformat(),
            "payload": payload_dict,
        }


# =============================================================================
# 7. SOURCE HEALTH (RESILIENCE & STATE MACHINE CONTRACT)
# =============================================================================

@dataclass(slots=True)
class SourceHealth:
    """Operational resilience state machine for data sources."""
    source_id: str
    source_url: str
    source_name: str
    status: SourceHealthStatus = SourceHealthStatus.HEALTHY
    consecutive_failures: int = 0
    consecutive_successes: int = 0
    last_attempt: Optional[datetime] = None
    last_success: Optional[datetime] = None
    last_status_code: Optional[int] = None
    cooldown_until: Optional[datetime] = None
    rate_limit_reset_at: Optional[datetime] = None
    working_bypass_tier: int = 0

    def record_success(self, working_tier: int = 0) -> None:
        now = datetime.now(UTC)
        self.consecutive_successes += 1
        self.consecutive_failures = 0
        self.last_success = now
        self.last_attempt = now
        self.status = SourceHealthStatus.HEALTHY
        self.cooldown_until = None
        self.working_bypass_tier = working_tier

    def record_failure(self, status_code: Optional[int] = None, retry_after_sec: Optional[int] = None) -> None:
        now = datetime.now(UTC)
        self.consecutive_failures += 1
        self.consecutive_successes = 0
        self.last_attempt = now
        self.last_status_code = status_code

        # State transition triggers
        if status_code in (404, 410):
            self.status = SourceHealthStatus.QUARANTINED
            self.cooldown_until = now + timedelta(days=7)
        elif status_code == 429:
            self.status = SourceHealthStatus.RATE_LIMITED
            backoff = retry_after_sec or 300
            self.cooldown_until = now + timedelta(seconds=backoff)
            self.rate_limit_reset_at = self.cooldown_until
        elif self.status == SourceHealthStatus.PROBATION:
            # Failed while on probation -> mark permanently DEAD
            self.status = SourceHealthStatus.DEAD
        elif self.consecutive_failures >= 5:
            self.status = SourceHealthStatus.COOLDOWN
            backoff_min = min(360, (2 ** (self.consecutive_failures - 5)) * 5)
            self.cooldown_until = now + timedelta(minutes=backoff_min)
        else:
            self.status = SourceHealthStatus.DEGRADED

    def check_probation_eligibility(self) -> bool:
        """Check if a quarantined source is eligible to enter probation."""
        if self.status == SourceHealthStatus.QUARANTINED:
            if self.cooldown_until and datetime.now(UTC) >= self.cooldown_until:
                self.status = SourceHealthStatus.PROBATION
                return True
        return False

    def is_eligible_to_poll(self) -> bool:
        if self.status == SourceHealthStatus.DEAD:
            return False
        self.check_probation_eligibility()
        if self.status in (SourceHealthStatus.COOLDOWN, SourceHealthStatus.RATE_LIMITED, SourceHealthStatus.QUARANTINED):
            if self.cooldown_until and datetime.now(UTC) < self.cooldown_until:
                return False
        return True

    def to_dict(self) -> Dict[str, Any]:
        return {
            "source_id": self.source_id,
            "source_url": self.source_url,
            "source_name": self.source_name,
            "status": self.status.value,
            "consecutive_failures": self.consecutive_failures,
            "consecutive_successes": self.consecutive_successes,
            "last_attempt": self.last_attempt.isoformat() if self.last_attempt else None,
            "last_success": self.last_success.isoformat() if self.last_success else None,
            "last_status_code": self.last_status_code,
            "cooldown_until": self.cooldown_until.isoformat() if self.cooldown_until else None,
            "working_bypass_tier": self.working_bypass_tier,
        }
```
