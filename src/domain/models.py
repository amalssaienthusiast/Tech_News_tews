"""
Canonical Domain Models for Tech News Scrapper.
Location: src/domain/models.py

Zero external dependencies. Pure standard library.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, UTC, timedelta
import hashlib
from types import MappingProxyType
from typing import Any, Dict, List, Optional, Tuple, Union
from uuid import uuid4

from .enums import (
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
from .validators import (
    DomainValidationError,
    canonicalize_url,
    validate_non_empty_string,
    validate_score_range,
    validate_utc_datetime,
)


# =============================================================================
# 1. SOURCE OBSERVATION (ACQUISITION CONTRACT)
# =============================================================================

@dataclass(frozen=True, slots=True)
class SourceObservation:
    """
    Raw, immutable acquisition data emitted by Zombie collectors and discovery adapters.
    
    Guarantees:
    - Immutable (frozen dataclass with MappingProxyType for nested dictionaries)
    - Deterministic SHA-256 identity based on (source_id, url)
    - Timezone-aware UTC timestamps
    """
    id: str
    source_id: str
    source_name: str
    source_tier: SourceTier
    zombie_species: ZombieSpecies
    url: str
    title: str
    raw_content: str = ""
    summary: str = ""
    image_url: Optional[str] = None
    published_at_hint: Optional[datetime] = None
    observed_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    headers: MappingProxyType = field(default_factory=lambda: MappingProxyType({}))
    metadata: MappingProxyType = field(default_factory=lambda: MappingProxyType({}))

    def __post_init__(self):
        validate_non_empty_string(self.id, "id")
        validate_non_empty_string(self.source_id, "source_id")
        validate_non_empty_string(self.source_name, "source_name")
        validate_non_empty_string(self.url, "url")
        validate_non_empty_string(self.title, "title")
        validate_utc_datetime(self.observed_at, "observed_at")
        if self.published_at_hint is not None:
            validate_utc_datetime(self.published_at_hint, "published_at_hint")

        # Guarantee read-only MappingProxyType for headers and metadata
        if not isinstance(self.headers, MappingProxyType):
            object.__setattr__(self, "headers", MappingProxyType(dict(self.headers)))
        if not isinstance(self.metadata, MappingProxyType):
            object.__setattr__(self, "metadata", MappingProxyType(dict(self.metadata)))

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
        observed_at: Optional[datetime] = None,
        headers: Optional[Dict[str, str]] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> "SourceObservation":
        """Factory method computing deterministic SHA-256 identity."""
        clean_url = url.strip()
        obs_id = hashlib.sha256(f"{source_id}|{clean_url.lower()}".encode("utf-8")).hexdigest()[:20]
        obs_time = observed_at or datetime.now(UTC)
        return cls(
            id=obs_id,
            source_id=source_id.strip(),
            source_name=source_name.strip(),
            source_tier=source_tier,
            zombie_species=zombie_species,
            url=clean_url,
            title=title.strip(),
            raw_content=raw_content,
            summary=summary.strip(),
            image_url=image_url.strip() if image_url else None,
            published_at_hint=published_at_hint,
            observed_at=obs_time,
            headers=MappingProxyType(dict(headers or {})),
            metadata=MappingProxyType(dict(metadata or {})),
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
            "headers": dict(self.headers),
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "SourceObservation":
        return cls.create(
            source_id=data["source_id"],
            source_name=data["source_name"],
            source_tier=SourceTier(data["source_tier"]),
            zombie_species=ZombieSpecies(data["zombie_species"]),
            url=data["url"],
            title=data["title"],
            raw_content=data.get("raw_content", ""),
            summary=data.get("summary", ""),
            image_url=data.get("image_url"),
            published_at_hint=datetime.fromisoformat(data["published_at_hint"]) if data.get("published_at_hint") else None,
            observed_at=datetime.fromisoformat(data["observed_at"]) if data.get("observed_at") else None,
            headers=data.get("headers"),
            metadata=data.get("metadata"),
        )


# =============================================================================
# 2. NORMALIZED ARTICLE (CLEAN INGESTION CONTRACT)
# =============================================================================

@dataclass(slots=True)
class NormalizedArticle:
    """
    Standardized article entity produced after URL canonicalization, HTML stripping,
    and text normalization.
    """
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
    discovered_at: datetime                        # Time observed (UTC)
    published_at: Optional[datetime] = None        # Authoritative publication time (UTC)
    language: str = "en"                           # ISO 639-1 code
    image_url: Optional[str] = None                # Hero / thumbnail image URL
    authors: Tuple[str, ...] = field(default_factory=tuple)
    tags: Tuple[str, ...] = field(default_factory=tuple)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        validate_non_empty_string(self.id, "id")
        validate_non_empty_string(self.title, "title", min_length=3)
        validate_non_empty_string(self.canonical_url, "canonical_url")
        validate_utc_datetime(self.discovered_at, "discovered_at")
        if self.published_at is not None:
            validate_utc_datetime(self.published_at, "published_at")
        if not self.canonical_url.startswith(("http://", "https://")):
            raise DomainValidationError(f"Invalid canonical URL scheme: {self.canonical_url}")
        if not isinstance(self.authors, tuple):
            self.authors = tuple(self.authors)
        if not isinstance(self.tags, tuple):
            self.tags = tuple(self.tags)

    @classmethod
    def create(
        cls,
        canonical_url: str,
        original_url: str,
        title: str,
        clean_text: str,
        summary: str,
        source_id: str,
        source_name: str,
        source_tier: SourceTier,
        zombie_species: ZombieSpecies,
        discovered_at: Optional[datetime] = None,
        published_at: Optional[datetime] = None,
        language: str = "en",
        image_url: Optional[str] = None,
        authors: Optional[Union[List[str], Tuple[str, ...]]] = None,
        tags: Optional[Union[List[str], Tuple[str, ...]]] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> "NormalizedArticle":
        """Factory method computing canonical URL hash identity."""
        canon = canonicalize_url(canonical_url)
        art_id = hashlib.sha256(canon.encode("utf-8")).hexdigest()[:16]
        disc_time = discovered_at or datetime.now(UTC)
        return cls(
            id=art_id,
            canonical_url=canon,
            original_url=original_url.strip(),
            title=title.strip(),
            clean_text=clean_text.strip(),
            summary=summary.strip(),
            source_id=source_id.strip(),
            source_name=source_name.strip(),
            source_tier=source_tier,
            zombie_species=zombie_species,
            discovered_at=disc_time,
            published_at=published_at,
            language=language.strip().lower(),
            image_url=image_url.strip() if image_url else None,
            authors=tuple(authors or ()),
            tags=tuple(tags or ()),
            metadata=metadata or {},
        )

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

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "NormalizedArticle":
        return cls.create(
            canonical_url=data["canonical_url"],
            original_url=data["original_url"],
            title=data["title"],
            clean_text=data.get("clean_text", ""),
            summary=data.get("summary", ""),
            source_id=data["source_id"],
            source_name=data["source_name"],
            source_tier=SourceTier(data["source_tier"]),
            zombie_species=ZombieSpecies(data["zombie_species"]),
            discovered_at=datetime.fromisoformat(data["discovered_at"]) if data.get("discovered_at") else None,
            published_at=datetime.fromisoformat(data["published_at"]) if data.get("published_at") else None,
            language=data.get("language", "en"),
            image_url=data.get("image_url"),
            authors=data.get("authors"),
            tags=data.get("tags"),
            metadata=data.get("metadata"),
        )


# =============================================================================
# 3. QUALITY REPORT (EVALUATION CONTRACT)
# =============================================================================

@dataclass(frozen=True, slots=True)
class QualityReport:
    """
    Explainable diagnostic evaluation from quality and relevance gates.
    
    Guarantees:
    - quality_score in [0.0, 1.0] (technical hygiene, headline quality, spam check)
    - relevance_score in [0.0, 1.0] (technology/science domain match)
    - If is_passed is False, rejection_reasons MUST NOT be empty.
    """
    article_id: str
    is_passed: bool
    quality_score: float
    relevance_score: float
    check_level: QualityCheckLevel = QualityCheckLevel.STANDARD
    rejection_reasons: Tuple[str, ...] = field(default_factory=tuple)
    matched_keywords: Tuple[str, ...] = field(default_factory=tuple)
    detected_categories: Tuple[str, ...] = field(default_factory=tuple)
    evaluated_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    def __post_init__(self):
        validate_non_empty_string(self.article_id, "article_id")
        validate_score_range(self.quality_score, "quality_score")
        validate_score_range(self.relevance_score, "relevance_score")
        validate_utc_datetime(self.evaluated_at, "evaluated_at")
        if not self.is_passed and not self.rejection_reasons:
            raise DomainValidationError("Rejected QualityReport must specify at least one rejection reason")
        if not isinstance(self.rejection_reasons, tuple):
            object.__setattr__(self, "rejection_reasons", tuple(self.rejection_reasons))
        if not isinstance(self.matched_keywords, tuple):
            object.__setattr__(self, "matched_keywords", tuple(self.matched_keywords))
        if not isinstance(self.detected_categories, tuple):
            object.__setattr__(self, "detected_categories", tuple(self.detected_categories))

    def to_dict(self) -> Dict[str, Any]:
        return {
            "article_id": self.article_id,
            "is_passed": self.is_passed,
            "quality_score": round(self.quality_score, 3),
            "relevance_score": round(self.relevance_score, 3),
            "check_level": self.check_level.value,
            "rejection_reasons": list(self.rejection_reasons),
            "matched_keywords": list(self.matched_keywords),
            "detected_categories": list(self.detected_categories),
            "evaluated_at": self.evaluated_at.isoformat(),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "QualityReport":
        return cls(
            article_id=data["article_id"],
            is_passed=data["is_passed"],
            quality_score=data["quality_score"],
            relevance_score=data["relevance_score"],
            check_level=QualityCheckLevel(data.get("check_level", "standard")),
            rejection_reasons=tuple(data.get("rejection_reasons", ())),
            matched_keywords=tuple(data.get("matched_keywords", ())),
            detected_categories=tuple(data.get("detected_categories", ())),
            evaluated_at=datetime.fromisoformat(data["evaluated_at"]) if data.get("evaluated_at") else datetime.now(UTC),
        )


# =============================================================================
# 4. DEDUP DECISION (DEDUPLICATION CONTRACT)
# =============================================================================

@dataclass(frozen=True, slots=True)
class DedupDecision:
    """
    Outcome of two-tier deduplication check (Bloom Filter + MinHash Title Shingling).
    
    Separates evaluate() (read-only similarity computation) from commit()
    (persistent indexing after downstream quality approval) to prevent dedup poisoning.
    """
    article_id: str
    action: DedupAction
    is_duplicate: bool
    canonical_url: str
    matched_article_id: Optional[str] = None
    similarity_score: float = 0.0
    minhash_signature: Optional[Tuple[int, ...]] = None
    evaluated_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    def __post_init__(self):
        validate_non_empty_string(self.article_id, "article_id")
        validate_non_empty_string(self.canonical_url, "canonical_url")
        validate_score_range(self.similarity_score, "similarity_score")
        validate_utc_datetime(self.evaluated_at, "evaluated_at")
        if self.is_duplicate and self.action == DedupAction.ACCEPTED:
            raise DomainValidationError("is_duplicate=True cannot have action=ACCEPTED")
        if self.minhash_signature is not None and not isinstance(self.minhash_signature, tuple):
            object.__setattr__(self, "minhash_signature", tuple(self.minhash_signature))

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

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "DedupDecision":
        return cls(
            article_id=data["article_id"],
            action=DedupAction(data["action"]),
            is_duplicate=data["is_duplicate"],
            canonical_url=data["canonical_url"],
            matched_article_id=data.get("matched_article_id"),
            similarity_score=data.get("similarity_score", 0.0),
            evaluated_at=datetime.fromisoformat(data["evaluated_at"]) if data.get("evaluated_at") else datetime.now(UTC),
        )


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

    def __post_init__(self):
        validate_non_empty_string(self.article_id, "article_id")
        validate_non_empty_string(self.url, "url")
        validate_non_empty_string(self.title, "title")
        validate_utc_datetime(self.discovered_at, "discovered_at")
        if self.published_at is not None:
            validate_utc_datetime(self.published_at, "published_at")

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

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "EventSourceEvidence":
        return cls(
            article_id=data["article_id"],
            url=data["url"],
            title=data["title"],
            source_name=data["source_name"],
            source_tier=SourceTier(data["source_tier"]),
            discovered_at=datetime.fromisoformat(data["discovered_at"]),
            published_at=datetime.fromisoformat(data["published_at"]) if data.get("published_at") else None,
            summary=data.get("summary", ""),
            image_url=data.get("image_url"),
            is_primary=data.get("is_primary", False),
        )


@dataclass(frozen=True, slots=True)
class TimelineEntry:
    """Chronological update within an event's lifecycle."""
    timestamp: datetime
    headline: str
    source_name: str
    source_url: str
    confidence_at_time: float
    entry_type: str = "update"      # "initial", "update", "confirmation", "resolution"

    def __post_init__(self):
        validate_utc_datetime(self.timestamp, "timestamp")
        validate_non_empty_string(self.headline, "headline")
        validate_score_range(self.confidence_at_time, "confidence_at_time")

    def to_dict(self) -> Dict[str, Any]:
        return {
            "timestamp": self.timestamp.isoformat(),
            "headline": self.headline,
            "source_name": self.source_name,
            "source_url": self.source_url,
            "confidence_at_time": round(self.confidence_at_time, 3),
            "entry_type": self.entry_type,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "TimelineEntry":
        return cls(
            timestamp=datetime.fromisoformat(data["timestamp"]),
            headline=data["headline"],
            source_name=data["source_name"],
            source_url=data["source_url"],
            confidence_at_time=data["confidence_at_time"],
            entry_type=data.get("entry_type", "update"),
        )


@dataclass(slots=True)
class TechEvent:
    """
    The primary technology intelligence aggregate root.
    
    Correlates multiple articles into one evolving event with:
    - Factual confidence (source corroboration)
    - Real-world importance (significance)
    - Novelty (cluster distance)
    - Temporal freshness
    - Explicit derived is_breaking rule
    """
    id: str                                        # Deterministic hash
    headline: str                                  # Synthesized event headline
    first_seen: datetime                           # Earliest observation timestamp
    last_updated: datetime                         # Most recent update timestamp
    entities: List[str] = field(default_factory=list)
    topics: List[str] = field(default_factory=list)
    sources: List[EventSourceEvidence] = field(default_factory=list)
    primary_source: Optional[str] = None
    confidence: float = 0.0                        # 0.0 to 1.0 (factual certainty)
    importance: float = 0.5                        # 0.0 to 1.0 (real-world significance)
    novelty: float = 1.0                           # 0.0 to 1.0 (uniqueness vs existing events)
    status: EventStatus = EventStatus.SUSPECTED
    freshness: FreshnessLevel = FreshnessLevel.FRESH
    freshness_score: float = 0.0                   # 0.0 to 1.0
    timeline: List[TimelineEntry] = field(default_factory=list)
    cluster_id: str = ""
    category: Optional[str] = None

    def __post_init__(self):
        validate_non_empty_string(self.id, "id")
        validate_non_empty_string(self.headline, "headline")
        validate_utc_datetime(self.first_seen, "first_seen")
        validate_utc_datetime(self.last_updated, "last_updated")
        validate_score_range(self.confidence, "confidence")
        validate_score_range(self.importance, "importance")
        validate_score_range(self.novelty, "novelty")
        validate_score_range(self.freshness_score, "freshness_score")

    @property
    def source_count(self) -> int:
        return len(self.sources)

    @property
    def is_breaking(self) -> bool:
        """
        Derived breaking news rule:
        Requires BREAKING freshness (<=5m), high factual confidence (>=0.70),
        and high real-world importance (>=0.60).
        """
        return (
            self.freshness == FreshnessLevel.BREAKING
            and self.confidence >= 0.70
            and self.importance >= 0.60
        )

    def add_source(self, source: EventSourceEvidence) -> bool:
        """Add source evidence if not already present. Returns True if newly added."""
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
            "entities": list(self.entities),
            "topics": list(self.topics),
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

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "TechEvent":
        sources = [EventSourceEvidence.from_dict(s) for s in data.get("sources", [])]
        timeline = [TimelineEntry.from_dict(t) for t in data.get("timeline", [])]
        return cls(
            id=data["id"],
            headline=data["headline"],
            first_seen=datetime.fromisoformat(data["first_seen"]),
            last_updated=datetime.fromisoformat(data["last_updated"]),
            entities=list(data.get("entities", [])),
            topics=list(data.get("topics", [])),
            sources=sources,
            primary_source=data.get("primary_source"),
            confidence=data.get("confidence", 0.0),
            importance=data.get("importance", 0.5),
            novelty=data.get("novelty", 1.0),
            status=EventStatus(data.get("status", "suspected")),
            freshness=FreshnessLevel(data.get("freshness", "fresh")),
            freshness_score=data.get("freshness_score", 0.0),
            timeline=timeline,
            cluster_id=data.get("cluster_id", ""),
            category=data.get("category"),
        )


# =============================================================================
# 6. PUBLICATION EVENT (DELIVERY CONTRACT)
# =============================================================================

PayloadType = Union[NormalizedArticle, TechEvent, Dict[str, Any]]


@dataclass(frozen=True, slots=True)
class PublicationEvent:
    """
    Strongly-typed envelope dispatched to the asynchronous Publication Bus.
    """
    event_id: str = field(default_factory=lambda: str(uuid4()))
    event_type: PublicationEventType = PublicationEventType.ARTICLE_PUBLISHED
    payload: PayloadType = field(default_factory=dict)
    channels: Tuple[PublicationChannel, ...] = (PublicationChannel.SSE_STREAM, PublicationChannel.TELEGRAM_BOT)
    priority: PublicationPriority = PublicationPriority.NORMAL
    published_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    schema_version: int = 1
    idempotency_key: str = ""

    def __post_init__(self):
        validate_non_empty_string(self.event_id, "event_id")
        validate_utc_datetime(self.published_at, "published_at")
        if not isinstance(self.channels, tuple):
            object.__setattr__(self, "channels", tuple(self.channels))
        if not self.idempotency_key:
            # Generate deterministic idempotency key from event type + payload id
            if hasattr(self.payload, "id"):
                object.__setattr__(self, "idempotency_key", f"{self.event_type.value}:{self.payload.id}")
            elif isinstance(self.payload, dict) and "id" in self.payload:
                object.__setattr__(self, "idempotency_key", f"{self.event_type.value}:{self.payload['id']}")
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
    """
    Operational resilience state machine for data sources.
    
    Complete State Transitions:
    - HEALTHY -> DEGRADED (1..4 consecutive failures)
    - HEALTHY/DEGRADED -> RATE_LIMITED (HTTP 429 received)
    - DEGRADED -> COOLDOWN (>=5 consecutive failures, exponential backoff)
    - ANY -> QUARANTINED (HTTP 404/410 received, quarantined 7 days)
    - QUARANTINED -> PROBATION (quarantine duration elapsed)
    - PROBATION -> HEALTHY (probe success)
    - PROBATION -> DEAD (probe failed after quarantine)
    - RATE_LIMITED/COOLDOWN -> HEALTHY (success after wait period)
    """
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

    def __post_init__(self):
        validate_non_empty_string(self.source_id, "source_id")
        validate_non_empty_string(self.source_url, "source_url")
        validate_non_empty_string(self.source_name, "source_name")
        if self.last_attempt is not None:
            validate_utc_datetime(self.last_attempt, "last_attempt")
        if self.last_success is not None:
            validate_utc_datetime(self.last_success, "last_success")
        if self.cooldown_until is not None:
            validate_utc_datetime(self.cooldown_until, "cooldown_until")

    def record_success(self, working_tier: int = 0) -> None:
        """Record a successful fetch, resetting error counters and moving to HEALTHY."""
        now = datetime.now(UTC)
        self.consecutive_successes += 1
        self.consecutive_failures = 0
        self.last_success = now
        self.last_attempt = now
        self.status = SourceHealthStatus.HEALTHY
        self.cooldown_until = None
        self.rate_limit_reset_at = None
        self.working_bypass_tier = working_tier

    def record_failure(self, status_code: Optional[int] = None, retry_after_sec: Optional[int] = None) -> None:
        """Record a fetch failure and execute state transition."""
        now = datetime.now(UTC)
        self.consecutive_failures += 1
        self.consecutive_successes = 0
        self.last_attempt = now
        self.last_status_code = status_code

        if self.status == SourceHealthStatus.PROBATION:
            # Failed while on probation -> permanently dead
            self.status = SourceHealthStatus.DEAD
        elif status_code in (404, 410):
            # Source not found or permanently gone -> 7 day quarantine
            self.status = SourceHealthStatus.QUARANTINED
            self.cooldown_until = now + timedelta(days=7)
        elif status_code == 429:
            # Explicit rate limit
            self.status = SourceHealthStatus.RATE_LIMITED
            backoff = retry_after_sec or 300
            self.cooldown_until = now + timedelta(seconds=backoff)
            self.rate_limit_reset_at = self.cooldown_until
        elif self.consecutive_failures >= 5:
            # Repeated failures -> exponential backoff (capped at 6 hours)
            self.status = SourceHealthStatus.COOLDOWN
            backoff_min = min(360, (2 ** (self.consecutive_failures - 5)) * 5)
            self.cooldown_until = now + timedelta(minutes=backoff_min)
        else:
            self.status = SourceHealthStatus.DEGRADED

    def check_probation_eligibility(self) -> bool:
        """Check if a quarantined source is ready to attempt a probe."""
        if self.status == SourceHealthStatus.QUARANTINED:
            if self.cooldown_until and datetime.now(UTC) >= self.cooldown_until:
                self.status = SourceHealthStatus.PROBATION
                return True
        return False

    def is_eligible_to_poll(self) -> bool:
        """Evaluate if the source is currently eligible for polling."""
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
            "rate_limit_reset_at": self.rate_limit_reset_at.isoformat() if self.rate_limit_reset_at else None,
            "working_bypass_tier": self.working_bypass_tier,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "SourceHealth":
        return cls(
            source_id=data["source_id"],
            source_url=data["source_url"],
            source_name=data["source_name"],
            status=SourceHealthStatus(data.get("status", "healthy")),
            consecutive_failures=data.get("consecutive_failures", 0),
            consecutive_successes=data.get("consecutive_successes", 0),
            last_attempt=datetime.fromisoformat(data["last_attempt"]) if data.get("last_attempt") else None,
            last_success=datetime.fromisoformat(data["last_success"]) if data.get("last_success") else None,
            last_status_code=data.get("last_status_code"),
            cooldown_until=datetime.fromisoformat(data["cooldown_until"]) if data.get("cooldown_until") else None,
            rate_limit_reset_at=datetime.fromisoformat(data["rate_limit_reset_at"]) if data.get("rate_limit_reset_at") else None,
            working_bypass_tier=data.get("working_bypass_tier", 0),
        )


# =============================================================================
# 7. ARTICLE SEARCH RESULT (LEXICAL FTS5 CONTRACT)
# =============================================================================

@dataclass(frozen=True, slots=True)
class ArticleSearchResult:
    """
    Immutable search result entity carrying authoritative NormalizedArticle,
    BM25 relevance score, and contextual match snippet.
    """
    article: NormalizedArticle
    relevance_score: float
    snippet: str = ""
