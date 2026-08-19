"""
Core module initialization.

Exports all core types, exceptions, and interfaces.
"""

from src.core.types import (
    # Enums
    QueryIntent,
    ContentType,
    SourceTier,
    ScrapingStatus,
    # Dataclasses
    TechScore,
    QueryResult,
    Article,
    Source,
    ScrapingResult,
    # Protocols
    Analyzer,
    Scraper,
    Cache,
    Repository,
    # Abstract Base Classes
    BaseAnalyzer,
    BaseScraper,
    BaseRepository,
)

from src.core.exceptions import (
    # Base
    TechScraperError,
    ErrorCode,
    ErrorContext,
    # Query
    QueryError,
    InvalidQueryError,
    NonTechQueryError,
    # Scraping
    ScrapingError,
    InvalidURLError,
    ScrapingConnectionError,
    ConnectionError,  # Alias for backward compatibility
    RateLimitedError,
    ContentExtractionError,
    # Database
    DatabaseError,
    RecordNotFoundError,
    DuplicateRecordError,
    # AI
    AIError,
    ModelNotLoadedError,
    InferenceError,
    # Validation
    ValidationError,
    MissingFieldError,
)

__all__ = [
    # Enums
    "QueryIntent",
    "ContentType",
    "SourceTier",
    "ScrapingStatus",
    # Dataclasses
    "TechScore",
    "QueryResult",
    "Article",
    "Source",
    "ScrapingResult",
    # Protocols
    "Analyzer",
    "Scraper",
    "Cache",
    "Repository",
    # ABCs
    "BaseAnalyzer",
    "BaseScraper",
    "BaseRepository",
    # Exceptions
    "TechScraperError",
    "ErrorCode",
    "ErrorContext",
    "QueryError",
    "InvalidQueryError",
    "NonTechQueryError",
    "ScrapingError",
    "InvalidURLError",
    "ScrapingConnectionError",
    "ConnectionError",  # Alias for backward compatibility
    "RateLimitedError",
    "ContentExtractionError",
    "DatabaseError",
    "RecordNotFoundError",
    "DuplicateRecordError",
    "AIError",
    "ModelNotLoadedError",
    "InferenceError",
    "ValidationError",
    "MissingFieldError",
]
