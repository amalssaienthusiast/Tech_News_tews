"""
Canonical Domain Enums for Tech News Scrapper.
Location: src/domain/enums.py

Zero external dependencies. Pure domain types.
"""

from enum import Enum
from typing import Optional


class ZombieSpecies(str, Enum):
    """Types of autonomous zombie collectors."""
    RSS = "z_rss"
    GITHUB = "z_github"
    HACKER_NEWS = "z_hacker"
    SECURITY = "z_security"
    CORPORATE = "z_corp"
    WEB = "z_web"
    DISCOVERY = "z_discovery"


class SourceTier(int, Enum):
    """Quality tier of news sources."""
    TIER_1_PREMIUM = 1       # Curated primary tech news (TechCrunch, Wired, Ars Technica)
    TIER_2_SPECIALIST = 2    # High-signal specialist (Hacker News, GitHub Trending, NVD)
    TIER_3_COMMUNITY = 3     # General community feeds, tech subreddits
    TIER_4_DISCOVERY = 4     # Automated discovery, unverified feeds

    # Compatibility aliases for legacy code
    TIER_1 = 1
    TIER_2 = 2
    TIER_3 = 3
    TIER_4 = 4


class FreshnessLevel(str, Enum):
    """
    Temporal classification tiers with deterministic age boundaries.
    
    Exact Boundaries:
      BREAKING:   [0, 5] minutes
      VERY_FRESH: (5, 30] minutes
      FRESH:      (30, 120] minutes
      RECENT:     (120, 360] minutes (2-6 hours)
      AGING:      (360, 1440] minutes (6-24 hours)
      OLD:        (1440, 4320] minutes (24-72 hours)
      STALE:      > 4320 minutes (>72 hours) -> Discard/Archive
      UNKNOWN:    Undated article fallback
    """
    BREAKING = "breaking"
    VERY_FRESH = "very_fresh"
    FRESH = "fresh"
    RECENT = "recent"
    AGING = "aging"
    OLD = "old"
    STALE = "stale"
    UNKNOWN = "unknown"

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

    @property
    def label(self) -> str:
        return {
            "breaking": "BREAKING",
            "very_fresh": "VERY FRESH",
            "fresh": "FRESH",
            "recent": "RECENT",
            "aging": "AGING",
            "old": "OLD",
            "stale": "STALE",
            "unknown": "UNKNOWN",
        }[self.value]

    @classmethod
    def from_age_minutes(cls, age_minutes: Optional[float]) -> "FreshnessLevel":
        """Deterministic conversion from age in minutes to FreshnessLevel."""
        if age_minutes is None:
            return cls.UNKNOWN
        if age_minutes < 0:
            return cls.BREAKING
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
    """Lifecycle states for a technology event aggregate."""
    SUSPECTED = "suspected"         # 1 source, low confidence (<0.30)
    CORROBORATED = "corroborated"   # Multiple sources agree (0.30–0.60)
    CONFIRMED = "confirmed"         # Primary or high-tier source confirmed (0.60–0.85)
    DEVELOPING = "developing"       # Active breaking updates (>0.85 and active updates)
    RESOLVED = "resolved"           # Event complete; no further updates expected
    STALE = "stale"                 # Inactive > 24h


class DedupAction(str, Enum):
    """Actions resulting from deduplication gate evaluation."""
    ACCEPTED = "accepted"                          # Genuinely unique -> proceed to indexing
    EXACT_URL_DUPLICATE = "exact_url_duplicate"    # Exact canonical URL match
    SIMILAR_TITLE_DUPLICATE = "similar_title_dup"  # MinHash Jaccard similarity >= threshold
    SUPERSEDED = "superseded"                      # Better revision of existing story


class SourceHealthStatus(str, Enum):
    """Operational health state machine states for data sources."""
    HEALTHY = "healthy"           # Normal operation, yielding articles
    DEGRADED = "degraded"         # 1-4 consecutive failures, retrying
    RATE_LIMITED = "rate_limited" # 429 received, backing off until Retry-After
    COOLDOWN = "cooldown"         # >=5 consecutive failures, exponential backoff
    QUARANTINED = "quarantined"   # 404/410 received, dormant for 7 days
    PROBATION = "probation"       # Quarantine expired; single probe attempt pending
    DEAD = "dead"                 # Probe failed after quarantine; permanently deactivated


class PublicationChannel(str, Enum):
    """Destination channels for published domain events."""
    SSE_STREAM = "sse_stream"
    TELEGRAM_BOT = "telegram_bot"
    WEBSOCKET = "websocket"
    FEED_BUFFER = "feed_buffer"


class PublicationEventType(str, Enum):
    """Types of published domain events."""
    ARTICLE_PUBLISHED = "article_published"
    EVENT_DETECTED = "event_detected"
    EVENT_UPDATED = "event_updated"
    BREAKING_ALERT = "breaking_alert"
    SYSTEM_STATUS = "system_status"


class PublicationPriority(int, Enum):
    """Priority levels for publication event dispatch."""
    HIGH = 1       # Breaking events, critical CVEs -> immediate dispatch
    NORMAL = 2     # Standard verified articles
    LOW = 3        # Background digests, operational stats


class QualityCheckLevel(str, Enum):
    """Evaluation strictness level for quality filtering."""
    STANDARD = "standard"
    STRICT = "strict"      # Used for breaking news pipeline
