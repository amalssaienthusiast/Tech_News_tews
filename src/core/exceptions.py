"""
Custom exception hierarchy for the Tech News Scraper.

This module defines a structured exception hierarchy following
enterprise error handling patterns. Each exception carries
contextual information for debugging and user feedback.
"""

from dataclasses import dataclass, field
from datetime import datetime, UTC
from enum import Enum, auto
from typing import Any, Dict, Optional


class ErrorCode(Enum):
    """Standardized error codes for categorization."""
    # General errors (1000-1099)
    UNKNOWN_ERROR = 1000
    CONFIGURATION_ERROR = 1001
    INITIALIZATION_ERROR = 1002
    
    # Query errors (1100-1199)
    INVALID_QUERY = 1100
    QUERY_TOO_SHORT = 1101
    QUERY_TOO_LONG = 1102
    NON_TECH_QUERY = 1103
    QUERY_ANALYSIS_FAILED = 1104
    
    # Scraping errors (1200-1299)
    SCRAPING_FAILED = 1200
    INVALID_URL = 1201
    CONNECTION_FAILED = 1202
    TIMEOUT = 1203
    RATE_LIMITED = 1204
    BLOCKED = 1205
    CONTENT_EXTRACTION_FAILED = 1206
    JAVASCRIPT_REQUIRED = 1207
    
    # Database errors (1300-1399)
    DATABASE_ERROR = 1300
    RECORD_NOT_FOUND = 1301
    DUPLICATE_RECORD = 1302
    QUERY_FAILED = 1303
    MIGRATION_FAILED = 1304
    
    # AI/ML errors (1400-1499)
    MODEL_NOT_LOADED = 1400
    INFERENCE_FAILED = 1401
    EMBEDDING_FAILED = 1402
    SUMMARIZATION_FAILED = 1403
    
    # Validation errors (1500-1599)
    VALIDATION_ERROR = 1500
    MISSING_REQUIRED_FIELD = 1501
    INVALID_FORMAT = 1502
    VALUE_OUT_OF_RANGE = 1503


@dataclass
class ErrorContext:
    """
    Contextual information for debugging.
    
    Attributes:
        timestamp: When the error occurred
        operation: What operation was being performed
        component: Which component raised the error
        details: Additional context-specific details
        correlation_id: ID for tracing across operations
    """
    timestamp: datetime = field(default_factory=lambda: datetime.now(UTC))
    operation: Optional[str] = None
    component: Optional[str] = None
    details: Dict[str, Any] = field(default_factory=dict)
    correlation_id: Optional[str] = None


class TechScraperError(Exception):
    """
    Base exception for all Tech News Scraper errors.
    
    All custom exceptions inherit from this class, providing
    consistent error handling and reporting capabilities.
    
    Attributes:
        message: Human-readable error message
        code: Standardized error code
        context: Additional context for debugging
        cause: Original exception if wrapping another error
    """
    
    def __init__(
        self,
        message: str,
        code: ErrorCode = ErrorCode.UNKNOWN_ERROR,
        context: Optional[ErrorContext] = None,
        cause: Optional[Exception] = None
    ) -> None:
        super().__init__(message)
        self.message = message
        self.code = code
        self.context = context or ErrorContext()
        self.cause = cause
    
    def to_dict(self) -> Dict[str, Any]:
        """Serialize error for logging/API response."""
        return {
            "error": self.__class__.__name__,
            "message": self.message,
            "code": self.code.value,
            "code_name": self.code.name,
            "timestamp": self.context.timestamp.isoformat(),
            "operation": self.context.operation,
            "component": self.context.component,
            "correlation_id": self.context.correlation_id,
            "details": self.context.details,
            "cause": str(self.cause) if self.cause else None,
        }
    
    def __str__(self) -> str:
        return f"[{self.code.name}] {self.message}"
    
    def __repr__(self) -> str:
        return (
            f"{self.__class__.__name__}("
            f"message={self.message!r}, "
            f"code={self.code}, "
            f"context={self.context!r})"
        )


# =============================================================================
# QUERY EXCEPTIONS
# =============================================================================

class QueryError(TechScraperError):
    """Base exception for query-related errors."""
    pass


class InvalidQueryError(QueryError):
    """Raised when query is malformed or invalid."""
    
    def __init__(
        self,
        message: str = "Invalid query provided",
        query: Optional[str] = None,
        **kwargs
    ) -> None:
        context = kwargs.pop("context", ErrorContext())
        if query:
            context.details["query"] = query
        super().__init__(
            message=message,
            code=ErrorCode.INVALID_QUERY,
            context=context,
            **kwargs
        )


class NonTechQueryError(QueryError):
    """Raised when query is not tech-related."""
    
    def __init__(
        self,
        query: str,
        tech_score: float,
        threshold: float = 0.5,
        **kwargs
    ) -> None:
        context = kwargs.pop("context", ErrorContext())
        context.details.update({
            "query": query,
            "tech_score": tech_score,
            "threshold": threshold,
        })
        
        message = (
            f"Query '{query}' is not tech-related "
            f"(score: {tech_score:.2f}, threshold: {threshold:.2f}). "
            "Please ask about technology, software, AI, programming, or related topics."
        )
        
        super().__init__(
            message=message,
            code=ErrorCode.NON_TECH_QUERY,
            context=context,
            **kwargs
        )
        self.query = query
        self.tech_score = tech_score
        self.threshold = threshold


# =============================================================================
# SCRAPING EXCEPTIONS
# =============================================================================

class ScrapingError(TechScraperError):
    """Base exception for scraping-related errors."""
    pass


class InvalidURLError(ScrapingError):
    """Raised when URL is invalid or malformed."""
    
    def __init__(
        self,
        url: str,
        reason: str = "Invalid URL format",
        **kwargs
    ) -> None:
        context = kwargs.pop("context", ErrorContext())
        context.details["url"] = url
        context.details["reason"] = reason
        
        super().__init__(
            message=f"Invalid URL '{url}': {reason}",
            code=ErrorCode.INVALID_URL,
            context=context,
            **kwargs
        )
        self.url = url


class ScrapingConnectionError(ScrapingError):
    """Raised when connection to URL fails."""
    
    def __init__(
        self,
        url: str,
        reason: Optional[str] = None,
        **kwargs
    ) -> None:
        context = kwargs.pop("context", ErrorContext())
        context.details["url"] = url
        if reason:
            context.details["reason"] = reason
        
        message = f"Failed to connect to '{url}'"
        if reason:
            message += f": {reason}"
        
        super().__init__(
            message=message,
            code=ErrorCode.CONNECTION_FAILED,
            context=context,
            **kwargs
        )
        self.url = url

# Alias for backward compatibility (deprecated - use ScrapingConnectionError)
ConnectionError = ScrapingConnectionError


class RateLimitedError(ScrapingError):
    """Raised when request is rate limited."""
    
    def __init__(
        self,
        url: str,
        retry_after: Optional[int] = None,
        **kwargs
    ) -> None:
        context = kwargs.pop("context", ErrorContext())
        context.details["url"] = url
        if retry_after:
            context.details["retry_after"] = retry_after
        
        message = f"Rate limited by '{url}'"
        if retry_after:
            message += f". Retry after {retry_after} seconds."
        
        super().__init__(
            message=message,
            code=ErrorCode.RATE_LIMITED,
            context=context,
            **kwargs
        )
        self.url = url
        self.retry_after = retry_after


class ContentExtractionError(ScrapingError):
    """Raised when content extraction fails."""
    
    def __init__(
        self,
        url: str,
        reason: str = "Could not extract content",
        **kwargs
    ) -> None:
        context = kwargs.pop("context", ErrorContext())
        context.details["url"] = url
        context.details["reason"] = reason
        
        super().__init__(
            message=f"Content extraction failed for '{url}': {reason}",
            code=ErrorCode.CONTENT_EXTRACTION_FAILED,
            context=context,
            **kwargs
        )
        self.url = url


# =============================================================================
# DATABASE EXCEPTIONS
# =============================================================================

class DatabaseError(TechScraperError):
    """Base exception for database-related errors."""
    pass


class RecordNotFoundError(DatabaseError):
    """Raised when a requested record is not found."""
    
    def __init__(
        self,
        entity_type: str,
        entity_id: str,
        **kwargs
    ) -> None:
        context = kwargs.pop("context", ErrorContext())
        context.details["entity_type"] = entity_type
        context.details["entity_id"] = entity_id
        
        super().__init__(
            message=f"{entity_type} with ID '{entity_id}' not found",
            code=ErrorCode.RECORD_NOT_FOUND,
            context=context,
            **kwargs
        )


class DuplicateRecordError(DatabaseError):
    """Raised when attempting to insert a duplicate record."""
    
    def __init__(
        self,
        entity_type: str,
        identifier: str,
        **kwargs
    ) -> None:
        context = kwargs.pop("context", ErrorContext())
        context.details["entity_type"] = entity_type
        context.details["identifier"] = identifier
        
        super().__init__(
            message=f"{entity_type} '{identifier}' already exists",
            code=ErrorCode.DUPLICATE_RECORD,
            context=context,
            **kwargs
        )


# =============================================================================
# AI/ML EXCEPTIONS
# =============================================================================

class AIError(TechScraperError):
    """Base exception for AI/ML-related errors."""
    pass


class ModelNotLoadedError(AIError):
    """Raised when AI model is not loaded."""
    
    def __init__(
        self,
        model_name: str,
        **kwargs
    ) -> None:
        context = kwargs.pop("context", ErrorContext())
        context.details["model_name"] = model_name
        
        super().__init__(
            message=f"AI model '{model_name}' is not loaded. "
                    "Initialize models before use.",
            code=ErrorCode.MODEL_NOT_LOADED,
            context=context,
            **kwargs
        )


class InferenceError(AIError):
    """Raised when AI inference fails."""
    
    def __init__(
        self,
        model_name: str,
        reason: Optional[str] = None,
        **kwargs
    ) -> None:
        context = kwargs.pop("context", ErrorContext())
        context.details["model_name"] = model_name
        if reason:
            context.details["reason"] = reason
        
        message = f"Inference failed for model '{model_name}'"
        if reason:
            message += f": {reason}"
        
        super().__init__(
            message=message,
            code=ErrorCode.INFERENCE_FAILED,
            context=context,
            **kwargs
        )


# =============================================================================
# VALIDATION EXCEPTIONS
# =============================================================================

class ValidationError(TechScraperError):
    """Base exception for validation errors."""
    pass


class MissingFieldError(ValidationError):
    """Raised when a required field is missing."""
    
    def __init__(
        self,
        field_name: str,
        entity_type: Optional[str] = None,
        **kwargs
    ) -> None:
        context = kwargs.pop("context", ErrorContext())
        context.details["field_name"] = field_name
        if entity_type:
            context.details["entity_type"] = entity_type
        
        message = f"Required field '{field_name}' is missing"
        if entity_type:
            message += f" in {entity_type}"
        
        super().__init__(
            message=message,
            code=ErrorCode.MISSING_REQUIRED_FIELD,
            context=context,
            **kwargs
        )
