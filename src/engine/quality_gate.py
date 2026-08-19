"""
QualityGate - Mandatory Single-Article Quality Gate wrapper around SourceQualityFilter.

Provides three check levels:
- check()           — Standard quality check (existing behavior)
- check_strict()    — Breaking pipeline: title ≥15 chars, tech relevance, non-spam
- check_standard()  — Standard pipeline: existing checks (thumbnail optional but preferred)
"""

import logging
from typing import Optional

from ..core.types import Article
from .quality_filter import SourceQualityFilter

logger = logging.getLogger(__name__)

class QualityGate:
    """
    Quality gate enforcing quality and timeliness filters per article.
    Supports multiple check levels for different pipeline tiers.
    """

    def __init__(self, filter_instance: Optional[SourceQualityFilter] = None):
        self._filter = filter_instance or SourceQualityFilter(strict_mode=True, max_age_hours=72)

    def check(self, article: Article) -> bool:
        """
        Standard quality check (backward-compatible).
        Returns True if article PASSES.
        Returns False if article is REJECTED.
        """
        if not article or not article.url:
            return False

        title = (article.title or "").strip()
        if len(title) < 5 or title.lower() in ("untitled", "no title", "none", "unknown"):
            return False

        filtered = self._filter.filter_articles([article])
        return len(filtered) == 1

    def check_strict(self, article: Article) -> str:
        """
        Strict quality check for the BREAKING NEWS pipeline.

        Enforces:
        - Title must be ≥ 15 characters (real headlines, not fragments)
        - Must pass tech/science relevance check
        - Must NOT be spam
        - Must have a valid URL

        Returns:
            "pass" if article passes all checks
            A rejection reason string if it fails (e.g., "title_too_short", "not_tech", "spam")
        """
        if not article or not article.url:
            return "no_url"

        title = (article.title or "").strip()

        # Breaking pipeline requires substantial titles
        if len(title) < 15:
            return "title_too_short"

        title_lower = title.lower()
        if title_lower in ("untitled", "no title", "none", "unknown", "breaking news"):
            return "generic_title"

        # Use the filter's internal methods for deeper checks
        # Quality check (spam + low quality detection)
        quality_result = self._filter._check_quality(article)
        if quality_result == "spam":
            return "spam"
        if quality_result == "low_quality":
            return "low_quality"

        # Tech/Science relevance (MANDATORY for breaking pipeline)
        if not self._filter._is_tech_science_relevant(article):
            return "not_tech"

        return "pass"

    def check_standard(self, article: Article) -> str:
        """
        Standard pipeline quality check with enhanced reporting.

        Same as check() but returns rejection reason instead of bool.

        Returns:
            "pass" if article passes
            A rejection reason string if it fails
        """
        if not article or not article.url:
            return "no_url"

        title = (article.title or "").strip()
        if len(title) < 5 or title.lower() in ("untitled", "no title", "none", "unknown"):
            return "bad_title"

        filtered = self._filter.filter_articles([article])
        if len(filtered) == 0:
            return "quality_filter_rejected"

        return "pass"
