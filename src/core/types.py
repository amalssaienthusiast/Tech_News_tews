"""
Core type definitions and protocols for the Tech News Scraper.

This module defines the fundamental types, protocols (interfaces), and
abstract base classes used throughout the application, following
Python's typing best practices and interface segregation principle.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, UTC
from enum import Enum, auto
from typing import (
    Any,
    Dict,
    Generic,
    List,
    Optional,
    Protocol,
    Set,
    Tuple,
    TypeVar,
    Union,
    runtime_checkable,
)


# =============================================================================
# ENUMS
# =============================================================================

class QueryIntent(Enum):
    """Classification of user query intent."""
    SEARCH = auto()          # Search for tech news
    ANALYZE_URL = auto()     # Deep analysis of specific URL
    DISCOVER = auto()        # Discover new sources
    TRENDING = auto()        # Get trending topics
    REJECTED = auto()        # Non-tech query rejected


class ContentType(Enum):
    """Type of scraped content."""
    ARTICLE = auto()
    BLOG_POST = auto()
    NEWS = auto()
    TUTORIAL = auto()
    DISCUSSION = auto()
    DOCUMENTATION = auto()
    UNKNOWN = auto()


class SourceTier(Enum):
    """Quality tier of news source."""
    TIER_1 = 1  # Premium sources (TechCrunch, Wired, etc.)
    TIER_2 = 2  # High quality (Hacker News, Dev.to, etc.)
    TIER_3 = 3  # Good sources (tech blogs, subreddits)
    TIER_4 = 4  # User-submitted or unverified


class ScrapingStatus(Enum):
    """Status of a scraping operation."""
    SUCCESS = auto()
    PARTIAL = auto()
    FAILED = auto()
    RATE_LIMITED = auto()
    BLOCKED = auto()
    TIMEOUT = auto()


# =============================================================================
# DATA CLASSES
# =============================================================================

@dataclass(frozen=True, slots=True)
class TechScore:
    """
    Tech relevance score for content or queries.
    
    Attributes:
        score: Float between 0.0 and 1.0
        confidence: Confidence in the score (0.0 to 1.0)
        matched_keywords: Keywords that contributed to the score
        categories: Detected tech categories
    """
    score: float
    confidence: float
    matched_keywords: Tuple[str, ...] = field(default_factory=tuple)
    categories: Tuple[str, ...] = field(default_factory=tuple)
    
    def is_tech_related(self, threshold: float = 0.5) -> bool:
        """Check if score meets tech relevance threshold."""
        return self.score >= threshold
    
    def __post_init__(self) -> None:
        """Validate score ranges."""
        if not 0.0 <= self.score <= 1.0:
            object.__setattr__(self, 'score', max(0.0, min(1.0, self.score)))
        if not 0.0 <= self.confidence <= 1.0:
            object.__setattr__(self, 'confidence', max(0.0, min(1.0, self.confidence)))


@dataclass(frozen=True, slots=True)
class QueryResult:
    """
    Result of query analysis.
    
    Attributes:
        original_query: The original user query
        intent: Classified intent type
        tech_score: Tech relevance score
        expanded_terms: Additional search terms
        rejection_reason: Reason if query was rejected
    """
    original_query: str
    intent: QueryIntent
    tech_score: TechScore
    expanded_terms: Tuple[str, ...] = field(default_factory=tuple)
    rejection_reason: Optional[str] = None
    
    @property
    def is_accepted(self) -> bool:
        """Check if query was accepted."""
        return self.intent != QueryIntent.REJECTED


@dataclass(slots=True)
class Article:
    """
    Represents a scraped article.
    
    Attributes:
        id: Unique identifier (MD5 hash of URL)
        url: Article URL
        title: Article title
        content: Full article content
        summary: AI-generated summary
        source: Source name
        source_tier: Quality tier of source
        published_at: Publication datetime
        scraped_at: Scraping datetime
        tech_score: Tech relevance score
        entities: Extracted entities
        keywords: Extracted keywords
        related_urls: URLs to related content
    """
    id: str
    url: str
    title: str
    content: str
    summary: str
    source: str
    source_tier: SourceTier
    published_at: Optional[datetime] = None
    scraped_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    tech_score: Optional[TechScore] = None
    entities: Dict[str, List[str]] = field(default_factory=dict)
    keywords: Tuple[str, ...] = field(default_factory=tuple)
    related_urls: Tuple[str, ...] = field(default_factory=tuple)
    image_url: Optional[str] = None
    category: Optional[str] = None
    pipeline: Optional[str] = None  # 'breaking' or 'standard' — set by pipeline that produced this article
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "id": self.id,
            "url": self.url,
            "title": self.title,
            "content": self.content,
            "summary": self.summary,
            "source": self.source,
            "source_tier": self.source_tier.value,
            "published_at": self.published_at.isoformat() if self.published_at else None,
            "scraped_at": self.scraped_at.isoformat(),
            "tech_score": self.tech_score.score if self.tech_score else None,
            "entities": self.entities,
            "keywords": list(self.keywords),
            "related_urls": list(self.related_urls),
            "image_url": self.image_url,
            "category": self.category,
            "pipeline": self.pipeline,
        }


@dataclass(slots=True)
class Source:
    """
    Represents a news source.
    
    Attributes:
        url: Base URL of the source
        name: Human-readable name
        tier: Quality tier
        domain: Domain name
        scrape_patterns: URL patterns for articles
        rate_limit: Requests per second allowed
        last_scraped: Last successful scrape time
        success_rate: Historical success rate
        article_count: Total articles scraped
    """
    url: str
    name: str
    tier: SourceTier
    domain: str
    scrape_patterns: Tuple[str, ...] = field(default_factory=tuple)
    rate_limit: float = 1.0
    last_scraped: Optional[datetime] = None
    success_rate: float = 1.0
    article_count: int = 0
    
    @property
    def priority_score(self) -> float:
        """Calculate priority score for scraping order."""
        tier_weight = 5 - self.tier.value  # Higher tier = higher weight
        recency_bonus = 0.5 if self.last_scraped is None else 0.0
        return tier_weight * self.success_rate + recency_bonus


@dataclass(frozen=True, slots=True)
class ScrapingResult:
    """
    Result of a scraping operation.
    
    Attributes:
        status: Operation status
        articles: List of scraped articles
        source: Source that was scraped
        duration_ms: Time taken in milliseconds
        error_message: Error message if failed
    """
    status: ScrapingStatus
    articles: Tuple[Article, ...]
    source: Source
    duration_ms: float
    error_message: Optional[str] = None
    
    @property
    def article_count(self) -> int:
        """Get number of articles scraped."""
        return len(self.articles)


# =============================================================================
# PROTOCOLS (Interfaces)
# =============================================================================

T = TypeVar('T')
K = TypeVar('K')
V = TypeVar('V')


@runtime_checkable
class Analyzer(Protocol):
    """Protocol for content analyzers."""
    
    def analyze(self, content: str) -> TechScore:
        """Analyze content and return tech score."""
        ...


@runtime_checkable
class Scraper(Protocol):
    """Protocol for web scrapers."""
    
    async def scrape(self, url: str) -> ScrapingResult:
        """Scrape a URL and return result."""
        ...
    
    async def scrape_batch(self, urls: List[str]) -> List[ScrapingResult]:
        """Scrape multiple URLs concurrently."""
        ...


@runtime_checkable
class Cache(Protocol[K, V]):
    """Protocol for cache implementations."""
    
    def get(self, key: K) -> Optional[V]:
        """Get value by key."""
        ...
    
    def set(self, key: K, value: V, ttl: Optional[int] = None) -> None:
        """Set value with optional TTL."""
        ...
    
    def delete(self, key: K) -> bool:
        """Delete key and return success."""
        ...
    
    def clear(self) -> None:
        """Clear all entries."""
        ...


@runtime_checkable
class Repository(Protocol[T]):
    """Protocol for data repositories."""
    
    def get(self, id: str) -> Optional[T]:
        """Get entity by ID."""
        ...
    
    def save(self, entity: T) -> bool:
        """Save entity."""
        ...
    
    def delete(self, id: str) -> bool:
        """Delete entity by ID."""
        ...
    
    def find_all(self) -> List[T]:
        """Get all entities."""
        ...


# =============================================================================
# ABSTRACT BASE CLASSES
# =============================================================================

class BaseAnalyzer(ABC):
    """Abstract base class for content analyzers."""
    
    @abstractmethod
    def analyze(self, content: str) -> TechScore:
        """Analyze content and return tech score."""
        pass
    
    @abstractmethod
    def analyze_batch(self, contents: List[str]) -> List[TechScore]:
        """Analyze multiple contents."""
        pass


class BaseScraper(ABC):
    """Abstract base class for web scrapers."""
    
    @abstractmethod
    async def scrape(self, url: str) -> ScrapingResult:
        """Scrape a single URL."""
        pass
    
    @abstractmethod
    async def scrape_batch(self, urls: List[str]) -> List[ScrapingResult]:
        """Scrape multiple URLs."""
        pass
    
    @abstractmethod
    def get_stats(self) -> Dict[str, Any]:
        """Get scraping statistics."""
        pass


class BaseRepository(ABC, Generic[T]):
    """Abstract base class for repositories."""
    
    @abstractmethod
    def get(self, id: str) -> Optional[T]:
        """Get entity by ID."""
        pass
    
    @abstractmethod
    def save(self, entity: T) -> bool:
        """Save entity."""
        pass
    
    @abstractmethod
    def delete(self, id: str) -> bool:
        """Delete entity by ID."""
        pass
    
    @abstractmethod
    def find_all(self) -> List[T]:
        """Get all entities."""
        pass
    
    @abstractmethod
    def count(self) -> int:
        """Get total count."""
        pass


# =============================================================================
# CANONICAL DOMAIN TYPES (RE-EXPORTS FOR BACKWARD COMPATIBILITY)
# =============================================================================

from ..domain.enums import (
    DedupAction as DomainDedupAction,
    EventStatus as DomainEventStatus,
    FreshnessLevel as DomainFreshnessLevel,
    PublicationChannel as DomainPublicationChannel,
    PublicationEventType as DomainPublicationEventType,
    PublicationPriority as DomainPublicationPriority,
    QualityCheckLevel as DomainQualityCheckLevel,
    SourceHealthStatus as DomainSourceHealthStatus,
    ZombieSpecies as DomainZombieSpecies,
)
from ..domain.models import (
    DedupDecision,
    EventSourceEvidence,
    NormalizedArticle,
    PayloadType,
    PublicationEvent,
    QualityReport,
    SourceHealth,
    SourceObservation,
    TechEvent,
    TimelineEntry,
)
from ..domain.validators import (
    DomainValidationError,
    InvariantViolationError,
    canonicalize_url,
)
