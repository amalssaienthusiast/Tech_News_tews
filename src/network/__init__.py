"""
Network Policy and Classification Package for Tech News Scrapper.
Location: src/network/__init__.py
"""

from .fetch_policy import FetchPolicy
from .retry_classifier import RetryCategory, RetryClassifier

__all__ = [
    "FetchPolicy",
    "RetryCategory",
    "RetryClassifier",
]
