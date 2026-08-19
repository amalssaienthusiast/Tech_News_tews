"""
Retry Classifier and Transient Error Categorization.
Location: src/network/retry_classifier.py
"""

from __future__ import annotations

from enum import Enum
import socket
from typing import Any, Dict, Optional, Tuple

from src.security.ssrf_guard import PayloadSizeLimitExceeded, SSRFSecurityError


class RetryCategory(str, Enum):
    """Classification of network and HTTP response outcomes."""
    SUCCESS = "success"
    RETRYABLE = "retryable"
    NON_RETRYABLE = "non_retryable"
    RATE_LIMITED = "rate_limited"
    SECURITY_REJECTED = "security_rejected"
    POISON_PAYLOAD = "poison_payload"


class RetryClassifier:
    """Classifies exceptions, HTTP status codes, and security errors into actionable retry categories."""

    @staticmethod
    def classify_status_code(status_code: int, headers: Optional[Dict[str, str]] = None) -> Tuple[RetryCategory, float]:
        """
        Classify HTTP status code and extract retry delay.
        Returns (RetryCategory, recommended_backoff_seconds).
        """
        if 200 <= status_code < 300:
            return RetryCategory.SUCCESS, 0.0

        if status_code == 429:
            retry_after = 60.0
            if headers:
                val = headers.get("Retry-After") or headers.get("retry-after")
                if val:
                    try:
                        retry_after = max(1.0, float(val))
                    except ValueError:
                        pass
            return RetryCategory.RATE_LIMITED, retry_after

        # Transient server errors
        if status_code in (408, 500, 502, 503, 504, 521, 522, 524):
            return RetryCategory.RETRYABLE, 5.0

        # Permanent client errors
        if 400 <= status_code < 500:
            return RetryCategory.NON_RETRYABLE, 0.0

        return RetryCategory.NON_RETRYABLE, 0.0

    @staticmethod
    def classify_exception(exc: BaseException) -> Tuple[RetryCategory, float]:
        """Classify Python / network exception."""
        if isinstance(exc, PayloadSizeLimitExceeded):
            return RetryCategory.POISON_PAYLOAD, 0.0

        if isinstance(exc, SSRFSecurityError):
            return RetryCategory.SECURITY_REJECTED, 0.0

        if isinstance(exc, (TimeoutError, socket.timeout)):
            return RetryCategory.RETRYABLE, 3.0

        if isinstance(exc, (ConnectionResetError, ConnectionRefusedError, ConnectionAbortedError)):
            return RetryCategory.RETRYABLE, 5.0

        if isinstance(exc, socket.gaierror):
            return RetryCategory.RETRYABLE, 10.0

        return RetryCategory.NON_RETRYABLE, 0.0
