"""
Core Domain Package for Tech News Scrapper.
Location: src/domain/__init__.py

Canonical export point for all domain entities, enums, validators, and exceptions.
Zero external dependencies.
"""

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
from .models import (
    ArticleSearchResult,
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
from .validators import (
    DomainValidationError,
    InvariantViolationError,
    canonicalize_url,
    validate_non_empty_string,
    validate_score_range,
    validate_utc_datetime,
)

__all__ = [
    # Enums
    "ZombieSpecies",
    "SourceTier",
    "FreshnessLevel",
    "EventStatus",
    "DedupAction",
    "SourceHealthStatus",
    "PublicationChannel",
    "PublicationEventType",
    "PublicationPriority",
    "QualityCheckLevel",
    # Models
    "SourceObservation",
    "NormalizedArticle",
    "ArticleSearchResult",
    "QualityReport",
    "DedupDecision",
    "EventSourceEvidence",
    "TimelineEntry",
    "TechEvent",
    "PublicationEvent",
    "SourceHealth",
    "PayloadType",
    # Validators & Exceptions
    "DomainValidationError",
    "InvariantViolationError",
    "canonicalize_url",
    "validate_utc_datetime",
    "validate_score_range",
    "validate_non_empty_string",
]
