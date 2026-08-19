"""
Domain Invariant Validators and Exceptions.
Location: src/domain/validators.py

Zero external dependencies. Pure standard library.
"""

from datetime import datetime, UTC
import re
from typing import Any, Dict, List, Optional, Tuple, Union
from urllib.parse import urlparse, parse_qsl, urlunparse, urlencode


# =============================================================================
# DOMAIN EXCEPTIONS
# =============================================================================

class DomainValidationError(ValueError):
    """Raised when a domain model invariant is violated at instantiation."""
    pass


class InvariantViolationError(DomainValidationError):
    """Raised when a business invariant is violated during lifecycle transitions."""
    pass


# =============================================================================
# VALIDATION HELPERS
# =============================================================================

TRACKING_PARAMS = {
    "utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content",
    "ref", "fbclid", "gclid", "igshid", "mc_eid", "_ga", "_hsenc", "_openstat",
    "ysclid", "msclkid", "spm", "scm", "trcid", "twclid"
}


def canonicalize_url(url: str) -> str:
    """
    Canonicalize a URL for unique identity and deduplication:
    - Strips whitespace
    - Lowercases scheme and hostname
    - Strips default ports (:80 for HTTP, :443 for HTTPS)
    - Strips known analytics/tracking query parameters (utm_*, ref, fbclid, etc.)
    - Alphabetically sorts remaining query parameters
    - Strips trailing slash from path (unless root path '/')
    - Strips fragments (#anchor)
    """
    if not url or not url.strip():
        raise DomainValidationError("URL cannot be empty")

    trimmed = url.strip()
    try:
        parsed = urlparse(trimmed)
        scheme = parsed.scheme.lower()
        if scheme not in ("http", "https"):
            raise DomainValidationError(f"Invalid URL scheme '{scheme}': must be http or https")

        netloc = parsed.netloc.lower()
        if not netloc:
            raise DomainValidationError(f"Invalid URL '{url}': missing network location/host")

        if netloc.endswith(":80") and scheme == "http":
            netloc = netloc[:-3]
        elif netloc.endswith(":443") and scheme == "https":
            netloc = netloc[:-4]

        path = parsed.path.rstrip("/")
        if not path:
            path = ""

        # Filter out tracking parameters and sort remaining query params
        query_params = parse_qsl(parsed.query, keep_blank_values=False)
        filtered_params = sorted([(k, v) for k, v in query_params if k.lower() not in TRACKING_PARAMS])
        query = urlencode(filtered_params)

        return urlunparse((scheme, netloc, path, parsed.params, query, ""))
    except DomainValidationError:
        raise
    except Exception as e:
        raise DomainValidationError(f"Malformed URL '{url}': {e}") from e


def validate_utc_datetime(dt: Optional[datetime], field_name: str = "datetime") -> Optional[datetime]:
    """Validate that a datetime is timezone-aware and in UTC."""
    if dt is None:
        return None
    if not isinstance(dt, datetime):
        raise DomainValidationError(f"{field_name} must be a datetime instance, got {type(dt)}")
    if dt.tzinfo is None:
        raise DomainValidationError(f"{field_name} must be timezone-aware (UTC)")
    return dt


def validate_score_range(score: float, field_name: str = "score", min_val: float = 0.0, max_val: float = 1.0) -> float:
    """Validate that a float score falls within the required range."""
    if not isinstance(score, (int, float)):
        raise DomainValidationError(f"{field_name} must be a number, got {type(score)}")
    if not (min_val <= score <= max_val):
        raise DomainValidationError(f"{field_name} ({score}) must be between {min_val} and {max_val}")
    return float(score)


def validate_non_empty_string(value: str, field_name: str = "field", min_length: int = 1) -> str:
    """Validate that a string is non-empty and meets minimum length."""
    if not isinstance(value, str):
        raise DomainValidationError(f"{field_name} must be a string, got {type(value)}")
    stripped = value.strip()
    if len(stripped) < min_length:
        raise DomainValidationError(f"{field_name} must be at least {min_length} character(s)")
    return stripped
