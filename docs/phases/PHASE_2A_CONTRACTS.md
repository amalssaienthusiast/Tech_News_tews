# Phase 2A Domain Contracts: Canonical Types & Invariants

**Document Status**: Phase 2A Design Specification  
**Authority**: Architecture Lead  
**Scope**: Canonical Domain Entities, Value Objects, Invariants, and Serialization Protocols

---

## 1. Domain Object Overview

The Tech News Scrapper canonical domain model consists of 8 core objects:

```text
┌────────────────────────────────────────────────────────────────────────────────────────┐
│                                CANONICAL DOMAIN TYPES                                  │
├────────────────────────────────────────────────────────────────────────────────────────┤
│ 1. SourceObservation   : Raw observation emitted by Zombie collectors & adapters       │
│ 2. NormalizedArticle   : Canonicalized, clean article representation                   │
│ 3. QualityReport       : Explainable evaluation from quality & relevance gates         │
│ 4. DedupDecision       : Deduplication analysis decision and similarity evidence       │
│ 5. FreshnessLevel      : Multi-tier freshness classification and score                 │
│ 6. TechEvent           : Aggregated technology intelligence event (Aggregate Root)     │
│ 7. PublicationEvent    : Envelope dispatched to the asynchronous Publication Bus       │
│ 8. SourceHealth        : Lifecycle & resilience state machine for data sources         │
└────────────────────────────────────────────────────────────────────────────────────────┘
```

---

## 2. Detailed Contract Specifications

### 2.1 `SourceObservation` (Acquisition Contract)

**Purpose**: Represents raw, unprocessed data captured from an external source before normalization or filtering. Emitted exclusively by Zombie species and discovery adapters.

```python
from dataclasses import dataclass, field
from datetime import datetime, UTC
from typing import Optional, Dict, Any
from enum import Enum

class ZombieSpecies(str, Enum):
    RSS = "z_rss"
    GITHUB = "z_github"
    HACKER_NEWS = "z_hacker"
    SECURITY = "z_security"
    CORPORATE = "z_corp"
    WEB = "z_web"
    DISCOVERY = "z_discovery"

@dataclass(frozen=True, slots=True)
class SourceObservation:
    id: str                                        # Deterministic hash of source_url + raw url
    source_id: str                                 # ID of the source configuration
    source_name: str                               # e.g., "TechCrunch", "Ars Technica"
    source_tier: int                               # 1=Curated/Premium, 2=Specialist, 3=Discovery
    zombie_species: ZombieSpecies                  # Collector that discovered this item
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
            raise ValueError("SourceObservation must have a non-empty URL")
        if not self.title or not self.title.strip():
            raise ValueError("SourceObservation must have a non-empty title")
        if self.source_tier not in (1, 2, 3, 4):
            raise ValueError("source_tier must be between 1 and 4")
        if self.observed_at.tzinfo is None:
            raise ValueError("observed_at must be timezone-aware (UTC)")

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "source_id": self.source_id,
            "source_name": self.source_name,
            "source_tier": self.source_tier,
            "zombie_species": self.zombie_species.value,
            "url": self.url,
            "title": self.title,
            "raw_content": self.raw_content,
            "summary": self.summary,
            "image_url": self.image_url,
            "published_at_hint": self.published_at_hint.isoformat() if self.published_at_hint else None,
            "observed_at": self.observed_at.isoformat(),
            "metadata": self.metadata,
        }
```

---

### 2.2 `NormalizedArticle` (Clean Ingestion Contract)

**Purpose**: The standardized representation of an article after URL canonicalization, HTML stripping, character normalization, and timestamp parsing.

```python
@dataclass(slots=True)
class NormalizedArticle:
    id: str                                        # Deterministic hash of canonical_url (MD5 or SHA256-16)
    canonical_url: str                             # URL stripped of UTM/tracking, lowercased host/scheme
    original_url: str                              # Original URL as observed
    title: str                                     # Clean Unicode title
    clean_text: str                                # Extracted plain text body
    summary: str                                   # Summary or excerpt
    source_id: str                                 # Source registry identifier
    source_name: str                               # Human-readable source name
    source_tier: int                               # 1, 2, 3, 4
    zombie_species: ZombieSpecies                  # Ingestion species
    discovered_at: datetime                        # Timestamp when observed
    published_at: Optional[datetime] = None        # Parsed authoritative publication timestamp
    language: str = "en"                           # ISO 639-1 language code
    image_url: Optional[str] = None                # Verified thumbnail/hero image URL
    authors: list[str] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        if not self.canonical_url or not self.canonical_url.startswith(("http://", "https://")):
            raise ValueError(f"Invalid canonical URL: {self.canonical_url}")
        if len(self.title.strip()) < 3:
            raise ValueError("Title must be at least 3 characters")

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
            "source_tier": self.source_tier,
            "zombie_species": self.zombie_species.value,
            "discovered_at": self.discovered_at.isoformat(),
            "published_at": self.published_at.isoformat() if self.published_at else None,
            "language": self.language,
            "image_url": self.image_url,
            "authors": self.authors,
            "tags": self.tags,
            "metadata": self.metadata,
        }
```

---

### 2.3 `QualityReport` (Evaluation & Filtering Contract)

**Purpose**: Explainable diagnostics emitted by the Quality Gate and Relevance Gate. Explains precisely why an article passed or was rejected.

```python
class QualityCheckLevel(str, Enum):
    STANDARD = "standard"
    STRICT = "strict"      # Used for breaking news pipeline

@dataclass(frozen=True, slots=True)
class QualityReport:
    article_id: str
    is_passed: bool
    quality_score: float                           # 0.0 to 1.0 composite quality score
    relevance_score: float                         # 0.0 to 1.0 technology relevance score
    check_level: QualityCheckLevel
    rejection_reasons: list[str] = field(default_factory=list)  # e.g., ["title_too_short", "spam_detected", "not_tech"]
    matched_keywords: list[str] = field(default_factory=list)
    detected_categories: list[str] = field(default_factory=list)
    evaluated_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    def __post_init__(self):
        if not 0.0 <= self.quality_score <= 1.0:
            raise ValueError("quality_score must be between 0.0 and 1.0")
        if not 0.0 <= self.relevance_score <= 1.0:
            raise ValueError("relevance_score must be between 0.0 and 1.0")
        if not self.is_passed and not self.rejection_reasons:
            raise ValueError("Rejected QualityReport must include at least one rejection reason")

    def to_dict(self) -> Dict[str, Any]:
        return {
            "article_id": self.article_id,
            "is_passed": self.is_passed,
            "quality_score": round(self.quality_score, 3),
            "relevance_score": round(self.relevance_score, 3),
            "check_level": self.check_level.value,
            "rejection_reasons": self.rejection_reasons,
            "matched_keywords": self.matched_keywords,
            "detected_categories": self.detected_categories,
            "evaluated_at": self.evaluated_at.isoformat(),
        }
```

---

### 2.4 `DedupDecision` (Deduplication Contract)

**Purpose**: Records the outcome of the two-tier deduplication gate (Bloom Filter + MinHash Title Shingling).

```python
class DedupAction(str, Enum):
    ACCEPTED = "accepted"                          # Genuinely new article -> cleared to index
    EXACT_URL_DUPLICATE = "exact_url_duplicate"    # Canonical URL match
    SIMILAR_TITLE_DUPLICATE = "similar_title_dup"  # MinHash Jaccard similarity ≥ threshold
    SUPERSEDED = "superseded"                      # Better revision of existing story

@dataclass(frozen=True, slots=True)
class DedupDecision:
    article_id: str
    action: DedupAction
    is_duplicate: bool
    canonical_url: str
    matched_article_id: Optional[str] = None
    similarity_score: float = 0.0                  # 0.0 to 1.0 (Jaccard similarity if applicable)
    minhash_signature: Optional[list[int]] = None
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
```

---

### 2.5 `FreshnessLevel` (Temporal Classification Contract)

**Purpose**: Fine-grained temporal tiering for stories and events.

```python
class FreshnessLevel(str, Enum):
    BREAKING = "breaking"           # 🔴  0–5 min
    VERY_FRESH = "very_fresh"       # 🟠  5–30 min
    FRESH = "fresh"                 # 🟡  30–120 min
    RECENT = "recent"               # 🟢  2–6 hours
    AGING = "aging"                 # 🔵  6–24 hours
    OLD = "old"                     # ⚫  24–72 hours
    STALE = "stale"                 # ❌  >72 hours (quarantined/discarded)
    UNKNOWN = "unknown"             # ❓  Undated article (requires verification)

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
        if age_minutes <= 5:
            return cls.BREAKING
        elif age_minutes <= 30:
            return cls.VERY_FRESH
        elif age_minutes <= 120:
            return cls.FRESH
        elif age_minutes <= 360:
            return cls.RECENT
        elif age_minutes <= 1440:
            return cls.AGING
        elif age_minutes <= 4320:
            return cls.OLD
        else:
            return cls.STALE
```

---

### 2.6 `TechEvent` (Aggregate Root Intelligence Contract)

**Purpose**: The central intelligence entity. Groups multiple source articles into a single evolving story with confidence scoring and timeline tracking.

```python
class EventStatus(str, Enum):
    SUSPECTED = "suspected"         # 1 source, low confidence (<0.3)
    CORROBORATED = "corroborated"   # Multiple sources agree (0.3–0.6)
    CONFIRMED = "confirmed"         # Primary or high-tier source confirmed (0.6–0.85)
    DEVELOPING = "developing"       # Active breaking updates (>0.85 and active)
    RESOLVED = "resolved"           # Event complete; no further updates expected
    STALE = "stale"                 # Inactive > 24h

@dataclass
class EventSourceEvidence:
    article_id: str
    url: str
    title: str
    source_name: str
    source_tier: int
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
            "source_tier": self.source_tier,
            "discovered_at": self.discovered_at.isoformat(),
            "published_at": self.published_at.isoformat() if self.published_at else None,
            "summary": self.summary,
            "image_url": self.image_url,
            "is_primary": self.is_primary,
        }

@dataclass
class TimelineEntry:
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

@dataclass
class TechEvent:
    id: str                                        # Deterministic hash
    headline: str                                  # Synthesized title
    first_seen: datetime
    last_updated: datetime
    entities: list[str] = field(default_factory=list)
    topics: list[str] = field(default_factory=list)
    sources: list[EventSourceEvidence] = field(default_factory=list)
    primary_source: Optional[str] = None
    confidence: float = 0.0                        # 0.0 to 1.0
    status: EventStatus = EventStatus.SUSPECTED
    freshness: FreshnessLevel = FreshnessLevel.FRESH
    freshness_score: float = 0.0                   # Composite freshness (0.0 to 1.0)
    timeline: list[TimelineEntry] = field(default_factory=list)
    cluster_id: str = ""
    category: Optional[str] = None

    @property
    def source_count(self) -> int:
        return len(self.sources)

    @property
    def is_breaking(self) -> bool:
        return self.freshness == FreshnessLevel.BREAKING and self.confidence >= 0.7

    def add_source(self, source: EventSourceEvidence) -> bool:
        """Add source evidence if not already present. Returns True if newly added."""
        if any(s.url == source.url for s in self.sources):
            return False
        self.sources.append(source)
        self.last_updated = datetime.now(UTC)
        if source.is_primary:
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
            "status": self.status.value,
            "freshness": self.freshness.value,
            "freshness_badge": self.freshness.badge,
            "freshness_score": round(self.freshness_score, 3),
            "timeline": [t.to_dict() for t in self.timeline],
            "cluster_id": self.cluster_id,
            "category": self.category,
            "is_breaking": self.is_breaking,
        }
```

---

### 2.7 `PublicationEvent` (Delivery Contract)

**Purpose**: Envelope pushed to `PublicationBus` and consumed by delivery surfaces (API SSE, Telegram Feeder Bot, WebSockets).

```python
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

class PublicationPriority(int, Enum):
    HIGH = 1       # Breaking news, critical CVEs -> immediate dispatch
    NORMAL = 2     # Standard news updates
    LOW = 3        # Periodic digests, background stats

@dataclass(frozen=True, slots=True)
class PublicationEvent:
    event_id: str
    event_type: PublicationEventType
    payload: Dict[str, Any]                        # Serialized NormalizedArticle or TechEvent
    channels: tuple[PublicationChannel, ...] = (PublicationChannel.SSE_STREAM, PublicationChannel.TELEGRAM_BOT)
    priority: PublicationPriority = PublicationPriority.NORMAL
    published_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    def to_dict(self) -> Dict[str, Any]:
        return {
            "event_id": self.event_id,
            "event_type": self.event_type.value,
            "channels": [c.value for c in self.channels],
            "priority": self.priority.value,
            "published_at": self.published_at.isoformat(),
            "payload": self.payload,
        }
```

---

### 2.8 `SourceHealth` (Resilience & State Machine Contract)

**Purpose**: Tracks operational health, rate-limiting cooldowns, and error backoff for external news sources.

```python
class SourceHealthStatus(str, Enum):
    HEALTHY = "healthy"           # Normal operation, yielding articles
    DEGRADED = "degraded"         # 1-4 consecutive failures, retrying
    RATE_LIMITED = "rate_limited" # 429 received, backing off until reset header
    COOLDOWN = "cooldown"         # ≥5 consecutive failures, exponential backoff
    QUARANTINED = "quarantined"   # 404/410 received, dormant for 7 days
    DEAD = "dead"                 # Permanent failure after quarantine

@dataclass
class SourceHealth:
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
    working_bypass_tier: int = 0                   # Last working BypassResolver tier (0..4)

    def record_success(self, working_tier: int = 0) -> None:
        self.consecutive_successes += 1
        self.consecutive_failures = 0
        self.last_success = datetime.now(UTC)
        self.last_attempt = datetime.now(UTC)
        self.status = SourceHealthStatus.HEALTHY
        self.cooldown_until = None
        self.working_bypass_tier = working_tier

    def record_failure(self, status_code: Optional[int] = None, retry_after_sec: Optional[int] = None) -> None:
        now = datetime.now(UTC)
        self.consecutive_failures += 1
        self.consecutive_successes = 0
        self.last_attempt = now
        self.last_status_code = status_code

        if status_code in (404, 410):
            self.status = SourceHealthStatus.QUARANTINED
            self.cooldown_until = now + timedelta(days=7)
        elif status_code == 429:
            self.status = SourceHealthStatus.RATE_LIMITED
            backoff = retry_after_sec or 300
            self.cooldown_until = now + timedelta(seconds=backoff)
        elif self.consecutive_failures >= 5:
            self.status = SourceHealthStatus.COOLDOWN
            # Exponential backoff capped at 6 hours
            backoff_min = min(360, (2 ** (self.consecutive_failures - 5)) * 5)
            self.cooldown_until = now + timedelta(minutes=backoff_min)
        else:
            self.status = SourceHealthStatus.DEGRADED

    def is_eligible_to_poll(self) -> bool:
        if self.status == SourceHealthStatus.DEAD:
            return False
        if self.cooldown_until and self.cooldown_until > datetime.now(UTC):
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
